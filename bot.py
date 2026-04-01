import json
import os
import sys
import time
from html import escape
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
DOCS_DIR = ROOT / "docs"
HISTORY_PATH = DOCS_DIR / "history.json"
GITHUB_API = "https://api.github.com"
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"

TOPIC_KEYWORDS = {
    "ai": ["ai", "llm", "agent", "rag", "inference", "model"],
    "cli": ["cli", "terminal", "shell", "tui"],
    "automation": ["automation", "workflow", "bot", "scheduler"],
    "security": ["security", "pentest", "auth", "sandbox", "crypto"],
    "developer-tools": ["developer", "devtools", "tooling", "debug", "build"],
}


@dataclass
class Config:
    github_token: str
    deepseek_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    public_history_url: str
    top_n: int
    notify_times: list[str]
    timezone: str
    topics: list[str]
    min_stars: int
    cooldown_days: int


def load_config() -> Config:
    load_dotenv()
    return Config(
        github_token=require_env("GITHUB_TOKEN"),
        deepseek_api_key=require_env("DEEPSEEK_API_KEY"),
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=require_env("TELEGRAM_CHAT_ID"),
        public_history_url=os.getenv("PUBLIC_HISTORY_URL", "").strip(),
        top_n=int(os.getenv("TOP_N", "3")),
        notify_times=parse_csv(os.getenv("NOTIFY_TIMES", "09:00")),
        timezone=os.getenv("TIMEZONE", "Asia/Tokyo"),
        topics=parse_csv(os.getenv("TOPICS", "ai,cli,automation")),
        min_stars=int(os.getenv("MIN_STARS", "30")),
        cooldown_days=int(os.getenv("COOLDOWN_DAYS", "14")),
    )


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"repos": {}, "notifications": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def save_history(history: list[dict[str, Any]]) -> None:
    DOCS_DIR.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def github_headers(config: Config) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config.github_token}",
        "User-Agent": "github-interesting-repo-notifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def build_search_queries(config: Config, now_utc: datetime) -> list[str]:
    created_after = (now_utc - timedelta(days=90)).date().isoformat()
    pushed_after = (now_utc - timedelta(days=14)).date().isoformat()
    queries = []
    for topic in config.topics:
        queries.append(
            " ".join(
                [
                    f"stars:>={config.min_stars}",
                    f"created:>={created_after}",
                    f"pushed:>={pushed_after}",
                    "archived:false",
                    "fork:false",
                    topic,
                ]
            )
        )
    return queries


def search_repositories(config: Config) -> list[dict[str, Any]]:
    now_utc = datetime.now(UTC)
    repos_by_name: dict[str, dict[str, Any]] = {}
    for query in build_search_queries(config, now_utc):
        response = requests.get(
            f"{GITHUB_API}/search/repositories",
            headers=github_headers(config),
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": 15,
            },
            timeout=30,
        )
        response.raise_for_status()
        for item in response.json().get("items", []):
            repos_by_name[item["full_name"]] = item
    return list(repos_by_name.values())


def fetch_readme(config: Config, owner: str, repo: str) -> str:
    response = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/readme",
        headers={
            **github_headers(config),
            "Accept": "application/vnd.github.raw+json",
        },
        timeout=30,
    )
    if response.status_code != 200:
        return ""
    return response.text[:8000]


def days_since(iso_value: str) -> int:
    dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    return max(0, (datetime.now(UTC) - dt).days)


def score_repo(repo: dict[str, Any], state: dict[str, Any], config: Config) -> float:
    repo_state = state["repos"].get(repo["full_name"], {})
    current_stars = repo["stargazers_count"]
    previous_stars = repo_state.get("last_stars", current_stars)
    star_growth = max(0, current_stars - previous_stars)

    created_days = days_since(repo["created_at"])
    pushed_days = days_since(repo["pushed_at"])
    description = (repo.get("description") or "").lower()
    topics = " ".join(repo.get("topics") or []).lower()
    text = f"{description} {topics}"

    niche_bonus = 0
    for topic_name in config.topics:
        for keyword in TOPIC_KEYWORDS.get(topic_name, []):
            if keyword in text:
                niche_bonus += 1

    readme_bonus = 3 if repo.get("_readme_text") else 0
    freshness = max(0, 90 - created_days) / 90
    activity = max(0, 14 - pushed_days) / 14

    score = 0.0
    score += star_growth * 0.45
    score += freshness * 20
    score += activity * 20
    score += niche_bonus * 2
    score += readme_bonus
    score += min(repo["stargazers_count"], 500) * 0.03
    return round(score, 2)


