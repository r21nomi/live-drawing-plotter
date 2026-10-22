# 運用ガイド（Raspberry Pi）

README の「日々の運用」で足りない場合に読むページです。

## 起動の仕組み

`deploy/install-pi.sh` が systemd のサービス `live-plotter@ユーザー名.service` を登録します。
Pi の電源が入るとこのサービスが自動で起動し、カメラを開き、AxiDraw に接続して描き始めます。
`uv run live-plotter` を手で実行するのは、オプションを試すときだけです。その場合は先にサービスを止めてください（カメラと AxiDraw を 2 つのプロセスで取り合うため）。

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
| 紙を替える（停止 → 記憶を消す → 再開） | `bash deploy/new-paper.sh` |
| 電源投入時の自動起動をやめる（搬出入のとき） | `sudo systemctl disable live-plotter@$USER.service` |
| 自動起動を戻す | `sudo systemctl enable live-plotter@$USER.service` |

## 止め方の違い

- `systemctl stop`、Ctrl+C、プレビュー窓の `q`: 描画中の 1 本を描き終えてからペンを上げ、ホームに戻って切断します。次回はそのまま続きから描けます。
- AxiDraw 本体の一時停止ボタン: その場で即停止します（緊急停止）。**キャリッジの位置が失われる** ので、次に起動する前に手でキャリッジを左上の角へ戻してください。この場合は自動再起動しません。

## 自動再起動と終了コード

| コード | 意味 | systemd の扱い |
|---|---|---|
| 0 | 正常終了（`--saturation-policy stop`、プレビューの `q`） | 再起動しない |
| 1 | カメラや AxiDraw が見つからない、画像処理が連続して失敗、カメラ映像が 30 秒止まった | 5 秒後に再起動 |
| 75 | 一時停止ボタンまたは USB 切断で途中停止。位置が不明 | 再起動しない。手でホームに戻してから `start` |

再起動後は保存してある「描画済みの記憶」を読み込むので、同じ紙の続きから描きます。

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
- **数分描いたら止まって動かない**: `systemctl status` で終了コードを確認。75 なら一時停止ボタンか USB 切断です。キャリッジを手でホームに戻してから `start` してください。
- **起動直後にノイズのような線を描く**: 自動露出が安定する前のフレームです。`--warmup` を 3 程度に増やしてください。
- **線が多すぎる／少なすぎる、同じ線を何度も描く**: [options.md](options.md) の「調整の目安」を参照。
