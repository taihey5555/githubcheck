import json
import os
import re
import re
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
LOGS_DIR = ROOT / "logs"
SEND_LOG_PATH = LOGS_DIR / "send.log"
GITHUB_API = "https://api.github.com"
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"

TOPIC_KEYWORDS = {
    "ai": ["ai", "llm", "agent", "rag", "inference", "model"],
    "cli": ["cli", "terminal", "shell", "tui"],
    "automation": ["automation", "workflow", "bot", "scheduler"],
    "security": ["security", "pentest", "auth", "sandbox", "crypto"],
    "developer-tools": ["developer", "devtools", "tooling", "debug", "build"],
}

REVIEW_STATES = [
    "unseen",
    "interested",
    "tested",
    "good",
    "meh",
    "production_candidate",
]

LOW_STAR_HIGH_SCORE = {
    "max_stars": 1000,
    "min_score": 70.0,
    "limit": 6,
}


@dataclass
class Config:
    github_token: str
    deepseek_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    public_history_url: str
    public_weekly_url: str
    top_n: int
    notify_times: list[str]
    timezone: str
    topics: list[str]
    min_stars: int
    cooldown_days: int


def get_run_bucket(config: Config, now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(config.timezone))
    slots = []
    for index, clock in enumerate(config.notify_times):
        hour, minute = map(int, clock.split(":"))
        scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slots.append((abs((local_now - scheduled).total_seconds()), index))
    slot_index = min(slots, key=lambda item: item[0])[1] if slots else 0
    return "morning" if slot_index == 0 else "evening"


