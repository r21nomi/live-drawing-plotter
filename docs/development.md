# 開発者向け

## 仕組み

1. カメラの最新フレームからエッジ（輪郭線）を抽出し、ペンの軌跡（ポリライン）に変換して紙の座標（mm）に写像します。
2. 「紙の上にすでに描いた場所」をラスタ（インクキャンバス）として記憶しています。
   まだ白い場所を多く通る線を優先して、1 サイクルあたりの線長予算（既定 400mm）のぶんだけ描きます。
3. 描いた線をインクキャンバスに記録して保存し、次のサイクルへ。

風景が変わらなければ新しく描くものがほとんどなく、ペンは自然に止まります。
風景が変わると、新しい輪郭のうちまだ白い場所だけを描き始めます。紙の上には「変化だけ」が積み重なります。

```
live_plotter/
  camera.py        最新フレームだけを保持する取り込みスレッド（--source で動画/画像ファイルも可）
  vectorize.py     フレーム → エッジ → ポリライン（ピクセル）→ 紙座標 mm
  ink_canvas.py    描画済みラスタ、新規性スコア、被覆率
  path_planning.py 線長予算内で新規性の高い線を選び、ペンアップ移動が短くなる順に並べる
  plotter.py       AxiDrawPlotter（pyaxidraw 対話 API）と DryRunPlotter（ハードウェアなし）
  persistence.py   インクキャンバスの保存と復元
  preview.py       プレビュー窓（カメラ | エッジ | 紙）。ヘッドレスでは自動で無効
  controls.py      一時停止・再開・新しい紙の指示（ロック付きの共有状態）
  status.py        いまの状態（サイクル、候補数、被覆率など）
  dashboard.py     ダッシュボードの HTTP サーバー（ページ、MJPEG、状態、操作）
  dashboard_page.py ダッシュボードの HTML
  main.py          メインループと CLI
deploy/
  install-pi.sh                Pi の初回セットアップ
  new-paper.sh                 紙の交換（停止 → 記憶消去 → 再起動）。ダッシュボードが使えないとき用
  live-plotter.service         systemd ユニット
  kiosk.sh / *.desktop         ダッシュボードを Chromium のキオスクモードで表示
```

## Mac での開発

```bash
uv sync --all-extras
```

AxiDraw なしで動かすには `--dry-run` を付けます。ペンの移動時間をスリープで模倣し、プレビュー窓に「紙の上の描画結果」を再現します。

```bash
uv run live-plotter --dry-run --autostart
```

`--autostart` を付けないと、ダッシュボード（`http://localhost:8080/`）の「開始」を押すまで描き始めません。
カメラの権限を求められたら許可してください（ターミナルアプリにカメラ権限が必要です）。

カメラなしでも試せます。画像ファイルは静止風景として、動画ファイルはループ再生されます。オプション調整に便利です。

```bash
uv run live-plotter --dry-run --autostart --source path/to/scene.png
```

Mac から実機の AxiDraw を動かすこともできます。`--dry-run` を外すだけです。

ダッシュボードは Mac でも `http://localhost:8080/` で開けます。標準ライブラリの `http.server` を別スレッドで動かし、
`/`（ページ）、`/camera.mjpg`（MJPEG）、`/paper.jpg`、`/edges.jpg`、`/status.json`、`POST /control`（`{"action": "pause"|"resume"|"new_paper"}`）を提供します。
メインループは 1 本描くごとに一時停止の指示を確認し、`dashboard.update()` で紙の状態と状況を送ります。

## テスト

```bash
uv run pytest
```

画像処理、インクキャンバス、経路計画、永続化、メインループは純粋関数として単体テストされています。
AxiDraw の層は pyaxidraw を模したフェイクで、カメラの層は画像・動画ファイルでテストしています。

## 依存関係

- OpenCV、numpy
- pyaxidraw（AxiDraw 公式 API）。PyPI にはなく、Evil Mad Scientist 配布の zip から入ります。`pyproject.toml` の extra `axidraw` に定義してあり、`uv sync --extra axidraw` で入ります。
- Python 3.11 以上（Raspberry Pi OS Bookworm の標準に合わせています）。
