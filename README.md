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
