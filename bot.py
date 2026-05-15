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
    "faceswap",
    "face swap",
    "real-time face swap",
    "realtime face swap",
    "deepfake",
    "deep-fake",
    "video deepfake",
    "realtime deepfake",
    "webcam deepfake",
    "fake webcam",
    "face changer",
    "face manipulation",
    "lip sync",
    "lip-sync",
    "facefusion",
    "deep-live-cam",
    "roop",
    "inswapper",
    "simswap",
    "deepfacelab",
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
    "face_deepfake_live": [
        "faceswap",
        "face swap",
        "face-swap",
        "real-time face swap",
        "realtime face swap",
        "deepfake",
        "deep-fake",
        "video deepfake",
        "video-deepfake",
        "realtime deepfake",
        "realtime-deepfake",
        "webcam deepfake",
        "deepfake webcam",
        "fake webcam",
        "face changer",
        "face manipulation",
        "face enhancer",
        "face enhancement",
        "face reenactment",
        "lip sync",
        "lip-sync",
        "lipsync",
        "one-click video deepfake",
        "single image",
        "facefusion",
        "deep-live-cam",
        "deep live cam",
        "roop",
        "inswapper",
        "simswap",
        "deepfacelab",
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

GRAY_CATEGORY_LABELS = {
    "adult_ai_media": "成人向けAI・メディア復元系",
    "scraper_downloader": "スクレイパー・ダウンローダー系",
    "reverse_modding": "逆解析・改造系",
    "policy_bypass": "規約・制限回避系",
    "security_research": "セキュリティ研究系",
    "face_deepfake_live": "顔入れ替え・リアルタイムdeepfake系",
    "needs_review": "要確認",
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
    "impersonation",
    "impersonate",
    "fake webcam",
    "webcam deepfake",
    "deepfake webcam",
    "realtime deepfake",
    "realtime-deepfake",
    "real-time deepfake",
    "one-click deepfake",
    "one-click video deepfake",
    "bypass kyc",
    "kyc bypass",
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


def gray_category_label(value: Any) -> str:
    category = str(value or "").strip()
    return GRAY_CATEGORY_LABELS.get(category, category)


def review_state_label(value: Any) -> str:
    normalized = normalize_review_state(value)
    return REVIEW_STATE_LABELS.get(normalized, normalized)


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
    gray_category = str((item.get("gray_profile") or {}).get("category") or "").strip()
    gray_category_display = gray_category_label(gray_category)
    if gray_category_display and gray_category_display not in seen:
        seen.add(gray_category_display)
        tags.append(gray_category_display)
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


def render_language_pills(items: list[dict[str, Any]], limit: int = 4) -> str:
    counts: dict[str, int] = {}
    for item in items:
        language = str(item.get("language") or "N/A")
        counts[language] = counts.get(language, 0) + 1
    ranking = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    if not ranking:
        return '<span class="language-pill">なし</span>'
    return "".join(
        f'<span class="language-pill">{escape(language)} <b>{count}</b></span>'
        for language, count in ranking
    )


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
                "description": normalize_card_description(item),
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
            entry["description"] = normalize_card_description(item) or entry["description"]
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
        try:
            detail_score_label = str(int(round(float(repo_data.get("latest_score") or 0))))
        except (TypeError, ValueError):
            detail_score_label = "0"
        shortcut_links = render_review_state_shortcuts("..", current_review_state)
        review_state_menu_items = "".join(
            f'<a class="review-state-option{" current" if state_name == current_review_state else ""}" '
            f'href="{escape(review_state_request_issue_url(repo_data["full_name"], state_name), quote=True)}" '
            f'target="_blank" rel="noreferrer" role="menuitem" data-review-state-option>'
            f'{escape(review_state_label(state_name))}</a>'
            for state_name in REVIEW_STATES
        )
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
            try:
                similar_score_label = str(int(round(float(similar_repo.get("latest_score") or 0))))
            except (TypeError, ValueError):
                similar_score_label = "0"
            similar_repo_cards.append(
                f"""
                <article class="related-mini">
                  <h3><a href="{repo_detail_href(str(similar_repo.get("full_name") or ""), path_prefix="..")}" target="_self">{escape(str(similar_repo.get("full_name") or ""))}</a></h3>
                  <p>by {escape(str((similar_repo.get("owner_login") or str(similar_repo.get("full_name") or "").split("/")[0]) or ""))}</p>
                  <div class="meta">
                    <span class="meta-stars">stars {int(similar_repo.get("latest_stars") or 0)}</span>
                    <span class="meta-language">{escape(str(similar_repo.get("language") or "N/A"))}</span>
                  </div>
                  <span class="related-score">{similar_score_label}</span>
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
        overview_points = [
            "リポジトリの用途と注目理由を確認",
            "通知時点の stars / language / score を確認",
            "関連リポジトリと過去通知へすぐ移動",
        ]
        overview_points_html = "".join(
            f"<li>{escape(point)}</li>" for point in overview_points
        )
        body_html = f"""
        <section class="section-block detail-page">
          <article class="card detail-hero-card">
            <div class="card-score">{detail_score_label}<small>スコア</small></div>
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
              <span class="meta-stars">stars {int(repo_data['latest_stars'])}</span>
              <span class="meta-language">{escape(str(repo_data['language'] or 'N/A'))}</span>
              <span class="date-label">{escape(last_sent_label)}</span>
            </div>
            {f'<p class="description">{escape(repo_data["description"])}</p>' if repo_data.get("description") else ''}
            {f'<div class="badge-row">{language_badge_html}<span class="badge review-state">状態 {escape(review_state_label(current_review_state))}</span>{topics_html}</div>' if topics_html or repo_data.get("language") else ''}
            <div class="detail-hero-actions">
              <a class="badge action-github" href="{escape(str(repo_data.get("html_url") or ""))}" target="_blank" rel="noreferrer">GitHubで見る</a>
              <div class="review-state-menu-wrap" data-review-state-menu>
                <button class="badge review-state-trigger" type="button" aria-label="状態を更新" aria-haspopup="menu" aria-expanded="false" data-review-state-trigger>↻</button>
                <div class="review-state-menu" role="menu" aria-label="状態を更新">
                  {review_state_menu_items}
                </div>
              </div>
            </div>
          </article>
          <nav class="detail-tabs" aria-label="リポジトリ詳細セクション">
            <a href="#overview">概要</a>
            <a href="#reason">選定理由</a>
            <a href="#stack">技術スタック</a>
            <a href="#stats">統計</a>
          </nav>
          <div class="detail-info-grid">
            <article id="overview" class="detail-info-card">
              <h3>概要</h3>
              {f'<p class="description">{escape(repo_data["description"])}</p>' if repo_data.get("description") else '<p class="description">説明文はまだ取得されていません。</p>'}
              <ul class="detail-check-list">{overview_points_html}</ul>
            </article>
            <article id="reason" class="detail-info-card">
              <h3>選定理由</h3>
              {f'<p class="description">{escape(repo_data["pick_reason"])}</p>' if repo_data.get("pick_reason") else '<p class="description">選定理由はまだありません。</p>'}
              {f'<div class="badge-row">{topics_html}</div>' if topics_html else ''}
            </article>
            <article id="stack" class="detail-info-card">
              <h3>技術スタック</h3>
              <div class="badge-row">{language_badge_html}<span class="badge review-state">状態 {escape(review_state_label(current_review_state))}</span></div>
              <div class="detail-links secondary-links">
                {language_link_html}
                <a class="badge" href="{score_focus_href}">高スコアの一覧を見る</a>
                <a class="badge" href="{low_star_focus_href}">低スター高スコアを見る</a>
                <a class="badge review-state" href="{current_state_href}">{escape(review_state_label(current_review_state))}の一覧を見る</a>
              </div>
            </article>
            <article class="detail-info-card">
              <h3>通知本文</h3>
              <pre>{linkify_text(str(repo_data.get("latest_x_post") or ""))}</pre>
            </article>
          </div>
        </section>
        <section id="stats" class="stats-grid">
          <article class="stat-card"><strong>{escape(repo_data["first_seen"].strftime("%Y-%m-%d %H:%M"))}</strong><span>初回出現日時</span></article>
          <article class="stat-card"><strong>{escape(repo_data["latest_seen"].strftime("%Y-%m-%d %H:%M"))}</strong><span>最新出現日時</span></article>
          <article class="stat-card"><strong>{int(repo_data["appearances"])}</strong><span>出現回数</span></article>
          <article class="stat-card"><strong>{escape(review_state_label(current_review_state))}</strong><span>状態</span></article>
        </section>
        {render_section_block(
            "関連リポジトリ",
            "同じ言語や共通タグを手がかりに、近いリポジトリを見返しやすく並べています。",
            "".join(similar_repo_cards),
            "このリポジトリに近い候補は、まだ十分に集まっていません。",
            layout_class="related-strip",
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


def normalize_card_description(item: dict[str, Any], limit: int | None = None) -> str:
    raw_summary = str(item.get("summary") or "").strip()
    raw_description = str(item.get("description") or "").strip()
    description = raw_summary or raw_description
    description = re.sub(r"\[(?:pick_reason|telegram|x)\]", " ", description, flags=re.IGNORECASE)
    description = re.sub(r"https?://\S+", " ", description)
    description = " ".join(description.split())
    if not description:
        return ""
    if limit is None or len(description) <= limit:
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
    html {{
      overflow-x: hidden;
    }}
    body {{
      margin: 0;
      font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
      color: var(--ink);
      background: var(--bg);
      font-size: 15px;
      line-height: 1.55;
      overflow-x: hidden;
    }}
    body.filter-sheet-open {{
      overflow: hidden;
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
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0 0 18px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface);
      box-shadow: var(--shadow);
      width: fit-content;
      max-width: 100%;
    }}
    .date-select-label {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .date-select {{
      min-width: 160px;
      max-width: 100%;
      border: 1px solid var(--line);
      background: var(--surface-muted);
      color: var(--ink);
      padding: 9px 34px 9px 12px;
      border-radius: 10px;
      font: inherit;
      font-size: 13px;
      font-weight: 800;
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
      position: relative;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 16px;
      margin: 0 0 10px;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
    }}
    .meta {{
      display: flex;
      gap: 10px;
      row-gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 10px;
      line-height: 1.3;
    }}
    .meta span {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: 0;
    }}
    .meta span::before {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1em;
      color: var(--accent);
      font-size: 0.9em;
      font-weight: 900;
      line-height: 1;
    }}
    .date-label::before {{ content: "◷"; }}
    .meta-bucket::before {{ content: none; }}
    .meta-score::before {{ content: none; }}
    .meta-count::before {{ content: "↻"; }}
    .meta-stars::before {{ content: "★"; }}
    .meta-language::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #1f6feb;
    }}
    .card-header {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
      margin-bottom: 8px;
      padding-right: 54px;
    }}
    .avatar {{
      width: 24px;
      height: 24px;
      border-radius: 999px;
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
      font-size: 16px;
      line-height: 1.22;
      letter-spacing: 0;
      font-weight: 900;
    }}
    .card h2 a {{
      color: var(--ink);
      overflow-wrap: anywhere;
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
      font-size: 11px;
      margin-bottom: 2px;
      line-height: 1.2;
    }}
    .owner-line a {{
      color: var(--muted);
    }}
    .description {{
      margin: 0 0 10px;
      color: rgba(15, 23, 42, 0.8);
      line-height: 1.55;
      font-size: 12.5px;
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .card > .description {{
      max-height: 4.9em;
      overflow-y: auto;
      padding-right: 4px;
      scrollbar-width: thin;
      overscroll-behavior: contain;
    }}
    .pick-reason {{
      margin: 0 0 10px;
      color: rgba(15, 23, 42, 0.72);
      line-height: 1.5;
      font-size: 12px;
      font-weight: 700;
      opacity: 0.92;
      overflow-wrap: anywhere;
    }}
    .badge-row {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin: 12px 0 0;
    }}
    .card-score {{
      position: absolute;
      top: 14px;
      right: 14px;
      display: inline-grid;
      place-items: center;
      min-width: 38px;
      min-height: 42px;
      padding: 5px 7px;
      border-radius: 10px;
      background: #e7f8ef;
      color: #078243;
      font-size: 16px;
      font-weight: 900;
      line-height: 1;
      text-align: center;
      box-shadow: inset 0 0 0 1px rgba(7, 130, 67, 0.08);
    }}
    .card-score small {{
      display: block;
      margin-top: 3px;
      font-size: 9px;
      font-weight: 900;
      line-height: 1;
    }}
    .detail-hero-card {{
      position: relative;
      padding: 22px;
      border-radius: 14px;
    }}
    .detail-hero-card .card-header {{
      padding-right: 64px;
      margin-bottom: 10px;
    }}
    .detail-hero-card .avatar {{
      width: 44px;
      height: 44px;
      border-radius: 999px;
    }}
    .detail-hero-card h2 {{
      color: var(--accent);
      font-size: 28px;
      line-height: 1.1;
    }}
    .detail-hero-actions {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 48px;
      gap: 10px;
      margin-top: 16px;
    }}
    .detail-hero-actions .badge {{
      min-height: 44px;
      justify-content: center;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 900;
    }}
    .detail-hero-actions .action-github {{
      background: #061b3a;
      color: #fff;
      border-color: #061b3a;
    }}
    .review-state-menu-wrap {{
      position: relative;
      min-width: 0;
    }}
    .detail-hero-actions .review-state-trigger {{
      width: 100%;
      background: #fff;
      color: var(--ink);
      border-color: var(--line);
      font-size: 18px;
      cursor: pointer;
    }}
    .detail-hero-actions .review-state-trigger:hover,
    .detail-hero-actions .review-state-trigger[aria-expanded="true"] {{
      background: #f3f7ff;
      border-color: #b9cef5;
      color: var(--accent);
    }}
    .review-state-menu {{
      position: absolute;
      right: 0;
      top: calc(100% + 8px);
      z-index: 30;
      display: none;
      width: min(220px, calc(100vw - 48px));
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
      box-shadow: var(--shadow);
    }}
    .review-state-menu.open {{
      display: grid;
      gap: 4px;
    }}
    .review-state-option {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 38px;
      padding: 9px 10px;
      border-radius: 8px;
      color: var(--ink);
      font-size: 13px;
      font-weight: 900;
    }}
    .review-state-option:hover {{
      background: var(--surface-muted);
      color: var(--accent);
    }}
    .review-state-option.current {{
      background: #fff5e6;
      color: var(--warn);
    }}
    .review-state-option.current::after {{
      content: "現在";
      color: var(--warn);
      font-size: 11px;
    }}
    .detail-tabs {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0;
      margin: 12px 0 14px;
      border-bottom: 1px solid var(--line);
    }}
    .detail-tabs a {{
      min-width: 0;
      padding: 11px 4px;
      color: var(--muted);
      text-align: center;
      font-size: 12px;
      font-weight: 900;
      border-bottom: 2px solid transparent;
    }}
    .detail-tabs a:first-child {{
      color: var(--accent);
      border-bottom-color: var(--accent);
    }}
    .detail-info-grid {{
      display: grid;
      gap: 14px;
    }}
    .detail-info-card {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface);
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
    }}
    .detail-info-card h3 {{
      margin: 0 0 10px;
      font-size: 16px;
      line-height: 1.3;
    }}
    .detail-check-list {{
      display: grid;
      gap: 8px;
      margin: 12px 0 0;
      padding: 0;
      list-style: none;
      color: rgba(15, 23, 42, 0.82);
      font-size: 13px;
      font-weight: 700;
      line-height: 1.55;
    }}
    .detail-check-list li {{
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
    }}
    .detail-check-list li::before {{
      content: "✓";
      display: inline-grid;
      place-items: center;
      width: 16px;
      height: 16px;
      border-radius: 999px;
      background: #12a163;
      color: #fff;
      font-size: 10px;
      font-weight: 900;
      line-height: 1;
      margin-top: 2px;
    }}
    .related-strip {{
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(128px, 1fr);
      gap: 10px;
      overflow-x: auto;
      padding-bottom: 4px;
    }}
    .related-mini {{
      position: relative;
      min-width: 0;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--surface);
      box-shadow: 0 10px 22px rgba(15, 23, 42, 0.06);
    }}
    .related-mini h3 {{
      margin: 0 0 4px;
      padding-right: 34px;
      font-size: 13px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}
    .related-mini p {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .related-score {{
      position: absolute;
      right: 10px;
      bottom: 12px;
      min-width: 30px;
      padding: 5px 6px;
      border-radius: 8px;
      background: #e7f8ef;
      color: #078243;
      text-align: center;
      font-size: 13px;
      font-weight: 900;
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
    .weekly-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 12px;
      margin: 0 0 22px;
      overflow-x: auto;
      padding-bottom: 2px;
    }}
    .weekly-kpi-card {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      min-height: 96px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--surface);
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
    }}
    .weekly-kpi-icon {{
      display: inline-grid;
      place-items: center;
      width: 30px;
      height: 30px;
      border-radius: 10px;
      background: #eef4ff;
      color: var(--accent);
      font-size: 15px;
      font-weight: 900;
    }}
    .weekly-kpi-icon.success {{
      background: #e8f8ef;
      color: var(--ok);
    }}
    .weekly-kpi-icon.warn {{
      background: #fff3dc;
      color: var(--warn);
    }}
    .weekly-kpi-icon.purple {{
      background: #f1eaff;
      color: #7c3aed;
    }}
    .weekly-kpi-body {{
      min-width: 0;
    }}
    .weekly-kpi-label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .weekly-kpi-value {{
      display: block;
      margin-top: 5px;
      color: var(--ink);
      font-size: 24px;
      line-height: 1;
      font-weight: 900;
    }}
    .weekly-kpi-sub {{
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .weekly-kpi-card .language-pills,
    .weekly-kpi-card .inline-links {{
      margin-top: 5px;
    }}
    .weekly-kpi-card .inline-links {{
      display: flex;
      gap: 5px;
      overflow-x: auto;
      scrollbar-width: none;
    }}
    .weekly-kpi-card .inline-links::-webkit-scrollbar {{
      display: none;
    }}
    .weekly-shell {{
      display: grid;
      gap: 14px;
    }}
    .weekly-heading {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 2px 2px 0;
    }}
    .weekly-heading h2 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }}
    .weekly-heading p {{
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }}
    .weekly-calendar-button {{
      display: inline-grid;
      place-items: center;
      width: 44px;
      height: 44px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
      color: var(--ink);
      font-size: 18px;
      font-weight: 900;
    }}
    .weekly-tabs,
    .weekly-ranking-tabs {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
    }}
    .weekly-ranking-tabs {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin: 6px 0 12px;
    }}
    .weekly-tab,
    .weekly-ranking-tab {{
      min-height: 34px;
      border: 0;
      border-radius: 11px;
      background: transparent;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      font-weight: 900;
      cursor: pointer;
    }}
    .weekly-tab.active,
    .weekly-ranking-tab.active {{
      background: var(--accent);
      color: #fff;
      box-shadow: 0 8px 16px rgba(37, 99, 235, 0.22);
    }}
    .weekly-panel,
    .weekly-ranking-panel {{
      display: none;
    }}
    .weekly-panel.active,
    .weekly-ranking-panel.active {{
      display: grid;
      gap: 14px;
    }}
    .weekly-card-panel {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
    }}
    .weekly-card-panel h3 {{
      margin: 0 0 12px;
      font-size: 17px;
      line-height: 1.2;
    }}
    .weekly-mini-chart {{
      display: grid;
      gap: 10px;
    }}
    .weekly-chart-bars {{
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 8px;
      align-items: end;
      min-height: 118px;
      padding: 10px 0 0;
      border-bottom: 1px solid var(--line);
    }}
    .weekly-chart-column {{
      display: grid;
      gap: 6px;
      justify-items: center;
      align-items: end;
      min-width: 0;
    }}
    .weekly-chart-bar {{
      width: 14px;
      min-height: 8px;
      border-radius: 6px 6px 2px 2px;
      background: linear-gradient(180deg, #2f7bff, #0b5cff);
    }}
    .weekly-chart-label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .weekly-topic-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .weekly-highlight-row {{
      display: grid;
      gap: 10px;
    }}
    .weekly-highlight {{
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr) 28px;
      gap: 10px;
      align-items: center;
      color: var(--ink);
      font-size: 12px;
      font-weight: 900;
    }}
    .weekly-highlight-track {{
      height: 7px;
      border-radius: 999px;
      background: var(--surface-muted);
      overflow: hidden;
    }}
    .weekly-highlight-fill {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
    }}
    .weekly-highlight:nth-child(2) .weekly-highlight-fill {{
      background: #8b5cf6;
    }}
    .weekly-highlight:nth-child(3) .weekly-highlight-fill {{
      background: #1fbf75;
    }}
    .weekly-highlight:nth-child(4) .weekly-highlight-fill {{
      background: var(--warn);
    }}
    .weekly-rank-list {{
      display: grid;
      gap: 10px;
    }}
    .weekly-rank-item {{
      position: relative;
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr) 52px;
      gap: 10px;
      align-items: center;
      min-height: 86px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
      color: var(--ink);
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
    }}
    .weekly-rank-number {{
      display: inline-grid;
      place-items: center;
      width: 30px;
      height: 30px;
      border-radius: 10px;
      background: #eef4ff;
      color: var(--accent);
      font-size: 14px;
      font-weight: 900;
    }}
    .weekly-rank-item.top1 .weekly-rank-number {{
      background: #fff0d6;
      color: var(--warn);
    }}
    .weekly-rank-main {{
      min-width: 0;
    }}
    .weekly-rank-title {{
      display: block;
      color: var(--accent);
      font-size: 15px;
      font-weight: 900;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .weekly-rank-owner,
    .weekly-rank-desc {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .weekly-rank-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 5px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .weekly-rank-score {{
      justify-self: end;
      display: inline-grid;
      place-items: center;
      min-width: 44px;
      min-height: 44px;
      border-radius: 10px;
      background: #dff8ea;
      color: var(--ok);
      font-size: 17px;
      line-height: 1;
      font-weight: 900;
    }}
    .weekly-rank-score small {{
      display: block;
      margin-top: 3px;
      font-size: 9px;
    }}
    .ops-shell {{
      display: grid;
      gap: 14px;
    }}
    .ops-heading {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      padding: 2px 2px 0;
    }}
    .ops-heading h2 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }}
    .ops-heading p {{
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }}
    .ops-refresh {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .ops-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .ops-kpi-card {{
      display: grid;
      grid-template-columns: 30px minmax(0, 1fr);
      gap: 9px;
      min-height: 86px;
      padding: 13px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
    }}
    .ops-icon {{
      display: inline-grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border-radius: 10px;
      background: #eef4ff;
      color: var(--accent);
      font-size: 14px;
      font-weight: 900;
    }}
    .ops-icon.ok {{
      background: #e8f8ef;
      color: var(--ok);
    }}
    .ops-icon.warn {{
      background: #fff3dc;
      color: var(--warn);
    }}
    .ops-icon.danger {{
      background: #feecec;
      color: #dc2626;
    }}
    .ops-kpi-card span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .ops-kpi-card strong {{
      display: block;
      margin: 5px 0 7px;
      color: var(--ink);
      font-size: 23px;
      line-height: 1;
      font-weight: 900;
    }}
    .ops-panel {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
    }}
    .ops-panel h3 {{
      margin: 0 0 12px;
      font-size: 17px;
      line-height: 1.2;
    }}
    .ops-job-list,
    .ops-log-list {{
      display: grid;
      gap: 0;
    }}
    .ops-job-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto 18px;
      gap: 10px;
      align-items: center;
      min-height: 38px;
      border-bottom: 1px solid var(--line);
      color: var(--ink);
      font-size: 13px;
      font-weight: 900;
    }}
    .ops-job-row:last-child {{
      border-bottom: 0;
    }}
    .ops-status {{
      display: inline-flex;
      justify-content: center;
      min-width: 54px;
      padding: 5px 10px;
      border-radius: 999px;
      background: #dff8ea;
      color: var(--ok);
      font-size: 11px;
      font-weight: 900;
    }}
    .ops-status.warn {{
      background: #fff3dc;
      color: var(--warn);
    }}
    .ops-status.fail {{
      background: #feecec;
      color: #dc2626;
    }}
    .ops-log-toolbar {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0;
      margin-bottom: 12px;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 13px;
      background: #fff;
    }}
    .ops-log-tab {{
      min-height: 32px;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: var(--ink);
      font: inherit;
      font-size: 12px;
      font-weight: 900;
      cursor: pointer;
    }}
    .ops-log-tab.active {{
      background: var(--accent);
      color: #fff;
    }}
    .ops-log-card {{
      display: grid;
      grid-template-columns: 24px minmax(0, 1fr) auto auto;
      gap: 10px;
      align-items: start;
      padding: 13px 0;
      border-bottom: 1px solid var(--line);
    }}
    .ops-log-card:last-child {{
      border-bottom: 0;
    }}
    .ops-log-icon {{
      display: inline-grid;
      place-items: center;
      width: 22px;
      height: 22px;
      border-radius: 999px;
      background: #e8f8ef;
      color: var(--ok);
      font-size: 12px;
      font-weight: 900;
    }}
    .ops-log-icon.warn {{
      background: #fff3dc;
      color: var(--warn);
    }}
    .ops-log-icon.fail {{
      background: #feecec;
      color: #dc2626;
    }}
    .ops-log-main {{
      min-width: 0;
    }}
    .ops-log-title {{
      display: block;
      color: var(--ink);
      font-size: 14px;
      font-weight: 900;
    }}
    .ops-log-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 8px 0;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .ops-log-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .ops-log-time {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .ops-alert-list {{
      display: grid;
      gap: 8px;
    }}
    .ops-alert-item {{
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      color: var(--ink);
      font-size: 12px;
      font-weight: 800;
    }}
    .detail-links {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.45fr);
      gap: 8px;
      margin: 14px 0 0;
      align-items: center;
    }}
    .detail-links.primary-links .badge:first-child,
    .detail-links.primary-links a:first-child {{
      background: #fff;
      color: var(--ink);
      border-color: var(--line);
    }}
    .detail-links.primary-links .badge:last-child,
    .detail-links.primary-links a:last-child {{
      background: #061b3a;
      color: #fff;
      border-color: #061b3a;
    }}
    .detail-links.secondary-links .badge,
    .detail-links.secondary-links a {{
      background: var(--surface-muted);
    }}
    .action-detail::before {{
      content: "i";
      display: inline-grid;
      place-items: center;
      width: 16px;
      height: 16px;
      border-radius: 999px;
      background: rgba(31, 111, 235, 0.12);
      color: #164ca4;
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
    }}
    .action-github::before {{
      content: "↗";
      font-weight: 900;
      line-height: 1;
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
      min-width: 0;
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
      overflow-wrap: anywhere;
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
    .kpi-total .kpi-icon {{
      background: #eef4ff;
      color: #1f6feb;
    }}
    .kpi-latest .kpi-icon {{
      background: #e8f8ef;
      color: #078243;
    }}
    .kpi-gray .kpi-icon {{
      background: #f1ecff;
      color: #7249d6;
    }}
    .kpi-score .kpi-icon {{
      background: #fff3dc;
      color: #e98600;
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
      flex-wrap: wrap;
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
    .filter-toggle {{
      display: none;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--surface-muted);
      color: var(--ink);
      padding: 10px 12px;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
      text-align: left;
    }}
    .archive-filter-body {{
      min-width: 0;
    }}
    .filter-sheet-header,
    .filter-sheet-actions {{
      display: none;
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
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 12px;
    }}
    .tab-panel.archive-list {{
      display: none;
    }}
    .tab-panel.archive-list.active {{
      display: grid;
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
      grid-auto-columns: minmax(260px, 1fr);
      gap: 10px;
      overflow-x: auto;
      padding: 2px 0 6px;
      scrollbar-width: thin;
    }}
    .spotlight-card {{
      position: relative;
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr) 48px;
      grid-template-rows: auto auto auto;
      gap: 7px 9px;
      align-items: start;
      min-height: 118px;
      max-height: 118px;
      padding: 12px;
      border: 1px solid #173b68;
      border-radius: 12px;
      background: #071d38;
      color: #fff;
      box-shadow: 0 10px 22px rgba(7, 29, 56, 0.18);
    }}
    .spotlight-avatar {{
      width: 30px;
      height: 30px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.22);
      background: rgba(255,255,255,0.1);
      object-fit: cover;
    }}
    .spotlight-main {{
      min-width: 0;
    }}
    .spotlight-owner {{
      display: block;
      margin-bottom: 2px;
      color: rgba(255,255,255,0.68);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .spotlight-title {{
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      color: #fff;
      font-size: 15px;
      line-height: 1.24;
      font-weight: 900;
      overflow-wrap: anywhere;
    }}
    .spotlight-title:hover {{
      color: #fff;
    }}
    .spotlight-score {{
      justify-self: end;
      display: inline-grid;
      place-items: center;
      min-width: 42px;
      min-height: 42px;
      padding: 5px 7px;
      border-radius: 10px;
      background: #dff8ea;
      color: #078243;
      font-size: 16px;
      font-weight: 900;
      line-height: 1;
      text-align: center;
    }}
    .spotlight-score small {{
      display: block;
      margin-top: 3px;
      font-size: 9px;
      font-weight: 900;
    }}
    .spotlight-meta {{
      grid-column: 1 / -1;
      display: flex;
      gap: 10px;
      align-items: center;
      min-width: 0;
      color: rgba(255,255,255,0.78);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
    }}
    .spotlight-meta span {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-width: 0;
    }}
    .spotlight-tags {{
      grid-column: 1 / span 2;
      display: flex;
      gap: 5px;
      min-width: 0;
      overflow: hidden;
    }}
    .spotlight-tag {{
      display: inline-flex;
      align-items: center;
      max-width: 92px;
      padding: 4px 7px;
      border: 1px solid rgba(255,255,255,0.13);
      border-radius: 7px;
      background: rgba(255,255,255,0.1);
      color: rgba(255,255,255,0.86);
      font-size: 10px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .spotlight-link {{
      grid-column: 3;
      justify-self: end;
      align-self: end;
      color: #fff;
      font-size: 12px;
      font-weight: 900;
    }}
    .mobile-segment {{
      display: none;
    }}
    .stat-card.compact strong {{
      font-size: 18px;
      line-height: 1.25;
    }}
    .language-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 8px;
    }}
    .language-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border-radius: 999px;
      background: var(--surface-muted);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 12px;
      font-weight: 800;
      line-height: 1;
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
        display: none;
      }}
      .brand-mark {{
        display: grid;
      }}
      .top-actions {{
        display: none;
      }}
      .site-header {{
        left: auto;
        right: auto;
        width: 100%;
        max-width: 100vw;
        overflow: hidden;
      }}
      .header-inner {{
        padding: 14px;
        max-width: 100%;
      }}
      .brand-row > span:not(.brand-mark) {{
        overflow: hidden;
      }}
      .brand strong,
      .brand span {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .mobile-segment {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 2px;
        padding: 4px;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: var(--surface);
        margin: 10px 14px 0;
        width: auto;
        max-width: none;
        overflow: hidden;
      }}
      .mobile-segment a {{
        min-width: 0;
        text-align: center;
        padding: 9px 8px;
        border-radius: 9px;
        color: var(--ink);
        font-weight: 900;
        font-size: 13.5px;
      }}
      .mobile-segment a[aria-current="page"] {{
        background: #1f6feb;
        color: #fff;
      }}
      .site-nav {{
        display: none !important;
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
        max-width: 100%;
      }}
      .hero {{
        display: none;
      }}
      .dashboard-hero {{
        grid-template-columns: 1fr;
        padding: 18px;
        border-radius: 16px;
        overflow: hidden;
      }}
      .mini-chart {{
        display: none;
      }}
      .kpi-grid {{
        grid-template-columns: none;
        grid-auto-flow: column;
        grid-auto-columns: minmax(106px, 31vw);
        gap: 8px;
        overflow-x: auto;
        padding: 1px 2px 8px;
        margin-bottom: 14px;
        scrollbar-width: none;
      }}
      .kpi-grid::-webkit-scrollbar {{
        display: none;
      }}
      .stats-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .weekly-kpi-grid {{
        grid-template-columns: none;
        grid-auto-flow: column;
        grid-auto-columns: minmax(106px, 31vw);
        gap: 8px;
        overflow-x: auto;
        padding: 1px 2px 8px;
        margin-bottom: 14px;
        scrollbar-width: none;
      }}
      .weekly-kpi-grid::-webkit-scrollbar {{
        display: none;
      }}
      .weekly-kpi-card {{
        grid-template-columns: 24px minmax(0, 1fr);
        gap: 7px;
        min-height: 94px;
        padding: 10px 9px;
        border-radius: 9px;
      }}
      .weekly-kpi-icon {{
        width: 24px;
        height: 24px;
        border-radius: 8px;
        font-size: 12px;
      }}
      .weekly-kpi-label {{
        font-size: 10px;
      }}
      .weekly-kpi-value {{
        font-size: 20px;
      }}
      .weekly-kpi-sub {{
        font-size: 10px;
      }}
      .weekly-heading h2 {{
        font-size: 22px;
      }}
      .weekly-tabs,
      .weekly-ranking-tabs {{
        border-radius: 12px;
      }}
      .weekly-tab,
      .weekly-ranking-tab {{
        min-height: 32px;
        font-size: 12px;
      }}
      .weekly-card-panel {{
        padding: 14px;
        border-radius: 12px;
      }}
      .weekly-chart-bars {{
        min-height: 112px;
        gap: 6px;
      }}
      .weekly-highlight {{
        grid-template-columns: 74px minmax(0, 1fr) 24px;
      }}
      .weekly-rank-item {{
        grid-template-columns: 30px minmax(0, 1fr) 48px;
        min-height: 82px;
        padding: 11px;
      }}
      .weekly-rank-title {{
        font-size: 14px;
      }}
      .ops-heading h2 {{
        font-size: 22px;
      }}
      .ops-kpi-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }}
      .ops-kpi-card {{
        grid-template-columns: 24px minmax(0, 1fr);
        gap: 7px;
        min-height: 82px;
        padding: 10px;
      }}
      .ops-icon {{
        width: 24px;
        height: 24px;
        border-radius: 8px;
        font-size: 12px;
      }}
      .ops-kpi-card strong {{
        font-size: 20px;
      }}
      .ops-panel {{
        padding: 14px;
        border-radius: 12px;
      }}
      .ops-log-card {{
        grid-template-columns: 22px minmax(0, 1fr) auto;
      }}
      .ops-log-card .ops-status {{
        grid-column: 2 / -1;
        justify-self: start;
      }}
      .ops-log-toolbar {{
        border-radius: 12px;
      }}
      .ops-log-tab {{
        font-size: 11px;
      }}
      .stat-card strong {{
        font-size: 22px;
        line-height: 1.12;
      }}
      .kpi-card {{
        grid-template-columns: 24px minmax(0, 1fr);
        gap: 7px;
        align-items: start;
        min-height: 72px;
        padding: 9px;
        border-radius: 10px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
      }}
      .kpi-icon {{
        width: 22px;
        height: 22px;
        border-radius: 7px;
        font-size: 12px;
      }}
      .kpi-card strong {{
        font-size: 18px;
        line-height: 1.05;
        margin: 1px 0 2px;
      }}
      .kpi-card span {{
        font-size: 10px;
        line-height: 1.25;
        font-weight: 800;
      }}
      .kpi-card div span:first-child {{
        display: block;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .archive-list {{
        grid-template-columns: 1fr;
      }}
      .archive-list .card {{
        min-width: 0;
      }}
      .spotlight-strip {{
        grid-auto-columns: minmax(220px, 72vw);
      }}
      .spotlight-card {{
        min-height: 112px;
        max-height: 112px;
        padding: 11px;
      }}
      .spotlight-title {{
        font-size: 14px;
      }}
      .card {{
        padding: 16px 14px;
        min-width: 0;
      }}
      .card-header {{
        align-items: flex-start;
        padding-right: 50px;
      }}
      .card h2 {{
        font-size: 16.5px;
        line-height: 1.28;
        font-weight: 900;
        overflow-wrap: anywhere;
      }}
      .owner-line {{
        font-size: 12.5px;
        font-weight: 750;
      }}
      .meta {{
        gap: 10px;
        row-gap: 7px;
        font-size: 12.5px;
        font-weight: 750;
      }}
      .meta span {{
        padding: 0;
      }}
      .description {{
        font-size: 13px;
        line-height: 1.62;
        font-weight: 650;
      }}
      .pick-reason {{
        font-size: 12.5px;
        line-height: 1.55;
        font-weight: 750;
      }}
      .badge {{
        font-size: 11.5px;
        font-weight: 700;
      }}
      .detail-links .badge,
      .detail-links a {{
        min-height: 38px;
        justify-content: center;
        font-size: 13px;
        font-weight: 850;
      }}
      .card-score {{
        top: 13px;
        right: 13px;
      }}
      .detail-hero-card {{
        padding: 18px;
      }}
      .detail-hero-card .avatar {{
        width: 38px;
        height: 38px;
      }}
      .detail-hero-card h2 {{
        font-size: 24px;
      }}
      .detail-tabs a {{
        font-size: 11.5px;
      }}
      .detail-info-card {{
        padding: 16px;
      }}
      .related-strip {{
        grid-auto-columns: minmax(122px, 42vw);
      }}
      pre {{
        font-size: 12px;
        overflow-wrap: anywhere;
      }}
      .panel-title {{
        align-items: stretch;
      }}
      .panel-title h2 {{
        flex: 1 1 auto;
      }}
      .mode-toggle {{
        width: 100%;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        order: 3;
      }}
      .filter-toggle {{
        display: block;
        order: 2;
      }}
      .archive-filter-body {{
        position: fixed;
        inset: 0;
        z-index: 60;
        display: flex;
        align-items: flex-end;
        justify-content: center;
        padding: 0;
        background: rgba(7, 24, 47, 0);
        opacity: 0;
        pointer-events: none;
        transition: opacity 180ms ease, background 180ms ease;
      }}
      .archive-filter-body.open {{
        opacity: 1;
        pointer-events: auto;
        background: rgba(7, 24, 47, 0.42);
      }}
      .archive-filter-sheet {{
        width: 100%;
        max-height: min(82vh, 760px);
        overflow-y: auto;
        padding: 18px 18px calc(18px + env(safe-area-inset-bottom));
        border-radius: 22px 22px 0 0;
        background: var(--surface);
        box-shadow: 0 -18px 46px rgba(15, 23, 42, 0.22);
        transform: translateY(100%);
        transition: transform 220ms ease;
      }}
      .archive-filter-body.open .archive-filter-sheet {{
        transform: translateY(0);
      }}
      .filter-sheet-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin: 0 0 14px;
      }}
      .filter-sheet-header::before {{
        content: "";
        position: absolute;
        left: 50%;
        top: 8px;
        width: 42px;
        height: 4px;
        border-radius: 999px;
        background: #d7dee8;
        transform: translateX(-50%);
      }}
      .filter-sheet-header h3 {{
        margin: 10px 0 0;
        font-size: 18px;
      }}
      .filter-sheet-close {{
        width: 36px;
        height: 36px;
        border: 0;
        border-radius: 999px;
        background: var(--surface-muted);
        color: var(--ink);
        font: inherit;
        font-size: 22px;
        line-height: 1;
        cursor: pointer;
      }}
      .archive-controls {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        padding: 12px;
        max-width: 100%;
        border: 0;
        padding: 0;
        background: transparent;
      }}
      .archive-controls .control-group:first-child,
      .archive-controls .control-group:nth-child(4),
      .archive-controls .control-group:nth-child(9) {{
        grid-column: 1 / -1;
      }}
      .control-group input,
      .control-group select,
      .archive-select-row select {{
        min-width: 0;
        max-width: 100%;
      }}
      .date-selector {{
        width: 100%;
        padding: 10px;
        margin-bottom: 14px;
      }}
      .date-select {{
        flex: 1 1 auto;
        min-width: 0;
      }}
      .stat-card.compact strong {{
        font-size: 14px;
      }}
      .filter-sheet-actions {{
        position: sticky;
        bottom: 0;
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
        gap: 10px;
        margin-top: 18px;
        padding-top: 12px;
        background: linear-gradient(180deg, rgba(255,255,255,0), var(--surface) 18%);
      }}
      .filter-action {{
        min-height: 48px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: var(--surface-muted);
        color: var(--ink);
        font: inherit;
        font-weight: 800;
        cursor: pointer;
      }}
      .filter-action.primary {{
        background: #07182f;
        color: #fff;
        border-color: #07182f;
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
    let activeDayTarget = daySelect?.value || '';
    const setActiveDay = (target) => {{
      if (!target) return;
      activeDayTarget = target;
      if (daySelect) daySelect.value = target;
      for (const panel of panels) panel.classList.remove('active');
      document.getElementById(target)?.classList.add('active');
    }};
    if (daySelect) {{
      daySelect.addEventListener('change', () => {{
        setActiveDay(daySelect.value);
      }});
    }}
    const weeklyArchiveSelect = document.querySelector('[data-weekly-archive-select]');
    if (weeklyArchiveSelect) {{
      weeklyArchiveSelect.addEventListener('change', () => {{
        const target = String(weeklyArchiveSelect.value || '').trim();
        if (target) window.location.href = target;
      }});
    }}
    const bindTabs = (buttonSelector, panelSelector, targetAttr) => {{
      const buttons = Array.from(document.querySelectorAll(buttonSelector));
      const panels = Array.from(document.querySelectorAll(panelSelector));
      if (!buttons.length || !panels.length) return;
      const activate = (target) => {{
        for (const button of buttons) {{
          const isActive = button.getAttribute(targetAttr) === target;
          button.classList.toggle('active', isActive);
          button.setAttribute('aria-selected', isActive ? 'true' : 'false');
        }}
        for (const panel of panels) {{
          panel.classList.toggle('active', panel.id === target);
        }}
      }};
      for (const button of buttons) {{
        button.addEventListener('click', () => activate(button.getAttribute(targetAttr)));
      }}
    }};
    bindTabs('[data-weekly-tab-target]', '[data-weekly-panel]', 'data-weekly-tab-target');
    bindTabs('[data-weekly-ranking-target]', '[data-weekly-ranking-panel]', 'data-weekly-ranking-target');
    const opsLogTabs = document.querySelectorAll('[data-ops-log-filter]');
    const opsLogCards = document.querySelectorAll('[data-ops-log-status]');
    for (const tab of opsLogTabs) {{
      tab.addEventListener('click', () => {{
        const target = String(tab.dataset.opsLogFilter || 'all');
        for (const item of opsLogTabs) item.classList.remove('active');
        tab.classList.add('active');
        for (const card of opsLogCards) {{
          const status = String(card.dataset.opsLogStatus || '');
          card.style.display = target === 'all' || status === target ? '' : 'none';
        }}
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
      const filterToggle = archiveRoot.querySelector('[data-filter-toggle]');
      const filterBody = archiveRoot.querySelector('[data-filter-body]');
      const filterClose = archiveRoot.querySelector('[data-filter-close]');
      const filterApply = archiveRoot.querySelector('[data-filter-apply]');
      const filterReset = archiveRoot.querySelector('[data-filter-reset]');
      const panelsById = new Map(Array.from(document.querySelectorAll('.tab-panel')).map((panel) => [panel.id, panel]));

      const activePanelId = () => activeDayTarget || '';
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
      const hasInitialFilters = Array.from(searchParams.keys()).some((key) => key !== 'mode');
      const setFilterBodyOpen = (open) => {{
        if (!filterToggle || !filterBody) return;
        filterBody.classList.toggle('open', open);
        document.body.classList.toggle('filter-sheet-open', open);
        filterToggle.setAttribute('aria-expanded', String(open));
        filterToggle.textContent = open ? 'フィルターを閉じる' : 'フィルターを開く';
      }};
      if (filterToggle && filterBody) {{
        setFilterBodyOpen(window.matchMedia('(min-width: 721px)').matches || hasInitialFilters);
        filterToggle.addEventListener('click', () => {{
          setFilterBodyOpen(!filterBody.classList.contains('open'));
        }});
        filterClose?.addEventListener('click', () => setFilterBodyOpen(false));
        filterApply?.addEventListener('click', () => {{
          applyArchiveFilters();
          setFilterBodyOpen(false);
        }});
        filterBody.addEventListener('click', (event) => {{
          if (event.target === filterBody) setFilterBodyOpen(false);
        }});
      }}
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
      const resetArchiveFilters = () => {{
        if (searchInput) searchInput.value = '';
        if (languageInput) languageInput.value = '';
        if (tagInput) tagInput.value = '';
        if (reviewStateInput) reviewStateInput.value = '';
        if (minStarsInput) minStarsInput.value = '';
        if (maxStarsInput) maxStarsInput.value = '';
        if (minScoreInput) minScoreInput.value = '';
        if (maxScoreInput) maxScoreInput.value = '';
        if (sortInput) sortInput.value = 'newest';
        archiveMode = 'normal';
        applyArchiveFilters();
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
      filterReset?.addEventListener('click', resetArchiveFilters);
      applyArchiveFilters();
    }}
    const reviewStateMenus = document.querySelectorAll('[data-review-state-menu]');
    if (reviewStateMenus.length) {{
      const closeReviewStateMenus = (exceptMenu) => {{
        for (const wrapper of reviewStateMenus) {{
          if (exceptMenu && wrapper === exceptMenu) continue;
          const trigger = wrapper.querySelector('[data-review-state-trigger]');
          const menu = wrapper.querySelector('.review-state-menu');
          trigger?.setAttribute('aria-expanded', 'false');
          menu?.classList.remove('open');
        }}
      }};
      for (const wrapper of reviewStateMenus) {{
        const trigger = wrapper.querySelector('[data-review-state-trigger]');
        const menu = wrapper.querySelector('.review-state-menu');
        if (!trigger || !menu) continue;
        trigger.addEventListener('click', (event) => {{
          event.stopPropagation();
          const willOpen = !menu.classList.contains('open');
          closeReviewStateMenus(wrapper);
          menu.classList.toggle('open', willOpen);
          trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        }});
        menu.addEventListener('click', (event) => event.stopPropagation());
        for (const option of menu.querySelectorAll('[data-review-state-option]')) {{
          option.addEventListener('click', () => closeReviewStateMenus());
        }}
      }}
      document.addEventListener('click', () => closeReviewStateMenus());
      document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape') closeReviewStateMenus();
      }});
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
            category_label = gray_category_label(gray.get("category"))
            gray_header = (
                f"{index}. {repo['full_name']} | {category_label} | {status_label}\n"
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
        <button class="filter-toggle" type="button" data-filter-toggle aria-expanded="false">フィルターを開く</button>
        <div class="mode-toggle" aria-label="表示モード">
          <button type="button" class="active" data-archive-mode="normal" aria-pressed="true">通常</button>
          <button type="button" data-archive-mode="gray" aria-pressed="false">グレー</button>
        </div>
      </div>
      <div class="archive-filter-body" data-filter-body>
      <div class="archive-filter-sheet" role="dialog" aria-modal="true" aria-labelledby="filter-sheet-title">
      <div class="filter-sheet-header">
        <h3 id="filter-sheet-title">フィルター</h3>
        <button class="filter-sheet-close" type="button" data-filter-close aria-label="フィルターを閉じる">×</button>
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
      <div class="filter-sheet-actions">
        <button class="filter-action" type="button" data-filter-reset>リセット</button>
        <button class="filter-action primary" type="button" data-filter-apply>検索する</button>
      </div>
      </div>
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
    try:
        score_label = str(int(round(float(score_value))))
    except (TypeError, ValueError):
        score_label = escape(str(score_value or 0))
    count_label = (
        f'<span class="meta-count">登場 {int(item.get("count") or 0)}回</span>'
        if item.get("count") is not None
        else ""
    )
    details_href = repo_detail_href(str(item.get("full_name") or ""), path_prefix)
    return f"""
    <article class="card{rank_class}" {attrs}{' data-archive-card' if archive_card else ''}>
      <div class="card-score">{score_label}<small>スコア</small></div>
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
        <span class="meta-stars">stars {int(item.get("stars") or 0)}</span>
        <span class="meta-language">{language}</span>
        {f'<span class="date-label">{sent_at}</span>' if sent_at else ''}
        {count_label}
      </div>
      {f'<p class="description">{description}</p>' if description else ''}
      {f'<p class="pick-reason">選定理由: {pick_reason}</p>' if pick_reason else ''}
      {f'<div class="badge-row"><span class="badge">{language}</span>{review_badge}{topics}</div>' if topics or language or review_badge else ''}
      <div class="detail-links primary-links">
        <a class="badge action-detail" href="{details_href}">詳細</a>
        <a class="badge action-github" href="{html_url}" target="_blank" rel="noreferrer">GitHub</a>
      </div>
    </article>
    """


def render_spotlight_card(
    item: dict[str, Any],
    review_state: str,
    path_prefix: str = ".",
) -> str:
    sent_at = escape(str(item.get("_display_time") or ""))
    full_name_raw = str(item.get("full_name") or "")
    full_name = escape(full_name_raw)
    html_url = escape(str(item.get("html_url") or ""))
    language = escape(str(item.get("language") or "N/A"))
    owner_login_raw, owner_html_url_raw, owner_avatar_url_raw = fallback_owner_fields(item)
    owner_login = escape(owner_login_raw)
    owner_html_url = escape(owner_html_url_raw)
    owner_avatar_url = escape(owner_avatar_url_raw)
    score_value = item.get("best_score", item.get("score", 0))
    try:
        score_label = str(int(round(float(score_value))))
    except (TypeError, ValueError):
        score_label = escape(str(score_value or 0))
    tags = [str(topic) for topic in extract_tags(item)[:2]]
    tag_html = "".join(
        f'<span class="spotlight-tag">#{escape(tag)}</span>'
        for tag in tags
    )
    if review_state:
        tag_html += f'<span class="spotlight-tag">状態 {escape(review_state_label(review_state))}</span>'
    details_href = repo_detail_href(full_name_raw, path_prefix)
    return f"""
    <article class="spotlight-card">
      <a href="{owner_html_url}" target="_blank" rel="noreferrer" aria-label="{owner_login}">
        <img class="spotlight-avatar" src="{owner_avatar_url}" alt="{owner_login}">
      </a>
      <div class="spotlight-main">
        <a class="spotlight-owner" href="{owner_html_url}" target="_blank" rel="noreferrer">@{owner_login}</a>
        <a class="spotlight-title" href="{details_href}">{full_name}</a>
      </div>
      <div class="spotlight-score">{score_label}<small>スコア</small></div>
      <div class="spotlight-meta">
        <span>★ stars {int(item.get("stars") or 0)}</span>
        <span>● {language}</span>
        {f'<span>◷ {sent_at}</span>' if sent_at else ''}
      </div>
      <div class="spotlight-tags">{tag_html}</div>
      <a class="spotlight-link" href="{details_href}">詳細</a>
    </article>
    """


def format_duration_label(started_raw: Any, finished_raw: Any) -> str:
    if not started_raw or not finished_raw:
        return "-"
    try:
        started = datetime.fromisoformat(str(started_raw))
        finished = datetime.fromisoformat(str(finished_raw))
    except ValueError:
        return "-"
    seconds = max(0, int((finished - started).total_seconds()))
    minutes, rest = divmod(seconds, 60)
    if minutes:
        return f"{minutes:02d}:{rest:02d}"
    return f"00:{rest:02d}"


def build_operations_summary_html(path_prefix: str = ".") -> str:
    state = load_state()
    history = load_history()
    run_status = str(state.get("last_run_status") or "unknown").strip() or "unknown"
    started_at_raw = state.get("last_run_started_at")
    finished_at_raw = state.get("last_run_finished_at")
    started_at = format_state_timestamp(started_at_raw)
    finished_at = format_state_timestamp(finished_at_raw)
    duration_label = format_duration_label(started_at_raw, finished_at_raw)
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
    latest_history = sorted(
        [item for item in history if item.get("sent_at")],
        key=lambda item: parse_sent_at(item["sent_at"]),
        reverse=True,
    )
    latest_day = ""
    today_items: list[dict[str, Any]] = []
    if latest_history:
        latest_dt = parse_sent_at(latest_history[0]["sent_at"]).astimezone(ZoneInfo("Asia/Tokyo"))
        latest_day = latest_dt.strftime("%Y/%m/%d")
        today_items = [
            item
            for item in latest_history
            if parse_sent_at(item["sent_at"]).astimezone(ZoneInfo("Asia/Tokyo")).date() == latest_dt.date()
        ]
    notifications_sent = len(today_items)
    scored_count = sum(1 for item in today_items if item.get("score") is not None)
    success_class = "" if run_status == "success" else ("fail" if run_status == "failed" else "warn")
    success_rate = "100%" if run_status == "success" else "0%"
    warning_count = len(deepseek_alerts)
    alert_rows = []
    if latest_warning_kind:
        alert_rows.append(
            f"""
            <div class="ops-alert-item">
              <span class="ops-log-icon warn">!</span>
              <span>{escape(deepseek_warning_label(latest_warning_kind))}: {escape(latest_warning_detail)}</span>
              <span>{escape(latest_warning_sent)}</span>
            </div>
            """
        )
    if run_error:
        alert_rows.append(
            f"""
            <div class="ops-alert-item">
              <span class="ops-log-icon fail">×</span>
              <span>最終実行エラー: {escape(run_error)}</span>
              <span>{escape(finished_at)}</span>
            </div>
            """
        )
    if not alert_rows:
        alert_rows.append(
            """
            <div class="ops-alert-item">
              <span class="ops-log-icon">i</span>
              <span>現在表示できる警告はありません</span>
              <span>-</span>
            </div>
            """
        )

    def status_badge(status: str, label: str) -> str:
        status_class = "fail" if status == "fail" else ("warn" if status == "warn" else "")
        return f'<span class="ops-status {status_class}">{escape(label)}</span>'

    log_items = [
        {
            "title": "GitHub取得ジョブ",
            "status": "success" if run_status == "success" else ("fail" if run_status == "failed" else "warn"),
            "label": run_status_label(run_status),
            "time": started_at,
            "meta": [f"処理件数 {len(today_items):,}件", f"時間 {duration_label}"],
            "tags": ["収集", "GitHub API"],
        },
        {
            "title": "AIスコアリング",
            "status": "success" if not run_error else "fail",
            "label": "成功" if not run_error else "失敗",
            "time": finished_at,
            "meta": [f"処理件数 {scored_count:,}件", "OpenAI/DeepSeek"],
            "tags": ["AI", "スコア"],
        },
        {
            "title": "Telegram通知",
            "status": "success" if notifications_sent else "warn",
            "label": "成功" if notifications_sent else "警告",
            "time": finished_at,
            "meta": [f"送信件数 {notifications_sent:,}件"],
            "tags": ["通知", "Telegram Bot"],
        },
        {
            "title": "週次集計",
            "status": "success" if history else "warn",
            "label": "成功" if history else "警告",
            "time": finished_at,
            "meta": [f"履歴 {len(history):,}件"],
            "tags": ["集計", "データベース"],
        },
    ]
    if run_error:
        log_items.append(
            {
                "title": "最終実行エラー",
                "status": "fail",
                "label": "失敗",
                "time": finished_at,
                "meta": [run_error],
                "tags": ["実行", "エラー"],
            }
        )
    log_cards = "".join(
        f"""
        <article class="ops-log-card" data-ops-log-status="{item['status']}">
          <span class="ops-log-icon {'fail' if item['status'] == 'fail' else ('warn' if item['status'] == 'warn' else '')}">{'×' if item['status'] == 'fail' else ('!' if item['status'] == 'warn' else '✓')}</span>
          <div class="ops-log-main">
            <strong class="ops-log-title">{escape(item['title'])}</strong>
            <div class="ops-log-meta">{''.join(f'<span>{escape(str(meta))}</span>' for meta in item['meta'])}</div>
            <div class="ops-log-tags">{''.join(f'<span class="badge">{escape(str(tag))}</span>' for tag in item['tags'])}</div>
          </div>
          <span class="ops-log-time">{escape(item['time'])}</span>
          {status_badge(item['status'], item['label'])}
        </article>
        """
        for item in log_items
    )
    return f"""
    <section class="ops-shell">
      <div class="ops-heading">
        <div>
          <h2>運用サマリー</h2>
          <p>収集・通知・警告の状態を確認</p>
        </div>
        <span class="ops-refresh">最終更新: {escape(finished_at)} ↻</span>
      </div>
      <section class="ops-kpi-grid" aria-label="運用KPI">
        <article class="ops-kpi-card">
          <span class="ops-icon">◷</span>
          <div><span>定時実行</span><strong>{escape(run_status_label(run_status))}</strong><span>{escape(success_rate)}</span></div>
        </article>
        <article class="ops-kpi-card">
          <span class="ops-icon ok">✓</span>
          <div><span>成功率</span><strong>{escape(success_rate)}</strong><span>最終実行</span></div>
        </article>
        <article class="ops-kpi-card">
          <span class="ops-icon">➤</span>
          <div><span>通知送信</span><strong>{notifications_sent}</strong><span>{escape(latest_day or '-')}</span></div>
        </article>
        <article class="ops-kpi-card">
          <span class="ops-icon {'warn' if warning_count else 'ok'}">!</span>
          <div><span>警告</span><strong>{warning_count}</strong><span>DeepSeek</span></div>
        </article>
      </section>
      <section class="ops-panel">
        <h3>実行状況</h3>
        <div class="ops-job-list">
          <div class="ops-job-row"><span>収集</span>{status_badge(log_items[0]["status"], log_items[0]["label"])}<span>›</span></div>
          <div class="ops-job-row"><span>スコアリング</span>{status_badge(log_items[1]["status"], log_items[1]["label"])}<span>›</span></div>
          <div class="ops-job-row"><span>Telegram通知</span>{status_badge(log_items[2]["status"], log_items[2]["label"])}<span>›</span></div>
          <div class="ops-job-row"><span>週次集計</span>{status_badge(log_items[3]["status"], log_items[3]["label"])}<span>›</span></div>
        </div>
      </section>
      <section class="ops-panel">
        <h3>実行ログ</h3>
        <div class="ops-log-toolbar" aria-label="実行ログフィルター">
          <button class="ops-log-tab active" type="button" data-ops-log-filter="all">すべて</button>
          <button class="ops-log-tab" type="button" data-ops-log-filter="success">成功</button>
          <button class="ops-log-tab" type="button" data-ops-log-filter="warn">警告</button>
          <button class="ops-log-tab" type="button" data-ops-log-filter="fail">失敗</button>
        </div>
        <div class="ops-log-list">{log_cards}</div>
      </section>
      <section class="ops-panel">
        <h3>DeepSeek 警告</h3>
        <div class="ops-alert-list">{''.join(alert_rows)}</div>
      </section>
      <div class="detail-links secondary-links">
        <a class="badge" href="{path_prefix}/operations.html">運用サマリーページを開く</a>
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

    day_options = []
    tab_panels = []
    for index, (day_key, items) in enumerate(grouped.items()):
        panel_class = "tab-panel active" if index == 0 else "tab-panel"
        tab_id = f"tab-{index}"
        selected = " selected" if index == 0 else ""
        day_options.append(
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
        render_spotlight_card(
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
      <article class="kpi-card kpi-total"><span class="kpi-icon" aria-hidden="true">▱</span><div><span>総リポジトリ数</span><strong>{stats['unique_repos']:,}</strong><span>アーカイブ済み</span></div></article>
      <article class="kpi-card kpi-latest"><span class="kpi-icon" aria-hidden="true">➤</span><div><span>最新日の通知</span><strong>{stats['latest_count']}</strong><span>{escape(stats['latest_day'] or '-')}</span></div></article>
      <article class="kpi-card kpi-gray"><span class="kpi-icon" aria-hidden="true">◆</span><div><span>グレー候補</span><strong>{stats['gray_count']}</strong><span>表示フィルタ対象</span></div></article>
      <article class="kpi-card kpi-score"><span class="kpi-icon" aria-hidden="true">↗</span><div><span>平均スコア</span><strong>{stats['avg_score']:.1f}</strong><span>履歴全体</span></div></article>
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
            "<div class='date-selector' aria-label='通知日を選択'>"
            "<label class='date-select-label' for='history-date-select'>通知日</label>"
            "<select id='history-date-select' class='date-select' data-day-select>"
            + "".join(day_options)
            + "</select></div>"
            if day_options
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
    body_html = build_operations_summary_html(".")
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
    avg_score = (
        sum(float(item.get("score") or 0) for item in this_week_items) / len(this_week_items)
        if this_week_items
        else 0.0
    )
    unique_repos = len({item.get("full_name") for item in this_week_items})
    previous_topics = {
        topic
        for item in history
        if item.get("sent_at") and parse_sent_at(item["sent_at"]) < range_start
        for topic in extract_tags(item)
    }
    weekly_topics: dict[str, int] = {}
    weekly_languages: dict[str, int] = {}
    tokyo = ZoneInfo("Asia/Tokyo")
    daily_counts: dict[str, int] = {}
    for offset in range(7):
        day = (range_start + timedelta(days=offset)).astimezone(tokyo)
        day_label = day.strftime("%-m/%-d") if os.name != "nt" else day.strftime("%#m/%#d")
        daily_counts[day_label] = 0
    for item in this_week_items:
        sent_at_dt = item.get("_parsed_sent_at") or parse_sent_at(item.get("sent_at"))
        day_label = sent_at_dt.astimezone(tokyo).strftime("%-m/%-d") if os.name != "nt" else sent_at_dt.astimezone(tokyo).strftime("%#m/%#d")
        daily_counts[day_label] = daily_counts.get(day_label, 0) + 1
        language = str(item.get("language") or "N/A")
        weekly_languages[language] = weekly_languages.get(language, 0) + 1
        for topic in extract_tags(item):
            weekly_topics[topic] = weekly_topics.get(topic, 0) + 1
    new_tags_count = len(set(weekly_topics) - previous_topics)
    max_daily_count = max(daily_counts.values()) if daily_counts else 1
    weekly_chart_html = "".join(
        f"""
        <div class="weekly-chart-column">
          <span class="weekly-chart-bar" title="{escape(day)} {count}件" style="height:{max(8, int((count / (max_daily_count or 1)) * 86))}px"></span>
          <span class="weekly-chart-label">{escape(day)}</span>
        </div>
        """
        for day, count in daily_counts.items()
    )
    topic_pills_html = "".join(
        f'<span class="badge topic">#{escape(topic)}</span>'
        for topic, _ in sorted(weekly_topics.items(), key=lambda pair: pair[1], reverse=True)[:6]
    ) or '<span class="badge">なし</span>'
    max_language_count = max(weekly_languages.values()) if weekly_languages else 1
    language_highlight_html = "".join(
        f"""
        <div class="weekly-highlight">
          <span>{escape(language)}</span>
          <span class="weekly-highlight-track"><span class="weekly-highlight-fill" style="width:{max(8, int((count / (max_language_count or 1)) * 100))}%"></span></span>
          <strong>{count}</strong>
        </div>
        """
        for language, count in sorted(weekly_languages.items(), key=lambda pair: pair[1], reverse=True)[:5]
    ) or '<span class="badge">なし</span>'
    rising_candidates = sorted(
        fresh_picks,
        key=lambda item: (
            int(item.get("stars_delta") or 0),
            float(item.get("score") or 0),
            int(item.get("stars") or 0),
        ),
        reverse=True,
    )

    def render_weekly_rank_card(item: dict[str, Any], rank: int) -> str:
        full_name_raw = str(item.get("full_name") or "")
        score_value = item.get("best_score", item.get("score", 0))
        try:
            score_label = str(int(round(float(score_value or 0))))
        except (TypeError, ValueError):
            score_label = "0"
        owner_login, _, _ = fallback_owner_fields(item)
        language = escape(str(item.get("language") or "N/A"))
        stars = int(item.get("stars", item.get("latest_stars") or 0) or 0)
        description = escape(normalize_card_description(item))
        return f"""
        <a class="weekly-rank-item{' top1' if rank == 1 else ''}" href="{repo_detail_href(full_name_raw, path_prefix=path_prefix)}">
          <span class="weekly-rank-number">{rank}</span>
          <span class="weekly-rank-main">
            <strong class="weekly-rank-title">{escape(full_name_raw)}</strong>
            <span class="weekly-rank-owner">by {escape(owner_login)}</span>
            <span class="weekly-rank-meta"><span>● {language}</span><span>★ {stars}</span></span>
            {f'<span class="weekly-rank-desc">{description}</span>' if description else ''}
          </span>
          <span class="weekly-rank-score">{score_label}<small>スコア</small></span>
        </a>
        """

    def render_weekly_ranking_panel(panel_id: str, items: list[dict[str, Any]]) -> str:
        cards = "".join(
            render_weekly_rank_card(item, index)
            for index, item in enumerate(items[:10], start=1)
        )
        return f"""
        <div id="{panel_id}" class="weekly-ranking-panel{' active' if panel_id == 'weekly-rank-total' else ''}" data-weekly-ranking-panel>
          <div class="weekly-rank-list">{cards or '<article class="empty-state">この条件に合うリポジトリは、今週まだありません。</article>'}</div>
        </div>
        """

    weekly_content_html = f"""
    <section class="weekly-shell">
      <div class="weekly-heading">
        <div>
          <h2>今週のまとめ</h2>
          <p>{escape(label)}</p>
        </div>
        <span class="weekly-calendar-button" aria-hidden="true">▣</span>
      </div>
      <div class="weekly-tabs" role="tablist" aria-label="週次ビュー">
        <button class="weekly-tab active" type="button" role="tab" aria-selected="true" data-weekly-tab-target="weekly-summary">まとめ</button>
        <button class="weekly-tab" type="button" role="tab" aria-selected="false" data-weekly-tab-target="weekly-ranking">ランキング</button>
      </div>
      <div id="weekly-summary" class="weekly-panel active" data-weekly-panel>
        <section class="weekly-kpi-grid" aria-label="週次サマリー">
      <article class="weekly-kpi-card">
        <span class="weekly-kpi-icon">▱</span>
        <div class="weekly-kpi-body">
          <span class="weekly-kpi-label">総リポジトリ数</span>
          <strong class="weekly-kpi-value">{unique_repos}</strong>
          <span class="weekly-kpi-sub">今週のリポジトリ数</span>
        </div>
      </article>
      <article class="weekly-kpi-card">
        <span class="weekly-kpi-icon success">▶</span>
        <div class="weekly-kpi-body">
          <span class="weekly-kpi-label">通知総数</span>
          <strong class="weekly-kpi-value">{len(this_week_items)}</strong>
          <span class="weekly-kpi-sub">{escape(label)}</span>
        </div>
      </article>
      <article class="weekly-kpi-card">
        <span class="weekly-kpi-icon purple">◆</span>
        <div class="weekly-kpi-body">
          <span class="weekly-kpi-label">新規タグ</span>
          <strong class="weekly-kpi-value">{new_tags_count}</strong>
          <span class="weekly-kpi-sub">今週初出</span>
        </div>
      </article>
      <article class="weekly-kpi-card">
        <span class="weekly-kpi-icon warn">↗</span>
        <div class="weekly-kpi-body">
          <span class="weekly-kpi-label">平均 score</span>
          <strong class="weekly-kpi-value">{avg_score:.1f}</strong>
          <span class="weekly-kpi-sub">週内平均</span>
        </div>
      </article>
    </section>
        <section class="weekly-card-panel">
          <h3>今週の通知推移</h3>
          <div class="weekly-mini-chart"><div class="weekly-chart-bars">{weekly_chart_html}</div></div>
        </section>
        <section class="weekly-card-panel">
          <h3>今週の注目トピック</h3>
          <div class="weekly-topic-row">{topic_pills_html}</div>
        </section>
        <section class="weekly-card-panel">
          <h3>カテゴリ別ハイライト</h3>
          <div class="weekly-highlight-row">{language_highlight_html}</div>
        </section>
      </div>
      <div id="weekly-ranking" class="weekly-panel" data-weekly-panel>
        <div class="weekly-heading">
          <div>
            <h2>週間ランキング</h2>
            <p>{escape(label)}</p>
          </div>
        </div>
        <div class="weekly-ranking-tabs" role="tablist" aria-label="週間ランキング">
          <button class="weekly-ranking-tab active" type="button" role="tab" aria-selected="true" data-weekly-ranking-target="weekly-rank-total">総合</button>
          <button class="weekly-ranking-tab" type="button" role="tab" aria-selected="false" data-weekly-ranking-target="weekly-rank-low-star">低スター発掘</button>
          <button class="weekly-ranking-tab" type="button" role="tab" aria-selected="false" data-weekly-ranking-target="weekly-rank-rising">急上昇</button>
        </div>
        {render_weekly_ranking_panel("weekly-rank-total", ranking)}
        {render_weekly_ranking_panel("weekly-rank-low-star", low_star_ranking)}
        {render_weekly_ranking_panel("weekly-rank-rising", rising_candidates)}
      </div>
    </section>
    """

    html = site_shell(
        "週間まとめ",
        f"{label} の通知履歴を、見返しやすい週次ビューとしてまとめています。",
        archive_links_html + weekly_content_html,
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
