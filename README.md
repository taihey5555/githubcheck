# GitHub Check

GitHub で面白そうな repo を拾って Telegram に通知し、その履歴を GitHub Pages 向けの静的 archive として見返せる小さな運用用ツールです。

通知だけで終わらせず、`history`、`weekly`、`repo 詳細ページ` を通して「発見、選別、再利用しやすい archive」として使う前提で育てています。

## 概要

- GitHub Search API で新しめ、動いている repo を収集
- ローカルの `state.json` で stars 差分と review state を管理
- 独自スコアで候補を並べて Telegram に通知
- `docs/index.html` に履歴 archive を生成
- `docs/weekly.html` に週次 archive を生成
- `docs/repos/<slug>.html` に repo 詳細ページを生成

## 現在の主な機能

- 通知
  - GitHub Search API で候補収集
  - DeepSeek API で日本語要約と `pick_reason` を生成
  - Telegram へ朝枠 / 夜枠で通知
- history archive
  - repo 名検索
  - language / tag / review state フィルタ
  - stars / score 範囲フィルタ
  - sort `newest / score / stars`
  - `Copy filtered link` / `Open filtered link` / URL 表示
- weekly archive
  - 今週の総合トップ
  - 今週の low-stars / high-score
  - 今週の新着で面白かったもの
  - review state 分布
  - `good / production_candidate / unseen` への導線
- repo 詳細ページ
  - repo 基本情報
  - review state
  - `pick_reason`
  - Similar Repos
  - Related History の比較表示
- review-state CLI
  - `set / get / unset / list`
  - `list --state`
  - `list --prefix`

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
```

`.env` を作って必要な値を入れてください。

最低限必要:

- `GITHUB_TOKEN`
- `DEEPSEEK_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

主な任意設定:

- `PUBLIC_HISTORY_URL`
- `PUBLIC_WEEKLY_URL`
- `TOP_N`
- `NOTIFY_TIMES`
- `TIMEZONE`
- `TOPICS`
- `COLLECTION_PROFILE`
- `GITHUB_SEARCH_SORTS`
- `GRAY_SEARCH_TERM_LIMIT`
- `MIN_STARS`
- `COOLDOWN_DAYS`
- `LOW_STAR_HIGH_SCORE_MAX_STARS`
- `LOW_STAR_HIGH_SCORE_MIN_SCORE`
- `LOW_STAR_HIGH_SCORE_LIMIT`

## 実行方法

1 回だけ強制実行:

```bash
python bot.py once --force
```

常駐:

```bash
python bot.py daemon
```

Telegram 疎通確認:

```bash
python bot.py test-telegram
```

静的ページ再生成:

```bash
python bot.py render
```

Windows では、定時運用は `python bot.py once --force` をタスクスケジューラで回す方が安定します。

## review-state CLI

利用できる state:

- `unseen`
- `interested`
- `tested`
- `good`
- `meh`
- `production_candidate`

設定:

```bash
python bot.py review-state set owner/repo good
```

取得:

```bash
python bot.py review-state get owner/repo
```

解除:

```bash
python bot.py review-state unset owner/repo
```

一覧:

```bash
python bot.py review-state list
python bot.py review-state list --state good
python bot.py review-state list --prefix owner/
```

補足:

- 未設定 repo の `get` は `unseen (unset)` を返します
- `state.json` に `review_states` が無くても自動補完します
- 不正 state はエラー終了します

## history archive の見方

`docs/index.html` は通知履歴を見返すための主 archive です。

使えるフィルタ:

- `search`
- `language`
- `tag`
- `review state`
- `stars_min`
- `stars_max`
- `score_min`
- `score_max`
- `sort`

`Copy filtered link` を使うと、今見ている条件をそのまま再現できる URL をコピーできます。

`Open filtered link` は同じ URL をその場で開くための導線です。

## history query string 一覧

`index.html` は以下の query を受け取れます。

- `search`
- `review_state`
- `language`
- `tag`
- `stars_min`
- `stars_max`
- `score_min`
- `score_max`
- `sort`

