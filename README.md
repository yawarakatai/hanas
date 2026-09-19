# hanas

選択範囲、クリップボード、標準入力、または引数の文章を AivisSpeech / VOICEVOX で読み上げる Linux 向けツールです。daemon がキューと `pw-play` を一元管理します。Python 3.11 以上、Wayland の入力取得には `wl-paste`、再生には PipeWire の `pw-play`、デスクトップ通知には `notify-send` が必要です。

## 開発環境

依存コマンドは `plainix.nix` で管理しています。

```sh
nix develop
uv sync
uv run hanas --help
```

`nix develop` には Python、`uv`、`wl-paste`、`pw-play`、`notify-send` が含まれます。hanas 自体の Python 実行時依存は標準ライブラリだけです。

## AivisSpeech Engine で検証する

`nix/aivisspeech-engine.nix` は公式 Linux x64 バイナリを固定ハッシュで取得し、NixOS で動くよう ELF をパッチする derivation です。コンテナランタイムは不要です。現時点では x86_64 Linux の CPU 実行を対象とします。

```sh
# ビルドだけ行う場合
nix build .#aivisspeech-engine

# Engine 1.2.0 を loopback で起動する場合
nix run .#aivisspeech-engine -- \
  --host 127.0.0.1 \
  --port 10101 \
  --disable_sentry
```

初回はデフォルト音声モデル（約 250 MB）と BERT モデル（約 650 MB）がダウンロードされるため、起動に数分かかる場合があります。モデルとキャッシュは `~/.local/share/AivisSpeech-Engine` に保存され、derivation の再ビルド後も残ります。Engine のログに起動完了が表示されたら、別のターミナルで疎通と話者を確認します。

```sh
nix develop
curl --noproxy '*' --fail http://127.0.0.1:10101/version
uv run hanas voices
```

表示されたスタイル ID を使い、まず設定ファイルを変更せずに一連の経路を確認できます。

```sh
# ターミナル1
uv run hanas daemon

# ターミナル2（VOICE_ID は `hanas voices` の先頭列など実在する値）
uv run hanas speak --wait --style-id VOICE_ID "AivisSpeech の動作確認です。"
uv run hanas status
```

音が出たら `config.example.toml` を設定先へコピーし、`style_id` を設定します。停止・置き換え・キューも次のように確認できます。

```sh
uv run hanas speak --style-id VOICE_ID "これは置き換え前の文章です。少し長めに読み上げます。"
uv run hanas speak --style-id VOICE_ID "こちらに置き換わります。"
uv run hanas speak --enqueue --style-id VOICE_ID "これはキューの末尾です。"
uv run hanas stop
```

利用した Engine と Nix store path を記録する場合:

```sh
curl --noproxy '*' --fail http://127.0.0.1:10101/version
nix build .#aivisspeech-engine --no-link --print-out-paths
```

終了は Engine 側のターミナルで Ctrl-C です。Engine derivation は実行ファイルだけを管理し、ユーザーのモデルデータやサービス設定を変更しません。

VOICEVOX を使う場合は Engine を別途起動し、設定 URL を通常 `http://127.0.0.1:50021` にします。

## 設定

`config.example.toml` を `$XDG_CONFIG_HOME/hanas/config.toml`（通常 `~/.config/hanas/config.toml`）へコピーします。今回の AivisSpeech 1.2.0 による実機確認ではスタイル ID `1878365378` を使用しました。

```sh
mkdir -p ~/.config/hanas
cp config.example.toml ~/.config/hanas/config.toml
$EDITOR ~/.config/hanas/config.toml
```

```toml
[engine]
url = "http://127.0.0.1:10101"
style_id = 1878365378
speed = 1.0
```

別のモデルを利用するときは `hanas voices` の先頭列を確認して `style_id` を変更してください。`style_id` と `speed` はすべての読み上げの既定値になり、必要な場合だけ `speak` のオプションで一時的に上書きできます。

スタイル未設定でも daemon と `voices` は起動できますが、`speak` は明示的な `--style-id` がなければ拒否されます。daemon は読み上げリクエストごとに設定ファイルを再読み込みするため、設定変更後の再起動は不要です。変更後に受け付けた読み上げから新しい設定が反映されます。設定ファイルに誤りがある場合、その読み上げは拒否されますが、修正すれば次のリクエストから復旧します。

## デスクトップ通知

再生開始時と、入力・Engine接続・音声合成・再生の失敗時にデスクトップ通知を表示します。通知の失敗によって読み上げが失敗することはありません。Nixパッケージには通知用の `notify-send` が含まれます。

## 利用方法

```sh
hanas daemon
hanas speak "処理が終わりました。"
hanas speak --selection
hanas speak --clipboard
hanas speak --stdin < text.txt
hanas speak --enqueue "次に読む文章"
hanas speak --wait --speed 1.2 --style-id 123 "確認です"
hanas stop
hanas status
hanas status --json
```

通常の `speak` は job の受理時点で ID を出して終了し、現在の読み上げと待機列を置き換えます。`--enqueue` は FIFO の末尾へ追加します。完了結果が必要なら `--wait` を使います。PRIMARY selection はアプリによって提供されない場合があります。その場合はコピー後に `--clipboard` を使ってください。

終了コードは 0（成功）、2（入力・設定）、3（daemon / Engine 接続）、4（合成・再生）、5（待機中 job のキャンセル）です。

## Nixパッケージ・systemd user service

日常利用向けに hanas と実行時の `pw-play` / `wl-paste` をまとめたパッケージをインストールできます。

```sh
nix profile add .#hanas
hanas --version
```

パッケージ内のuser serviceを有効にします。シンボリックリンク先にはNix storeの絶対パスを使うため、serviceの `ExecStart` も開発ディレクトリに依存しません。

```sh
mkdir -p ~/.config/systemd/user
ln -sfn "$(readlink -f ~/.nix-profile/share/systemd/user/hanas.service)" \
  ~/.config/systemd/user/hanas.service
systemctl --user daemon-reload
systemctl --user enable --now hanas.service
systemctl --user status hanas.service
```

AivisSpeech Engineは別プロセスとして先に起動してください。パッケージを更新した場合は次を実行します。

```sh
nix profile upgrade hanas
systemctl --user daemon-reload
systemctl --user restart hanas.service
```

niri の例は `examples/niri.kdl` にあります。既存の `binds` に内容を統合し、キー競合を確認してください。ユーザー設定は自動変更されません。

ショートカットからの標準エラーは通常画面に表示されません。問題時は次を確認します。

```sh
hanas status
journalctl --user -u hanas.service
# 選択取得など送信前の問題はターミナルで同じコマンドを再実行
hanas speak --selection
```

## テスト

```sh
uv run python -m unittest discover -s tests -v
```

実 Engine を使う確認状況は `docs/VALIDATION.md` を参照してください。
