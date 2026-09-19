# hanas 仕様策定時の検証記録

検証日: 2026-09-19（Asia/Tokyo）

関連文書: [実装指示書](../IMPLEMENTATION.md)

第 1〜7 節は実装前の成立性確認である。実装後の自動検証結果は第 8 節に追記する。実 Engine を使う製品動作はまだ検証していない。

## 1. 確認した環境

| 項目                          | 結果                                                                        |
| ----------------------------- | --------------------------------------------------------------------------- |
| OS                            | NixOS 26.11、ビルド `26.11.20260917.e554fab`                                |
| セッション                    | `XDG_SESSION_TYPE=wayland`、`XDG_CURRENT_DESKTOP=niri`                      |
| Wayland                       | `WAYLAND_DISPLAY=wayland-1`                                                 |
| runtime ディレクトリ          | `/run/user/1000`                                                            |
| Python                        | 3.14.7                                                                      |
| wl-clipboard                  | 2.3.0                                                                       |
| pw-play                       | libpipewire 1.6.8 でビルド・リンク                                          |
| niri                          | unstable 2026-08-02、commit `feb3e43f1475e0865bb89cbd1e898b34d1d2ccf6`      |
| systemd                       | 261.2                                                                       |
| 利用可能なコマンド            | `python3`, `curl`, `wl-paste`, `pw-play`, `niri`, `systemctl`, `nix`, `git` |
| PATH 上で見つからなかったもの | `docker`, `podman`, `cargo`, `rustc`, `uv`, `wayland-info`, `pactl`         |

コマンドが PATH にないことは、システム全体に一切インストールされていないことまでは意味しない。

作業開始時、アプリの実装ファイルはなかった。`git status --short` は終了コード 128、`not a git repository`。`.git` というディレクトリの存在だけで Git 管理済みと判断しない。

## 2. TTS エンジンへの接続確認

Python 標準ライブラリで proxy を無効にし、各 URL へ 2 秒の timeout で GET した。

| URL                              | 実測結果                        |
| -------------------------------- | ------------------------------- |
| `http://127.0.0.1:10101/version` | `Connection refused`、errno 111 |
| `http://127.0.0.1:50021/version` | `Connection refused`、errno 111 |

最初のサンドボックス内の接続試行は `Operation not permitted` だった。これをエンジン停止の証拠にはせず、権限制約外で読み取り専用の GET をやり直して、上表の結果を得た。

判断: 検証時点の標準ポートでは API を利用できない。TTS の音質や速度は測定できなかった。別ポート、リモートエンジン、モデルの配置、GPU の有無は調査していない。

再現用コマンド（読み取り専用）:

```sh
curl --noproxy '*' --connect-timeout 2 --max-time 3 --fail --silent --show-error \
  http://127.0.0.1:10101/version
curl --noproxy '*' --connect-timeout 2 --max-time 3 --fail --silent --show-error \
  http://127.0.0.1:50021/version
```

モデル・コンテナイメージのダウンロード、エンジンのインストール、サービスの有効化は行っていない。

## 3. Wayland のクリップボード形式

以下を各 3 秒の timeout 付きで実行した。クリップボードの本文は読み取っていない。

```sh
wl-paste --primary --list-types
wl-paste --list-types
```

| 対象                 | 終了コード | 確認できた形式の抜粋                                                 |
| -------------------- | ---------- | -------------------------------------------------------------------- |
| PRIMARY selection    | 0          | `text/plain;charset=utf-8`, `text/plain`, `text/html`, `UTF8_STRING` |
| 通常のクリップボード | 0          | `text/plain;charset=utf-8`, `text/plain`, `text/html`                |

判断: 現在の niri セッションで両方の選択バッファへアクセスでき、テキスト形式が提示されている。全アプリで「現在選択中の本文」を取得できることは未確認。ブラウザ・ターミナルそれぞれの実データ転送は実装後の手動試験に残す。

