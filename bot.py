import json
import os
import re
import re
import sys
import time
import hashlib
from html import escape
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
DOCS_DIR = ROOT / "docs"
REPOS_DIR = DOCS_DIR / "repos"
HISTORY_PATH = DOCS_DIR / "history.json"
WEEKLY_ARCHIVE_DIR = DOCS_DIR / "weekly"
LOGS_DIR = ROOT / "logs"
SEND_LOG_PATH = LOGS_DIR / "send.log"
CONTROL_REPO_FULL_NAME = "taihey5555/githubcheck"
CONTROL_REPO_ISSUES_NEW_URL = f"https://github.com/{CONTROL_REPO_FULL_NAME}/issues/new"
GITHUB_API = "https://api.github.com"
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"

TOPIC_KEYWORDS = {
    "ai": ["ai", "llm", "agent", "rag", "inference", "model"],
    "agents": ["agent", "agents", "agentic"],
    "cli": ["cli", "terminal", "shell", "tui"],
    "automation": ["automation", "workflow", "bot", "scheduler"],
    "scraping": ["scraping", "scraper", "crawler", "crawl"],
    "monitoring": ["monitoring", "monitor", "alert", "observability"],
    "security": ["security", "pentest", "auth", "sandbox", "crypto"],
    "developer-tools": ["developer", "devtools", "tooling", "debug", "build"],
}

GRAY_SEARCH_KEYWORDS = [
    "mosaic restore",
    "deepmosaic",
    "uncensor",
    "scraper",
    "downloader",
    "bypass",
    "reverse engineering",
    "mod",
    "patcher",
    "nsfw ai",
    "watermark remover",
    "video restoration",
]

GRAY_CATEGORY_KEYWORDS = {
    "adult_ai_media": [
        "adult",
        "nsfw",
        "jav",
        "mosaic",
        "pixelated",
        "uncensor",
        "decensor",
        "deepmosaic",
        "video restoration",
        "watermark remover",
        "image restoration",
    ],
    "scraper_downloader": [
        "scraper",
        "scraping",
        "crawler",
        "downloader",
        "download",
        "extractor",
        "ripper",
        "archiver",
    ],
    "reverse_modding": [
        "reverse engineering",
        "reverse-engineering",
        "decompiler",
        "disassembler",
        "patcher",
        "mod",
        "modding",
        "hook",
        "injector",
        "unofficial client",
    ],
    "policy_bypass": [
        "bypass",
        "unlock",
        "region lock",
        "geo restriction",
        "adblock",
        "paywall",
        "drm",
        "captcha",
        "anti detection",
    ],
    "security_research": [
        "security research",
        "ctf",
        "sandbox",
        "vulnerability",
        "forensics",
        "osint",
        "malware analysis",
    ],
}

GRAY_EXCLUDE_KEYWORDS = [
    "credential stealer",
    "token stealer",
    "password stealer",
    "malware builder",
    "ransomware",
    "botnet",
    "keylogger",
    "phishing kit",
    "csam",
    "child sexual",
]

GRAY_NEEDS_REVIEW_KEYWORDS = [
    "exploit",
    "poc exploit",
    "crack",
    "piracy",
    "account checker",
    "credential",
    "session hijack",
    "shellcode",
]

GRAY_SEED_KEYWORD_LIMIT = 24
GRAY_SEARCH_TERM_LIMIT = 16

REVIEW_STATES = [
    "unseen",
    "interested",
    "tested",
    "good",
    "meh",
    "production_candidate",
]

REVIEW_STATE_LABELS = {
    "unseen": "未確認",
    "interested": "気になる",
    "tested": "試した",
    "good": "良い",
    "meh": "微妙",
    "production_candidate": "本番候補",
}

RUN_STATUS_LABELS = {
    "running": "実行中",
    "success": "成功",
    "failed": "失敗",
    "unknown": "不明",
}

DEEPSEEK_WARNING_LABELS = {
    "quota/auth/billing": "認証・課金・残高",
    "rate_limit": "レート制限",
}

