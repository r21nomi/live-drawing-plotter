# 運用ガイド（Raspberry Pi）

README の「日々の運用」で足りない場合に読むページです。

## 起動の仕組み

`deploy/install-pi.sh` が systemd のサービス `live-plotter@ユーザー名.service` を登録します。
Pi の電源が入るとこのサービスが自動で起動し、カメラを開き、AxiDraw に接続して描き始めます。
`uv run live-plotter` を手で実行するのは、オプションを試すときだけです。その場合は先にサービスを止めてください（カメラと AxiDraw を 2 つのプロセスで取り合うため）。

## ダッシュボード

本体プロセスが `http://localhost:8080/` でダッシュボードを配信し、Pi のデスクトップ起動時に Chromium がキオスクモード（全画面）でそれを表示します。
起動直後は「開始待ち」で、AxiDraw への接続とカメラ映像の配信だけを行い、ペンは動かしません。描画は「開始」を押してから始まります（起動と同時に描き始めたい場合は `--autostart`）。

起動順は「ダッシュボード → カメラ → AxiDraw」です。カメラや AxiDraw に接続できなくても本体は終了せず、ダッシュボードに原因を赤字で表示して 5 秒ごとに再試行します。稼働中にカメラが止まったり AxiDraw が外れたりした場合も同じ待機状態に戻ります。
同じ Wi-Fi 内の他の端末からは `http://raspberrypi.local:8080/`（ホスト名は環境に合わせて）で開けます。認証はありません。会場の共有ネットワークで困る場合は `--no-web` で止めてください。

| 操作 | 意味 |
|---|---|
| 開始 | 起動後、または新しい紙のあとに描き始める（まだ何も描いていないときの表示） |
| 一時停止 | 描画中の 1 本を描き終えたらペンを上げて待機。本体プロセスは動き続け、カメラ映像も流れ続ける |
| 再開 | 続きから描く。一時停止中に風景が変わっていれば、新しい風景を描く |
| 新しい紙 | 描画済みの記憶を消して待機。紙をセットして「開始」を押すと白紙として開始 |

キオスク表示は `deploy/kiosk.sh` が行い、`~/.config/autostart/live-plotter-kiosk.desktop` からデスクトップログイン時に起動します。
手で起動したいときは `bash deploy/kiosk.sh`、閉じたいときは Alt+F4 です。
Chromium が自動起動しない環境（labwc / wayfire の設定による）では、`~/.config/labwc/autostart` または `~/.config/wayfire.ini` の `[autostart]` に `/home/ユーザー名/live-drawing-plotter/deploy/kiosk.sh` を追加してください。

## コマンド一覧

以下の `$USER` には自分のユーザー名が自動で入ります。

| やりたいこと | コマンド |
|---|---|
| 動いているか、最後に止まった理由を見る | `systemctl status live-plotter@$USER.service` |
| ログを流して見る（Ctrl+C で表示を抜けても作品は止まらない） | `journalctl -u live-plotter@$USER.service -f` |
| 直近のログを見る | `journalctl -u live-plotter@$USER.service -n 50` |
| 止める（1 本描き終えてからペンを上げ、ホームへ） | `sudo systemctl stop live-plotter@$USER.service` |
| 再開する（記憶を読み込み、同じ紙の続きから） | `sudo systemctl start live-plotter@$USER.service` |
| 止めてすぐ起動し直す | `sudo systemctl restart live-plotter@$USER.service` |
| 紙を替える（ダッシュボードが使えないとき。停止 → 記憶を消す → 再開） | `bash deploy/new-paper.sh` |
| 電源投入時の自動起動をやめる（搬出入のとき） | `sudo systemctl disable live-plotter@$USER.service` |
| 自動起動を戻す | `sudo systemctl enable live-plotter@$USER.service` |

## 止め方の違い

- ダッシュボードの「一時停止」: 1 本描き終えたらペンを上げて待機します。本体は動いたままなので、「再開」で即座に続けられます。
- `systemctl stop`、Ctrl+C、プレビュー窓の `q`: 描画中の 1 本を描き終えてからペンを上げ、ホームに戻って切断します。次回はそのまま続きから描けます。
- AxiDraw 本体の一時停止ボタン: その場で即停止します（緊急停止）。**キャリッジの位置が失われる** ので、ダッシュボードの指示どおり手でキャリッジを左上の角へ戻してから「開始」を押してください。本体は AxiDraw に接続し直して続きから描きます。

## 障害時の振る舞い

| 状況 | ダッシュボードの表示 | 本体の動き |
|---|---|---|
| カメラが開けない、映像が 30 秒止まった | カメラが見つかりません | 5 秒ごとにカメラを開き直す。開けたら元の状態に戻る |
| AxiDraw に接続できない、接続が切れた | AxiDraw に接続できません | 5 秒ごとに接続し直す |
| 一時停止ボタン、USB 切断で途中停止 | AxiDraw が停止しました | 一時停止して待つ。手でホームに戻して「開始」を押すと接続し直して続きから描く |
| 映像処理が 10 回連続で失敗 | 映像の処理に失敗しています | カメラを開き直す |

中断の前後で描いた分は 1 本ごとに保存してあるので、復帰後は保存内容を読み直して続きから描きます。

systemd による再起動は、予期しない異常終了のときだけ起こります（`Restart=on-failure`、5 秒後）。正常終了（`--saturation-policy stop`、プレビューの `q`）は再起動しません。

## 描画済みの記憶（インクメモリ）

「紙のどこに描いたか」は `~/live-drawing-plotter/state/` に保存されます。

- `state/ink_canvas.png`: 紙の状態（白がインク）。画像として開いて確認できます。
- `state/state.json`: 紙サイズ、累計線長、サイクル数。

1 本描くごとに保存するので、電源断のあとも続きから描けます。紙を替えたときは `deploy/new-paper.sh` がこのディレクトリを消します。
紙サイズや余白の設定が保存時と違う場合は、保存内容を無視して白紙から始めます（ログに警告が出ます）。

## 起動オプションを変える

`/etc/systemd/system/live-plotter@.service` の `ExecStart` 行にオプションを足し、反映します。オプションの一覧は [options.md](options.md) にあります。

```bash
sudo systemctl daemon-reload && sudo systemctl restart live-plotter@$USER.service
```

## トラブルシューティング

- **AxiDraw に接続できない**: USB と電源を確認。実行ユーザーが `dialout` グループに入っている必要があります（`install-pi.sh` が追加しますが、反映には再起動が必要です）。
- **カメラが開けない**: Pi 5 は `/dev/video*` が多数あり、0 番が USB カメラとは限りません。`v4l2-ctl --list-devices` で確認し、`--source /dev/v4l/by-id/usb-...-video-index0` のように by-id のパスで指定すると差し替えに強くなります。
- **数分描いたら止まって動かない**: ダッシュボードの赤字を見てください。「AxiDraw が停止しました」なら一時停止ボタンか USB 切断です。キャリッジを手でホームに戻してから「開始」を押してください。
- **ダッシュボードが自動で出ない**: `bash deploy/kiosk.sh` を手で実行して表示されるか確認。表示されるなら自動起動の登録方法の問題です（上記）。
- **起動直後にノイズのような線を描く**: 自動露出が安定する前のフレームです。`--warmup` を 3 程度に増やしてください。
- **線が多すぎる／少なすぎる、同じ線を何度も描く**: [options.md](options.md) の「調整の目安」を参照。
