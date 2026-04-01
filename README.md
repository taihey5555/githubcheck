# GitHub Interesting Repo Notifier

GitHubで面白そうなリポジトリを拾って、DeepSeek APIで日本語要約し、決まった時刻にTelegramへ通知する最小構成です。

## できること

- GitHub Search APIで新しめ・動いているrepoを収集
- ローカルの `state.json` を使って star 増加をざっくり追跡
- 独自スコアで「面白そう」順に並べる
- DeepSeek APIで日本語要約を生成
- Telegram Botへ定時通知
- 同じrepoの連続通知を抑止

## 前提

- Python 3.11+
- GitHub Personal Access Token
- DeepSeek API Key
- Telegram Bot Token
- Telegram Chat ID

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`.env` を埋めてください。

## 実行

1回だけ実行:

```bash
python bot.py once
```

常駐して定時通知:

```bash
python bot.py daemon
```

Windowsならタスクスケジューラで `python bot.py once` を時刻指定で回す方が安定します。

## ランキング基準

### 通常通知

通知候補の repo は以下をもとに点数化しています。

- 前回観測時からの star 増加
- repo の新しさ
- 最近 push されているか
- `ai`, `cli`, `automation`, `security`, `developer-tools` への一致
- README があるか
- 現在の star 数

要するに、最近伸びていて、新しく、ちゃんと動いている repo を優先します。

時間帯ごとの違い:

- 朝 `09:00`: 新顔寄り。star増加、新しさ、最近の活動を重めに見ます。
- 夜 `20:00`: 尖り寄り。ニッチさ、変わり種キーワード、技術的なクセを重めに見ます。

### 週間トップ10

週間トップ10は、直前1週間に通知した履歴から集計します。

- その週に何回ピックされたか
- その repo の最高 score
- star 数

その週に継続して強かった repo が上に来る仕組みです。

## 軽い Agent 性

この bot には大きな自律制御は入れておらず、軽い agent 層として `pick_reason` だけを追加しています。
`pick_reason` は「なぜこの repo を拾ったか」を短く示す補助情報で、Telegram 通知と履歴ページで使います。
これは大規模な multi-agent 化ではなく、既存の通知フローに薄く理由付けを足しただけの最小拡張です。

## Skill

repo ローカルの skill は `skills/repo-digest/SKILL.md` だけです。
通知文、`pick_reason`、履歴メタの拡張を最小変更で扱う時の方針だけを持たせています。