DEEPSEEK_WARNING_COOLDOWN_HOURS = 12

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
    collection_profile: str = "general"
    github_search_sorts: list[str] | None = None


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
        collection_profile=os.getenv("COLLECTION_PROFILE", "general").strip().lower(),
        github_search_sorts=parse_csv(os.getenv("GITHUB_SEARCH_SORTS", "stars,updated")),
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
        return {"repos": {}, "notifications": {}, "review_states": {}, "alerts": {}}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.setdefault("repos", {})
    state.setdefault("notifications", {})
    state.setdefault("review_states", {})
    state.setdefault("alerts", {})
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_run_status(
    state: dict[str, Any],
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    if started_at is not None:
        state["last_run_started_at"] = started_at
    if finished_at is not None:
        state["last_run_finished_at"] = finished_at
    if status is not None:
        state["last_run_status"] = status
    if error:
        state["last_run_error"] = error
    elif error is None:
        state.pop("last_run_error", None)
    save_state(state)


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


def format_state_timestamp(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return dt.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")


def parse_state_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def normalize_review_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    return state if state in REVIEW_STATES else "unseen"


def review_state_label(value: Any) -> str:
    normalized = normalize_review_state(value)
    return REVIEW_STATE_LABELS.get(normalized, normalized)


def review_state_options_html(selected_state: str) -> str:
    return "".join(
        f'<option value="{escape(state)}"{" selected" if state == selected_state else ""}>'
        f"{escape(review_state_label(state))}</option>"
        for state in REVIEW_STATES
    )


def review_state_request_issue_url(full_name: str, state: str) -> str:
    repo_name = str(full_name or "").strip()
    normalized_state = normalize_review_state(state)
    params = urlencode(
        {
            "title": f"[review-state] {repo_name} -> {normalized_state}",
            "body": (
                "repo: "
                + repo_name
                + "\nstate: "
                + normalized_state
                + "\nsource: pages\n\n"
                + "送信すると workflow が state.json を更新して Pages を再生成します。"
            ),
        }
    )
    return f"{CONTROL_REPO_ISSUES_NEW_URL}?{params}"


def run_status_label(value: Any) -> str:
    normalized = str(value or "").strip().lower() or "unknown"
    return RUN_STATUS_LABELS.get(normalized, normalized)


def deepseek_warning_label(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized == "none":
        return "なし"
    return DEEPSEEK_WARNING_LABELS.get(normalized, normalized)


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
    gray_category = str((item.get("gray_profile") or {}).get("category") or "").strip().lower()
    if gray_category and gray_category not in seen:
        seen.add(gray_category)
        tags.append(gray_category)
    return tags


def build_card_dataset(item: dict[str, Any], review_state: str) -> dict[str, str]:
    sent_at = str(item.get("sent_at") or "")
    score = float(item.get("score") or 0)
    stars = int(item.get("stars") or 0)
    gray = gray_display_profile(item)
    return {
        "bucket": str(item.get("bucket") or "morning"),
        "name": str(item.get("full_name") or "").lower(),
        "language": str(item.get("language") or "N/A").lower(),
        "tags": " ".join(extract_tags(item)),
        "stars": str(stars),
        "score": f"{score:.2f}",
        "sent-at": sent_at,
        "review-state": review_state,
        "gray-mode": "true" if gray["is_gray"] else "false",
        "gray-category": gray["category"],
        "gray-risk": gray["risk_status"],
    }


def render_data_attrs(values: dict[str, str]) -> str:
    return " ".join(
        f'data-{key}="{escape(value, quote=True)}"'
        for key, value in values.items()
    )


def gray_display_profile(item: dict[str, Any]) -> dict[str, str | bool]:
    """Classify for display only. Never writes back to history/state."""
    existing = item.get("gray_profile") if isinstance(item.get("gray_profile"), dict) else {}
    category = str(existing.get("category") or "").strip()
    risk_status = str(existing.get("risk_status") or "").strip()
    if category:
        return {
            "is_gray": risk_status != "exclude",
            "category": category,
            "risk_status": risk_status or "allow",
        }

    text = normalize_keyword(
        " ".join(
            [
                str(item.get("full_name") or ""),
                str(item.get("description") or ""),
                str(item.get("pick_reason") or ""),
                str(item.get("x_post") or item.get("latest_x_post") or ""),
                " ".join(str(topic) for topic in item.get("topics") or []),
            ]
        )
    )
    matched_category = ""
    matched_count = 0
    for candidate_category, keywords in GRAY_CATEGORY_KEYWORDS.items():
        hits = keyword_hits(text, keywords)
        if len(hits) > matched_count:
            matched_category = candidate_category
            matched_count = len(hits)

    if not matched_category:
        return {"is_gray": False, "category": "", "risk_status": "normal"}

    risk_hits = keyword_hits(text, GRAY_EXCLUDE_KEYWORDS)
    review_hits = keyword_hits(text, GRAY_NEEDS_REVIEW_KEYWORDS)
    if risk_hits:
        risk_status = "exclude"
    elif review_hits:
        risk_status = "needs_review"
    else:
        risk_status = "allow"
    return {
        "is_gray": risk_status != "exclude",
        "category": matched_category,
        "risk_status": risk_status,
    }


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


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def format_delta(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return ""
    if digits:
        return f"{value:+.{digits}f}"
    return f"{int(value):+d}"


def repo_slug(full_name: str) -> str:
    normalized = str(full_name or "").strip().lower()
    if not normalized:
        normalized = "repo"
    safe = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "repo"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}"


def repo_detail_href(full_name: str, path_prefix: str = ".") -> str:
    return f"{path_prefix}/repos/{repo_slug(full_name)}.html"


def history_archive_href(
    path_prefix: str = ".",
    **params: Any,
) -> str:
    query: dict[str, str] = {}
    review_state = normalize_review_state(params.get("review_state"))
    if params.get("review_state") is not None:
        query["review_state"] = review_state
    language = str(params.get("language") or "").strip().lower()
    if language:
        query["language"] = language
    tag = str(params.get("tag") or "").strip().lower()
    if tag:
        query["tag"] = tag
    for key in ("stars_min", "stars_max", "score_min", "score_max"):
        value = params.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number < 0:
            continue
        query[key] = f"{number:g}"
    sort = str(params.get("sort") or "").strip().lower()
    if sort in {"newest", "score", "stars"}:
        query["sort"] = sort
    query_string = urlencode(query)
    return f"{path_prefix}/index.html" + (f"?{query_string}" if query_string else "")


def tokyo_week_start(value: datetime) -> datetime:
    tokyo_value = value.astimezone(ZoneInfo("Asia/Tokyo"))
    return (tokyo_value - timedelta(days=tokyo_value.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def build_week_label(range_start: datetime, range_end: datetime) -> str:
    return (
        f"{range_start.month}/{range_start.day}"
        f" - {(range_end - timedelta(days=1)).month}/{(range_end - timedelta(days=1)).day}"
        if range_end > range_start
        else f"{range_start.month}/{range_start.day}"
    )


def weekly_archive_slug(week_start: datetime) -> str:
    return week_start.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def weekly_archive_href(week_start: datetime, path_prefix: str = ".") -> str:
    return f"{path_prefix}/weekly/{weekly_archive_slug(week_start)}.html"


def collect_weekly_archive_starts(history: list[dict[str, Any]]) -> list[datetime]:
    week_starts: dict[str, datetime] = {}
    for item in history:
        sent_at = item.get("sent_at")
        if not sent_at:
            continue
        week_start = tokyo_week_start(parse_sent_at(sent_at))
        week_starts[weekly_archive_slug(week_start)] = week_start
    return sorted(week_starts.values(), reverse=True)


def normalized_language_query(value: Any) -> str:
    language_value = str(value or "N/A").strip()
    if not language_value or language_value == "N/A":
        return ""
    return language_value.lower()


def render_empty_state(message: str) -> str:
    return f"<p class='empty-state'>{escape(message)}</p>"


def render_section_block(
    title: str,
    description: str,
    content_html: str,
    empty_message: str,
    layout_class: str = "section-grid",
    links_html: str = "",
) -> str:
    return (
        "<section class='section-block'>"
        "<div class='section-header'>"
        f"<h2>{escape(title)}</h2>"
        f"<p>{escape(description)}{links_html}</p>"
        "</div>"
        + (
            f"<div class='{layout_class}'>{content_html}</div>"
            if content_html
            else render_empty_state(empty_message)
        )
        + "</section>"
    )


def render_review_state_shortcuts(path_prefix: str, current_review_state: str) -> str:
    return "".join(
        (
            f'<a class="badge{" review-state" if state_name == current_review_state else ""}" '
            f'href="{history_archive_href(path_prefix=path_prefix, review_state=state_name)}">'
            f'{escape(review_state_label(state_name))}を見る</a>'
        )
        for state_name in ["good", "production_candidate", "unseen", "interested", "tested"]
    )


def aggregate_repo_history(
    history: list[dict[str, Any]],
    review_states: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    # Detail page is repo-centric, so collapse repeated notifications into one record
    # and keep just enough per-entry data to explain score/stars/topic changes later.
    aggregated: dict[str, dict[str, Any]] = {}
    for item in history:
        full_name = str(item.get("full_name") or "").strip()
        sent_at = item.get("sent_at")
        if not full_name or not sent_at:
            continue
        sent_at_dt = parse_sent_at(sent_at)
        owner_login, owner_html_url, owner_avatar_url = fallback_owner_fields(item)
        entry = aggregated.setdefault(
            full_name,
            {
                "full_name": full_name,
                "slug": repo_slug(full_name),
                "html_url": item.get("html_url") or "",
                "owner_login": owner_login,
                "owner_html_url": owner_html_url,
                "owner_avatar_url": owner_avatar_url,
                "review_state": normalize_review_state(review_states.get(full_name)),
                "first_seen": sent_at_dt,
                "latest_seen": sent_at_dt,
                "appearances": 0,
                "latest_score": float(item.get("score") or 0),
                "latest_stars": int(item.get("stars") or 0),
                "language": item.get("language") or "N/A",
                "description": item.get("description") or "",
                "pick_reason": item.get("pick_reason") or "",
                "latest_x_post": item.get("x_post") or "",
                "topics": item.get("topics") or [],
                "history_entries": [],
            },
        )
        entry["appearances"] += 1
        entry["first_seen"] = min(entry["first_seen"], sent_at_dt)
        if sent_at_dt >= entry["latest_seen"]:
            entry["latest_seen"] = sent_at_dt
            entry["latest_score"] = float(item.get("score") or 0)
            entry["latest_stars"] = int(item.get("stars") or 0)
            entry["language"] = item.get("language") or entry["language"] or "N/A"
            entry["description"] = item.get("description") or entry["description"]
            entry["pick_reason"] = item.get("pick_reason") or entry["pick_reason"]
            entry["latest_x_post"] = item.get("x_post") or entry["latest_x_post"]
            entry["html_url"] = item.get("html_url") or entry["html_url"]
        merged_topics = list(dict.fromkeys((entry.get("topics") or []) + (item.get("topics") or [])))
        entry["topics"] = merged_topics[:12]
        entry["history_entries"].append(
            {
                "sent_at": sent_at_dt,
                "score": safe_float(item.get("score")),
                "stars": safe_int(item.get("stars")),
                "bucket": item.get("bucket") or "morning",
                "language": item.get("language") or "",
                "pick_reason": item.get("pick_reason") or "",
                "topics": extract_tags(item),
                "review_state": normalize_review_state(review_states.get(full_name)),
            }
        )
    for entry in aggregated.values():
        entry["history_entries"].sort(key=lambda item: item["sent_at"], reverse=True)
        for index, history_entry in enumerate(entry["history_entries"]):
            previous_entry = entry["history_entries"][index + 1] if index + 1 < len(entry["history_entries"]) else None
            history_entry["score_delta"] = None
            history_entry["stars_delta"] = None
            history_entry["pick_reason_changed"] = False
            history_entry["topics_added"] = []
            history_entry["topics_removed"] = []
            if previous_entry is None:
                continue
            current_score = history_entry.get("score")
            previous_score = previous_entry.get("score")
            if current_score is not None and previous_score is not None:
                history_entry["score_delta"] = current_score - previous_score
            current_stars = history_entry.get("stars")
            previous_stars = previous_entry.get("stars")
            if current_stars is not None and previous_stars is not None:
                history_entry["stars_delta"] = current_stars - previous_stars
            history_entry["pick_reason_changed"] = (
                str(history_entry.get("pick_reason") or "").strip()
                != str(previous_entry.get("pick_reason") or "").strip()
            )
            current_topics = set(history_entry.get("topics") or [])
            previous_topics = set(previous_entry.get("topics") or [])
            history_entry["topics_added"] = sorted(current_topics - previous_topics)
            history_entry["topics_removed"] = sorted(previous_topics - current_topics)
    return aggregated


def find_similar_repos(
    target_repo: dict[str, Any],
    aggregated: dict[str, dict[str, Any]],
    limit: int = 4,
) -> list[dict[str, Any]]:
    # Keep similarity heuristic intentionally light: same language and shared tags
    # are enough to suggest nearby repos without introducing a heavier ranking model.
    target_name = str(target_repo.get("full_name") or "")
    target_language = str(target_repo.get("language") or "").strip().lower()
    target_topics = set(extract_tags(target_repo))
    target_state = normalize_review_state(target_repo.get("review_state"))
    target_score = float(target_repo.get("latest_score") or 0)
    candidates: list[tuple[tuple[float, float, float], dict[str, Any]]] = []
    for repo_data in aggregated.values():
        if str(repo_data.get("full_name") or "") == target_name:
            continue
        repo_language = str(repo_data.get("language") or "").strip().lower()
        repo_topics = set(extract_tags(repo_data))
        shared_topics = sorted(target_topics & repo_topics)
        same_language = bool(
            target_language and repo_language and target_language != "n/a" and target_language == repo_language
        )
        same_state = normalize_review_state(repo_data.get("review_state")) == target_state
        similarity_score = (
            len(shared_topics) * 4
            + (2 if same_language else 0)
            + (1 if same_state and target_state != "unseen" else 0)
        )
        if similarity_score <= 0:
            continue
        reason_parts = []
        if same_language:
            reason_parts.append(f"同じ言語: {repo_data.get('language') or 'N/A'}")
        if shared_topics:
            reason_parts.append(
                "共通タグ: "
                + ", ".join(f"#{topic}" for topic in shared_topics[:3])
            )
        if same_state and target_state != "unseen":
            reason_parts.append(f"同じ状態: {review_state_label(target_state)}")
        candidate = dict(repo_data)
        candidate["similarity_reason"] = " / ".join(reason_parts)
        candidate["shared_topics"] = shared_topics
        score_gap = abs(float(repo_data.get("latest_score") or 0) - target_score)
        candidates.append(
            (
                (
                    float(similarity_score),
                    -score_gap,
                    float(repo_data.get("latest_score") or 0),
                ),
                candidate,
            )
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in candidates[:limit]]


def render_repo_detail_sites() -> None:
    history = load_history()
    state = load_state()
    aggregated = aggregate_repo_history(history, state.get("review_states", {}))
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    for repo in REPOS_DIR.glob("*.html"):
        if repo.name == "index.html":
            continue
        repo.unlink()
    cooldown_days = parse_int_env("COOLDOWN_DAYS", 14, minimum=0)
    for repo_data in aggregated.values():
        state_repo = state.get("repos", {}).get(repo_data["full_name"], {})
        state_notification = state.get("notifications", {}).get(repo_data["full_name"], {})
        last_sent_dt = parse_state_iso(state_notification.get("last_sent"))
        cooldown_remaining_days = None
        if last_sent_dt is not None:
            cooldown_until = last_sent_dt + timedelta(days=cooldown_days)
            cooldown_remaining = cooldown_until - datetime.now(UTC)
            cooldown_remaining_days = max(0, cooldown_remaining.days + (1 if cooldown_remaining.seconds > 0 else 0))
        cooldown_label = (
            f"クールダウン中（残り{cooldown_remaining_days}日）"
            if cooldown_remaining_days and cooldown_remaining_days > 0
            else "クールダウン解除"
        )
        if last_sent_dt is None:
            cooldown_label = "クールダウン情報なし"
        last_sent_label = format_state_timestamp(state_notification.get("last_sent"))
        last_seen_label = format_state_timestamp(state_repo.get("last_seen"))
        last_stars_value = state_repo.get("last_stars")
        last_stars_label = str(int(last_stars_value)) if last_stars_value is not None else "-"
        low_star_settings = low_star_high_score_settings()
        current_review_state = normalize_review_state(repo_data.get("review_state"))
        current_state_href = history_archive_href(path_prefix="..", review_state=current_review_state)
        language_value = str(repo_data.get("language") or "N/A").strip()
        language_query = normalized_language_query(repo_data.get("language"))
        language_href = history_archive_href(path_prefix="..", language=language_query) if language_query else ""
        score_focus_href = history_archive_href(
            path_prefix="..",
            score_min=repo_data.get("latest_score") or 0,
            sort="score",
        )
        low_star_focus_href = history_archive_href(
            path_prefix="..",
            stars_max=low_star_settings["max_stars"],
            score_min=low_star_settings["min_score"],
            sort="score",
        )
        shortcut_links = render_review_state_shortcuts("..", current_review_state)
        review_state_request_link = review_state_request_issue_url(
            repo_data["full_name"], current_review_state
        )
        review_state_controls_html = f"""
        <div class="review-state-panel" data-review-state-panel data-repo-full-name="{escape(repo_data["full_name"], quote=True)}">
          <h3>状態を更新</h3>
          <p class="pick-reason">GitHub の issue 作成画面を開いて更新要求を送ります。送信後、workflow が state.json を更新して Pages を再生成します。</p>
          <div class="review-state-actions">
            <select data-review-state-select aria-label="更新する状態">
              {review_state_options_html(current_review_state)}
            </select>
            <a class="badge review-state" href="{escape(review_state_request_link, quote=True)}" target="_blank" rel="noreferrer" data-review-state-link>GitHubで「{escape(review_state_label(current_review_state))}」に更新</a>
          </div>
          <p class="review-state-note" data-review-state-note>送信後の成功・失敗は作成された issue にコメントされます。</p>
        </div>
        """
        topics_html = "".join(
            f'<a class="badge topic" href="{history_archive_href(path_prefix="..", tag=topic)}">#{escape(topic)}</a>'
            for topic in repo_data.get("topics") or []
        )
        language_badge_html = (
            f'<a class="badge" href="{language_href}">{escape(language_value)}</a>'
            if language_href
            else f'<span class="badge">{escape(language_value or "N/A")}</span>'
        )
        language_link_html = (
            f'<a class="badge" href="{language_href}">{escape(language_value)} のリポジトリ一覧を見る</a>'
            if language_href
            else ""
        )
        similar_repos = find_similar_repos(repo_data, aggregated)
        similar_repo_cards = []
        # Similar repos are a lightweight "what else should I open next" aid,
        # so reuse existing archive metadata instead of fetching anything new.
        for similar_repo in similar_repos:
            shared_topics = "".join(
                f'<a class="badge topic" href="{history_archive_href(path_prefix="..", tag=topic)}">#{escape(topic)}</a>'
                for topic in similar_repo.get("shared_topics") or []
            )
            similar_repo_cards.append(
                f"""
                <article class="history-item">
                  <div class="meta">
                    <span>{escape(str(similar_repo.get("language") or "N/A"))}</span>
                    <span>score {float(similar_repo.get("latest_score") or 0):.2f}</span>
                    <span>stars {int(similar_repo.get("latest_stars") or 0)}</span>
                    <span>状態 {escape(review_state_label(similar_repo.get("review_state")))}</span>
                  </div>
                  <h3><a href="{repo_detail_href(str(similar_repo.get("full_name") or ""), path_prefix="..")}" target="_self">{escape(str(similar_repo.get("full_name") or ""))}</a></h3>
                  {f'<p class="pick-reason">{escape(str(similar_repo.get("similarity_reason") or ""))}</p>' if similar_repo.get("similarity_reason") else ''}
                  {f'<p class="description">{escape(str(similar_repo.get("description") or ""))}</p>' if similar_repo.get("description") else ''}
                  {f'<div class="badge-row">{shared_topics}</div>' if shared_topics else ''}
                  <div class="detail-links primary-links">
                    <a class="badge" href="{repo_detail_href(str(similar_repo.get("full_name") or ""), path_prefix="..")}">詳細</a>
                    <a class="badge" href="{escape(str(similar_repo.get("html_url") or ""))}" target="_blank" rel="noreferrer">GitHub</a>
                  </div>
                </article>
                """
            )
        history_items = []
        # Related history focuses on "what changed since last time" rather than raw dumps,
        # so each entry carries deltas that make repeated notifications easier to compare.
        for item in repo_data["history_entries"]:
            bucket = "朝の新顔枠" if item["bucket"] == "morning" else "夜の尖り枠"
            pick_reason = escape(item["pick_reason"] or "")
            score_delta = format_delta(item.get("score_delta"), digits=2)
            stars_delta = format_delta(item.get("stars_delta"))
            language = escape(str(item.get("language") or "N/A"))
            review_state = escape(review_state_label(item.get("review_state")))
            topics_html = "".join(
                f'<span class="badge topic">#{escape(topic)}</span>'
                for topic in item.get("topics") or []
            )
            topic_changes = []
            if item.get("topics_added"):
                topic_changes.append(
                    "追加: " + ", ".join(f"#{topic}" for topic in item["topics_added"][:4])
                )
            if item.get("topics_removed"):
                topic_changes.append(
                    "削除: " + ", ".join(f"#{topic}" for topic in item["topics_removed"][:4])
                )
            history_items.append(
                f"""
                <article class="history-item">
                  <div class="meta">
                    <span class="date-label">{escape(item["sent_at"].strftime("%Y-%m-%d %H:%M"))}</span>
                    <span>{bucket}</span>
                    <span>score {item["score"] if item["score"] is not None else "-"}</span>
                    {f'<span>前回比 {score_delta}</span>' if score_delta else ''}
                    <span>stars {item["stars"] if item["stars"] is not None else "-"}</span>
                    {f'<span>前回比 {stars_delta}</span>' if stars_delta else ''}
                    <span>{language}</span>
                    <span>状態 {review_state}</span>
                  </div>
                  {f'<p class="pick-reason">選定理由: {pick_reason}</p>' if pick_reason else ''}
                  {f'<p class="pick-reason">選定理由が前回から変化しています</p>' if item.get("pick_reason_changed") else ''}
                  {f'<p class="pick-reason">トピック変化: {" / ".join(topic_changes)}</p>' if topic_changes else ''}
                  {f'<div class="badge-row">{topics_html}</div>' if topics_html else ''}
                </article>
                """
            )
        body_html = f"""
        <section class="section-block">
          <article class="card">
            <div class="card-header">
              <img class="avatar" src="{escape(repo_data['owner_avatar_url'])}" alt="{escape(repo_data['owner_login'])}">
              <div class="card-title-wrap">
                <div class="owner-line">
                  <a href="{escape(repo_data['owner_html_url'])}" target="_blank" rel="noreferrer">@{escape(repo_data['owner_login'])}</a>
                </div>
                <h2>{escape(repo_data['full_name'])}</h2>
              </div>
            </div>
            <div class="meta">
              <span>stars {int(repo_data['latest_stars'])}</span>
              <span>score {repo_data['latest_score']}</span>
              <span>{escape(str(repo_data['language'] or 'N/A'))}</span>
              <span>状態 {escape(review_state_label(current_review_state))}</span>
              <span>登場 {int(repo_data['appearances'])}回</span>
            </div>
            <div class="meta">
              <span>最終通知 {escape(last_sent_label)}</span>
              <span>{escape(cooldown_label)}</span>
              <span>最終観測 {escape(last_seen_label)}</span>
              <span>最終stars {escape(last_stars_label)}</span>
            </div>
            {review_state_controls_html}
            {f'<p class="pick-reason">選定理由: {escape(repo_data["pick_reason"])}</p>' if repo_data.get("pick_reason") else ''}
            {f'<p class="description">{escape(repo_data["description"])}</p>' if repo_data.get("description") else ''}
            <pre>{linkify_text(str(repo_data.get("latest_x_post") or ""))}</pre>
            {f'<div class="badge-row">{language_badge_html}<span class="badge review-state">状態 {escape(review_state_label(current_review_state))}</span>{topics_html}</div>' if topics_html or repo_data.get("language") else ''}
            <div class="detail-links primary-links">
              <a class="badge" href="{escape(str(repo_data.get("html_url") or ""))}" target="_blank" rel="noreferrer">GitHub</a>
              <a class="badge" href="../index.html">履歴</a>
              <a class="badge" href="../weekly.html">週間</a>
            </div>
            <div class="detail-links secondary-links">
              <a class="badge review-state" href="{current_state_href}">{escape(review_state_label(current_review_state))}の一覧を見る</a>
            </div>
            <div class="detail-links secondary-links">
              {language_link_html}
              <a class="badge" href="{score_focus_href}">高スコアの一覧を見る</a>
              <a class="badge" href="{low_star_focus_href}">低スター高スコアを見る</a>
            </div>
            <div class="detail-links secondary-links">
              {shortcut_links}
            </div>
          </article>
        </section>
        <section class="stats-grid">
          <article class="stat-card"><strong>{escape(repo_data["first_seen"].strftime("%Y-%m-%d %H:%M"))}</strong><span>初回出現日時</span></article>
          <article class="stat-card"><strong>{escape(repo_data["latest_seen"].strftime("%Y-%m-%d %H:%M"))}</strong><span>最新出現日時</span></article>
          <article class="stat-card"><strong>{int(repo_data["appearances"])}</strong><span>出現回数</span></article>
          <article class="stat-card"><strong>{escape(review_state_label(current_review_state))}</strong><span>状態</span></article>
        </section>
        {render_section_block(
            "似ているリポジトリ",
            "同じ言語や共通タグを手がかりに、近いリポジトリを見返しやすく並べています。",
            "".join(similar_repo_cards),
            "このリポジトリに近い候補は、まだ十分に集まっていません。",
            layout_class="history-list",
        )}
        {render_section_block(
            "関連する履歴",
            "同じリポジトリの通知履歴を新しい順に並べています。score や stars の変化もここで追えます。",
            "".join(history_items),
            "このリポジトリの比較できる履歴は、まだありません。",
            layout_class="history-list",
        )}
        """
        html = site_shell(
            repo_data["full_name"],
            "リポジトリごとの通知履歴をまとめた静的詳細ページです。",
            body_html,
            "detail",
            path_prefix="..",
        )
        (REPOS_DIR / f"{repo_data['slug']}.html").write_text(html, encoding="utf-8")


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


def site_shell(
    title: str,
    subtitle: str,
    body_html: str,
    current_page: str,
    path_prefix: str = ".",
) -> str:
    history_active = 'aria-current="page"' if current_page == "history" else ""
    weekly_active = 'aria-current="page"' if current_page == "weekly" else ""
    operations_active = 'aria-current="page"' if current_page == "operations" else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --surface: #ffffff;
      --surface-muted: #f1f4f8;
      --surface-strong: #e7edf4;
      --ink: #172033;
      --muted: #637083;
      --subtle: #8994a6;
      --line: #d7dee8;
      --line-soft: #e8edf4;
      --accent: #1f6feb;
      --accent-2: #0f8a7a;
      --warn: #a35c00;
      --shadow: 0 8px 24px rgba(23, 32, 51, 0.06);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
      color: var(--ink);
      background: var(--bg);
      font-size: 15px;
      line-height: 1.55;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .site-header {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(255, 255, 255, 0.94);
      border-bottom: 1px solid var(--line);
    }}
    .header-inner {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand {{
      display: inline-flex;
      flex-direction: column;
      gap: 1px;
      color: var(--ink);
    }}
    .brand strong {{
      font-size: 14px;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .brand span {{
      font-size: 12px;
      color: var(--muted);
    }}
    .menu-toggle {{
      display: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.7);
      border-radius: 8px;
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
      border-radius: 8px;
    }}
    .site-nav {{
      display: flex;
      gap: 6px;
      align-items: center;
    }}
    .site-nav a {{
      color: var(--ink);
      padding: 7px 10px;
      border-radius: 8px;
      border: 1px solid transparent;
      font-size: 13px;
    }}
    .site-nav a[aria-current="page"] {{
      background: #eef4ff;
      color: #164ca4;
      border-color: #b8cdf8;
    }}
    .site-nav a:hover {{
      background: var(--surface-muted);
      border-color: var(--line);
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 24px 64px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 24px;
      margin-bottom: 18px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }}
    .hero h1 {{
      margin: 0 0 6px;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1.04;
      letter-spacing: 0;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      max-width: 760px;
    }}
    .date-selector {{
      margin: 0 0 22px;
    }}
    .date-select {{
      width: min(280px, 100%);
      border: 1px solid var(--line);
      background: rgba(238, 243, 248, 0.96);
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 8px;
      font: inherit;
    }}
    .filter-bar {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 18px;
    }}
    .archive-controls {{
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(220px, 1.5fr) repeat(auto-fit, minmax(140px, 1fr));
      margin: 0 0 12px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: none;
    }}
    .control-group {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .control-group label {{
      font-size: 11px;
      color: var(--muted);
      font-weight: 700;
    }}
    .control-group input,
    .control-group select {{
      width: 100%;
      border: 1px solid var(--line);
      background: var(--surface-muted);
      color: var(--ink);
      padding: 8px 10px;
      border-radius: 8px;
      font: inherit;
      font-size: 13px;
    }}
    .archive-summary {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .archive-share {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 0 0 12px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: none;
    }}
    .archive-share input {{
      flex: 1 1 320px;
      min-width: 220px;
      border: 1px solid var(--line);
      background: var(--surface-muted);
      color: var(--ink);
      padding: 10px 12px;
      border-radius: 8px;
      font: inherit;
    }}
    .archive-share-status {{
      color: var(--muted);
      font-size: 12px;
    }}
    .section-block {{
      margin: 0 0 28px;
      background: transparent;
      border: 0;
      border-radius: 0;
    }}
    .section-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
      margin: 0 0 16px;
      align-items: start;
    }}
    .section-header h2,
    .section-header h3 {{
      margin: 0;
    }}
    .section-header p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
      max-width: 720px;
    }}
    .section-grid {{
      display: grid;
      gap: 12px;
    }}
    .empty-state {{
      padding: 18px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--muted);
    }}
    .tab-button,
    .filter-button {{
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      padding: 8px 12px;
      border-radius: 8px;
      cursor: pointer;
      font: inherit;
      transition: transform 120ms ease, background 120ms ease;
    }}
    .tab-button:hover,
    .filter-button:hover {{
      transform: translateY(-1px);
      background: var(--surface-muted);
    }}
    .tab-button.active,
    .filter-button.active {{
      background: #eaf6f4;
      color: #0b655a;
      border-color: #bde4de;
    }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .card.hidden-by-filter {{ display: none; }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin: 0 0 10px;
      box-shadow: none;
    }}
    .meta {{
      display: flex;
      gap: 6px;
      row-gap: 6px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 10px;
      line-height: 1.3;
    }}
    .meta span {{
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 6px;
      background: var(--surface-muted);
      border: 1px solid rgba(15, 23, 42, 0.06);
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .avatar {{
      width: 42px;
      height: 42px;
      border-radius: 8px;
      object-fit: cover;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.9);
      flex: 0 0 auto;
    }}
    .card-title-wrap {{
      min-width: 0;
      flex: 1 1 auto;
    }}
    .card h2 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.22;
      letter-spacing: 0;
    }}
    .card h2 a {{
      color: var(--ink);
    }}
    .card:hover {{
      border-color: #b8cdf8;
      box-shadow: var(--shadow);
    }}
    .owner-line {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 2px;
    }}
    .owner-line a {{
      color: var(--muted);
    }}
    .description {{
      margin: 0 0 10px;
      color: rgba(15, 23, 42, 0.78);
      line-height: 1.6;
      font-size: 13px;
    }}
    .pick-reason {{
      margin: 0 0 10px;
      color: rgba(15, 23, 42, 0.72);
      line-height: 1.5;
      font-size: 12px;
      opacity: 0.92;
      padding-left: 10px;
      border-left: 3px solid #b8cdf8;
    }}
    .badge-row {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin: 14px 0 0;
    }}
    .archive-select-row {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .archive-select-row label {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .archive-select-row select {{
      min-width: min(320px, 100%);
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      font: inherit;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 5px 8px;
      border-radius: 6px;
      background: var(--surface-muted);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 11px;
      line-height: 1;
      font-weight: 500;
    }}
    .badge.topic {{
      background: #eef4ff;
      color: #164ca4;
      border-color: #c8d8f6;
    }}
    .badge.review-state {{
      background: #fff5e6;
      color: var(--warn);
      border-color: #f0d2a5;
    }}
    .review-state-panel {{
      margin-top: 14px;
      padding: 14px 16px;
      border: 1px solid rgba(15, 23, 42, 0.08);
      border-radius: 8px;
      background: var(--surface-muted);
    }}
    .review-state-panel h3 {{
      margin: 0 0 8px;
      font-size: 0.98rem;
    }}
    .review-state-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-top: 10px;
    }}
    .review-state-actions select {{
      min-width: 180px;
      font: inherit;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      padding: 10px 12px;
      color: var(--text);
    }}
    .review-state-note {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .date-label {{
      font-variant-numeric: tabular-nums;
    }}
    .rank-card {{
      position: relative;
      overflow: hidden;
    }}
    .rank-number {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: #eef4ff;
      border: 1px solid #b8cdf8;
      color: #164ca4;
      font-weight: 700;
      font-size: 18px;
      flex: 0 0 auto;
    }}
    .rank-card.top1 {{
      border-width: 1px;
      border-color: #f0d2a5;
      background: #fffaf2;
    }}
    .rank-card.top1 .rank-number {{
      width: 44px;
      height: 44px;
      background: #fff0d6;
      color: var(--warn);
      font-size: 20px;
    }}
    .rank-card.top2 .rank-number,
    .rank-card.top3 .rank-number {{
      background: #eaf6f4;
      color: #0b655a;
      border-color: #bde4de;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 0 0 22px;
    }}
    .stat-card {{
      padding: 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      box-shadow: none;
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
    .detail-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 14px 0 0;
      align-items: center;
    }}
    .detail-links.primary-links .badge:first-child,
    .detail-links.primary-links a:first-child {{
      background: #eef4ff;
      color: #164ca4;
      border-color: #b8cdf8;
    }}
    .detail-links.secondary-links .badge,
    .detail-links.secondary-links a {{
      background: var(--surface-muted);
    }}
    .inline-links {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    .history-list {{
      display: grid;
      gap: 10px;
    }}
    .history-item {{
      padding: 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      box-shadow: none;
    }}
    .history-item h3 {{
      margin: 0 0 10px;
      font-size: 17px;
      line-height: 1.3;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: clamp(20px, 3vw, 24px);
      line-height: 1.15;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 12px 0 0;
      font: inherit;
      line-height: 1.62;
      padding: 12px;
      border-radius: 8px;
      background: var(--surface-muted);
      border: 1px solid var(--line-soft);
    }}
    .app-shell {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 76px minmax(0, 1fr);
    }}
    .side-rail {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 16px 8px;
      background: linear-gradient(180deg, #07182f 0%, #082442 100%);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 16px;
      z-index: 30;
    }}
    .side-logo {{
      width: 42px;
      height: 42px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      background: rgba(255,255,255,0.12);
      color: #fff;
      font-weight: 800;
      letter-spacing: 0;
      border: 1px solid rgba(255,255,255,0.16);
    }}
    .side-nav {{
      width: 100%;
      display: grid;
      gap: 8px;
    }}
    .side-nav a {{
      min-height: 58px;
      padding: 8px 4px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      gap: 4px;
      color: rgba(255,255,255,0.76);
      font-size: 11px;
      border: 1px solid transparent;
    }}
    .side-nav a[aria-current="page"] {{
      background: #0f4da0;
      color: #fff;
      border-color: rgba(255,255,255,0.12);
    }}
    .nav-icon {{
      font-size: 18px;
      line-height: 1;
      font-weight: 800;
    }}
    .app-main {{
      min-width: 0;
    }}
    .site-header {{
      left: 76px;
    }}
    .brand-row {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }}
    .brand.brand-row {{
      flex-direction: row;
    }}
    .brand-row > span:not(.brand-mark) {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}
    .brand-mark {{
      width: 30px;
      height: 30px;
      border-radius: 10px;
      display: none;
      place-items: center;
      background: #07182f;
      color: #fff;
      font-size: 13px;
      font-weight: 800;
      flex: 0 0 auto;
    }}
    .top-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
    }}
    .icon-button {{
      width: 36px;
      height: 36px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      display: grid;
      place-items: center;
      font-weight: 800;
    }}
    .dashboard-hero {{
      padding: 22px 24px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--surface);
      box-shadow: var(--shadow);
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
      gap: 24px;
      align-items: center;
      margin: 0 0 18px;
    }}
    .dashboard-hero h2 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 3vw, 40px);
      line-height: 1.08;
    }}
    .hero-kicker {{
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
    }}
    .hero-copy {{
      margin: 0;
      color: var(--muted);
      max-width: 620px;
    }}
    .hero-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .hero-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      border-radius: 999px;
      background: var(--surface-muted);
      color: var(--ink);
      font-size: 12px;
      font-weight: 700;
    }}
    .mini-chart {{
      height: 132px;
      padding: 14px;
      border-left: 1px solid var(--line);
    }}
    .mini-chart-title {{
      margin: 0 0 10px;
      font-weight: 800;
      font-size: 13px;
    }}
    .mini-bars {{
      height: 78px;
      display: flex;
      align-items: end;
      gap: 8px;
      border-bottom: 1px solid var(--line-soft);
    }}
    .mini-bar {{
      flex: 1;
      min-width: 12px;
      border-radius: 7px 7px 0 0;
      background: linear-gradient(180deg, #2f7df6, #185bd8);
    }}
    .mini-chart-labels {{
      display: flex;
      justify-content: space-between;
      color: var(--subtle);
      font-size: 11px;
      margin-top: 7px;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 0 0 16px;
    }}
    .kpi-card {{
      display: grid;
      grid-template-columns: 48px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      min-height: 88px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }}
    .kpi-icon {{
      width: 48px;
      height: 48px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      background: #eef4ff;
      color: #164ca4;
      font-weight: 900;
    }}
    .kpi-card strong {{
      display: block;
      font-size: 26px;
      line-height: 1.05;
      margin: 2px 0;
    }}
    .kpi-card span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .dashboard-panel {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 16px;
      margin: 0 0 16px;
    }}
    .panel-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 0 0 14px;
    }}
    .panel-title h2,
    .panel-title h3 {{
      margin: 0;
      font-size: 18px;
    }}
    .mode-toggle {{
      display: inline-grid;
      grid-template-columns: repeat(2, minmax(84px, 1fr));
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--surface-muted);
      gap: 3px;
    }}
    .mode-toggle button {{
      border: 0;
      border-radius: 8px;
      padding: 8px 10px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }}
    .mode-toggle button.active {{
      background: #1f6feb;
      color: #fff;
      box-shadow: 0 6px 14px rgba(31, 111, 235, 0.22);
    }}
    .archive-controls {{
      box-shadow: none;
      border-radius: 12px;
      margin-bottom: 12px;
    }}
    .archive-share {{
      display: none;
    }}
    .archive-list {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }}
    .archive-list .card {{
      margin: 0;
      display: flex;
      flex-direction: column;
    }}
    .archive-list pre {{
      max-height: 8.2em;
      overflow: hidden;
    }}
    .spotlight-strip {{
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(240px, 1fr);
      gap: 12px;
      overflow-x: auto;
      padding-bottom: 4px;
    }}
    .spotlight-strip .card {{
      margin: 0;
      background: #071d38;
      border-color: #12345f;
      color: #fff;
    }}
    .spotlight-strip .card a,
    .spotlight-strip .card h2 a {{
      color: #fff;
    }}
    .spotlight-strip .meta span,
    .spotlight-strip pre,
    .spotlight-strip .badge {{
      background: rgba(255,255,255,0.1);
      border-color: rgba(255,255,255,0.12);
      color: rgba(255,255,255,0.86);
    }}
    .mobile-segment {{
      display: none;
    }}
    body.gray-mode .card[data-archive-card][data-gray-mode="false"] {{
      display: none;
    }}
    @media (max-width: 720px) {{
      .app-shell {{
        display: block;
      }}
      .side-rail {{
        display: none;
      }}
      .menu-toggle {{
        display: inline-flex;
      }}
      .brand-mark {{
        display: grid;
      }}
      .top-actions {{
        display: none;
      }}
      .mobile-segment {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 2px;
        padding: 4px;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: var(--surface);
        margin: 10px 14px 0;
      }}
      .mobile-segment a {{
        text-align: center;
        padding: 8px;
        border-radius: 9px;
        color: var(--ink);
        font-weight: 800;
        font-size: 13px;
      }}
      .mobile-segment a[aria-current="page"] {{
        background: #1f6feb;
        color: #fff;
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
        border-radius: 8px;
        background: var(--surface);
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
        padding: 22px 14px 48px;
      }}
      .hero {{
        display: none;
      }}
      .dashboard-hero {{
        grid-template-columns: 1fr;
        padding: 18px;
        border-radius: 16px;
      }}
      .mini-chart {{
        display: none;
      }}
      .kpi-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .stats-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .stat-card strong {{
        font-size: 22px;
        line-height: 1.12;
      }}
      .kpi-card {{
        grid-template-columns: 1fr;
        gap: 8px;
      }}
      .archive-list {{
        grid-template-columns: 1fr;
      }}
      .spotlight-strip {{
        grid-auto-columns: minmax(170px, 74vw);
      }}
      .card {{
        padding: 14px;
      }}
      .archive-controls {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="side-rail" aria-label="主要ナビゲーション">
      <a class="side-logo" href="{path_prefix}/index.html" aria-label="GitHub Check">GH</a>
      <nav class="side-nav">
        <a href="{path_prefix}/index.html" {history_active}><span class="nav-icon">H</span><span>履歴</span></a>
        <a href="{path_prefix}/weekly.html" {weekly_active}><span class="nav-icon">W</span><span>週次</span></a>
        <a href="{path_prefix}/operations.html" {operations_active}><span class="nav-icon">O</span><span>運用</span></a>
      </nav>
    </aside>
    <div class="app-main">
      <header class="site-header">
        <div class="header-inner">
          <a class="brand brand-row" href="{path_prefix}/index.html">
            <span class="brand-mark">GH</span>
            <span>
              <strong>GitHub Check</strong>
              <span>repo 通知の履歴と週間まとめ</span>
            </span>
          </a>
          <nav id="site-nav" class="site-nav">
            <a href="{path_prefix}/index.html" {history_active}>履歴</a>
            <a href="{path_prefix}/weekly.html" {weekly_active}>週次</a>
            <a href="{path_prefix}/operations.html" {operations_active}>運用サマリー</a>
          </nav>
          <div class="top-actions" aria-label="ページ操作">
            <span>静的アーカイブ</span>
            <span class="icon-button" aria-hidden="true">R</span>
          </div>
          <button class="menu-toggle" aria-label="メニューを開く" aria-expanded="false" aria-controls="site-nav">
            <span class="menu-icon" aria-hidden="true">
              <span></span>
              <span></span>
              <span></span>
            </span>
          </button>
        </div>
        <nav class="mobile-segment" aria-label="主要ナビゲーション">
          <a href="{path_prefix}/index.html" {history_active}>履歴</a>
          <a href="{path_prefix}/weekly.html" {weekly_active}>週次</a>
          <a href="{path_prefix}/operations.html" {operations_active}>運用</a>
        </nav>
      </header>
      <main>
        {body_html}
      </main>
    </div>
  </div>
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
    const weeklyArchiveSelect = document.querySelector('[data-weekly-archive-select]');
    if (weeklyArchiveSelect) {{
      weeklyArchiveSelect.addEventListener('change', () => {{
        const target = String(weeklyArchiveSelect.value || '').trim();
        if (target) window.location.href = target;
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
      const copyLinkButton = archiveRoot.querySelector('[data-copy-filter-link]');
      const openLink = archiveRoot.querySelector('[data-open-filter-link]');
      const linkOutput = archiveRoot.querySelector('[data-filter-link-output]');
      const shareStatus = archiveRoot.querySelector('[data-filter-link-status]');
      const panelsById = new Map(Array.from(document.querySelectorAll('.tab-panel')).map((panel) => [panel.id, panel]));

      const activePanelId = () => daySelect ? daySelect.value : '';
      const activeBucket = () => document.querySelector('[data-bucket-filter].active')?.dataset.bucketFilter || 'all';
      const normalizeText = (value) => String(value || '').toLowerCase();
      const allowedReviewStates = new Set(['unseen', 'interested', 'tested', 'good', 'meh', 'production_candidate']);
      const allowedSorts = new Set(['newest', 'score', 'stars']);
      const searchParams = new URLSearchParams(window.location.search);
      const initialSearch = String(searchParams.get('search') || '').trim();
      const initialReviewState = normalizeText(searchParams.get('review_state'));
      const initialLanguage = normalizeText(searchParams.get('language'));
      const initialTag = normalizeText(searchParams.get('tag'));
      const initialStarsMin = searchParams.get('stars_min');
      const initialStarsMax = searchParams.get('stars_max');
      const initialScoreMin = searchParams.get('score_min');
      const initialScoreMax = searchParams.get('score_max');
      const initialSort = normalizeText(searchParams.get('sort'));
      const initialMode = normalizeText(searchParams.get('mode')) === 'gray' ? 'gray' : 'normal';
      const modeButtons = Array.from(document.querySelectorAll('[data-archive-mode]'));
      let archiveMode = initialMode;
      const parseNumber = (value) => {{
        if (value === '' || value == null) return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
      }};
      const setNumericInputIfValid = (input, rawValue) => {{
        if (!input) return;
        const parsed = parseNumber(rawValue);
        if (parsed == null || parsed < 0) return;
        input.value = String(parsed);
      }};
      const buildArchiveShareUrl = () => {{
        const params = new URLSearchParams();
        const search = String(searchInput?.value || '').trim();
        const reviewState = normalizeText(reviewStateInput?.value);
        const language = normalizeText(languageInput?.value);
        const tag = normalizeText(tagInput?.value);
        const minStars = parseNumber(minStarsInput?.value);
        const maxStars = parseNumber(maxStarsInput?.value);
        const minScore = parseNumber(minScoreInput?.value);
        const maxScore = parseNumber(maxScoreInput?.value);
        const sortKey = normalizeText(sortInput?.value || 'newest');
        if (archiveMode === 'gray') params.set('mode', 'gray');
        if (search) params.set('search', search);
        if (allowedReviewStates.has(reviewState)) params.set('review_state', reviewState);
        if (language && Array.from(languageInput?.options || []).some((option) => option.value === language)) {{
          params.set('language', language);
        }}
        if (tag && Array.from(tagInput?.options || []).some((option) => option.value === tag)) {{
          params.set('tag', tag);
        }}
        if (minStars != null && minStars >= 0) params.set('stars_min', String(minStars));
        if (maxStars != null && maxStars >= 0) params.set('stars_max', String(maxStars));
        if (minScore != null && minScore >= 0) params.set('score_min', String(minScore));
        if (maxScore != null && maxScore >= 0) params.set('score_max', String(maxScore));
        if (allowedSorts.has(sortKey) && sortKey !== 'newest') params.set('sort', sortKey);
        const shareUrl = new URL(window.location.pathname, window.location.href);
        shareUrl.search = params.toString();
        return shareUrl.toString();
      }};
      const updateArchiveShareUi = (statusText = '') => {{
        const shareUrl = buildArchiveShareUrl();
        if (openLink) openLink.href = shareUrl;
        if (linkOutput) linkOutput.value = shareUrl;
        if (shareStatus) shareStatus.textContent = statusText || '';
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
        document.body.classList.toggle('gray-mode', archiveMode === 'gray');
        for (const button of modeButtons) {{
          const active = button.dataset.archiveMode === archiveMode;
          button.classList.toggle('active', active);
          button.setAttribute('aria-pressed', String(active));
        }}

        for (const card of archiveCards) {{
          const inActivePanel = !panelId || card.closest('.tab-panel')?.id === panelId;
          const matchesBucket = bucket === 'all' || card.dataset.bucket === bucket;
          const name = normalizeText(card.dataset.name);
          const cardLanguage = normalizeText(card.dataset.language);
          const tags = normalizeText(card.dataset.tags);
          const cardReviewState = normalizeText(card.dataset.reviewState);
          const cardGrayMode = normalizeText(card.dataset.grayMode);
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
          const matchesMode = archiveMode !== 'gray' || cardGrayMode === 'true';
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
            matchesMaxScore &&
            matchesMode;
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
        updateArchiveShareUi();
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
      for (const button of modeButtons) {{
        button.addEventListener('click', () => {{
          archiveMode = button.dataset.archiveMode === 'gray' ? 'gray' : 'normal';
          applyArchiveFilters();
        }});
      }}
      if (daySelect) {{
        daySelect.addEventListener('change', applyArchiveFilters);
      }}
      if (reviewStateInput && allowedReviewStates.has(initialReviewState)) {{
        reviewStateInput.value = initialReviewState;
      }}
      if (searchInput && initialSearch) {{
        searchInput.value = initialSearch;
      }}
      if (languageInput && initialLanguage && Array.from(languageInput.options).some((option) => option.value === initialLanguage)) {{
        languageInput.value = initialLanguage;
      }}
      if (tagInput && initialTag && Array.from(tagInput.options).some((option) => option.value === initialTag)) {{
        tagInput.value = initialTag;
      }}
      setNumericInputIfValid(minStarsInput, initialStarsMin);
      setNumericInputIfValid(maxStarsInput, initialStarsMax);
      setNumericInputIfValid(minScoreInput, initialScoreMin);
      setNumericInputIfValid(maxScoreInput, initialScoreMax);
      if (sortInput && allowedSorts.has(initialSort)) {{
        sortInput.value = initialSort;
      }}
      for (const button of filterButtons) {{
        button.addEventListener('click', applyArchiveFilters);
      }}
      if (copyLinkButton) {{
        copyLinkButton.addEventListener('click', async () => {{
          const shareUrl = buildArchiveShareUrl();
          try {{
            if (navigator.clipboard?.writeText) {{
              await navigator.clipboard.writeText(shareUrl);
            }} else {{
              throw new Error('clipboard-unavailable');
            }}
            updateArchiveShareUi('現在の絞り込み URL をコピーしました');
          }} catch (_error) {{
            if (linkOutput) {{
              linkOutput.focus();
              linkOutput.select();
            }}
            updateArchiveShareUi('URL を選択したので、そのまま手動でコピーしてください');
          }}
        }});
      }}
      applyArchiveFilters();
    }}
    const reviewStatePanels = document.querySelectorAll('[data-review-state-panel]');
    if (reviewStatePanels.length) {{
      const reviewStateLabels = {{
        unseen: '未確認',
        interested: '気になる',
        tested: '試した',
        good: '良い',
        meh: '微妙',
        production_candidate: '本番候補',
      }};
      const buildReviewStateIssueUrl = (fullName, state) => {{
        const params = new URLSearchParams({{
          title: `[review-state] ${{fullName}} -> ${{state}}`,
          body:
            `repo: ${{fullName}}\\nstate: ${{state}}\\nsource: pages\\n\\n送信すると workflow が state.json を更新して Pages を再生成します。`,
        }});
        return `https://github.com/{CONTROL_REPO_FULL_NAME}/issues/new?${{params.toString()}}`;
      }};
      for (const panel of reviewStatePanels) {{
        const fullName = String(panel.dataset.repoFullName || '').trim();
        const select = panel.querySelector('[data-review-state-select]');
        const link = panel.querySelector('[data-review-state-link]');
        const note = panel.querySelector('[data-review-state-note]');
        if (!fullName || !select || !link) continue;
        const updateReviewStateLink = () => {{
          const selectedState = String(select.value || 'unseen').trim();
          const label = reviewStateLabels[selectedState] || selectedState;
          link.href = buildReviewStateIssueUrl(fullName, selectedState);
          link.textContent = `GitHubで「${{label}}」に更新`;
          if (note) {{
            note.textContent = `GitHub の issue 作成画面が開きます。${{label}} で送信すると、workflow が state.json を更新して Pages を再生成します。`;
          }}
        }};
        select.addEventListener('change', updateReviewStateLink);
        updateReviewStateLink();
      }}
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


def is_gray_profile(config: Config) -> bool:
    return config.collection_profile == "gray"


def normalize_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def gray_seed_keywords_from_state(state: dict[str, Any] | None) -> list[str]:
    if not state:
        return []
    keywords = (state.get("gray_collection") or {}).get("keywords") or []
    normalized = []
    for keyword in keywords:
        if not isinstance(keyword, str):
            continue
        keyword = normalize_keyword(keyword)
        if 2 <= len(keyword) <= 48 and keyword not in normalized:
            normalized.append(keyword)
    return normalized[:GRAY_SEED_KEYWORD_LIMIT]


def build_gray_search_terms(config: Config, state: dict[str, Any] | None = None) -> list[str]:
    terms = list(GRAY_SEARCH_KEYWORDS)
    terms.extend(config.topics)
    terms.extend(gray_seed_keywords_from_state(state))
    unique_terms = list(dict.fromkeys(normalize_keyword(item) for item in terms if item.strip()))
    try:
        limit = int(os.getenv("GRAY_SEARCH_TERM_LIMIT", str(GRAY_SEARCH_TERM_LIMIT)))
    except ValueError:
        limit = GRAY_SEARCH_TERM_LIMIT
    return unique_terms[: max(1, limit)]


def build_search_queries(
    config: Config,
    now_utc: datetime,
    state: dict[str, Any] | None = None,
) -> list[str]:
    created_after = (now_utc - timedelta(days=90)).date().isoformat()
    pushed_after = (now_utc - timedelta(days=14)).date().isoformat()
    queries = []
    search_terms = build_gray_search_terms(config, state) if is_gray_profile(config) else config.topics
    for topic in search_terms:
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


def search_repositories(
    config: Config,
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    now_utc = datetime.now(UTC)
    repos_by_name: dict[str, dict[str, Any]] = {}
    sorts = config.github_search_sorts or ["stars", "updated"]
    for query in build_search_queries(config, now_utc, state):
        for sort in sorts:
            response = requests.get(
                f"{GITHUB_API}/search/repositories",
                headers=github_headers(config),
                params={
                    "q": query,
                    "sort": sort,
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


def repo_text_blob(repo: dict[str, Any]) -> str:
    parts = [
        repo.get("full_name") or "",
        repo.get("name") or "",
        repo.get("description") or "",
        " ".join(repo.get("topics") or []),
        repo.get("_readme_text") or "",
    ]
    return normalize_keyword(" ".join(parts))


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    hits = []
    for keyword in keywords:
        normalized = normalize_keyword(keyword)
        if normalized and normalized in text:
            hits.append(keyword)
    return hits


def analyze_gray_repo(repo: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    text = repo_text_blob(repo)
    category_hits: dict[str, list[str]] = {}
    for category, keywords in GRAY_CATEGORY_KEYWORDS.items():
        hits = keyword_hits(text, keywords)
        if hits:
            category_hits[category] = hits

    if category_hits:
        category = max(category_hits.items(), key=lambda item: len(item[1]))[0]
    else:
        category = "needs_review"

    exclude_hits = keyword_hits(text, GRAY_EXCLUDE_KEYWORDS)
    review_hits = keyword_hits(text, GRAY_NEEDS_REVIEW_KEYWORDS)
    if exclude_hits:
        risk_status = "exclude"
    elif review_hits or not category_hits:
        risk_status = "needs_review"
    else:
        risk_status = "allow"

    grey_score = min(
        100.0,
        sum(len(hits) for hits in category_hits.values()) * 12.0 + (8.0 if category_hits else 0.0),
    )
    repo_state = state["repos"].get(repo["full_name"], {})
    current_stars = int(repo.get("stargazers_count") or 0)
    previous_stars = int(repo_state.get("last_stars", current_stars) or current_stars)
    star_growth = max(0, current_stars - previous_stars)
    pushed_days = days_since(repo["pushed_at"])
    created_days = days_since(repo["created_at"])
    attention_score = min(
        100.0,
        star_growth * 8.0
        + min(current_stars, 2000) / 20.0
        + min(int(repo.get("forks_count") or 0), 500) / 10.0
        + max(0, 14 - pushed_days) * 2.0,
    )
    freshness_score = min(
        100.0,
        max(0, 90 - created_days) / 90 * 70.0
        + max(0, 14 - pushed_days) / 14 * 30.0,
    )
    final_score = grey_score * 0.45 + attention_score * 0.35 + freshness_score * 0.20
    reasons = []
    if category_hits:
        reasons.append(f"{category}: " + ", ".join(category_hits[category][:3]))
    if review_hits:
        reasons.append("needs review: " + ", ".join(review_hits[:2]))
    if exclude_hits:
        reasons.append("excluded risk: " + ", ".join(exclude_hits[:2]))

    return {
        "category": category,
        "risk_status": risk_status,
        "grey_score": round(grey_score, 2),
        "attention_score": round(attention_score, 2),
        "freshness_score": round(freshness_score, 2),
        "final_score": round(final_score, 2),
        "reason": "; ".join(reasons) if reasons else "判定語が弱いため要確認",
        "matched_keywords": sorted({hit for hits in category_hits.values() for hit in hits})[:12],
        "risk_keywords": exclude_hits + review_hits,
    }


def score_repo(
    repo: dict[str, Any],
    state: dict[str, Any],
    config: Config,
    bucket: str = "morning",
) -> float:
    if is_gray_profile(config):
        gray = repo.get("_gray_profile") or analyze_gray_repo(repo, state)
        repo["_gray_profile"] = gray
        return float(gray["final_score"])

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
                    f"Gray classification: {json.dumps(repo.get('_gray_profile') or {}, ensure_ascii=False)}\n"
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
    has_gray = any(repo.get("_gray_profile") for repo in repos)
    if has_gray:
        messages = ["グレー系GitHubランキング"]
    else:
        messages = ["朝の新顔枠" if bucket == "morning" else "夜の尖り枠"]
    for index, repo in enumerate(repos, start=1):
        x_post = repo["_x_post"]
        pick_reason = (repo.get("_pick_reason") or "").strip()
        gray = repo.get("_gray_profile") or {}
        if gray:
            status_label = "要確認" if gray.get("risk_status") == "needs_review" else "収集対象"
            gray_header = (
                f"{index}. {repo['full_name']} | {gray.get('category')} | {status_label}\n"
                f"score={repo['_score']} "
                f"(grey={gray.get('grey_score')}, attention={gray.get('attention_score')}, "
                f"fresh={gray.get('freshness_score')})\n"
                f"reason: {gray.get('reason')}\n"
                f"stars={repo['stargazers_count']} / updated={repo['pushed_at'][:10]}"
            )
            messages.append(f"{gray_header}\n{x_post[:500]}")
            continue
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


def classify_deepseek_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        status_code = exc.response.status_code
        body = (exc.response.text or "").lower()
        detail = f"status={status_code}"
        if any(token in body for token in ["quota", "billing", "balance", "credit", "insufficient", "auth", "unauthorized", "api key"]):
            return "quota/auth/billing", detail
        if status_code in {401, 402, 403}:
            return "quota/auth/billing", detail
        if status_code == 429 or "rate limit" in body or "too many requests" in body:
            return "rate_limit", detail
        if status_code >= 500:
            return "server/network", detail
        return "unknown", detail
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return "server/network", exc.__class__.__name__
    if isinstance(exc, requests.exceptions.RequestException):
        return "server/network", exc.__class__.__name__
    return "unknown", exc.__class__.__name__


def should_send_deepseek_warning(state: dict[str, Any], warning_kind: str) -> bool:
    alert_state = state.setdefault("alerts", {}).setdefault("deepseek", {})
    last_sent = alert_state.get(warning_kind, {}).get("last_sent")
    if not last_sent:
        return True
    return datetime.now(UTC) - datetime.fromisoformat(last_sent) >= timedelta(hours=DEEPSEEK_WARNING_COOLDOWN_HOURS)


def maybe_send_deepseek_warning(
    config: Config,
    state: dict[str, Any],
    repo: dict[str, Any],
    exc: Exception,
) -> None:
    warning_kind, detail = classify_deepseek_error(exc)
    if not should_send_deepseek_warning(state, warning_kind):
        return
    text = "\n".join(
        [
            f"DeepSeek warning: {warning_kind}",
            "fallback summary used",
            f"detail: {detail}",
            f"repo: {repo.get('full_name') or 'unknown'}",
        ]
    )
    try:
        send_telegram_text(config, text)
    except Exception as warning_exc:
        append_send_log(
            "deepseek_warning_failed",
            warning_kind=warning_kind,
            detail=detail,
            repo=repo.get("full_name"),
            error=str(warning_exc),
        )
        return
    state.setdefault("alerts", {}).setdefault("deepseek", {})[warning_kind] = {
        "last_sent": datetime.now(UTC).isoformat(),
        "last_repo": repo.get("full_name") or "",
        "detail": detail,
    }
    save_state(state)
    append_send_log(
        "deepseek_warning_sent",
        warning_kind=warning_kind,
        detail=detail,
        repo=repo.get("full_name"),
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
        if is_gray_profile(config):
            repo["_gray_profile"] = analyze_gray_repo(repo, state)
            if repo["_gray_profile"]["risk_status"] == "exclude":
                continue
        repo["_score"] = score_repo(repo, state, config, bucket)
        enriched.append(repo)
    enriched.sort(key=lambda item: item["_score"], reverse=True)
    return enriched[: config.top_n]


def extract_gray_seed_terms(repo: dict[str, Any]) -> list[str]:
    terms = []
    for topic in repo.get("topics") or []:
        topic = normalize_keyword(str(topic).replace("-", " "))
        if 3 <= len(topic) <= 32:
            terms.append(topic)
    gray = repo.get("_gray_profile") or {}
    for keyword in gray.get("matched_keywords") or []:
        keyword = normalize_keyword(str(keyword))
        if 3 <= len(keyword) <= 32:
            terms.append(keyword)
    return terms


def update_gray_seed_keywords(state: dict[str, Any], repos: list[dict[str, Any]]) -> None:
    if not repos:
        return
    gray_collection = state.setdefault("gray_collection", {})
    existing = gray_seed_keywords_from_state(state)
    candidates = []
    for repo in repos:
        gray = repo.get("_gray_profile") or {}
        if not gray or gray.get("risk_status") == "exclude":
            continue
        candidates.extend(extract_gray_seed_terms(repo))
    merged = list(dict.fromkeys(existing + candidates))
    gray_collection["keywords"] = merged[:GRAY_SEED_KEYWORD_LIMIT]
    gray_collection["updated_at"] = datetime.now(UTC).isoformat()


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
    update_gray_seed_keywords(state, repos)


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
                "gray_profile": repo.get("_gray_profile") or {},
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
        f'<option value="{escape(state)}">{escape(review_state_label(state))}</option>'
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
    <section class="dashboard-panel" data-archive-root>
      <div class="panel-title">
        <h2>検索・フィルター</h2>
        <div class="mode-toggle" aria-label="表示モード">
          <button type="button" class="active" data-archive-mode="normal" aria-pressed="true">通常</button>
          <button type="button" data-archive-mode="gray" aria-pressed="false">グレー</button>
        </div>
      </div>
      <div class="archive-controls">
      <div class="control-group">
        <label for="search-name">Repo 名検索</label>
        <input id="search-name" type="search" placeholder="owner/repo" data-filter-search>
      </div>
      <div class="control-group">
        <label for="filter-language">言語</label>
        <select id="filter-language" data-filter-language>
          <option value="">すべて</option>
          {language_options}
        </select>
      </div>
      <div class="control-group">
        <label for="filter-tag">ハッシュタグ / タグ</label>
        <select id="filter-tag" data-filter-tag>
          <option value="">すべて</option>
          {tag_options}
        </select>
      </div>
      <div class="control-group">
        <label for="filter-review-state">状態</label>
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
      </div>
      <div class="archive-share">
        <button class="filter-button" type="button" data-copy-filter-link>現在の絞り込みURLをコピー</button>
        <a class="badge" href="./index.html" data-open-filter-link>この絞り込みを開く</a>
        <input type="text" readonly value="./index.html" data-filter-link-output aria-label="共有用の絞り込みURL">
        <span class="archive-share-status" data-filter-link-status></span>
      </div>
      <p class="archive-summary" data-filter-count>{len(history)} 件表示</p>
    </section>
    """


def render_repo_card(
    item: dict[str, Any],
    review_state: str,
    rank: int | None = None,
    archive_card: bool = False,
    path_prefix: str = ".",
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
        f'<span class="badge review-state">状態 {escape(review_state_label(review_state))}</span>'
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
        f"<span>登場 {int(item.get('count') or 0)}回</span>"
        if item.get("count") is not None
        else ""
    )
    details_href = repo_detail_href(str(item.get("full_name") or ""), path_prefix)
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
      <div class="detail-links primary-links">
        <a class="badge" href="{details_href}">詳細</a>
        <a class="badge" href="{html_url}" target="_blank" rel="noreferrer">GitHub</a>
      </div>
      {f'<div class="badge-row"><span class="badge">{language}</span>{review_badge}{topics}</div>' if topics or language or review_badge else ''}
    </article>
    """


def build_operations_summary_html(path_prefix: str = ".") -> str:
    state = load_state()
    run_status = str(state.get("last_run_status") or "unknown").strip() or "unknown"
    started_at = format_state_timestamp(state.get("last_run_started_at"))
    finished_at = format_state_timestamp(state.get("last_run_finished_at"))
    run_error = " ".join(str(state.get("last_run_error") or "").split())
    deepseek_alerts = state.get("alerts", {}).get("deepseek", {})
    latest_warning_kind = ""
    latest_warning_payload: dict[str, Any] = {}
    latest_warning_at = ""
    for warning_kind, payload in deepseek_alerts.items():
        if not isinstance(payload, dict):
            continue
        last_sent_raw = str(payload.get("last_sent") or "")
        if last_sent_raw > latest_warning_at:
            latest_warning_at = last_sent_raw
            latest_warning_kind = warning_kind
            latest_warning_payload = payload
    latest_warning_sent = format_state_timestamp(latest_warning_payload.get("last_sent"))
    latest_warning_repo = str(latest_warning_payload.get("last_repo") or "-").strip() or "-"
    latest_warning_detail = " ".join(str(latest_warning_payload.get("detail") or "").split()) or "-"
    operations_link = f'{path_prefix}/operations.html'
    return f"""
    <section class="section-block">
      <div class="section-header">
        <h2>運用サマリー</h2>
        <p>定時実行の状態と DeepSeek の直近警告を、Pages 上ですぐ確認するための小さい運用サマリーです。</p>
      </div>
      <div class="section-grid">
        <article class="card">
          <h3>実行状況</h3>
          <div class="meta">
            <span>状態 {escape(run_status_label(run_status))}</span>
            <span>開始 {escape(started_at)}</span>
            <span>終了 {escape(finished_at)}</span>
          </div>
          {f'<p class="pick-reason">エラー: {escape(run_error)}</p>' if run_error else '<p class="pick-reason">エラー: -</p>'}
        </article>
        <article class="card">
          <h3>DeepSeek 警告</h3>
          <div class="meta">
            <span>最新 {escape(deepseek_warning_label(latest_warning_kind or "none"))}</span>
            <span>送信 {escape(latest_warning_sent)}</span>
            <span>対象 {escape(latest_warning_repo)}</span>
          </div>
          <p class="pick-reason">詳細: {escape(latest_warning_detail)}</p>
        </article>
      </div>
      <div class="detail-links secondary-links">
        <a class="badge" href="{operations_link}">運用サマリーページを開く</a>
      </div>
    </section>
    """


def history_dashboard_stats(history: list[dict[str, Any]]) -> dict[str, Any]:
    unique_repos = {str(item.get("full_name") or "") for item in history if item.get("full_name")}
    scores = [float(item.get("score") or 0) for item in history]
    latest_day = ""
    latest_count = 0
    day_counts: dict[str, int] = {}
    tokyo = ZoneInfo("Asia/Tokyo")
    for item in history:
        sent_at = item.get("sent_at")
        if not sent_at:
            continue
        day = parse_sent_at(sent_at).astimezone(tokyo).strftime("%-m/%-d") if os.name != "nt" else parse_sent_at(sent_at).astimezone(tokyo).strftime("%#m/%#d")
        day_counts[day] = day_counts.get(day, 0) + 1
    if day_counts:
        latest_day = next(iter(day_counts.keys()))
        latest_count = day_counts[latest_day]
    return {
        "unique_repos": len(unique_repos),
        "total_notifications": len(history),
        "latest_day": latest_day,
        "latest_count": latest_count,
        "avg_score": sum(scores) / len(scores) if scores else 0,
        "gray_count": sum(1 for item in history if gray_display_profile(item)["is_gray"]),
        "day_counts": list(day_counts.items())[:7],
    }


def render_mini_chart(day_counts: list[tuple[str, int]]) -> str:
    if not day_counts:
        return ""
    max_count = max(count for _, count in day_counts) or 1
    bars = "".join(
        f'<span class="mini-bar" style="height:{max(12, int(count / max_count * 76))}px"></span>'
        for _, count in day_counts
    )
    labels = "".join(f"<span>{escape(day)}</span>" for day, _ in day_counts)
    return f"""
    <div class="mini-chart" aria-label="最近の通知数">
      <p class="mini-chart-title">通知アクティビティ</p>
      <div class="mini-bars">{bars}</div>
      <div class="mini-chart-labels">{labels}</div>
    </div>
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
            <section id="{tab_id}" class="{panel_class} archive-list">
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
    stats = history_dashboard_stats(history)
    hero_html = f"""
    <section class="dashboard-hero">
      <div>
        <p class="hero-kicker">GitHub repository archive</p>
        <h2>通知履歴</h2>
        <p class="hero-copy">Telegram通知のリポジトリを検索・選別・再利用しやすい形で見返せるアーカイブです。</p>
        <div class="hero-pills">
          <span class="hero-pill">毎日自動収集</span>
          <span class="hero-pill">AIスコアリング</span>
          <span class="hero-pill">人力レビュー併用</span>
        </div>
      </div>
      {render_mini_chart(stats["day_counts"])}
    </section>
    <section class="kpi-grid">
      <article class="kpi-card"><span class="kpi-icon">R</span><div><span>総リポジトリ数</span><strong>{stats['unique_repos']:,}</strong><span>アーカイブ済み</span></div></article>
      <article class="kpi-card"><span class="kpi-icon">N</span><div><span>最新日の通知</span><strong>{stats['latest_count']}</strong><span>{escape(stats['latest_day'] or '-')}</span></div></article>
      <article class="kpi-card"><span class="kpi-icon">G</span><div><span>グレー候補</span><strong>{stats['gray_count']}</strong><span>表示フィルタ対象</span></div></article>
      <article class="kpi-card"><span class="kpi-icon">S</span><div><span>平均スコア</span><strong>{stats['avg_score']:.1f}</strong><span>履歴全体</span></div></article>
    </section>
    """
    low_star_section = f"""
    <section class="dashboard-panel">
      <div class="panel-title">
        <div>
          <h2>低スター高スコア発掘</h2>
          <p class="archive-summary">stars がまだ少なくても、score が高いリポジトリを見つけるための発掘枠です。</p>
        </div>
        <a class="badge" href="{history_archive_href(stars_max=settings['max_stars'], score_min=settings['min_score'], sort='score')}">もっと見る</a>
      </div>
      <div class="spotlight-strip">
        {low_star_cards}
      </div>
    </section>
    """ if low_star_cards else ""
    body_html = (
        hero_html
        + low_star_section
        + build_archive_controls(history)
        +
        (
            "<div class='filter-bar dashboard-panel'>"
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
            else render_empty_state("まだ通知履歴がありません。次回の render 後にここへ表示されます。")
        )
    )
    html = site_shell(
        "通知履歴",
        "Telegram に送ったリポジトリを、検索・選別・再利用しやすい形で見返せるアーカイブです。",
        body_html,
        "history",
    )
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def render_operations_site() -> None:
    body_html = (
        """
        <section class="dashboard-hero">
          <div>
            <p class="hero-kicker">Operations</p>
            <h2>運用サマリー</h2>
            <p class="hero-copy">定時実行の状態や DeepSeek の警告など、運用上の確認項目をまとめたページです。</p>
          </div>
        </section>
        """
        + build_operations_summary_html(".")
    )
    html = site_shell(
        "運用サマリー",
        "定時実行の状態や DeepSeek の警告など、運用上の確認項目をまとめたページです。",
        body_html,
        "operations",
    )
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "operations.html").write_text(html, encoding="utf-8")


def build_week_window(
    now: datetime,
    scope: str = "previous",
) -> tuple[datetime, datetime, str]:
    tokyo_now = now.astimezone(ZoneInfo("Asia/Tokyo"))
    week_start = tokyo_week_start(now)
    if scope == "current":
        range_start = week_start
        range_end = tokyo_now
    else:
        range_start = week_start - timedelta(days=7)
        range_end = week_start
    label = build_week_label(range_start, range_end)
    return range_start, range_end, label


def build_weekly_ranking(
    history: list[dict[str, Any]],
    now: datetime,
    scope: str = "previous",
) -> tuple[list[dict[str, Any]], str]:
    range_start, range_end, label = build_week_window(now, scope)
    return build_weekly_ranking_for_range(history, range_start, range_end), label


def build_weekly_ranking_for_range(
    history: list[dict[str, Any]],
    range_start: datetime,
    range_end: datetime,
) -> list[dict[str, Any]]:
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

    return sorted(
        aggregated.values(),
        key=lambda item: (item["count"], item["best_score"], item["stars"]),
        reverse=True,
    )[:10]


def build_weekly_archive_links_html(
    archive_weeks: list[datetime],
    latest_week_start: datetime,
    selected_week_start: datetime,
    path_prefix: str = ".",
) -> str:
    options = [
        (
            f"{path_prefix}/weekly.html",
            f"最新週 {build_week_label(latest_week_start, latest_week_start + timedelta(days=7))}",
            weekly_archive_slug(latest_week_start) == weekly_archive_slug(selected_week_start),
        )
    ]
    for week_start in archive_weeks:
        if weekly_archive_slug(week_start) == weekly_archive_slug(latest_week_start):
            continue
        options.append(
            (
                weekly_archive_href(week_start, path_prefix),
                build_week_label(week_start, week_start + timedelta(days=7)),
                weekly_archive_slug(week_start) == weekly_archive_slug(selected_week_start),
            )
        )
    option_html = "".join(
        f'<option value="{escape(href)}"{" selected" if selected else ""}>{escape(label)}</option>'
        for href, label, selected in options
    )
    controls_html = (
        '<div class="archive-select-row">'
        '<label for="weekly-archive-select">表示する週</label>'
        f'<select id="weekly-archive-select" data-weekly-archive-select>{option_html}</select>'
        "</div>"
    )
    return render_section_block(
        "週次アーカイブ",
        "最新の週次ページに加えて、過去週のランキングもここから選べます。",
        controls_html,
        "過去週のアーカイブはまだありません。",
    )


def render_weekly_page(
    history: list[dict[str, Any]],
    review_states: dict[str, Any],
    range_start: datetime,
    range_end: datetime,
    label: str,
    archive_links_html: str = "",
    path_prefix: str = ".",
) -> str:
    settings = low_star_high_score_settings()
    ranking = build_weekly_ranking_for_range(history, range_start, range_end)
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
    review_state_summary = " ".join(
        f'<a class="badge" href="{history_archive_href(review_state=state_name)}">{escape(review_state_label(state_name))} {review_state_counts[state_name]}</a>'
        for state_name in REVIEW_STATES
        if review_state_counts.get(state_name)
    ) or "なし"
    low_star_history_href = history_archive_href(
        stars_max=settings["max_stars"],
        score_min=settings["min_score"],
        sort="score",
    )
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
    <section class="dashboard-hero">
      <div>
        <p class="hero-kicker">Weekly summary</p>
        <h2>週間まとめ</h2>
        <p class="hero-copy">{escape(label)} の通知履歴を、見返しやすい週次ビューとしてまとめています。</p>
      </div>
    </section>
    <section class="stats-grid">
      <article class="stat-card"><strong>{unique_repos}</strong><span>今週のリポジトリ数</span></article>
      <article class="stat-card"><strong>{len(this_week_items)}</strong><span>通知総数</span></article>
      <article class="stat-card"><strong>{avg_score:.1f}</strong><span>平均 score</span></article>
      <article class="stat-card"><strong>{escape(summarize_languages(this_week_items, 4))}</strong><span>言語分布</span></article>
      <article class="stat-card"><strong class="inline-links">{review_state_summary}</strong><span>状態の分布</span></article>
    </section>
    """

    def render_week_section(
        title: str,
        description: str,
        items: list[dict[str, Any]],
        links_html: str = "",
    ) -> str:
        cards = "".join(
            render_repo_card(
                item,
                normalize_review_state(review_states.get(item.get("full_name"))),
                rank=index,
            )
            for index, item in enumerate(items, start=1)
        )
        return render_section_block(
            title,
            description,
            cards,
            "この条件に合うリポジトリは、今週まだありません。",
            links_html=links_html,
        )

    html = site_shell(
        "週間まとめ",
        f"{label} の通知履歴を、見返しやすい週次ビューとしてまとめています。",
        archive_links_html
        + stats_html
        + render_week_section(
            "今週の良い / 本番候補",
            "すでに手応えがあるリポジトリを、状態ベースで先に見返せます。",
            review_priority_items,
            links_html=(
                f' <span class="inline-links"><a class="badge" href="{history_archive_href(review_state="good", sort="score")}">良いをすべて見る</a>'
                f'<a class="badge" href="{history_archive_href(review_state="production_candidate", sort="score")}">本番候補をすべて見る</a></span>'
            ),
        )
        + render_week_section(
            "今週の未確認リポジトリ",
            "まだ見ていないリポジトリをまとめています。あとで確認する入口として使えます。",
            unseen_items,
            links_html=(
                f' <span class="inline-links"><a class="badge" href="{history_archive_href(review_state="unseen", sort="newest")}">未確認をすべて見る</a></span>'
            ),
        )
        + render_week_section(
            "今週の総合トップ",
            "pick 回数、最高 score、stars をまとめて見た総合ランキングです。まず全体感をつかむのに向いています。",
            ranking,
        )
        + render_week_section(
            "今週の低スター枠トップ",
            "stars が少なくても評価が高いリポジトリを先に見たいときの入口です。",
            low_star_ranking,
            links_html=(
                f' <span class="inline-links"><a class="badge" href="{low_star_history_href}">低スター高スコアをすべて見る</a></span>'
            ),
        )
        + render_week_section(
            "今週の新着で面白かったもの",
            "今週通知したものを新しい順で見返せます。未確認の掘り起こしにも使えます。",
            fresh_picks,
        ),
        "weekly",
        path_prefix=path_prefix,
    )
    return html


def render_weekly_site(now: datetime | None = None) -> None:
    history = load_history()
    state = load_state()
    review_states = state.get("review_states", {})
    if now is None:
        now = datetime.now(UTC)
    range_start, range_end, label = build_week_window(now, "current")
    archive_weeks = collect_weekly_archive_starts(history)
    archive_links_html = build_weekly_archive_links_html(
        archive_weeks,
        range_start,
        range_start,
    )
    html = render_weekly_page(
        history,
        review_states,
        range_start,
        range_end,
        label,
        archive_links_html=archive_links_html,
    )
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "weekly.html").write_text(html, encoding="utf-8")
    WEEKLY_ARCHIVE_DIR.mkdir(exist_ok=True)
    current_week_slug = weekly_archive_slug(range_start)
    for week_start in archive_weeks:
        week_slug = weekly_archive_slug(week_start)
        if week_slug == current_week_slug:
            continue
        archive_html = render_weekly_page(
            history,
            review_states,
            week_start,
            week_start + timedelta(days=7),
            build_week_label(week_start, week_start + timedelta(days=7)),
            archive_links_html=build_weekly_archive_links_html(
                archive_weeks,
                range_start,
                week_start,
                path_prefix="..",
            ),
            path_prefix="..",
        )
        (WEEKLY_ARCHIVE_DIR / f"{week_slug}.html").write_text(
            archive_html,
            encoding="utf-8",
        )


def render_static_sites(now: datetime | None = None) -> None:
    render_history_site()
    render_weekly_site(now)
    render_operations_site()
    render_repo_detail_sites()


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
    state = load_state()
    started_at = now.isoformat()
    record_run_status(
        state,
        started_at=started_at,
        finished_at=None,
        status="running",
        error=None,
    )
    append_send_log(
        "run_start",
        trigger=trigger,
        bucket=bucket,
        started_at=started_at,
    )
    try:
        print("Searching repositories...")
        repos = search_repositories(config, state)
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
            record_run_status(
                state,
                finished_at=datetime.now(UTC).isoformat(),
                status="success",
                error=None,
            )
            render_static_sites(now)
            append_send_log(
                "run_end",
                trigger=trigger,
                bucket=bucket,
                status="success",
                count=0,
            )
            print("No candidates to notify.")
            return

        for repo in candidates:
            print(f"Summarizing {repo['full_name']}...")
            try:
                generated = build_deepseek_summary(config, repo)
                repo["_summary"], repo["_x_post"], repo["_pick_reason"] = split_generated_content(generated, repo)
            except Exception as exc:
                maybe_send_deepseek_warning(config, state, repo, exc)
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
        record_run_status(
            state,
            finished_at=datetime.now(UTC).isoformat(),
            status="success",
            error=None,
        )
        append_history(candidates, bucket)
        render_static_sites(now)
        if now.astimezone(ZoneInfo(config.timezone)).weekday() == 0:
            weekly_message = build_weekly_telegram_message(config, now)
            if weekly_message:
                send_telegram_text(config, weekly_message)
        append_send_log(
            "run_end",
            trigger=trigger,
            bucket=bucket,
            status="success",
            count=len(candidates),
        )
        print(f"Posted {len(candidates)} repositories.")
    except Exception as exc:
        record_run_status(
            state,
            finished_at=datetime.now(UTC).isoformat(),
            status="failed",
            error=f"{exc.__class__.__name__}: {exc}",
        )
        append_send_log(
            "run_fail",
            trigger=trigger,
            bucket=bucket,
            error=f"{exc.__class__.__name__}: {exc}",
        )
        raise


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
