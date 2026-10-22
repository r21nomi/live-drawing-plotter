# live-drawing-plotter

Web カメラが捉えた風景を、AxiDraw ペンプロッターでリアルタイムに描き続ける作品です。
一度動き出すと、風景が変わるたびに新しい輪郭だけを紙に描き足していきます。操作は要りません。

- 機材: Raspberry Pi 5、USB ウェブカメラ、AxiDraw V3（A4 横）
- 詳しい説明: [運用ガイド](docs/operations.md) / [オプションと調整](docs/options.md) / [開発者向け](docs/development.md)

## 初回のセットアップ（1 回だけ）

1. Raspberry Pi に USB ウェブカメラと AxiDraw をつなぎ、AxiDraw の電源を入れる。
2. このプロジェクトを Pi の `~/live-drawing-plotter` に置く。
3. セットアップスクリプトを実行する（Python 環境、AxiDraw API、シリアル権限、自動起動の登録をまとめて行います）。

```bash
bash deploy/install-pi.sh
```

4. 再起動する。

```bash
sudo reboot
```

これで、以後は Pi の電源を入れるだけで自動的に描き始めます。

## 日々の運用

### 描画を始める

1. 紙をセットし、ペン先を紙の左上の角（AxiDraw のホーム位置）に合わせる。
2. Pi の電源を入れる。

それだけです。起動から 1 分ほどで描き始めます。コマンドを打つ必要はありません。

### 描画を止める

```bash
sudo systemctl stop live-plotter@$USER.service
```

描画中の 1 本を描き終えてからペンを上げ、ホームに戻って止まります。再開は `stop` を `start` に替えて実行します。電源を切る前に止めてください。

### 紙を替える

紙を替えるときは「前の紙にどこまで描いたか」の記憶も消す必要があります。次のスクリプトが停止、記憶の消去、再開までを行います。

```bash
bash deploy/new-paper.sh
```

### 困ったとき

- ペンが動かない: ログを見る。`journalctl -u live-plotter@$USER.service -n 50`
- AxiDraw の一時停止ボタンを押した、または途中で止まった: キャリッジを手で左上の角に戻してから `sudo systemctl start live-plotter@$USER.service`
- それ以外は [運用ガイド](docs/operations.md) のトラブルシューティングへ。