例:

- `index.html?review_state=good&sort=score`
- `index.html?review_state=unseen&sort=newest`
- `index.html?stars_max=1000&score_min=70&sort=score`
- `index.html?language=python`
- `index.html?tag=agentic-ai`
- `index.html?search=cli`

ルール:

- 空値は無視
- 不正な state は無視
- 不正な数値や負数は無視
- `sort` は `newest / score / stars` のみ

## weekly archive の見方

`docs/weekly.html` は current week を見返す週次 archive です。

主な見どころ:

- 今週の `good / production_candidate`
- 今週の未確認 repo
- 今週の総合トップ
- 今週の low-stars / high-score
- 今週の新着で面白かったもの
- review state 分布

weekly からは、review state や low-stars / high-score 条件付きで `history` に戻れます。

## repo 詳細ページの見方

`docs/repos/<slug>.html` は repo ごとの静的詳細ページです。

主な内容:

- repo 基本情報
- review state
- `pick_reason`
- description
- latest x post
- topics
- 初回出現日時 / 最新出現日時 / 出現回数
- Similar Repos
- Related History

### Similar Repos

既存の archive データだけを使って、近い repo を軽く並べています。

優先する要素:

- 同じ language
- 共通 topics / tags
- review state は軽い tie-breaker

### Related History

同じ repo の履歴を新しい順に並べます。

比較表示として以下を出します。

- 通知日時
- score
- stars
- bucket
- pick_reason
- review state
- language
- topics
- score 前回比
- stars 前回比
- pick_reason の変化
- topic の増減

## よく使う URL 例

```text
index.html?review_state=good&sort=score
index.html?review_state=unseen&sort=newest
index.html?stars_max=1000&score_min=70&sort=score
index.html?language=python
index.html?tag=agentic-ai
index.html?search=cli
```

## 運用メモ

- `state.json`
  - `repos`: stars 追跡用
  - `notifications`: 通知履歴と抑止用
  - `review_states`: 手動 review state 管理用
- `docs/history.json`
  - archive と weekly の元データです
- `docs/*.html`
  - 生成物です
  - 直接編集せず `python bot.py render` で再生成してください
- low-stars / high-score の閾値は `.env` で外出し済みです
- Pages 側では保存せず、ローカルで `state.json` を更新してから `render` する運用です

## ランキング基準

通知候補の repo は以下をもとに点数化しています。

- 前回観測時からの star 増加
- repo の新しさ
- 最近 push されているか
- `ai`, `cli`, `automation`, `security`, `developer-tools` への一致
- README があるか
- 現在の star 数

時間帯ごとの違い:

- 朝 `09:00`: 新顔寄り
- 夜 `20:00`: 尖り寄り

週間ランキングは、週内の `pick 回数 / 最高 score / stars` を使って見返しやすい順に並べています。

## グレー系ランキング

`COLLECTION_PROFILE=gray` にすると、通常の技術トレンド収集ではなく、合法寄りだが際どい OSS を拾うランキングに切り替わります。

対象例:

- 成人向けAI / モザイク・画像・動画復元
- スクレイパー / ダウンローダー / 抽出ツール
- 逆解析 / modding / patcher / 非公式client
- 制限回避やポリシー回避に近いツール
- 防御・検証寄りのセキュリティ研究

明確な認証情報窃取、マルウェア、CSAM、侵入・悪用手順中心の repo は除外または `needs_review` 扱いにします。

使う設定例:

```env
COLLECTION_PROFILE=gray
TOP_N=10
GITHUB_SEARCH_SORTS=stars,updated
GRAY_SEARCH_TERM_LIMIT=16
```

gray mode の score は以下を合成します。

- `grey_score`: グレー度
- `attention_score`: stars、forks、star増加、直近push
- `freshness_score`: 作成日と更新日の新しさ

通知には分類ラベル、要確認フラグ、score内訳、選定理由を含めます。

## Skill

repo ローカルの skill は `skills/repo-digest/SKILL.md` だけです。