`wl-paste --help` で `--primary`、`--no-newline`、`--type`、`--list-types` の存在も確認した。[公式マニュアル](https://github.com/bugaevc/wl-clipboard/blob/master/data/wl-clipboard.1)

## 4. PipeWire への再生

Python の `wave` モジュールで次の WAV を一時ディレクトリに作成し、`pw-play` に渡した。

- 24,000 Hz、モノラル、16 bit PCM。
- 長さ 0.2 秒、全サンプル 0 の無音。
- `pw-play` の実行期限は 5 秒。

結果: 終了コード 0、標準エラーなし。子プロセス開始から終了までの観測値は 367 ms。一時 WAV は検証後に削除した。

これは WAV ファイルから PipeWire へ再生する経路の確認であり、実際に音が聞こえること、選択されている出力機器の妥当性、TTS の発話遅延を確認したものではない。367 ms を再生開始遅延として使ってはいけない。

再現用の Python コード:

```python
import subprocess
import tempfile
import wave
from pathlib import Path

with tempfile.TemporaryDirectory(prefix="hanas-audio-probe-") as directory:
    path = Path(directory) / "silence.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\0\0" * 4800)
    subprocess.run(["pw-play", str(path)], check=True, timeout=5)
```

公式マニュアルでも `pw-play` によるファイル再生が説明されている。[PipeWire pw-cat / pw-play](https://docs.pipewire.org/page_man_pw-cat_1.html)

## 5. niri のキー設定例

[実装指示書](../IMPLEMENTATION.md) の KDL ブロックだけを一時ファイルに保存して実行した。

```sh
niri validate --config /tmp/EXAMPLE/niri.kdl
```

結果: 終了コード 0、`config is valid`。

現在のユーザー設定は変更していない。これは `repeat=false`、キー指定、`spawn` 引数の構文検証であり、既存キーとの競合や、まだ存在しない `hanas` の実行確認ではない。[niri 公式キー設定](https://github.com/niri-wm/niri/wiki/Configuration:-Key-Bindings)

## 6. 公式資料・コードの調査

以下は 2026-09-19 に閲覧した資料に基づく。`master` は変化するため、実装時に採用するリリースの API と照合する。ローカルで動くエンジンのバージョンは確認できていない。

| 調査結果                                               | 仕様への反映                                                      | 根拠                                                                                                                                                                                         |
| ------------------------------------------------------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AivisSpeech Engine は Linux / CPU と公式コンテナに対応 | エンジン単体を第一候補とする。コンテナ利用には別途 runtime が必要 | [公式 README](https://github.com/Aivis-Project/AivisSpeech-Engine)                                                                                                                           |
| 基本経路は `/audio_query` と `/synthesis`              | この 2 API を共通アダプターの中心にする                           | [AivisSpeech ルーター](https://github.com/Aivis-Project/AivisSpeech-Engine/blob/master/voicevox_engine/app/routers/tts_pipeline.py)、[VOICEVOX](https://github.com/VOICEVOX/voicevox_engine) |
| AivisSpeech の通常 synthesis は全 WAV を作って応答する | 文単位の先読みを行う。音声の逐次応答を前提にしない                | [ルーター実装](https://github.com/Aivis-Project/AivisSpeech-Engine/blob/master/voicevox_engine/app/routers/tts_pipeline.py)                                                                  |
| AivisSpeech の cancellable synthesis は 501            | stop は再生停止と結果無効化で実現                                 | [ルーター実装](https://github.com/Aivis-Project/AivisSpeech-Engine/blob/master/voicevox_engine/app/routers/tts_pipeline.py)                                                                  |
| AivisSpeech のスタイル ID は符号付き 32 bit            | 正数限定や配列番号として扱わない                                  | [API 互換性](https://github.com/Aivis-Project/AivisSpeech-Engine#voicevox-api-との互換性について)                                                                                            |
| `kana` の意味と独自フィールドが VOICEVOX と異なる      | AudioQuery をそのまま保持し、話速のみ変更                         | [API 互換性](https://github.com/Aivis-Project/AivisSpeech-Engine#voicevox-api-との互換性について)                                                                                            |
| AivisSpeech の speedScale は正の有限数として検証される | NaN / Inf / 0 / 負数を拒否。製品側は 0.5〜2.0 に限定              | [AudioQuery モデル](https://github.com/Aivis-Project/AivisSpeech-Engine/blob/master/voicevox_engine/model.py)                                                                                |

VOICEVOX の資料にはストリーミング・キャンセル API の説明もあるが、AivisSpeech と共通に使用できる根拠にはならない。初版では利用しない。

## 7. 未検証事項と実装後の記録項目

| 項目                       | 現状         | 次に記録するもの                                            |
| -------------------------- | ------------ | ----------------------------------------------------------- |
| AivisSpeech 導入           | 1.2.0で発話確認済み | モデル名、コールド時・ウォーム時の所要時間             |
| 音質・話速                 | 既定速度で発話確認済み | 速度変更時の聴感                                        |
| 合成速度                   | 未計測       | 初回・2 回目以降の先頭再生までの時間、入力文字数、CPU / GPU |
| 文分割                     | 設計のみ     | 文間の不自然さ、チャンク長、URL やコードでの挙動            |
| stop / 置き換え            | 再生中の実機確認済み | 合成中・先読み中それぞれの競合試験                         |
| ブラウザ・ターミナルの選択 | 形式列挙のみ | アプリ名と版、既知の選択文字列での取得結果                  |
| systemd user service       | 未導入       | セッション開始・終了、PATH、PipeWire 接続、再起動           |
| VOICEVOX 互換              | 資料確認のみ | 実エンジンの版、話者、基本 API の成功                       |

## 8. 実装後の自動検証

Python 標準ライブラリの `unittest` により、次を偽 HTTP Engine と状態単体テストで確認した。

- ANSI CSI / OSC 除去、UTF-8・サイズ制限、分割後の文字の欠落・重複がないこと。
- 未知 AudioQuery フィールドを保持し、話速だけを変更すること。
- 日本語、改行、`&`、`?` の URL エンコードと負のスタイル ID。
- 設定の未知キー・不正速度の拒否。
- 置き換え・停止によるキャンセルと待機キュー上限。

実行コマンド:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

自動テスト作成時には AivisSpeech / VOICEVOX が停止していた。その後、ユーザーが AivisSpeech Engine 1.2.0 のNix derivationを起動し、スタイル ID `1878365378` による実際の読み上げを確認した。再生中の `stop` が機能することと、通常の読み上げ要求を連続送信すると先の音声が中断されて新しい音声へ置き換わることも確認した。モデル名、計測時間、合成中・先読み中の競合、VOICEVOXは引き続き未検証である。ユーザーの systemd / niri 設定は自動変更していない。

### Plainix / AivisSpeech derivation 準備確認

`plainix.nix` に `curl`、`pipewire`、`wl-clipboard` を追加した。Plainix の `packages` は nixpkgs のパッケージ名を受け取るため、独自の AivisSpeech Engine は `nix/aivisspeech-engine.nix` と flake の `packages` / `apps` 出力として定義した。

AivisSpeech Engine 1.2.0 の公式 Linux x64 バイナリを固定ハッシュで取得し、`nix build .#aivisspeech-engine` が成功すること、生成された `aivisspeech-engine --help` が NixOS 上で終了コード 0 になることを確認した。その後の Engine 本起動とスタイル ID `1878365378` による可聴な読み上げはユーザーが確認した。再現手順は README の「AivisSpeech Engine で検証する」に記載した。

`nix/hanas.nix` も追加し、`nix build .#hanas` 内で9件の自動テストが成功すること、生成物のCLIがバージョンを表示できること、systemd user unitの `ExecStart` がNix store内の絶対パスになることを確認した。
