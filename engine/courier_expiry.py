#!/usr/bin/env python3
"""Junco Mail Auto-Expiry Engine.

Manages:
1. Per-provider notification auto-delete rules (`expiry_rules` table), seeded
   with built-in presets (all OFF by default, Trash action by default,
   starred threads protected by default) plus custom user rules.
2. Per-thread scheduled deletion (`thread_expiries` table), supporting both
   explicit manual schedules ("Delete after 2 years · college") and automatic
   rule-based schedules, with manual schedules always taking precedence.
3. Safe, indexed, zero-busy-poll sweeping with live starred re-checks, dry-run
   previews, hourly idle throttling, and audit logging (`expiry_audit_log`).

Database lives at `~/.local/state/courier/expiry.db` (respecting XDG_STATE_HOME)
so tests and demo profiles stay completely isolated from real user data.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courier_sync as sync  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_SWEEP_INTERVAL = 60 * 60  # At most once per hour when idle
DEFAULT_SWEEP_BATCH = 200
VALID_ACTIONS = ("trash", "delete")

# Built-in provider presets — ALL default to enabled=False, retention_days=7,
# notifications_only=True, skip_starred=True, action="trash".
BUILTIN_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "builtin:github",
        "provider_key": "github",
        "display_name": "GitHub",
        "retention_days": 7,
        "match_senders": [
            "notifications@github.com",
            "noreply@github.com",
            "*@notifications.github.com",
            "*@github.com",
        ],
        "match_headers": ["x-github-"],
    },
    {
        "id": "builtin:linear",
        "provider_key": "linear",
        "display_name": "Linear",
        "retention_days": 7,
        "match_senders": [
            "notifications@linear.app",
            "noreply@linear.app",
            "*@linear.app",
        ],
        "match_headers": ["x-linear-"],
    },
    {
        "id": "builtin:gitlab",
        "provider_key": "gitlab",
        "display_name": "GitLab",
        "retention_days": 7,
        "match_senders": [
            "gitlab@*",
            "noreply@gitlab.com",
            "*@mg.gitlab.com",
            "*@gitlab.com",
        ],
        "match_headers": ["x-gitlab-"],
    },
    {
        "id": "builtin:jira",
        "provider_key": "jira",
        "display_name": "Jira / Atlassian",
        "retention_days": 7,
        "match_senders": [
            "jira@*.atlassian.net",
            "noreply@am.atlassian.com",
            "notifications@atlassian.com",
            "*@*.atlassian.net",
        ],
        "match_headers": ["x-jira-", "x-atlassian-"],
    },
    {
        "id": "builtin:slack",
        "provider_key": "slack",
        "display_name": "Slack",
        "retention_days": 7,
        "match_senders": [
            "notification@slack.com",
            "notifications@slack.com",
            "feedback@slack.com",
            "no-reply@slack.com",
        ],
        "match_headers": [],
    },
    {
        "id": "builtin:vercel",
        "provider_key": "vercel",
        "display_name": "Vercel",
        "retention_days": 7,
        "match_senders": [
            "notifications@vercel.com",
            "noreply@vercel.com",
            "*@vercel.com",
        ],
        "match_headers": [],
    },
    {
        "id": "builtin:stripe",
        "provider_key": "stripe",
        "display_name": "Stripe",
        "retention_days": 7,
        "match_senders": [
            "notifications@stripe.com",
            "noreply@stripe.com",
            "*@stripe.com",
        ],
        "match_headers": [],
    },
    {
        "id": "builtin:notion",
        "provider_key": "notion",
        "display_name": "Notion",
        "retention_days": 7,
        "match_senders": [
            "notify@mail.notion.so",
            "noreply@mail.notion.so",
            "*@mail.notion.so",
        ],
        "match_headers": [],
    },
    {
        "id": "builtin:linkedin",
        "provider_key": "linkedin",
        "display_name": "LinkedIn",
        "retention_days": 7,
        "match_senders": [
            "*-noreply@linkedin.com",
            "notifications-noreply@linkedin.com",
            "messages-noreply@linkedin.com",
            "jobalerts-noreply@linkedin.com",
        ],
        "match_headers": [],
    },
]

NOTIFICATION_HEADER_PREFIXES = (
    "x-github-",
    "x-gitlab-",
    "x-jira-",
    "x-atlassian-",
    "x-linear-",
    "x-sentry-",
    "x-bitbucket-",
    "x-gitea-",
    "x-forgejo-",
    "x-circleci",
    "x-buildkite",
    "x-jenkins",
    "x-travis",
    "x-notifications",
)

NOTIFICATION_LOCAL_RE = re.compile(
    r"(?:^|[-_.+])("
    r"no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|notify|alerts?|"
    r"mailer-daemon|postmaster|bounces?|automated|bot|digest|updates?|jira|gitlab"
    r")(?:$|[-_.+])",
    re.I,
)

BULK_PRECEDENCE = {"bulk", "list", "junk", "auto_reply", "auto-reply"}

DURATION_RE = re.compile(
    r"^\s*(\d+)\s*(h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|m|mo|mos|month|months|y|yr|yrs|year|years)\s*$",
    re.I,
)
ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


class ExpiryError(Exception):
    """User-facing validation or operation error for auto-expiry."""


# Time helpers ----------------------------------------------------------------


def utc_now(now: datetime | float | int | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(float(now), tz=timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def iso_utc(moment: datetime | float | int | None = None) -> str:
    return utc_now(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(moment: datetime, months: int) -> datetime:
    import calendar

    total = (moment.year * 12 + (moment.month - 1)) + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def parse_expiry_time(
    spec: str,
    now: datetime | float | int | None = None,
    *,
    allow_past: bool = False,
) -> datetime:
    """Parse a friendly duration ('7d', '30d', '6m', '1y', '2y', '3y') or
    explicit ISO date ('YYYY-MM-DD') / ISO timestamp into UTC datetime."""
    if not spec or not isinstance(spec, str):
        raise ExpiryError("Specify a duration (like 7d, 6m, 2y) or a date (YYYY-MM-DD).")
    base = utc_now(now)
    text = spec.strip()

    dur = DURATION_RE.match(text)
    if dur:
        amount = int(dur.group(1))
        unit = dur.group(2).lower()
        if amount <= 0:
            raise ExpiryError("Duration must be greater than zero.")
        if unit.startswith("h"):
            target = base + timedelta(hours=amount)
        elif unit.startswith("d"):
            target = base + timedelta(days=amount)
        elif unit.startswith("w"):
            target = base + timedelta(weeks=amount)
        elif unit.startswith("m"):
            target = add_months(base, amount)
        elif unit.startswith("y"):
            target = add_months(base, amount * 12)
        else:
            raise ExpiryError(f"Unsupported duration unit in {spec!r}.")
        return target

    date_match = ISO_DATE_RE.match(text)
    if date_match:
        try:
            year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
            target = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            raise ExpiryError(f"Invalid date {spec!r}. Use YYYY-MM-DD.") from None
        if not allow_past and target <= base:
            raise ExpiryError("Pick a date in the future.")
        return target

    try:
        target = parse_iso_utc(text)
    except ValueError:
        raise ExpiryError(
            f"Could not parse {spec!r}. Use a duration like 7d, 30d, 6m, 2y or a date like YYYY-MM-DD."
        ) from None
    if not allow_past and target <= base:
        raise ExpiryError("Pick a date and time in the future.")
    return target


def format_remaining(expires_at: str, now: datetime | float | int | None = None) -> str:
    """Short human label for badges: '2y', '6m', '14d', '5d', '< 1d', 'Due'."""
    base = utc_now(now)
    try:
        target = parse_iso_utc(expires_at)
    except ValueError:
        return ""
    seconds = (target - base).total_seconds()
    if seconds <= 0:
        return "Due"
    days = seconds / 86400.0
    if days < 1:
        hours = max(1, int(round(seconds / 3600.0)))
        return f"{hours}h"
    if days < 45:
        return f"{max(1, int(round(days)))}d"
    if days < 345:
        months = max(1, int(round(days / 30.4375)))
        return f"{months}m"
    years = days / 365.25
    whole_years = int(years)
    rem_months = int(round((years - whole_years) * 12))
    if rem_months >= 12:
        whole_years += 1
        rem_months = 0
    if rem_months > 0 and whole_years < 3:
        return f"{whole_years}y {rem_months}m"
    return f"{max(1, round(years))}y"


# Database & migrations -------------------------------------------------------


def default_db_path() -> Path:
    override = os.environ.get("COURIER_EXPIRY_DB")
    if override:
        return Path(override)
    return sync.state_dir() / "expiry.db"


def open_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open (and migrate + seed) the auto-expiry SQLite database."""
    target = str(db_path) if db_path is not None else str(default_db_path())
    if target != ":memory:":
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA temp_store = MEMORY")
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if target == ":memory:" or user_version < SCHEMA_VERSION:
        if target != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        init_db(conn)
        if target != ":memory:":
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Idempotent schema migration & built-in provider seeding."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
        }
        now_str = iso_utc()
        if 1 not in applied:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS expiry_rules (
                    id TEXT PRIMARY KEY,
                    provider_key TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
                    retention_days INTEGER NOT NULL DEFAULT 7 CHECK (retention_days >= 1),
                    match_senders TEXT NOT NULL DEFAULT '[]',
                    match_headers TEXT NOT NULL DEFAULT '[]',
                    notifications_only INTEGER NOT NULL DEFAULT 1 CHECK (notifications_only IN (0, 1)),
                    skip_starred INTEGER NOT NULL DEFAULT 1 CHECK (skip_starred IN (0, 1)),
                    action TEXT NOT NULL DEFAULT 'trash' CHECK (action IN ('trash', 'delete')),
                    is_builtin INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS thread_expiries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT 'trash' CHECK (action IN ('trash', 'delete')),
                    subject TEXT NOT NULL DEFAULT '',
                    sender TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    executed_at TEXT,
                    cancelled_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_thread_expiries_expires_at
                    ON thread_expiries(expires_at);

                CREATE INDEX IF NOT EXISTS idx_thread_expiries_due
                    ON thread_expiries(expires_at)
                    WHERE executed_at IS NULL AND cancelled_at IS NULL;

                CREATE INDEX IF NOT EXISTS idx_thread_expiries_source_active
                    ON thread_expiries(source)
                    WHERE executed_at IS NULL AND cancelled_at IS NULL;

                CREATE TABLE IF NOT EXISTS expiry_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    action TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_expiry_audit_created_at
                    ON expiry_audit_log(created_at DESC);

                CREATE TABLE IF NOT EXISTS expiry_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, now_str),
            )
        # Seed built-in presets idempotently (never overwriting user modifications).
        for preset in BUILTIN_PROVIDERS:
            conn.execute(
                """
                INSERT OR IGNORE INTO expiry_rules (
                    id, provider_key, display_name, enabled, retention_days,
                    match_senders, match_headers, notifications_only, skip_starred,
                    action, is_builtin, created_at, updated_at
                ) VALUES (?, ?, ?, 0, ?, ?, ?, 1, 1, 'trash', 1, ?, ?)
                """,
                (
                    preset["id"],
                    preset["provider_key"],
                    preset["display_name"],
                    preset["retention_days"],
                    json.dumps(preset["match_senders"]),
                    json.dumps(preset["match_headers"]),
                    now_str,
                    now_str,
                ),
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# Serialization helpers -------------------------------------------------------


def _row_to_rule(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "provider_key": row["provider_key"],
        "display_name": row["display_name"],
        "enabled": bool(row["enabled"]),
        "retention_days": int(row["retention_days"]),
        "match_senders": json.loads(row["match_senders"] or "[]"),
        "match_headers": json.loads(row["match_headers"] or "[]"),
        "notifications_only": bool(row["notifications_only"]),
        "skip_starred": bool(row["skip_starred"]),
        "action": row["action"],
        "is_builtin": bool(row["is_builtin"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_expiry(row: sqlite3.Row, now: datetime | float | int | None = None) -> dict[str, Any]:
    source = row["source"]
    is_rule = source.startswith("rule:")
    provider_key = source.split(":", 1)[1] if is_rule else ""
    expires_at = row["expires_at"]
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "expires_at": expires_at,
        "source": source,
        "is_rule": is_rule,
        "provider_key": provider_key,
        "note": row["note"] or "",
        "action": row["action"],
        "subject": row["subject"] or "",
        "sender": row["sender"] or "",
        "remaining": format_remaining(expires_at, now),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "executed_at": row["executed_at"],
        "cancelled_at": row["cancelled_at"],
    }


# Rules CRUD ------------------------------------------------------------------


def list_rules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM expiry_rules ORDER BY is_builtin DESC, created_at ASC, display_name ASC"
    ).fetchall()
    return [_row_to_rule(r) for r in rows]


def get_rule(conn: sqlite3.Connection, rule_id_or_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM expiry_rules WHERE id = ? OR provider_key = ?",
        (rule_id_or_key, rule_id_or_key),
    ).fetchone()
    return _row_to_rule(row) if row else None


def _normalize_patterns(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items = [part.strip().lower() for part in re.split(r"[,;\n]+", raw) if part.strip()]
    elif isinstance(raw, list):
        items = [str(part).strip().lower() for part in raw if str(part).strip()]
    else:
        items = []
    # Deduplicate while preserving order
    seen: set[str] = set()
    clean: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            clean.append(item)
    return clean


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "provider"


def save_rule(conn: sqlite3.Connection, payload: dict[str, Any], now: datetime | float | int | None = None) -> dict[str, Any]:
    """Create a custom rule or update an existing built-in / custom rule."""
    if not isinstance(payload, dict):
        raise ExpiryError("Rule payload must be a JSON object.")

    now_str = iso_utc(now)
    existing: dict[str, Any] | None = None
    lookup = payload.get("id") or payload.get("provider_key")
    if lookup:
        existing = get_rule(conn, str(lookup))

    display_name = str(payload.get("display_name", existing["display_name"] if existing else "")).strip()
    if not display_name:
        raise ExpiryError("Give the provider a name.")

    try:
        retention_days = int(payload.get("retention_days", existing["retention_days"] if existing else 7))
    except (TypeError, ValueError):
        raise ExpiryError("Retention days must be a whole number.") from None
    if retention_days < 1 or retention_days > 3650:
        raise ExpiryError("Retention days must be between 1 and 3650.")

    senders_input = payload["match_senders"] if "match_senders" in payload else (existing["match_senders"] if existing else [])
    match_senders = _normalize_patterns(senders_input)
    if not match_senders:
        raise ExpiryError("Add at least one sender address or domain pattern.")

    headers_input = payload["match_headers"] if "match_headers" in payload else (existing["match_headers"] if existing else [])
    match_headers = _normalize_patterns(headers_input)

    enabled = bool(payload.get("enabled", existing["enabled"] if existing else False))
    notifications_only = bool(
        payload.get("notifications_only", existing["notifications_only"] if existing else True)
    )
    skip_starred = bool(payload.get("skip_starred", existing["skip_starred"] if existing else True))
    action = str(payload.get("action", existing["action"] if existing else "trash")).strip().lower()
    if action not in VALID_ACTIONS:
        raise ExpiryError(f"Action must be one of: {', '.join(VALID_ACTIONS)}.")

    with conn:
        if existing:
            conn.execute(
                """
                UPDATE expiry_rules
                SET display_name = ?, enabled = ?, retention_days = ?,
                    match_senders = ?, match_headers = ?, notifications_only = ?,
                    skip_starred = ?, action = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    display_name,
                    int(enabled),
                    retention_days,
                    json.dumps(match_senders),
                    json.dumps(match_headers),
                    int(notifications_only),
                    int(skip_starred),
                    action,
                    now_str,
                    existing["id"],
                ),
            )
            rule_id = existing["id"]
            provider_key = existing["provider_key"]
            # If disabled, clear unexecuted rule-scheduled expiries for this rule so
            # turning a rule OFF takes effect immediately.
            if not enabled:
                conn.execute(
                    """
                    UPDATE thread_expiries
                    SET cancelled_at = ?, updated_at = ?
                    WHERE source = ? AND executed_at IS NULL AND cancelled_at IS NULL
                    """,
                    (now_str, now_str, f"rule:{provider_key}"),
                )
        else:
            raw_key = str(payload.get("provider_key", "")).strip().lower()
            if raw_key and not raw_key.startswith("custom:"):
                raw_key = f"custom:{_slugify(raw_key)}"
            if not raw_key:
                base_slug = _slugify(display_name)
                candidate = f"custom:{base_slug}"
                suffix = 2
                while get_rule(conn, candidate) is not None:
                    candidate = f"custom:{base_slug}-{suffix}"
                    suffix += 1
                raw_key = candidate
            rule_id = str(payload.get("id") or raw_key)
            if get_rule(conn, raw_key) is not None:
                raise ExpiryError(f"A rule for {raw_key!r} already exists.")
            conn.execute(
                """
                INSERT INTO expiry_rules (
                    id, provider_key, display_name, enabled, retention_days,
                    match_senders, match_headers, notifications_only, skip_starred,
                    action, is_builtin, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    rule_id,
                    raw_key,
                    display_name,
                    int(enabled),
                    retention_days,
                    json.dumps(match_senders),
                    json.dumps(match_headers),
                    int(notifications_only),
                    int(skip_starred),
                    action,
                    now_str,
                    now_str,
                ),
            )
    saved = get_rule(conn, rule_id)
    assert saved is not None
    return saved


def delete_rule(conn: sqlite3.Connection, rule_id_or_key: str, now: datetime | float | int | None = None) -> dict[str, Any]:
    existing = get_rule(conn, rule_id_or_key)
    if existing is None:
        raise ExpiryError(f"Rule {rule_id_or_key!r} not found.")
    if existing["is_builtin"]:
        raise ExpiryError("Built-in providers cannot be deleted; turn them off instead.")
    now_str = iso_utc(now)
    with conn:
        conn.execute(
            """
            UPDATE thread_expiries
            SET cancelled_at = ?, updated_at = ?
            WHERE source = ? AND executed_at IS NULL AND cancelled_at IS NULL
            """,
            (now_str, now_str, f"rule:{existing['provider_key']}"),
        )
        conn.execute("DELETE FROM expiry_rules WHERE id = ?", (existing["id"],))
    return {"deleted": existing["id"], "provider_key": existing["provider_key"]}


# Notification classification & matching --------------------------------------


def extract_address(header_from: str) -> str:
    import email.utils

    _, addr = email.utils.parseaddr(header_from or "")
    return addr.strip().lower()


def matches_sender(sender: str, patterns: list[str]) -> bool:
    """Match an email address against sender patterns:
    - exact address: 'notifications@github.com'
    - wildcard glob: 'gitlab@*', 'jira@*.atlassian.net', '*-noreply@linkedin.com'
    - domain / @domain: 'github.com', '@github.com' (matches domain & subdomains)
    """
    addr = sender.strip().lower()
    if not addr or "@" not in addr:
        return False
    _, _, domain = addr.partition("@")
    fnmatch_fn = None
    for raw in patterns:
        pat = raw.strip().lower()
        if not pat:
            continue
        if "*" in pat or "?" in pat:
            if fnmatch_fn is None:
                import fnmatch

                fnmatch_fn = fnmatch.fnmatch
            if fnmatch_fn(addr, pat):
                return True
        elif "@" in pat:
            if pat.startswith("@"):
                dom = pat[1:]
                if domain == dom or domain.endswith("." + dom):
                    return True
            elif addr == pat:
                return True
        else:
            # Bare domain
            if domain == pat or domain.endswith("." + pat):
                return True
    return False


def is_notification(
    headers: dict[str, str],
    sender: str,
    extra_header_prefixes: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Return (is_notification, matched_signals).

    Checks standard notification/automated mail signals so personal 1-on-1
    human replies from the same domain (e.g. alice@github.com) are NOT flagged.
    """
    signals: list[str] = []
    lowered = {k.lower(): str(v).strip() for k, v in (headers or {}).items()}
    prefixes = tuple(NOTIFICATION_HEADER_PREFIXES) + tuple(
        p.lower() for p in (extra_header_prefixes or []) if p
    )

    for key in lowered:
        if any(key.startswith(prefix) for prefix in prefixes):
            signals.append(f"header:{key}")
            break

    if "list-id" in lowered and lowered["list-id"]:
        signals.append("header:list-id")

    auto_sub = lowered.get("auto-submitted", "").lower()
    if auto_sub and auto_sub != "no":
        signals.append(f"header:auto-submitted={auto_sub}")

    prec = lowered.get("precedence", "").lower()
    if prec in BULK_PRECEDENCE:
        signals.append(f"header:precedence={prec}")

    if "x-auto-response-suppress" in lowered:
        signals.append("header:x-auto-response-suppress")

    addr = sender.strip().lower()
    local = addr.partition("@")[0] if "@" in addr else addr
    if local and NOTIFICATION_LOCAL_RE.search(local):
        signals.append(f"sender:{local}")

    return (len(signals) > 0), signals


def matches_rule(rule: dict[str, Any], headers: dict[str, str], sender: str) -> bool:
    """Check whether a message with `headers` and `sender` matches `rule`."""
    addr = sender.strip().lower()
    if not matches_sender(addr, rule.get("match_senders", [])):
        return False
    if rule.get("notifications_only", True):
        is_notif, _ = is_notification(headers, addr, rule.get("match_headers") or [])
        return is_notif
    return True


# Per-thread expiry CRUD ------------------------------------------------------


def set_thread_expiry(
    conn: sqlite3.Connection,
    thread_id: str,
    *,
    after: str | None = None,
    expires_at: str | datetime | None = None,
    note: str = "",
    action: str = "trash",
    source: str = "manual",
    subject: str = "",
    sender: str = "",
    now: datetime | float | int | None = None,
    allow_past: bool = False,
) -> dict[str, Any]:
    """Create or update a scheduled deletion on `thread_id`.

    Manual schedules (`source == 'manual'`) always override any rule-based
    schedule and clear previous cancellation/execution state.
    Rule schedules (`source.startswith('rule:')`) NEVER override an active
    manual schedule.
    """
    tid = (thread_id or "").strip()
    if tid.startswith("thread:"):
        tid = tid[len("thread:"):]
    if not tid:
        raise ExpiryError("Thread ID is required.")
    action = (action or "trash").strip().lower()
    if action not in VALID_ACTIONS:
        raise ExpiryError(f"Action must be one of: {', '.join(VALID_ACTIONS)}.")
    note = (note or "").strip()[:120]

    base = utc_now(now)
    if expires_at is not None:
        target = (
            utc_now(expires_at)
            if isinstance(expires_at, datetime)
            else parse_expiry_time(str(expires_at), base, allow_past=allow_past)
        )
    elif after is not None:
        target = parse_expiry_time(after, base, allow_past=allow_past)
    else:
        raise ExpiryError("Provide either `after` (e.g. '2y') or `expires_at` (ISO date).")

    target_iso = iso_utc(target)
    now_str = iso_utc(base)

    with conn:
        existing = conn.execute(
            "SELECT * FROM thread_expiries WHERE thread_id = ?", (tid,)
        ).fetchone()
        if existing is not None:
            is_existing_active = existing["executed_at"] is None and existing["cancelled_at"] is None
            if source.startswith("rule:"):
                # NEVER override an active manual schedule!
                if existing["source"] == "manual" and is_existing_active:
                    return _row_to_expiry(existing, base)
                # Respect explicit cancellation of the same rule unless manually re-set.
                if existing["cancelled_at"] is not None and existing["source"] == source:
                    return _row_to_expiry(existing, base)
            conn.execute(
                """
                UPDATE thread_expiries
                SET expires_at = ?, source = ?, note = ?, action = ?,
                    subject = COALESCE(NULLIF(?, ''), subject),
                    sender = COALESCE(NULLIF(?, ''), sender),
                    updated_at = ?, executed_at = NULL, cancelled_at = NULL
                WHERE thread_id = ?
                """,
                (target_iso, source, note, action, subject, sender, now_str, tid),
            )
        else:
            conn.execute(
                """
                INSERT INTO thread_expiries (
                    thread_id, expires_at, source, note, action,
                    subject, sender, created_at, updated_at, executed_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (tid, target_iso, source, note, action, subject, sender, now_str, now_str),
            )
    row = conn.execute("SELECT * FROM thread_expiries WHERE thread_id = ?", (tid,)).fetchone()
    assert row is not None
    return _row_to_expiry(row, base)


def cancel_thread_expiry(
    conn: sqlite3.Connection,
    thread_id: str,
    now: datetime | float | int | None = None,
) -> dict[str, Any]:
    tid = (thread_id or "").strip()
    if tid.startswith("thread:"):
        tid = tid[len("thread:"):]
    if not tid:
        raise ExpiryError("Thread ID is required.")
    now_str = iso_utc(now)
    with conn:
        row = conn.execute("SELECT * FROM thread_expiries WHERE thread_id = ?", (tid,)).fetchone()
        if row is None:
            return {"thread_id": tid, "cancelled": False}
        conn.execute(
            """
            UPDATE thread_expiries
            SET cancelled_at = ?, updated_at = ?
            WHERE thread_id = ? AND executed_at IS NULL
            """,
            (now_str, now_str, tid),
        )
    return {"thread_id": tid, "cancelled": True, "cancelled_at": now_str}


def get_thread_expiry(
    conn: sqlite3.Connection,
    thread_id: str,
    *,
    include_inactive: bool = False,
    now: datetime | float | int | None = None,
) -> dict[str, Any] | None:
    tid = (thread_id or "").strip()
    if tid.startswith("thread:"):
        tid = tid[len("thread:"):]
    if not tid:
        return None
    if include_inactive:
        row = conn.execute("SELECT * FROM thread_expiries WHERE thread_id = ?", (tid,)).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM thread_expiries
            WHERE thread_id = ? AND executed_at IS NULL AND cancelled_at IS NULL
            """,
            (tid,),
        ).fetchone()
    return _row_to_expiry(row, now) if row else None


def list_expiries(
    conn: sqlite3.Connection,
    *,
    include_inactive: bool = False,
    source: str | None = None,
    limit: int = 500,
    now: datetime | float | int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_inactive:
        clauses.append("executed_at IS NULL AND cancelled_at IS NULL")
    if source:
        if source == "rule":
            clauses.append("source LIKE 'rule:%'")
        else:
            clauses.append("source = ?")
            params.append(source)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM thread_expiries {where} ORDER BY expires_at ASC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_expiry(r, now) for r in rows]


def active_expiries_map(
    conn: sqlite3.Connection | None = None,
    now: datetime | float | int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fast thread_id -> expiry dict for UI badges; returns {} if DB not yet created."""
    own = conn is None
    if own:
        db_file = default_db_path()
        if not db_file.exists():
            return {}
        conn = open_db(db_file)
    try:
        rows = conn.execute(
            """
            SELECT * FROM thread_expiries
            WHERE executed_at IS NULL AND cancelled_at IS NULL
            """
        ).fetchall()
        return {r["thread_id"]: _row_to_expiry(r, now) for r in rows}
    finally:
        if own and conn is not None:
            conn.close()


def list_audit_log(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM expiry_audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# Index inspection, rule matching & sync hook ---------------------------------


def _read_message_headers(message) -> dict[str, str]:
    try:
        paths = [str(p) for p in message.filenames()]
    except Exception:
        paths = [str(message.path)] if hasattr(message, "path") else []
    headers = sync.read_headers(paths)
    if not headers:
        # Fallback for mock message objects in unit tests
        for key in ("From", "Subject", "List-Id", "Auto-Submitted", "Precedence", "X-GitHub-Reason", "X-GitLab-Project", "X-Jira-FingerPrint", "X-Linear-Event"):
            try:
                val = message.header(key.lower())
                if val:
                    headers[key] = str(val)
            except (LookupError, AttributeError):
                pass
    return headers


def _sender_query_for_rule(rule: dict[str, Any]) -> str:
    """Narrow notmuch query for fast candidate lookup before full header check."""
    terms: list[str] = []
    for raw in rule.get("match_senders", []):
        pat = raw.strip().lower()
        if not pat:
            continue
        if "@" in pat:
            local, _, dom = pat.partition("@")
            dom_clean = dom.lstrip("*.")
            if dom_clean and "*" not in dom_clean and "?" not in dom_clean:
                terms.append(f'from:"{dom_clean}"')
            elif local and "*" not in local and "?" not in local:
                terms.append(f'from:"{local}"')
        else:
            clean = pat.lstrip("*.")
            if clean and "*" not in clean and "?" not in clean:
                terms.append(f'from:"{clean}"')
    # Deduplicate
    unique = list(dict.fromkeys(terms))
    base = sync.HIDDEN + " and not tag:sent"
    if not unique:
        return base
    return f"({' or '.join(unique)}) and {base}"


def _resolve_thread_messages(db, thread_id: str) -> list[Any]:
    """Return visible notmuch messages for a thread_id (or fallback message_id)."""
    tid = thread_id.strip()
    if tid.startswith("thread:"):
        tid = tid[len("thread:"):]
    if not tid:
        return []
    msgs = list(db.messages(f"thread:{tid} and {sync.HIDDEN}"))
    if msgs:
        return msgs
    try:
        msg = db.find(tid)
        # If the user passed a message_id, resolve its whole thread if visible
        tmsgs = list(db.messages(f"thread:{msg.threadid} and {sync.HIDDEN}"))
        return tmsgs or ([msg] if not ({"trash", "spam", "unsent", "draft"} & set(msg.tags)) else [])
    except LookupError:
        return []


def _group_thread_candidates(index, rule: dict[str, Any], limit: int = 2000) -> dict[str, dict[str, Any]]:
    """Scan notmuch for threads matching `rule`, returning per-thread metadata."""
    query = _sender_query_for_rule(rule)
    threads: dict[str, dict[str, Any]] = {}
    scanned = 0
    for message in index.db.messages(query):
        scanned += 1
        if scanned > limit:
            break
        tags = set(message.tags)
        if {"sent", "trash", "spam", "unsent", "draft"} & tags:
            continue
        headers = _read_message_headers(message)
        sender = extract_address(headers.get("From", ""))
        if not matches_rule(rule, headers, sender):
            continue
        tid = message.threadid
        epoch = int(message.date)
        info = threads.get(tid)
        if info is None:
            threads[tid] = {
                "thread_id": tid,
                "message_id": message.messageid,
                "subject": headers.get("Subject", "") or "(no subject)",
                "sender": sender,
                "last_message_epoch": epoch,
                "starred": "flagged" in tags,
            }
        else:
            if epoch > info["last_message_epoch"]:
                info["last_message_epoch"] = epoch
                info["message_id"] = message.messageid
                info["subject"] = headers.get("Subject", "") or info["subject"]
            if "flagged" in tags:
                info["starred"] = True
    # Also check if any OTHER message in the thread is starred or newer (single query per thread).
    for tid, info in threads.items():
        for msg in index.db.messages(f"thread:{tid} and {sync.HIDDEN}"):
            epoch = int(msg.date)
            if epoch > info["last_message_epoch"]:
                info["last_message_epoch"] = epoch
            if not info["starred"] and "flagged" in set(msg.tags):
                info["starred"] = True
    return threads


def preview_rule(
    conn: sqlite3.Connection,
    index,
    rule_id_or_key: str,
    now: datetime | float | int | None = None,
    *,
    sample_limit: int = 10,
    rule: dict[str, Any] | None = None,
    active_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Dry-run preview of a single rule: how many threads match and when they expire."""
    rule = rule if rule is not None else get_rule(conn, rule_id_or_key)
    if rule is None:
        raise ExpiryError(f"Rule {rule_id_or_key!r} not found.")
    base = utc_now(now)
    candidates = _group_thread_candidates(index, rule)
    if active_map is None:
        active_map = active_expiries_map(conn, base)

    matched: list[dict[str, Any]] = []
    skipped_starred = 0
    skipped_manual = 0
    due_now_count = 0

    for tid, info in sorted(candidates.items(), key=lambda kv: -kv[1]["last_message_epoch"]):
        if rule["skip_starred"] and info["starred"]:
            skipped_starred += 1
            continue
        existing = active_map.get(tid)
        if existing and existing["source"] == "manual":
            skipped_manual += 1
            continue
        last_dt = utc_now(info["last_message_epoch"])
        exp_dt = last_dt + timedelta(days=rule["retention_days"])
        is_due = exp_dt <= base
        if is_due:
            due_now_count += 1
        matched.append(
            {
                "thread_id": tid,
                "message_id": info["message_id"],
                "subject": info["subject"],
                "sender": info["sender"],
                "last_message_at": iso_utc(last_dt),
                "expires_at": iso_utc(exp_dt),
                "remaining": format_remaining(iso_utc(exp_dt), base),
                "due_now": is_due,
            }
        )

    return {
        "rule": rule,
        "match_count": len(matched),
        "due_now_count": due_now_count,
        "skipped_starred": skipped_starred,
        "skipped_manual": skipped_manual,
        "sample": matched[:sample_limit],
    }


def apply_rule_to_existing(
    conn: sqlite3.Connection,
    index,
    rule_id_or_key: str,
    now: datetime | float | int | None = None,
) -> dict[str, Any]:
    """Schedule existing matching threads when a rule is enabled or updated."""
    rule = get_rule(conn, rule_id_or_key)
    if rule is None:
        raise ExpiryError(f"Rule {rule_id_or_key!r} not found.")
    if not rule["enabled"]:
        return {"rule_id": rule["id"], "scheduled": 0, "skipped_starred": 0, "skipped_manual": 0}
    base = utc_now(now)
    candidates = _group_thread_candidates(index, rule)
    source = f"rule:{rule['provider_key']}"
    scheduled = 0
    skipped_starred = 0
    skipped_manual = 0
    active_map = active_expiries_map(conn, base)

    for tid, info in candidates.items():
        if rule["skip_starred"] and info["starred"]:
            skipped_starred += 1
            continue
        existing = active_map.get(tid)
        if existing and existing["source"] == "manual":
            skipped_manual += 1
            continue
        exp_dt = utc_now(info["last_message_epoch"]) + timedelta(days=rule["retention_days"])
        before = conn.execute("SELECT cancelled_at, source FROM thread_expiries WHERE thread_id = ?", (tid,)).fetchone()
        if before is not None and before["cancelled_at"] is not None and before["source"] == source:
            continue
        set_thread_expiry(
            conn,
            tid,
            expires_at=exp_dt,
            source=source,
            action=rule["action"],
            subject=info["subject"],
            sender=info["sender"],
            now=base,
            allow_past=True,
        )
        scheduled += 1
    return {
        "rule_id": rule["id"],
        "scheduled": scheduled,
        "skipped_starred": skipped_starred,
        "skipped_manual": skipped_manual,
    }


def apply_rules_for_messages(
    db,
    message_ids: list[str],
    conn: sqlite3.Connection | None = None,
    now: datetime | float | int | None = None,
) -> dict[str, int]:
    """Apply enabled provider rules to newly synced messages.

    Calculates `expires_at = last_message_at + retention_days` per thread.
    Never overrides an explicit `manual` schedule. Short-circuits in O(1)
    when no rules are enabled.
    """
    if not message_ids:
        return {"checked": 0, "scheduled": 0}
    own = conn is None
    if own:
        db_file = default_db_path()
        if not db_file.exists():
            # Built-in rules all default to OFF; if DB doesn't exist yet,
            # zero rules are enabled -> instant no-op!
            return {"checked": 0, "scheduled": 0}
        conn = open_db(db_file)
    try:
        enabled_rules = [r for r in list_rules(conn) if r["enabled"]]
        if not enabled_rules:
            return {"checked": 0, "scheduled": 0}

        base = utc_now(now)
        active_map = active_expiries_map(conn, base)
        scheduled = 0
        checked = 0
        seen_threads: set[str] = set()

        for msg_id in message_ids:
            try:
                message = db.find(msg_id)
            except LookupError:
                continue
            checked += 1
            tags = set(message.tags)
            if {"sent", "trash", "spam", "unsent", "draft"} & tags:
                continue
            tid = message.threadid
            if tid in seen_threads:
                continue
            existing = active_map.get(tid)
            if existing and existing["source"] == "manual":
                seen_threads.add(tid)
                continue

            headers = _read_message_headers(message)
            sender = extract_address(headers.get("From", ""))
            matched_rules = [r for r in enabled_rules if matches_rule(r, headers, sender)]
            if not matched_rules:
                continue

            # Check thread-level starred & latest message timestamp
            thread_msgs = list(db.messages(f"thread:{tid} and {sync.HIDDEN}"))
            if not thread_msgs:
                thread_msgs = [message]
            thread_starred = any("flagged" in set(m.tags) for m in thread_msgs)
            last_epoch = max(int(m.date) for m in thread_msgs)
            # Pick safest matching rule (longest retention if multiple match)
            chosen = max(matched_rules, key=lambda r: r["retention_days"])
            if chosen["skip_starred"] and thread_starred:
                seen_threads.add(tid)
                continue

            exp_dt = utc_now(last_epoch) + timedelta(days=chosen["retention_days"])
            source = f"rule:{chosen['provider_key']}"
            row_before = conn.execute(
                "SELECT cancelled_at, source FROM thread_expiries WHERE thread_id = ?", (tid,)
            ).fetchone()
            if row_before is not None and row_before["cancelled_at"] is not None and row_before["source"] == source:
                seen_threads.add(tid)
                continue

            set_thread_expiry(
                conn,
                tid,
                expires_at=exp_dt,
                source=source,
                action=chosen["action"],
                subject=headers.get("Subject", "") or "(no subject)",
                sender=sender,
                now=base,
                allow_past=True,
            )
            seen_threads.add(tid)
            scheduled += 1

        return {"checked": checked, "scheduled": scheduled}
    finally:
        if own and conn is not None:
            conn.close()


# Preview due & Safe Sweeper --------------------------------------------------


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM expiry_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO expiry_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _log_audit(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    source: str,
    action: str,
    message_count: int = 0,
    note: str = "",
    detail: str = "",
    now_str: str,
) -> None:
    conn.execute(
        """
        INSERT INTO expiry_audit_log (
            thread_id, source, action, message_count, note, detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (thread_id, source, action, message_count, note, detail, now_str),
    )


def preview_due(
    conn: sqlite3.Connection,
    index=None,
    now: datetime | float | int | None = None,
    *,
    batch_limit: int = DEFAULT_SWEEP_BATCH,
) -> dict[str, Any]:
    """Dry-run of all due expiries without deleting anything."""
    return sweep_due(
        conn,
        act=None,
        open_index=(lambda: index) if index is not None else None,
        dry_run=True,
        now=now,
        force=True,
        batch_limit=batch_limit,
        _close_index=False,
    )


def sweep_due(
    conn: sqlite3.Connection,
    act: Callable[[str, list[str]], Any] | None,
    open_index: Callable[[], Any] | None = None,
    *,
    dry_run: bool = False,
    now: datetime | float | int | None = None,
    force: bool = False,
    min_interval_seconds: int = DEFAULT_SWEEP_INTERVAL,
    batch_limit: int = DEFAULT_SWEEP_BATCH,
    _close_index: bool = True,
) -> dict[str, Any]:
    """Execute (or dry-run) due thread expiries safely.

    Performance:
    - Single indexed SQLite query using `idx_thread_expiries_due`.
    - When `force=False` and `not dry_run`, throttles to at most once per
      `min_interval_seconds` (1 hour default) so idle background ticks burn ~0 CPU.
    - Does not open the notmuch index if zero items are due.

    Safety:
    - Re-checks `skip_starred` right before executing rule-based expiries.
      If the user starred the thread after scheduling, skips deletion, cancels
      the rule expiry, and writes a `skipped_starred` audit entry.
    - Uses `trash` by default (recoverable in Gmail).
    - Records `executed_at` + `expiry_audit_log` entry for every action.
    """
    base = utc_now(now)
    now_str = iso_utc(base)

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "checked_at": now_str,
        "due_count": 0,
        "executed_count": 0,
        "trashed_messages": 0,
        "skipped_starred": 0,
        "skipped_missing": 0,
        "skipped_disabled": 0,
        "throttled": False,
        "items": [],
        "problems": [],
    }

    if not dry_run and not force and min_interval_seconds > 0:
        last = _get_meta(conn, "last_sweep_at")
        if last:
            try:
                elapsed = (base - parse_iso_utc(last)).total_seconds()
                if 0 <= elapsed < min_interval_seconds:
                    report["throttled"] = True
                    return report
            except ValueError:
                pass

    due_rows = conn.execute(
        """
        SELECT * FROM thread_expiries
        WHERE expires_at <= ? AND executed_at IS NULL AND cancelled_at IS NULL
        ORDER BY expires_at ASC
        LIMIT ?
        """,
        (now_str, batch_limit),
    ).fetchall()

    report["due_count"] = len(due_rows)
    if not due_rows:
        if not dry_run:
            with conn:
                _set_meta(conn, "last_sweep_at", now_str)
        return report

    rules_by_key = {r["provider_key"]: r for r in list_rules(conn)}
    index = open_index() if open_index is not None else None

    try:
        for row in due_rows:
            entry = _row_to_expiry(row, base)
            tid = entry["thread_id"]
            source = entry["source"]
            is_rule = entry["is_rule"]
            rule = rules_by_key.get(entry["provider_key"]) if is_rule else None

            # Defensive: if a rule was disabled or deleted, don't execute its entries
            if is_rule and (rule is None or not rule["enabled"]):
                report["skipped_disabled"] += 1
                item_summary = {**entry, "status": "skipped_disabled", "message_count": 0}
                report["items"].append(item_summary)
                if not dry_run:
                    with conn:
                        conn.execute(
                            "UPDATE thread_expiries SET cancelled_at = ?, updated_at = ? WHERE thread_id = ?",
                            (now_str, now_str, tid),
                        )
                        _log_audit(
                            conn,
                            thread_id=tid,
                            source=source,
                            action="skipped_disabled",
                            note=entry["note"],
                            detail="Rule is disabled or removed",
                            now_str=now_str,
                        )
                continue

            # Resolve messages in notmuch (if index available)
            msg_ids: list[str] = []
            starred = False
            if index is not None:
                msgs = _resolve_thread_messages(index.db, tid)
                if not msgs:
                    report["skipped_missing"] += 1
                    report["items"].append({**entry, "status": "skipped_missing", "message_count": 0})
                    if not dry_run:
                        with conn:
                            conn.execute(
                                "UPDATE thread_expiries SET executed_at = ?, updated_at = ? WHERE thread_id = ?",
                                (now_str, now_str, tid),
                            )
                            _log_audit(
                                conn,
                                thread_id=tid,
                                source=source,
                                action="skipped_missing",
                                note=entry["note"],
                                detail="No visible messages remaining in thread",
                                now_str=now_str,
                            )
                    continue
                starred = any("flagged" in set(m.tags) for m in msgs)
                msg_ids = [m.messageid for m in msgs]
            else:
                msg_ids = [tid]

            # Re-check skip_starred right before executing rule-based expiries
            if is_rule and (rule["skip_starred"] if rule else True) and starred:
                report["skipped_starred"] += 1
                report["items"].append({**entry, "status": "skipped_starred", "message_count": len(msg_ids)})
                if not dry_run:
                    with conn:
                        conn.execute(
                            "UPDATE thread_expiries SET cancelled_at = ?, updated_at = ? WHERE thread_id = ?",
                            (now_str, now_str, tid),
                        )
                        _log_audit(
                            conn,
                            thread_id=tid,
                            source=source,
                            action="skipped_starred",
                            message_count=len(msg_ids),
                            note=entry["note"],
                            detail="Thread was starred; protected from rule auto-expiry",
                            now_str=now_str,
                        )
                continue

            action = entry["action"] if entry["action"] in VALID_ACTIONS else "trash"
            if dry_run:
                report["items"].append(
                    {
                        **entry,
                        "status": "would_execute",
                        "message_count": len(msg_ids),
                        "message_ids": msg_ids,
                    }
                )
                continue

            if act is None:
                raise ExpiryError("An action callback is required to execute expiries.")

            try:
                act(action, msg_ids)
            except Exception as err:  # noqa: BLE001
                report["problems"].append(f"{tid}: {err}")
                with conn:
                    _log_audit(
                        conn,
                        thread_id=tid,
                        source=source,
                        action="error",
                        message_count=len(msg_ids),
                        note=entry["note"],
                        detail=str(err),
                        now_str=now_str,
                    )
                continue

            with conn:
                conn.execute(
                    "UPDATE thread_expiries SET executed_at = ?, updated_at = ? WHERE thread_id = ?",
                    (now_str, now_str, tid),
                )
                _log_audit(
                    conn,
                    thread_id=tid,
                    source=source,
                    action=action,
                    message_count=len(msg_ids),
                    note=entry["note"],
                    detail=f"Executed {action} on {len(msg_ids)} message(s)",
                    now_str=now_str,
                )
            report["executed_count"] += 1
            report["trashed_messages"] += len(msg_ids)
            report["items"].append(
                {**entry, "status": "executed", "message_count": len(msg_ids)}
            )

        if not dry_run:
            with conn:
                _set_meta(conn, "last_sweep_at", now_str)
    finally:
        if index is not None and _close_index:
            index.close()

    return report


# Sync hook wrapper -----------------------------------------------------------


def after_sync(message_ids: list[str], now: datetime | float | int | None = None) -> dict[str, int]:
    """Called by courier_sync.index() after indexing newly arrived mail."""
    if not message_ids:
        return {"checked": 0, "scheduled": 0}
    db_file = default_db_path()
    if not db_file.exists():
        return {"checked": 0, "scheduled": 0}
    import notmuch2

    conn = open_db(db_file)
    try:
        if not any(r["enabled"] for r in list_rules(conn)):
            return {"checked": 0, "scheduled": 0}
        with notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY) as db:
            return apply_rules_for_messages(db, message_ids, conn=conn, now=now)
    finally:
        conn.close()


# CLI -------------------------------------------------------------------------


def _try_open_mail_index():
    try:
        import courier_mail

        return courier_mail.Index()
    except Exception:
        return None


def _resolve_canonical_thread(index, thread_or_msg_id: str) -> tuple[str, str, str]:
    """Return (canonical_thread_id, subject, sender) if found in notmuch."""
    tid = thread_or_msg_id.strip()
    if tid.startswith("thread:"):
        tid = tid[len("thread:"):]
    if index is None:
        return tid, "", ""
    msgs = _resolve_thread_messages(index.db, tid)
    if not msgs:
        return tid, "", ""
    latest = max(msgs, key=lambda m: int(m.date))
    headers = _read_message_headers(latest)
    return latest.threadid, headers.get("Subject", "") or "(no subject)", extract_address(headers.get("From", ""))


def build_parser(prog: str = "courier expiry"):
    import argparse

    parser = argparse.ArgumentParser(prog=prog, description="Junco Mail auto-expiry rules & scheduled deletions.")
    parser.add_argument("--db", default="", help="Override SQLite DB path (for testing)")
    sub = parser.add_subparsers(dest="expiry_command", required=True)

    p_rules = sub.add_parser("rules", help="List provider auto-expiry rules (with optional live match counts)")
    p_rules.add_argument("--with-counts", action="store_true", help="Include live thread match counts from the mail index")

    p_save = sub.add_parser("rule-save", help="Add or update an expiry rule from JSON or flags")
    p_save.add_argument("json", nargs="?", default="", help="Rule JSON object")
    p_save.add_argument("--id", dest="rule_id", default="")
    p_save.add_argument("--provider", dest="provider_key", default="")
    p_save.add_argument("--name", dest="display_name", default="")
    p_save.add_argument("--days", dest="retention_days", type=int, default=None)
    p_save.add_argument("--senders", default="", help="Comma-separated sender patterns/domains")
    p_save.add_argument("--enable", action="store_true")
    p_save.add_argument("--disable", action="store_true")
    p_save.add_argument("--notifications-only", dest="notifications_only", choices=["true", "false"], default="")
    p_save.add_argument("--skip-starred", dest="skip_starred", choices=["true", "false"], default="")
    p_save.add_argument("--action", choices=list(VALID_ACTIONS), default="")
    p_save.add_argument("--no-apply", action="store_true", help="Do not scan existing threads after enabling")

    p_del = sub.add_parser("rule-delete", help="Delete a custom provider rule")
    p_del.add_argument("id")

    p_prev = sub.add_parser("preview", help="Preview threads matching a rule (dry-run)")
    p_prev.add_argument("rule_id")

    p_list = sub.add_parser("list", help="List scheduled thread deletions")
    p_list.add_argument("--all", dest="include_inactive", action="store_true", help="Include executed/cancelled items")
    p_list.add_argument("--source", default="", help="Filter by source: manual, rule, or rule:<provider>")

    p_set = sub.add_parser("set", help="Schedule a thread (or message) for future deletion")
    p_set.add_argument("thread_id", help="Notmuch thread ID or Message-ID")
    p_set.add_argument("--after", default="", help="Friendly duration: 7d, 14d, 30d, 6m, 1y, 2y, 3y")
    p_set.add_argument("--on", "--date", dest="on_date", default="", help="Explicit date YYYY-MM-DD or ISO timestamp")
    p_set.add_argument("--note", default="", help="Short label (e.g. 'college')")
    p_set.add_argument("--action", choices=list(VALID_ACTIONS), default="trash")
    p_set.add_argument("--subject", default="")
    p_set.add_argument("--sender", default="")

    p_cancel = sub.add_parser("cancel", help="Cancel a scheduled deletion for a thread")
    p_cancel.add_argument("thread_id")

    p_run = sub.add_parser("run", help="Run the expiry sweeper (or preview with --dry-run)")
    p_run.add_argument("--dry-run", action="store_true", help="Report what would expire without deleting")
    p_run.add_argument("--force", action="store_true", help="Bypass the 1-hour idle throttle")

    p_audit = sub.add_parser("audit", help="Show recent expiry audit log entries")
    p_audit.add_argument("--limit", type=int, default=50)

    return parser


def run_cli(argv: list[str] | None = None, prog: str = "courier expiry") -> int:
    parser = build_parser(prog=prog)
    args = parser.parse_args(argv)
    db_path = Path(args.db) if args.db else None
    conn = open_db(db_path)
    try:
        cmd = args.expiry_command
        if cmd == "rules":
            items = list_rules(conn)
            if args.with_counts:
                index = _try_open_mail_index()
                if index is not None:
                    try:
                        base = utc_now()
                        shared_active = active_expiries_map(conn, base)
                        for item in items:
                            prev = preview_rule(conn, index, item["id"], base, rule=item, active_map=shared_active)
                            item["match_count"] = prev["match_count"]
                            item["due_now_count"] = prev["due_now_count"]
                            item["skipped_starred"] = prev["skipped_starred"]
                    finally:
                        index.close()
            result: Any = {"rules": items}

        elif cmd == "rule-save":
            payload: dict[str, Any] = json.loads(args.json) if args.json else {}
            if args.rule_id:
                payload["id"] = args.rule_id
            if args.provider_key:
                payload["provider_key"] = args.provider_key
            if args.display_name:
                payload["display_name"] = args.display_name
            if args.retention_days is not None:
                payload["retention_days"] = args.retention_days
            if args.senders:
                payload["match_senders"] = _normalize_patterns(args.senders)
            if args.enable:
                payload["enabled"] = True
            elif args.disable:
                payload["enabled"] = False
            if args.notifications_only:
                payload["notifications_only"] = args.notifications_only == "true"
            if args.skip_starred:
                payload["skip_starred"] = args.skip_starred == "true"
            if args.action:
                payload["action"] = args.action
            saved = save_rule(conn, payload)
            applied_info = None
            if saved["enabled"] and not args.no_apply:
                index = _try_open_mail_index()
                if index is not None:
                    try:
                        applied_info = apply_rule_to_existing(conn, index, saved["id"])
                        prev = preview_rule(conn, index, saved["id"])
                        saved["match_count"] = prev["match_count"]
                        saved["due_now_count"] = prev["due_now_count"]
                    finally:
                        index.close()
            result = {"rule": saved}
            if applied_info is not None:
                result["applied"] = applied_info

        elif cmd == "rule-delete":
            result = delete_rule(conn, args.id)

        elif cmd == "preview":
            index = _try_open_mail_index()
            if index is None:
                raise ExpiryError("Mail index is not available.")
            try:
                result = preview_rule(conn, index, args.rule_id)
            finally:
                index.close()

        elif cmd == "list":
            result = {
                "items": list_expiries(
                    conn,
                    include_inactive=args.include_inactive,
                    source=args.source or None,
                )
            }

        elif cmd == "set":
            if not args.after and not args.on_date:
                raise ExpiryError("Specify --after (e.g. 2y, 30d) or --on (YYYY-MM-DD).")
            tid = args.thread_id
            subj, sndr = args.subject, args.sender
            index = _try_open_mail_index()
            if index is not None:
                try:
                    resolved_tid, found_subj, found_sndr = _resolve_canonical_thread(index, tid)
                    tid = resolved_tid
                    subj = subj or found_subj
                    sndr = sndr or found_sndr
                finally:
                    index.close()
            result = set_thread_expiry(
                conn,
                tid,
                after=args.after or None,
                expires_at=args.on_date or None,
                note=args.note,
                action=args.action,
                subject=subj,
                sender=sndr,
            )

        elif cmd == "cancel":
            tid = args.thread_id
            index = _try_open_mail_index()
            if index is not None:
                try:
                    if get_thread_expiry(conn, tid) is None:
                        resolved_tid, _, _ = _resolve_canonical_thread(index, tid)
                        tid = resolved_tid
                finally:
                    index.close()
            result = cancel_thread_expiry(conn, tid)

        elif cmd == "run":
            import courier_mail

            act_fn = None if args.dry_run else (lambda action, ids: courier_mail.act(action, ids))
            open_idx = _try_open_mail_index
            result = sweep_due(
                conn,
                act_fn,
                open_index=open_idx,
                dry_run=args.dry_run,
                force=args.force or args.dry_run,
            )

        elif cmd == "audit":
            result = {"entries": list_audit_log(conn, limit=args.limit)}
        else:
            raise ExpiryError(f"Unknown command {cmd!r}")

        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    except (ExpiryError, ValueError) as err:
        print(json.dumps({"error": str(err)}))
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(run_cli())