def should_skip(repo: dict[str, Any], state: dict[str, Any], config: Config) -> bool:
    notification = state["notifications"].get(repo["full_name"])
    if not notification:
        return False
    last_sent = datetime.fromisoformat(notification["last_sent"])
    return datetime.now(UTC) - last_sent < timedelta(days=config.cooldown_days)


def build_deepseek_summary(config: Config, repo: dict[str, Any]) -> str:
    prompt = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "あなたはGitHubの新しい技術トレンドを紹介する編集者です。"
                    "要点を短く、具体的に、日本語で書いてください。"
                    "X投稿文はクリックしたくなるが誇張しない文にしてください。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "以下のGitHubリポジトリを日本語で要約してください。\n"
                    "出力は必ず次の形式にしてください。\n\n"
                    "[telegram]\n"
                    "1行目: 何が面白いかを20文字前後で\n"
                    "2行目: どんな用途かを1文\n"
                    "3行目: 技術的な見どころを1文\n"
                    "4行目: どういう人に刺さるかを1文\n\n"
                    "[x]\n"
                    "X投稿用の短文を1つ。\n"
                    "条件:\n"
                    "- 140文字以内を目安にする\n"
                    "- 日本語\n"
                    "- 誇張しすぎない\n"
                    "- リポジトリ名を本文中に自然に入れる\n"
                    "- 文体は自然でややカジュアル、宣伝っぽくしない\n"
                    "- 何ができるかを入れる\n"
                    "- なぜ面白いかを入れる\n"
                    "- どんな人や用途に向いているかを短く入れる\n"
                    "- 抽象語より具体語を優先する\n"
                    "- 3段落か4段落に改行して読みやすくする\n"
                    "- 1段落目は短い導入か一言で始める\n"
                    "- 2段落目で何ができるかと面白さを具体的に書く\n"
                    "- 3段落目で向いている人や用途を書く\n"
                    "- 最後の段落に必ずURLをそのまま入れる\n"
                    "- ハッシュタグは2個まで\n\n"
                    "避けたい表現:\n"
                    "- おすすめです\n"
                    "- 常に最新です\n"
                    "- 革新的です\n"
                    "- 最強です\n\n"
                    "目指す文の方向:\n"
                    "- 落ち着いている\n"
                    "- 一読で用途が分かる\n"
                    "- コピペしてそのままXに流せる\n\n"
                    f"Repository: {repo['full_name']}\n"
                    f"Description: {repo.get('description') or 'N/A'}\n"
                    f"Language: {repo.get('language') or 'N/A'}\n"
                    f"Stars: {repo['stargazers_count']}\n"
                    f"Topics: {', '.join(repo.get('topics') or [])}\n"
                    f"URL: {repo['html_url']}\n"
                    f"README:\n{repo.get('_readme_text') or 'READMEなし'}"
                ),
            },
        ],
        "temperature": 0.5,
    }
    response = requests.post(
        DEEPSEEK_API,
        headers={
            "Authorization": f"Bearer {config.deepseek_api_key}",
            "Content-Type": "application/json",
        },
        json=prompt,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def split_generated_content(content: str, repo: dict[str, Any]) -> tuple[str, str]:
    telegram_text = ""
    x_text = ""

    if "[telegram]" in content and "[x]" in content:
        telegram_part, x_part = content.split("[x]", 1)
        telegram_text = telegram_part.replace("[telegram]", "", 1).strip()
        x_text = x_part.strip()
    else:
        telegram_text = content.strip()

    if not telegram_text:
        telegram_text = (
            f"{repo.get('description') or '説明なし'}\n"
            f"Language: {repo.get('language') or 'N/A'}\n"
            f"Stars: {repo['stargazers_count']}\n"
            f"URL: {repo['html_url']}"
        )

    if not x_text:
        x_text = (
            f"{repo['full_name']} は {repo.get('description') or '説明なし'}。\n\n"
            f"刺さる人: OSSを追う開発者。\n\n"
            f"{repo['html_url']}\n"
            "#GitHub"
        )

    return telegram_text, x_text


def build_telegram_message(repos: list[dict[str, Any]]) -> str:
    parts = ["今日のGitHub面白そう枠"]
    for repo in repos:
        summary = repo["_summary"]
        full_name = repo["full_name"]
        language = repo.get("language") or "N/A"
        html_url = repo["html_url"]
        parts.append(
            "\n".join(
                [
                    full_name,
                    f"stars={repo['stargazers_count']} / forks={repo['forks_count']} / lang={language}",
                    f"score={repo['_score']} / updated={repo['pushed_at'][:10]}",
                    summary,
                    html_url,
                ]
            )
        )
    return "\n\n".join(parts)


def build_telegram_messages(repos: list[dict[str, Any]]) -> list[str]:
    messages = ["今日のGitHub面白そう枠"]
    for repo in repos:
        x_post = repo["_x_post"]
        messages.append(x_post[:600])
    return messages


def post_to_telegram(config: Config, repos: list[dict[str, Any]]) -> None:
    messages = build_telegram_messages(repos)
    if config.public_history_url:
        messages.append(f"過去ログを見る: {config.public_history_url}")

    for index, chunk in enumerate(messages, start=1):
        response = requests.post(
            f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
            json={
                "chat_id": config.telegram_chat_id,
                "text": chunk,
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                "Telegram send failed: "
                f"message_index={index}, status={response.status_code}, "
                f"body={response.text}, preview={chunk[:300]!r}"
            )


def send_telegram_test(config: Config) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
        json={
            "chat_id": config.telegram_chat_id,
            "text": "telegram test from github notifier",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Telegram test failed: status={response.status_code}, body={response.text}"
        )
    print("Telegram test sent.")


def enrich_repositories(config: Config, repos: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    enriched = []
    for repo in repos:
        if should_skip(repo, state, config):
            continue
        owner, name = repo["full_name"].split("/", 1)
        repo["_readme_text"] = fetch_readme(config, owner, name)
        repo["_score"] = score_repo(repo, state, config)
        enriched.append(repo)
    enriched.sort(key=lambda item: item["_score"], reverse=True)
    return enriched[: config.top_n]


def update_state(state: dict[str, Any], repos: list[dict[str, Any]]) -> None:
    now_iso = datetime.now(UTC).isoformat()
    for repo in repos:
        state["repos"][repo["full_name"]] = {
            "last_stars": repo["stargazers_count"],
            "last_seen": now_iso,
        }
        state["notifications"][repo["full_name"]] = {
            "last_sent": now_iso,
        }


def append_history(repos: list[dict[str, Any]]) -> None:
    history = load_history()
    sent_at = datetime.now(UTC).isoformat()
    for repo in repos:
        history.append(
            {
                "sent_at": sent_at,
                "full_name": repo["full_name"],
                "html_url": repo["html_url"],
                "x_post": repo["_x_post"],
                "summary": repo["_summary"],
                "score": repo["_score"],
                "stars": repo["stargazers_count"],
                "forks": repo["forks_count"],
                "language": repo.get("language") or "N/A",
            }
        )
    save_history(history[-300:])


def render_history_site() -> None:
    history = list(reversed(load_history()))
    grouped: dict[str, list[dict[str, Any]]] = {}
    tokyo = ZoneInfo("Asia/Tokyo")
    for item in history:
        sent_at_dt = datetime.fromisoformat(item["sent_at"]).astimezone(tokyo)
        day_key = f"{sent_at_dt.month}/{sent_at_dt.day}"
        item["_display_time"] = sent_at_dt.strftime("%Y-%m-%d %H:%M")
        grouped.setdefault(day_key, []).append(item)

    tab_buttons = []
    tab_panels = []
    for index, (day_key, items) in enumerate(grouped.items()):
        button_class = "tab-button active" if index == 0 else "tab-button"
        panel_class = "tab-panel active" if index == 0 else "tab-panel"
        tab_id = f"tab-{index}"
        tab_buttons.append(
            f'<button class="{button_class}" data-tab="{tab_id}">{escape(day_key)}</button>'
        )

        cards = []
        for item in items:
            sent_at = escape(item["_display_time"])
            full_name = escape(item["full_name"])
            html_url = escape(item["html_url"])
            x_post = escape(item["x_post"])
            language = escape(item["language"])
            cards.append(
                f"""
                <article class="card">
                  <div class="meta">
                    <span>{sent_at}</span>
                    <span>score {item["score"]}</span>
                    <span>stars {item["stars"]}</span>
                    <span>{language}</span>
                  </div>
                  <h2><a href="{html_url}" target="_blank" rel="noreferrer">{full_name}</a></h2>
                  <pre>{x_post}</pre>
                </article>
                """
            )

        tab_panels.append(
            f"""
            <section id="{tab_id}" class="{panel_class}">
              {''.join(cards)}
            </section>
            """
        )

    html = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GitHub Repo Notifier History</title>
  <style>
    :root {{
      --bg: #f3efe6;
      --panel: #fffaf0;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #d6d3d1;
      --accent: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fde68a 0, transparent 30%),
        linear-gradient(180deg, #fffaf0 0%, #f3efe6 100%);
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      padding: 40px 20px 64px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(32px, 6vw, 56px);
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    p {{
      margin: 0 0 24px;
      color: var(--muted);
    }}
    .tabs {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0 0 22px;
    }}
    .tab-button {{
      border: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.72);
      color: var(--ink);
      padding: 10px 16px;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
      transition: transform 120ms ease, background 120ms ease;
    }}
    .tab-button:hover {{
      transform: translateY(-1px);
      background: #fff;
    }}
    .tab-button.active {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    .tab-panel {{
      display: none;
    }}
    .tab-panel.active {{
      display: block;
    }}
    .card {{
      background: rgba(255, 250, 240, 0.88);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      margin: 0 0 16px;
      box-shadow: 0 14px 30px rgba(31, 41, 55, 0.08);
      backdrop-filter: blur(10px);
    }}
    .meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 20px;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font: inherit;
      line-height: 1.7;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Repo History</h1>
    <p>Telegram に送った X 投稿文の履歴です。日付タブをクリックするとその日の通知だけ見られます。</p>
    {"<div class='tabs'>" + ''.join(tab_buttons) + "</div>" if tab_buttons else ""}
    {''.join(tab_panels) if tab_panels else '<p>まだ履歴はありません。</p>'}
  </main>
  <script>
    const buttons = document.querySelectorAll('.tab-button');
    const panels = document.querySelectorAll('.tab-panel');
    for (const button of buttons) {{
      button.addEventListener('click', () => {{
        const target = button.dataset.tab;
        for (const item of buttons) item.classList.remove('active');
        for (const panel of panels) panel.classList.remove('active');
        button.classList.add('active');
        document.getElementById(target)?.classList.add('active');
      }});
    }}
  </script>
</body>
</html>
"""
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def refresh_star_snapshots(state: dict[str, Any], repos: list[dict[str, Any]]) -> None:
    now_iso = datetime.now(UTC).isoformat()
    for repo in repos:
        state["repos"][repo["full_name"]] = {
            "last_stars": repo["stargazers_count"],
            "last_seen": now_iso,
        }


def run_once(config: Config) -> None:
    print("Searching repositories...")
    state = load_state()
    repos = search_repositories(config)
    print(f"Found {len(repos)} repositories.")
    candidates = enrich_repositories(config, repos, state)
    print(f"Selected {len(candidates)} candidates.")
    if not candidates:
        refresh_star_snapshots(state, repos)
        save_state(state)
        print("No candidates to notify.")
        return

    for repo in candidates:
        print(f"Summarizing {repo['full_name']}...")
        try:
            generated = build_deepseek_summary(config, repo)
            repo["_summary"], repo["_x_post"] = split_generated_content(generated, repo)
        except Exception:
            repo["_summary"] = (
                f"{repo.get('description') or '説明なし'}\n"
                f"Language: {repo.get('language') or 'N/A'}\n"
                f"Stars: {repo['stargazers_count']}\n"
                f"URL: {repo['html_url']}"
            )
            repo["_x_post"] = (
                f"{repo['full_name']} は {repo.get('description') or '説明なし'}。"
                f" {repo['html_url']} #GitHub"
            )

    print("Sending Telegram messages...")
    post_to_telegram(config, candidates)
    refresh_star_snapshots(state, repos)
    update_state(state, candidates)
    save_state(state)
    append_history(candidates)
    render_history_site()
    print(f"Posted {len(candidates)} repositories.")


def next_run_time(config: Config) -> datetime:
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    candidates = []
    for clock in config.notify_times:
        hour, minute = map(int, clock.split(":"))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)
        candidates.append(scheduled)
    return min(candidates)


def run_daemon(config: Config) -> None:
    while True:
        scheduled = next_run_time(config)
        wait_seconds = max(1, int((scheduled - datetime.now(ZoneInfo(config.timezone))).total_seconds()))
        print(f"Next run at {scheduled.isoformat()}")
        time.sleep(wait_seconds)
        try:
            run_once(config)
        except Exception as exc:
            print(f"Run failed: {exc}", file=sys.stderr)
            time.sleep(30)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"once", "daemon", "test-telegram"}:
        print("Usage: python bot.py [once|daemon|test-telegram]")
        raise SystemExit(1)

    config = load_config()
    mode = sys.argv[1]
    if mode == "test-telegram":
        send_telegram_test(config)
        return
    if mode == "once":
        run_once(config)
        return
    run_daemon(config)


if __name__ == "__main__":
    main()