def load_config() -> Config:
    load_dotenv()
    return Config(
        github_token=require_env("GITHUB_TOKEN"),
        deepseek_api_key=require_env("DEEPSEEK_API_KEY"),
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=require_env("TELEGRAM_CHAT_ID"),
        public_history_url=os.getenv("PUBLIC_HISTORY_URL", "").strip(),
        public_weekly_url=os.getenv("PUBLIC_WEEKLY_URL", "").strip(),
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
        return {"repos": {}, "notifications": {}, "review_states": {}}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.setdefault("repos", {})
    state.setdefault("notifications", {})
    state.setdefault("review_states", {})
    return state


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


def parse_sent_at(sent_at: str) -> datetime:
    return datetime.fromisoformat(sent_at).astimezone(ZoneInfo("Asia/Tokyo"))


def normalize_review_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    return state if state in REVIEW_STATES else "unseen"


def parse_int_env(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def parse_float_env(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def low_star_high_score_settings() -> dict[str, int | float]:
    load_dotenv()
    return {
        "max_stars": parse_int_env(
            "LOW_STAR_HIGH_SCORE_MAX_STARS",
            int(LOW_STAR_HIGH_SCORE["max_stars"]),
            minimum=0,
        ),
        "min_score": parse_float_env(
            "LOW_STAR_HIGH_SCORE_MIN_SCORE",
            float(LOW_STAR_HIGH_SCORE["min_score"]),
            minimum=0.0,
        ),
        "limit": parse_int_env(
            "LOW_STAR_HIGH_SCORE_LIMIT",
            int(LOW_STAR_HIGH_SCORE["limit"]),
            minimum=1,
        ),
    }


def validate_review_state_or_exit(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in REVIEW_STATES:
        print(
            "Invalid review state. "
            f"Expected one of: {', '.join(REVIEW_STATES)}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return normalized


def review_state_usage() -> str:
    return (
        "Usage:\n"
        "  python bot.py review-state set <owner/repo> <state>\n"
        "  python bot.py review-state unset <owner/repo>\n"
        "  python bot.py review-state get <owner/repo>\n"
        "  python bot.py review-state list [--state <state>] [--prefix <owner/>]"
    )


def review_state_set(full_name: str, raw_state: str) -> None:
    normalized_full_name = str(full_name or "").strip()
    if not normalized_full_name:
        print(review_state_usage(), file=sys.stderr)
        raise SystemExit(1)
    state = load_state()
    review_state = validate_review_state_or_exit(raw_state)
    state["review_states"][normalized_full_name] = review_state
    save_state(state)
    print(f"{normalized_full_name}: {review_state}")


def review_state_get(full_name: str) -> None:
    normalized_full_name = str(full_name or "").strip()
    if not normalized_full_name:
        print(review_state_usage(), file=sys.stderr)
        raise SystemExit(1)
    state = load_state()
    raw_value = state.get("review_states", {}).get(normalized_full_name)
    normalized = normalize_review_state(raw_value)
    suffix = "" if raw_value else " (unset)"
    print(f"{normalized_full_name}: {normalized}{suffix}")


def review_state_unset(full_name: str) -> None:
    normalized_full_name = str(full_name or "").strip()
    if not normalized_full_name:
        print(review_state_usage(), file=sys.stderr)
        raise SystemExit(1)
    state = load_state()
    removed = state.get("review_states", {}).pop(normalized_full_name, None)
    save_state(state)
    suffix = "removed" if removed else "already unset"
    print(f"{normalized_full_name}: {suffix}")


def review_state_list(
    state_filter: str | None = None,
    prefix_filter: str | None = None,
) -> None:
    state = load_state()
    review_states = state.get("review_states", {})
    if not review_states:
        print("review_states: empty")
        return
    matches = []
    for full_name in sorted(review_states):
        normalized = normalize_review_state(review_states.get(full_name))
        if state_filter and normalized != state_filter:
            continue
        if prefix_filter and not full_name.startswith(prefix_filter):
            continue
        matches.append((full_name, normalized))
    if not matches:
        print("review_states: no matches")
        return
    for full_name, normalized in matches:
        print(f"{full_name}: {normalized}")


def parse_review_state_list_args(args: list[str]) -> tuple[str | None, str | None]:
    state_filter = None
    prefix_filter = None
    index = 0
    while index < len(args):
        option = args[index]
        if option == "--state":
            if index + 1 >= len(args):
                print(review_state_usage(), file=sys.stderr)
                raise SystemExit(1)
            state_filter = validate_review_state_or_exit(args[index + 1])
            index += 2
            continue
        if option == "--prefix":
            if index + 1 >= len(args):
                print(review_state_usage(), file=sys.stderr)
                raise SystemExit(1)
            prefix_filter = str(args[index + 1] or "").strip()
            index += 2
            continue
        print(review_state_usage(), file=sys.stderr)
        raise SystemExit(1)
    return state_filter, prefix_filter


def handle_review_state_cli(args: list[str]) -> None:
    if not args:
        print(review_state_usage(), file=sys.stderr)
        raise SystemExit(1)
    action = args[0]
    if action == "set" and len(args) == 3:
        review_state_set(args[1], args[2])
        return
    if action == "get" and len(args) == 2:
        review_state_get(args[1])
        return
    if action == "unset" and len(args) == 2:
        review_state_unset(args[1])
        return
    if action == "list":
        state_filter, prefix_filter = parse_review_state_list_args(args[1:])
        review_state_list(state_filter=state_filter, prefix_filter=prefix_filter)
        return
    print(review_state_usage(), file=sys.stderr)
    raise SystemExit(1)


def extract_tags(item: dict[str, Any]) -> list[str]:
    tags = []
    seen = set()
    for topic in item.get("topics") or []:
        normalized = str(topic).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            tags.append(normalized)
    for raw in re.findall(r"#([^\s#]+)", str(item.get("x_post") or "")):
        normalized = raw.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            tags.append(normalized)
    return tags


def build_card_dataset(item: dict[str, Any], review_state: str) -> dict[str, str]:
    sent_at = str(item.get("sent_at") or "")
    score = float(item.get("score") or 0)
    stars = int(item.get("stars") or 0)
    return {
        "bucket": str(item.get("bucket") or "morning"),
        "name": str(item.get("full_name") or "").lower(),
        "language": str(item.get("language") or "N/A").lower(),
        "tags": " ".join(extract_tags(item)),
        "stars": str(stars),
        "score": f"{score:.2f}",
        "sent-at": sent_at,
        "review-state": review_state,
    }


def render_data_attrs(values: dict[str, str]) -> str:
    return " ".join(
        f'data-{key}="{escape(value, quote=True)}"'
        for key, value in values.items()
    )


def is_low_star_high_score(item: dict[str, Any]) -> bool:
    settings = low_star_high_score_settings()
    return (
        int(item.get("stars") or 0) <= int(settings["max_stars"])
        and float(item.get("score") or 0) >= float(settings["min_score"])
    )


def summarize_languages(items: list[dict[str, Any]], limit: int = 5) -> str:
    counts: dict[str, int] = {}
    for item in items:
        language = str(item.get("language") or "N/A")
        counts[language] = counts.get(language, 0) + 1
    ranking = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    if not ranking:
        return "なし"
    return ", ".join(f"{language} {count}" for language, count in ranking)


def append_send_log(event: str, **fields: Any) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": event,
        "logged_at": datetime.now(UTC).isoformat(),
        **fields,
    }
    with SEND_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def fallback_owner_fields(item: dict[str, Any]) -> tuple[str, str, str]:
    full_name = (item.get("full_name") or "").strip()
    owner_from_name = full_name.split("/", 1)[0] if "/" in full_name else full_name
    owner_login = (item.get("owner_login") or owner_from_name).strip()
    owner_html_url = (item.get("owner_html_url") or "").strip()
    if not owner_html_url and owner_login:
        owner_html_url = f"https://github.com/{owner_login}"
    owner_avatar_url = (item.get("owner_avatar_url") or "").strip()
    if not owner_avatar_url:
        owner_avatar_url = "https://github.githubassets.com/favicons/favicon.png"
    return owner_login, owner_html_url or item["html_url"], owner_avatar_url


def normalize_card_description(item: dict[str, Any], limit: int = 140) -> str:
    description = " ".join(str(item.get("description") or "").split())
    if not description:
        return ""
    if len(description) <= limit:
        return description
    return description[: limit - 3].rstrip() + "..."


def linkify_text(text: str) -> str:
    escaped = escape(text)
    pattern = re.compile(r"(https?://[^\s<]+)")
    return pattern.sub(r'<a href="\1" target="_blank" rel="noreferrer">\1</a>', escaped)


def site_shell(title: str, subtitle: str, body_html: str, current_page: str) -> str:
    history_active = 'aria-current="page"' if current_page == "history" else ""
    weekly_active = 'aria-current="page"' if current_page == "weekly" else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f5efe4;
      --bg-alt: #eaf3ff;
      --panel: rgba(255, 252, 245, 0.88);
      --ink: #1f2937;
      --muted: #6b7280;
      --line: rgba(148, 163, 184, 0.35);
      --accent: #0f766e;
      --accent-2: #b45309;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fde68a 0, transparent 24%),
        radial-gradient(circle at top right, #bfdbfe 0, transparent 26%),
        linear-gradient(180deg, var(--bg) 0%, var(--bg-alt) 100%);
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .site-header {{
      position: sticky;
      top: 0;
      z-index: 20;
      backdrop-filter: blur(14px);
      background: rgba(255, 250, 240, 0.82);
      border-bottom: 1px solid var(--line);
    }}
    .header-inner {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand {{
      display: inline-flex;
      flex-direction: column;
      gap: 2px;
      color: var(--ink);
    }}
    .brand strong {{
      font-size: 15px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .brand span {{
      font-size: 13px;
      color: var(--muted);
    }}
    .menu-toggle {{
      display: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.7);
      border-radius: 999px;
      width: 44px;
      height: 44px;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      padding: 0;
    }}
    .menu-icon {{
      display: inline-flex;
      flex-direction: column;
      gap: 4px;
      align-items: center;
      justify-content: center;
    }}
    .menu-icon span {{
      display: block;
      width: 18px;
      height: 2px;
      background: var(--ink);
      border-radius: 999px;
    }}
    .site-nav {{
      display: flex;
      gap: 10px;
      align-items: center;
    }}
    .site-nav a {{
      color: var(--ink);
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid transparent;
    }}
    .site-nav a[aria-current="page"] {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    .site-nav a:hover {{
      background: rgba(255,255,255,0.72);
      border-color: var(--line);
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 36px 20px 64px;
    }}
    .hero {{
      margin-bottom: 24px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: clamp(34px, 7vw, 64px);
      line-height: 0.95;
      letter-spacing: -0.05em;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: clamp(15px, 2.4vw, 18px);
      max-width: 720px;
    }}
    .date-selector {{
      margin: 0 0 22px;
    }}
    .date-select {{
      width: min(280px, 100%);
      border: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.92);
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 14px;
      font: inherit;
    }}
    .filter-bar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0 0 18px;
    }}
    .archive-controls {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      margin: 0 0 18px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255, 250, 240, 0.72);
      box-shadow: var(--shadow);
    }}
    .control-group {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .control-group label {{
      font-size: 12px;
      color: var(--muted);
    }}
    .control-group input,
    .control-group select {{
      width: 100%;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.86);
      color: var(--ink);
      padding: 10px 12px;
      border-radius: 12px;
      font: inherit;
    }}
    .archive-summary {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 13px;
    }}
    .section-block {{
      margin: 0 0 28px;
    }}
    .section-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px;
      margin: 0 0 12px;
      align-items: end;
    }}
    .section-header h2,
    .section-header h3 {{
      margin: 0;
    }}
    .section-header p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      max-width: 720px;
    }}
    .section-grid {{
      display: grid;
      gap: 16px;
    }}
    .empty-state {{
      padding: 18px;
      border: 1px dashed var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.55);
      color: var(--muted);
    }}
    .tab-button,
    .filter-button {{
      border: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.72);
      color: var(--ink);
      padding: 10px 16px;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
      transition: transform 120ms ease, background 120ms ease;
    }}
    .tab-button:hover,
    .filter-button:hover {{
      transform: translateY(-1px);
      background: #fff;
    }}
    .tab-button.active,
    .filter-button.active {{
      background: var(--accent-2);
      color: white;
      border-color: var(--accent-2);
    }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .card.hidden-by-filter {{ display: none; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      margin: 0 0 16px;
      box-shadow: var(--shadow);
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
    .card-header {{
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 14px;
    }}
    .avatar {{
      width: 52px;
      height: 52px;
      border-radius: 50%;
      object-fit: cover;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.9);
      flex: 0 0 auto;
    }}
    .card-title-wrap {{
      min-width: 0;
      flex: 1 1 auto;
    }}
    .owner-line {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 4px;
    }}
    .owner-line a {{
      color: var(--muted);
    }}
    .description {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    .pick-reason {{
      margin: 0 0 10px;
      color: var(--muted);
      line-height: 1.5;
      font-size: 12px;
      opacity: 0.82;
    }}
    .badge-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 10px 0 0;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.74);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 12px;
      line-height: 1;
    }}
    .badge.topic {{
      background: rgba(15, 118, 110, 0.08);
      color: var(--accent);
      border-color: rgba(15, 118, 110, 0.16);
    }}
    .badge.review-state {{
      background: rgba(180, 83, 9, 0.10);
      color: var(--accent-2);
      border-color: rgba(180, 83, 9, 0.18);
    }}
    .date-label {{
      font-variant-numeric: tabular-nums;
    }}
    .rank-card {{
      position: relative;
      overflow: hidden;
    }}
    .rank-card::after {{
      content: "";
      position: absolute;
      inset: auto -40px -40px auto;
      width: 140px;
      height: 140px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(15,118,110,0.14) 0, rgba(15,118,110,0) 70%);
      pointer-events: none;
    }}
    .rank-number {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 42px;
      height: 42px;
      border-radius: 50%;
      background: var(--accent);
      color: white;
      font-weight: 700;
      font-size: 18px;
      flex: 0 0 auto;
    }}
    .rank-card.top1 {{
      border-width: 2px;
      border-color: rgba(180, 83, 9, 0.32);
      background: linear-gradient(135deg, rgba(255,250,240,0.96), rgba(254,243,199,0.92));
    }}
    .rank-card.top1 .rank-number {{
      width: 56px;
      height: 56px;
      background: linear-gradient(135deg, #b45309, #f59e0b);
      font-size: 22px;
    }}
    .rank-card.top2 .rank-number,
    .rank-card.top3 .rank-number {{
      background: linear-gradient(135deg, #0f766e, #14b8a6);
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 0 0 22px;
    }}
    .stat-card {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.70);
      box-shadow: var(--shadow);
    }}
    .stat-card strong {{
      display: block;
      font-size: 28px;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .stat-card span {{
      color: var(--muted);
      font-size: 13px;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: clamp(20px, 3vw, 24px);
      line-height: 1.15;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font: inherit;
      line-height: 1.7;
    }}
    @media (max-width: 720px) {{
      .menu-toggle {{
        display: inline-flex;
      }}
      .site-nav {{
        position: absolute;
        top: calc(100% + 8px);
        right: 20px;
        left: 20px;
        display: none;
        flex-direction: column;
        align-items: stretch;
        padding: 12px;
        border: 1px solid var(--line);
        border-radius: 20px;
        background: rgba(255, 250, 240, 0.96);
        box-shadow: var(--shadow);
      }}
      .site-nav.open {{
        display: flex;
      }}
      .site-nav a {{
        width: 100%;
        text-align: center;
      }}
      main {{
        padding-top: 28px;
      }}
      .card {{
        padding: 16px;
      }}
    }}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="./index.html">
        <strong>GitHub Check</strong>
        <span>repo digest and weekly ranking</span>
      </a>
      <button class="menu-toggle" aria-label="メニューを開く" aria-expanded="false" aria-controls="site-nav">
        <span class="menu-icon" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
      </button>
      <nav id="site-nav" class="site-nav">
        <a href="./index.html" {history_active}>履歴</a>
        <a href="./weekly.html" {weekly_active}>週間トップ10</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="hero">
      <h1>{escape(title)}</h1>
      <p>{escape(subtitle)}</p>
    </section>
    {body_html}
  </main>
  <script>
    const toggle = document.querySelector('.menu-toggle');
    const nav = document.getElementById('site-nav');
    if (toggle && nav) {{
      toggle.addEventListener('click', () => {{
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        nav.classList.toggle('open');
      }});
      nav.querySelectorAll('a').forEach((link) => {{
        link.addEventListener('click', () => {{
          nav.classList.remove('open');
          toggle.setAttribute('aria-expanded', 'false');
        }});
      }});
    }}
    const daySelect = document.querySelector('[data-day-select]');
    const panels = document.querySelectorAll('.tab-panel');
    if (daySelect) {{
      daySelect.addEventListener('change', () => {{
        const target = daySelect.value;
        for (const panel of panels) panel.classList.remove('active');
        document.getElementById(target)?.classList.add('active');
      }});
    }}
    const filterButtons = document.querySelectorAll('[data-bucket-filter]');
    const cards = document.querySelectorAll('[data-bucket]');
    for (const button of filterButtons) {{
      button.addEventListener('click', () => {{
        const target = button.dataset.bucketFilter;
        for (const item of filterButtons) item.classList.remove('active');
        button.classList.add('active');
        for (const card of cards) {{
          const matches = target === 'all' || card.dataset.bucket === target;
          card.classList.toggle('hidden-by-filter', !matches);
        }}
      }});
    }}
    const archiveRoot = document.querySelector('[data-archive-root]');
    if (archiveRoot) {{
      const archiveCards = Array.from(document.querySelectorAll('[data-archive-card]'));
      const searchInput = archiveRoot.querySelector('[data-filter-search]');
      const languageInput = archiveRoot.querySelector('[data-filter-language]');
      const tagInput = archiveRoot.querySelector('[data-filter-tag]');
      const reviewStateInput = archiveRoot.querySelector('[data-filter-review-state]');
      const minStarsInput = archiveRoot.querySelector('[data-filter-stars-min]');
      const maxStarsInput = archiveRoot.querySelector('[data-filter-stars-max]');
      const minScoreInput = archiveRoot.querySelector('[data-filter-score-min]');
      const maxScoreInput = archiveRoot.querySelector('[data-filter-score-max]');
      const sortInput = archiveRoot.querySelector('[data-filter-sort]');
      const countOutput = document.querySelector('[data-filter-count]');
      const panelsById = new Map(Array.from(document.querySelectorAll('.tab-panel')).map((panel) => [panel.id, panel]));

      const activePanelId = () => daySelect ? daySelect.value : '';
      const activeBucket = () => document.querySelector('[data-bucket-filter].active')?.dataset.bucketFilter || 'all';
      const normalizeText = (value) => String(value || '').toLowerCase();
      const parseNumber = (value) => {{
        if (value === '' || value == null) return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
      }};

      const applyArchiveFilters = () => {{
        const search = normalizeText(searchInput?.value);
        const language = normalizeText(languageInput?.value);
        const tag = normalizeText(tagInput?.value);
        const reviewState = normalizeText(reviewStateInput?.value);
        const minStars = parseNumber(minStarsInput?.value);
        const maxStars = parseNumber(maxStarsInput?.value);
        const minScore = parseNumber(minScoreInput?.value);
        const maxScore = parseNumber(maxScoreInput?.value);
        const sortKey = sortInput?.value || 'newest';
        const panelId = activePanelId();
        const bucket = activeBucket();

        for (const card of archiveCards) {{
          const inActivePanel = !panelId || card.closest('.tab-panel')?.id === panelId;
          const matchesBucket = bucket === 'all' || card.dataset.bucket === bucket;
          const name = normalizeText(card.dataset.name);
          const cardLanguage = normalizeText(card.dataset.language);
          const tags = normalizeText(card.dataset.tags);
          const cardReviewState = normalizeText(card.dataset.reviewState);
          const stars = parseNumber(card.dataset.stars) ?? 0;
          const score = parseNumber(card.dataset.score) ?? 0;
          const matchesSearch = !search || name.includes(search);
          const matchesLanguage = !language || cardLanguage === language;
          const matchesTag = !tag || tags.includes(tag);
          const matchesReviewState = !reviewState || cardReviewState === reviewState;
          const matchesMinStars = minStars == null || stars >= minStars;
          const matchesMaxStars = maxStars == null || stars <= maxStars;
          const matchesMinScore = minScore == null || score >= minScore;
          const matchesMaxScore = maxScore == null || score <= maxScore;
          const visible =
            inActivePanel &&
            matchesBucket &&
            matchesSearch &&
            matchesLanguage &&
            matchesTag &&
            matchesReviewState &&
            matchesMinStars &&
            matchesMaxStars &&
            matchesMinScore &&
            matchesMaxScore;
          card.classList.toggle('hidden-by-filter', !visible);
        }}

        const activePanel = panelId ? panelsById.get(panelId) : null;
        const sortableCards = archiveCards.filter((card) => !card.classList.contains('hidden-by-filter'));
        sortableCards.sort((left, right) => {{
          if (sortKey === 'score') return Number(right.dataset.score || 0) - Number(left.dataset.score || 0);
          if (sortKey === 'stars') return Number(right.dataset.stars || 0) - Number(left.dataset.stars || 0);
          return String(right.dataset.sentAt || '').localeCompare(String(left.dataset.sentAt || ''));
        }});
        if (activePanel) {{
          for (const card of sortableCards) {{
            activePanel.appendChild(card);
          }}
        }}
        if (countOutput) {{
          countOutput.textContent = `${{sortableCards.length}} 件表示`;
        }}
      }};

      [
        searchInput,
        languageInput,
        tagInput,
        reviewStateInput,
        minStarsInput,
        maxStarsInput,
        minScoreInput,
        maxScoreInput,
        sortInput,
      ].filter(Boolean).forEach((element) => {{
        element.addEventListener('input', applyArchiveFilters);
        element.addEventListener('change', applyArchiveFilters);
      }});
      if (daySelect) {{
        daySelect.addEventListener('change', applyArchiveFilters);
      }}
      for (const button of filterButtons) {{
        button.addEventListener('click', applyArchiveFilters);
      }}
      applyArchiveFilters();
    }}
  </script>
</body>
</html>
"""


def linkify_text(text: str) -> str:
    escaped = escape(text)
    pattern = re.compile(r"(https?://[^\s<]+)")
    return pattern.sub(r'<a href="\1" target="_blank" rel="noreferrer">\1</a>', escaped)


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


def score_repo(
    repo: dict[str, Any],
    state: dict[str, Any],
    config: Config,
    bucket: str = "morning",
) -> float:
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

    weird_bonus = 0
    weird_keywords = [
        "retro",
        "emulator",
        "reverse",
        "decompiler",
        "engine",
        "compiler",
        "game",
        "simulation",
        "sandbox",
        "self-hosted",
        "offline",
        "local-first",
    ]
    for keyword in weird_keywords:
        if keyword in text:
            weird_bonus += 1

    readme_bonus = 3 if repo.get("_readme_text") else 0
    freshness = max(0, 90 - created_days) / 90
    activity = max(0, 14 - pushed_days) / 14

    score = 0.0
    if bucket == "evening":
        score += star_growth * 0.25
        score += freshness * 10
        score += activity * 16
        score += niche_bonus * 3
        score += weird_bonus * 5
    else:
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
                    "[pick_reason]\n"
                    "1行で短く、この repo を拾った理由を書く\n"
                    "条件:\n"
                    "- 28文字以内を目安にする\n"
                    "- 箇条書きにしない\n"
                    "- score や数値をそのまま並べない\n"
                    "- 新しさ、伸び、尖り、用途のどれかを短く示す\n\n"
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


def split_generated_content(content: str, repo: dict[str, Any]) -> tuple[str, str, str]:
    pick_reason = ""
    telegram_text = ""
    x_text = ""

    if "[pick_reason]" in content:
        _, content = content.split("[pick_reason]", 1)
        if "[telegram]" in content:
            pick_part, content = content.split("[telegram]", 1)
            pick_reason = pick_part.strip()
            content = "[telegram]" + content

    if "[telegram]" in content and "[x]" in content:
        telegram_part, x_part = content.split("[x]", 1)
        telegram_text = telegram_part.replace("[telegram]", "", 1).strip()
        x_text = x_part.strip()
    else:
        telegram_text = content.strip()

    if not pick_reason:
        if repo.get("_score", 0) >= 40:
            pick_reason = "直近で伸びが強い"
        elif repo.get("description"):
            pick_reason = "用途が分かりやすい"
        else:
            pick_reason = "今の注目候補"

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

    return telegram_text, x_text, pick_reason[:28]


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


def build_telegram_messages(repos: list[dict[str, Any]], bucket: str) -> list[str]:
    messages = ["朝の新顔枠" if bucket == "morning" else "夜の尖り枠"]
    for repo in repos:
        x_post = repo["_x_post"]
        pick_reason = (repo.get("_pick_reason") or "").strip()
        if pick_reason:
            messages.append(f"選定理由: {pick_reason}\n{x_post[:600]}")
        else:
            messages.append(x_post[:600])
    return messages


def send_telegram_text(config: Config, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
        json={
            "chat_id": config.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"status={response.status_code}, body={response.text}"
        )


def post_to_telegram(config: Config, repos: list[dict[str, Any]], bucket: str) -> None:
    messages = build_telegram_messages(repos, bucket)
    if config.public_history_url:
        messages.append(f"過去ログを見る: {config.public_history_url}")

    for index, chunk in enumerate(messages, start=1):
        try:
            send_telegram_text(config, chunk)
        except RuntimeError as exc:
            raise RuntimeError(
                "Telegram send failed: "
                f"message_index={index}, detail={exc}, preview={chunk[:300]!r}"
            )


def send_telegram_test(config: Config) -> None:
    send_telegram_text(config, "telegram test from github notifier")
    print("Telegram test sent.")


def enrich_repositories(
    config: Config,
    repos: list[dict[str, Any]],
    state: dict[str, Any],
    bucket: str,
) -> list[dict[str, Any]]:
    enriched = []
    for repo in repos:
        if should_skip(repo, state, config):
            continue
        owner, name = repo["full_name"].split("/", 1)
        repo["_readme_text"] = fetch_readme(config, owner, name)
        repo["_score"] = score_repo(repo, state, config, bucket)
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


def append_history(repos: list[dict[str, Any]], bucket: str) -> None:
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
                "description": repo.get("description") or "",
                "topics": repo.get("topics") or [],
                "owner_login": (repo.get("owner") or {}).get("login", ""),
                "owner_avatar_url": (repo.get("owner") or {}).get("avatar_url", ""),
                "owner_html_url": (repo.get("owner") or {}).get("html_url", ""),
                "bucket": bucket,
                "pick_reason": repo.get("_pick_reason") or "",
            }
        )
    save_history(history[-300:])


def build_archive_controls(history: list[dict[str, Any]]) -> str:
    settings = low_star_high_score_settings()
    languages = sorted(
        {str(item.get("language") or "N/A") for item in history},
        key=lambda value: value.lower(),
    )
    tags = sorted({tag for item in history for tag in extract_tags(item)})
    review_state_options = "".join(
        f'<option value="{escape(state)}">{escape(state)}</option>'
        for state in REVIEW_STATES
    )
    language_options = "".join(
        f'<option value="{escape(language.lower())}">{escape(language)}</option>'
        for language in languages
    )
    tag_options = "".join(
        f'<option value="{escape(tag)}">#{escape(tag)}</option>' for tag in tags[:80]
    )
    return f"""
    <section class="archive-controls" data-archive-root>
      <div class="control-group">
        <label for="search-name">Repo 名検索</label>
        <input id="search-name" type="search" placeholder="owner/repo" data-filter-search>
      </div>
      <div class="control-group">
        <label for="filter-language">Language</label>
        <select id="filter-language" data-filter-language>
          <option value="">すべて</option>
          {language_options}
        </select>
      </div>
      <div class="control-group">
        <label for="filter-tag">Hashtag / Tag</label>
        <select id="filter-tag" data-filter-tag>
          <option value="">すべて</option>
          {tag_options}
        </select>
      </div>
      <div class="control-group">
        <label for="filter-review-state">Review State</label>
        <select id="filter-review-state" data-filter-review-state>
          <option value="">すべて</option>
          {review_state_options}
        </select>
      </div>
      <div class="control-group">
        <label for="filter-stars-min">Stars 最小</label>
        <input id="filter-stars-min" type="number" min="0" placeholder="0" data-filter-stars-min>
      </div>
      <div class="control-group">
        <label for="filter-stars-max">Stars 最大</label>
        <input id="filter-stars-max" type="number" min="0" placeholder="{int(settings["max_stars"])}" data-filter-stars-max>
      </div>
      <div class="control-group">
        <label for="filter-score-min">Score 最小</label>
        <input id="filter-score-min" type="number" min="0" step="0.01" placeholder="0" data-filter-score-min>
      </div>
      <div class="control-group">
        <label for="filter-score-max">Score 最大</label>
        <input id="filter-score-max" type="number" min="0" step="0.01" placeholder="999" data-filter-score-max>
      </div>
      <div class="control-group">
        <label for="filter-sort">並び替え</label>
        <select id="filter-sort" data-filter-sort>
          <option value="newest">新着順</option>
          <option value="score">score順</option>
          <option value="stars">stars順</option>
        </select>
      </div>
    </section>
    <p class="archive-summary" data-filter-count>{len(history)} 件表示</p>
    """


def render_repo_card(
    item: dict[str, Any],
    review_state: str,
    rank: int | None = None,
    archive_card: bool = False,
) -> str:
    sent_at = escape(str(item.get("_display_time") or ""))
    full_name = escape(str(item.get("full_name") or ""))
    html_url = escape(str(item.get("html_url") or ""))
    x_post = linkify_text(str(item.get("x_post") or item.get("latest_x_post") or ""))
    language_label = str(item.get("language") or "N/A")
    language = escape(language_label)
    description = escape(normalize_card_description(item))
    owner_login_raw, owner_html_url_raw, owner_avatar_url_raw = fallback_owner_fields(item)
    owner_login = escape(owner_login_raw)
    owner_html_url = escape(owner_html_url_raw)
    owner_avatar_url = escape(owner_avatar_url_raw)
    bucket = str(item.get("bucket") or "morning")
    bucket_label = "朝の新顔枠" if bucket == "morning" else "夜の尖り枠"
    pick_reason = escape(str(item.get("pick_reason") or ""))
    topics = "".join(
        f'<span class="badge topic">#{escape(topic)}</span>'
        for topic in extract_tags(item)[:6]
    )
    review_badge = (
        f'<span class="badge review-state">state {escape(review_state)}</span>'
        if review_state
        else ""
    )
    attrs = render_data_attrs(build_card_dataset(item, review_state))
    rank_class = " rank-card" if rank is not None else ""
    if rank == 1:
        rank_class += " top1"
    elif rank == 2:
        rank_class += " top2"
    elif rank == 3:
        rank_class += " top3"
    rank_badge = f'<span class="rank-number">{rank}</span>' if rank is not None else ""
    score_value = item.get("best_score", item.get("score", 0))
    count_label = (
        f"<span>picked {int(item.get('count') or 0)} times</span>"
        if item.get("count") is not None
        else ""
    )
    return f"""
    <article class="card{rank_class}" {attrs}{' data-archive-card' if archive_card else ''}>
      <div class="card-header">
        {rank_badge}
        <img class="avatar" src="{owner_avatar_url}" alt="{owner_login}">
        <div class="card-title-wrap">
          <div class="owner-line">
            <a href="{owner_html_url}" target="_blank" rel="noreferrer">@{owner_login}</a>
          </div>
          <h2><a href="{html_url}" target="_blank" rel="noreferrer">{full_name}</a></h2>
        </div>
      </div>
      <div class="meta">
        {f'<span class="date-label">通知 {sent_at}</span>' if sent_at else ''}
        <span>{bucket_label}</span>
        <span>score {score_value}</span>
        {count_label}
        <span>stars {int(item.get("stars") or 0)}</span>
        <span>{language}</span>
      </div>
      {f'<p class="pick-reason">選定理由: {pick_reason}</p>' if pick_reason else ''}
      {f'<p class="description">{description}</p>' if description else ''}
      <pre>{x_post}</pre>
      {f'<div class="badge-row"><span class="badge">{language}</span>{review_badge}{topics}</div>' if topics or language or review_badge else ''}
    </article>
    """


def render_history_site() -> None:
    settings = low_star_high_score_settings()
    history = list(reversed(load_history()))
    state = load_state()
    review_states = state.get("review_states", {})
    grouped: dict[str, list[dict[str, Any]]] = {}
    tokyo = ZoneInfo("Asia/Tokyo")
    for item in history:
        sent_at_dt = datetime.fromisoformat(item["sent_at"]).astimezone(tokyo)
        day_key = f"{sent_at_dt.month}/{sent_at_dt.day}"
        item["_display_time"] = sent_at_dt.strftime("%Y-%m-%d %H:%M")
        grouped.setdefault(day_key, []).append(item)

    tab_options = []
    tab_panels = []
    for index, (day_key, items) in enumerate(grouped.items()):
        panel_class = "tab-panel active" if index == 0 else "tab-panel"
        tab_id = f"tab-{index}"
        selected = " selected" if index == 0 else ""
        tab_options.append(
            f'<option value="{tab_id}"{selected}>{escape(day_key)}</option>'
        )

        cards = []
        for item in items:
            review_state = normalize_review_state(review_states.get(item.get("full_name")))
            cards.append(render_repo_card(item, review_state, archive_card=True))

        tab_panels.append(
            f"""
            <section id="{tab_id}" class="{panel_class}">
              {''.join(cards)}
            </section>
            """
        )

    low_star_items = [
        item for item in history if is_low_star_high_score(item)
    ][: int(settings["limit"])]
    low_star_cards = "".join(
        render_repo_card(
            item,
            normalize_review_state(review_states.get(item.get("full_name"))),
        )
        for item in low_star_items
    )
    body_html = (
        (
            "<section class='section-block'>"
            "<div class='section-header'>"
            "<h2>Low Stars / High Score</h2>"
            f"<p>stars <= {int(settings['max_stars'])} かつ score >= {float(settings['min_score']):g} の発掘枠です。</p>"
            "</div>"
            + (
                f"<div class='section-grid'>{low_star_cards}</div>"
                if low_star_cards
                else "<p class='empty-state'>条件に合う repo はまだありません。</p>"
            )
            + "</section>"
        )
        + build_archive_controls(history)
        +
        (
            "<div class='filter-bar'>"
            "<button class='filter-button active' data-bucket-filter='all'>全部</button>"
            "<button class='filter-button' data-bucket-filter='morning'>朝の新顔枠</button>"
            "<button class='filter-button' data-bucket-filter='evening'>夜の尖り枠</button>"
            "</div>"
        )
        + (
            "<div class='date-selector'><select class='date-select' data-day-select>"
            + "".join(tab_options)
            + "</select></div>"
            if tab_options
            else ""
        )
        + (
            "".join(tab_panels)
            if tab_panels
            else "<p class='empty-state'>まだ履歴はありません。</p>"
        )
    )
    html = site_shell(
        "Repo History",
        "Telegram に送った repo を、検索・選別・再利用しやすい形で見返せるアーカイブです。",
        body_html,
        "history",
    )
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def build_week_window(
    now: datetime,
    scope: str = "previous",
) -> tuple[datetime, datetime, str]:
    tokyo_now = now.astimezone(ZoneInfo("Asia/Tokyo"))
    week_start = (tokyo_now - timedelta(days=tokyo_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if scope == "current":
        range_start = week_start
        range_end = tokyo_now
    else:
        range_start = week_start - timedelta(days=7)
        range_end = week_start
    label = (
        f"{range_start.month}/{range_start.day}"
        f" - {(range_end - timedelta(days=1)).month}/{(range_end - timedelta(days=1)).day}"
        if range_end > range_start
        else f"{range_start.month}/{range_start.day}"
    )
    return range_start, range_end, label


def build_weekly_ranking(
    history: list[dict[str, Any]],
    now: datetime,
    scope: str = "previous",
) -> tuple[list[dict[str, Any]], str]:
    range_start, range_end, label = build_week_window(now, scope)

    aggregated: dict[str, dict[str, Any]] = {}
    for item in history:
        sent_at = item.get("sent_at")
        full_name = item.get("full_name")
        if not sent_at or not full_name:
            continue
        sent_at_dt = parse_sent_at(sent_at)
        if not (range_start <= sent_at_dt < range_end):
            continue
        owner_login, owner_html_url, owner_avatar_url = fallback_owner_fields(item)
        entry = aggregated.setdefault(
            full_name,
            {
                "full_name": full_name,
                "html_url": item.get("html_url") or "",
                "language": item.get("language") or "N/A",
                "count": 0,
                "best_score": 0.0,
                "latest_x_post": item.get("x_post") or "",
                "latest_sent_at": sent_at_dt,
                "stars": item.get("stars") or 0,
                "description": normalize_card_description(item),
                "topics": item.get("topics") or [],
                "owner_login": owner_login,
                "owner_avatar_url": owner_avatar_url,
                "owner_html_url": owner_html_url,
                "bucket": item.get("bucket") or "morning",
                "pick_reason": item.get("pick_reason") or "",
            },
        )
        entry["count"] += 1
        item_score = float(item.get("score") or 0)
        if item_score >= entry["best_score"]:
            entry["best_score"] = item_score
            entry["latest_x_post"] = item.get("x_post") or ""
            entry["stars"] = item.get("stars") or 0
        if sent_at_dt > entry["latest_sent_at"]:
            entry["latest_sent_at"] = sent_at_dt

    ranking = sorted(
        aggregated.values(),
        key=lambda item: (item["count"], item["best_score"], item["stars"]),
        reverse=True,
    )[:10]
    return ranking, label


def render_weekly_site(now: datetime | None = None) -> None:
    settings = low_star_high_score_settings()
    history = load_history()
    state = load_state()
    review_states = state.get("review_states", {})
    if now is None:
        now = datetime.now(UTC)
    ranking, label = build_weekly_ranking(history, now, scope="current")
    range_start, range_end, _ = build_week_window(now, "current")
    this_week_items = []
    for item in history:
        sent_at = item.get("sent_at")
        if not sent_at:
            continue
        sent_at_dt = parse_sent_at(sent_at)
        if range_start <= sent_at_dt < range_end:
            enriched_item = dict(item)
            enriched_item["_parsed_sent_at"] = sent_at_dt
            this_week_items.append(enriched_item)
    low_star_ranking = [item for item in ranking if is_low_star_high_score(item)][
        : int(settings["limit"])
    ]
    fresh_repo_map: dict[str, dict[str, Any]] = {}
    for item in sorted(
        this_week_items,
        key=lambda current: (
            current.get("_parsed_sent_at"),
            float(current.get("score") or 0),
        ),
        reverse=True,
    ):
        full_name = str(item.get("full_name") or "").strip()
        if not full_name or full_name in fresh_repo_map:
            continue
        fresh_repo_map[full_name] = item
    fresh_picks = list(fresh_repo_map.values())[: int(settings["limit"])]
    weekly_repo_items = ranking[:]
    review_state_counts: dict[str, int] = {}
    for item in weekly_repo_items:
        review_state = normalize_review_state(review_states.get(item.get("full_name")))
        item["_review_state"] = review_state
        review_state_counts[review_state] = review_state_counts.get(review_state, 0) + 1
    review_state_summary = ", ".join(
        f"{state_name} {review_state_counts[state_name]}"
        for state_name in REVIEW_STATES
        if review_state_counts.get(state_name)
    ) or "なし"
    review_priority_items = [
        item
        for item in weekly_repo_items
        if item.get("_review_state") in {"good", "production_candidate"}
    ][: int(settings["limit"])]
    unseen_items = [
        item for item in weekly_repo_items if item.get("_review_state") == "unseen"
    ][: int(settings["limit"])]
    avg_score = (
        sum(float(item.get("score") or 0) for item in this_week_items) / len(this_week_items)
        if this_week_items
        else 0.0
    )
    unique_repos = len({item.get("full_name") for item in this_week_items})
    stats_html = f"""
    <section class="stats-grid">
      <article class="stat-card"><strong>{unique_repos}</strong><span>今週の repo 数</span></article>
      <article class="stat-card"><strong>{len(this_week_items)}</strong><span>通知総数</span></article>
      <article class="stat-card"><strong>{avg_score:.1f}</strong><span>平均 score</span></article>
      <article class="stat-card"><strong>{escape(summarize_languages(this_week_items, 4))}</strong><span>言語分布</span></article>
      <article class="stat-card"><strong>{escape(review_state_summary)}</strong><span>review state 分布</span></article>
    </section>
    """

    def render_week_section(title: str, description: str, items: list[dict[str, Any]]) -> str:
        cards = "".join(
            render_repo_card(
                item,
                normalize_review_state(review_states.get(item.get("full_name"))),
                rank=index,
            )
            for index, item in enumerate(items, start=1)
        )
        return (
            "<section class='section-block'>"
            "<div class='section-header'>"
            f"<h2>{escape(title)}</h2>"
            f"<p>{escape(description)}</p>"
            "</div>"
            + (
                f"<div class='section-grid'>{cards}</div>"
                if cards
                else "<p class='empty-state'>該当する repo はまだありません。</p>"
            )
            + "</section>"
        )

    html = site_shell(
        "Weekly Archive",
        f"{label} の通知履歴から、再利用しやすい週次ビューを作っています。",
        stats_html
        + render_week_section(
            "今週の good / production_candidate",
            "見返す優先度が高い repo を review state ベースでまとめています。",
            review_priority_items,
        )
        + render_week_section(
            "今週の未確認 repo",
            "review state が unseen のものです。未確認が多い週かどうかもここで分かります。",
            unseen_items,
        )
        + render_week_section(
            "今週の総合トップ",
            "pick 回数、最高 score、stars をまとめて見た総合ランキングです。review state も併せて見返せます。",
            ranking,
        )
        + render_week_section(
            "今週の低スター枠トップ",
            f"stars <= {int(settings['max_stars'])} かつ score >= {float(settings['min_score']):g} の発掘枠です。",
            low_star_ranking,
        )
        + render_week_section(
            "今週の新着で面白かったもの",
            "今週通知したものを新着寄りで並べています。未確認の掘り起こしにも使えます。",
            fresh_picks,
        ),
        "weekly",
    )
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "weekly.html").write_text(html, encoding="utf-8")


def render_static_sites(now: datetime | None = None) -> None:
    render_history_site()
    render_weekly_site(now)


def build_weekly_telegram_message(config: Config, now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(UTC)
    ranking, label = build_weekly_ranking(load_history(), now, scope="previous")
    if not ranking:
        return ""

    lines = [f"週間トップ10 {label}"]
    for index, item in enumerate(ranking, start=1):
        lines.append(
            f"{index}. {item['full_name']} | score={item['best_score']} | picked={item['count']}"
        )
    if config.public_weekly_url:
        lines.append("")
        lines.append(f"ページで見る: {config.public_weekly_url}")
    return "\n".join(lines)


def refresh_star_snapshots(state: dict[str, Any], repos: list[dict[str, Any]]) -> None:
    now_iso = datetime.now(UTC).isoformat()
    for repo in repos:
        state["repos"][repo["full_name"]] = {
            "last_stars": repo["stargazers_count"],
            "last_seen": now_iso,
        }


def run_once(config: Config, trigger: str = "manual") -> None:
    now = datetime.now(UTC)
    bucket = get_run_bucket(config, now)
    print("Searching repositories...")
    state = load_state()
    repos = search_repositories(config)
    print(f"Found {len(repos)} repositories.")
    candidates = enrich_repositories(config, repos, state, bucket)
    print(f"Selected {len(candidates)} candidates for {bucket}.")
    if not candidates:
        append_send_log(
            "skip_no_candidates",
            trigger=trigger,
            bucket=bucket,
            searched=len(repos),
        )
        refresh_star_snapshots(state, repos)
        save_state(state)
        render_static_sites(now)
        print("No candidates to notify.")
        return

    for repo in candidates:
        print(f"Summarizing {repo['full_name']}...")
        try:
            generated = build_deepseek_summary(config, repo)
            repo["_summary"], repo["_x_post"], repo["_pick_reason"] = split_generated_content(generated, repo)
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
            repo["_pick_reason"] = "今の注目候補"

    print("Sending Telegram messages...")
    append_send_log(
        "send_start",
        trigger=trigger,
        bucket=bucket,
        count=len(candidates),
        repos=[repo["full_name"] for repo in candidates],
    )
    post_to_telegram(config, candidates, bucket)
    append_send_log(
        "send_success",
        trigger=trigger,
        bucket=bucket,
        count=len(candidates),
        repos=[repo["full_name"] for repo in candidates],
    )
    refresh_star_snapshots(state, repos)
    update_state(state, candidates)
    save_state(state)
    append_history(candidates, bucket)
    render_static_sites(now)
    if now.astimezone(ZoneInfo(config.timezone)).weekday() == 0:
        weekly_message = build_weekly_telegram_message(config, now)
        if weekly_message:
            send_telegram_text(config, weekly_message)
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
            run_once(config, trigger="daemon")
        except Exception as exc:
            print(f"Run failed: {exc}", file=sys.stderr)
            time.sleep(30)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"once", "daemon", "test-telegram", "render", "review-state"}:
        print(
            "Usage: python bot.py "
            "[once --force|daemon|test-telegram|render|review-state]"
        )
        raise SystemExit(1)

    mode = sys.argv[1]
    if mode == "review-state":
        handle_review_state_cli(sys.argv[2:])
        return
    if mode == "render":
        render_static_sites()
        print("Rendered docs pages.")
        return

    config = load_config()
    if mode == "test-telegram":
        send_telegram_test(config)
        return
    if mode == "once":
        if "--force" not in sys.argv[2:]:
            print("Refusing immediate send. Use: python bot.py once --force")
            raise SystemExit(2)
        run_once(config, trigger="once_force")
        return
    run_daemon(config)


if __name__ == "__main__":
    main()
