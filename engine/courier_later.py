"""Things Courier does later, on its own clock: snoozed emails coming back,
reminders, scheduled sends, emails set to delete themselves, and the
automation rules (auto-archive, auto-delete, move to a label).

Gmail has no snooze, reminders or retention over IMAP, so Courier keeps them
in small JSON files in ~/.local/state/courier and `courier-mail tick` (run
every minute by courier-tick.timer) does whatever is due. Every change to
Gmail goes through courier_mail.act, the same path the app's buttons use.
"""

from __future__ import annotations

import email
import email.policy
import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import courier_sync as sync

# How long a rule may run per tick, in emails, so a new rule over years of
# mail works through it in steps instead of one enormous Gmail command.
RULE_BATCH = 300
# Rules run at most this often.
RULE_EVERY = 60 * 60
# Retention periods the app offers, in days.
PERIODS = {"1w": 7, "1m": 30, "6m": 182, "1y": 365, "5y": 5 * 365}
PERIOD_NAMES = {"1w": "1 week", "1m": "1 month", "6m": "6 months", "1y": "1 year", "5y": "5 years"}
RULE_KINDS = {"archive", "delete", "move"}
RULE_CATEGORIES = {"", "people", "updates", "newsletters", "dev", "college", "meeting"}


class LaterError(Exception):
    pass


# Files ----------------------------------------------------------------------------


def path(name: str) -> Path:
    return sync.state_dir() / name


def load(name: str, default):
    try:
        return json.loads(path(name).read_text())
    except (FileNotFoundError, ValueError):
        return default


def save(name: str, data) -> None:
    sync.write_private(path(name), json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def notify(title: str, body: str, icon: str = "mail-message-new") -> None:
    sync.desktop_notify(title, body, "-a", "Junco", "-i", icon)


def moment(value: str) -> float:
    """An ISO date-time ("2026-11-22T09:00") as epoch seconds, local time."""
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        raise LaterError(f"“{value}” isn't a date and time.") from None


# Snooze ---------------------------------------------------------------------------


def snoozed() -> list[dict]:
    return load("snoozed.json", {"items": []})["items"]


def snooze(act, ids: list[str], until: str, subject: str = "") -> dict:
    """Archives now; brings the emails back to the inbox at `until`."""
    when = moment(until)
    if when <= time.time():
        raise LaterError("Pick a time in the future.")
    act("archive", ids)
    kept = [item for item in snoozed() if item["id"] not in ids]
    kept += [{"id": message_id, "until": when, "subject": subject} for message_id in ids]
    save("snoozed.json", {"items": kept})
    return {"snoozed": ids, "until": when}


def unsnooze(act, ids: list[str]) -> dict:
    act("inbox", ids)
    save("snoozed.json", {"items": [item for item in snoozed() if item["id"] not in ids]})
    return {"unsnoozed": ids}


# Reminders ------------------------------------------------------------------------


def reminders() -> list[dict]:
    return load("reminders.json", {"items": []})["items"]


def remind(message_id: str, at: str, subject: str) -> dict:
    when = moment(at)
    if when <= time.time():
        raise LaterError("Pick a time in the future.")
    kept = [item for item in reminders() if item["id"] != message_id]
    kept.append({"id": message_id, "at": when, "subject": subject})
    save("reminders.json", {"items": sorted(kept, key=lambda item: item["at"])})
    return {"id": message_id, "at": when}


def unremind(message_id: str) -> dict:
    save("reminders.json", {"items": [item for item in reminders() if item["id"] != message_id]})
    return {"id": message_id}


# Scheduled sending ----------------------------------------------------------------


def scheduled() -> list[dict]:
    return load("scheduled.json", {"items": []})["items"]


def schedule(account: str, message: email.message.EmailMessage, at: str) -> dict:
    when = moment(at)
    if when <= time.time() + 30:
        raise LaterError("Pick a time at least a minute from now.")
    folder = path("scheduled")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}.eml"
    sync.write_private(folder / name, message.as_bytes(policy=email.policy.SMTP).decode("utf-8", "replace"))
    item = {"file": name, "at": when, "account": account, "to": message.get("To", "") or message.get("Bcc", ""), "subject": message.get("Subject", "")}
    save("scheduled.json", {"items": sorted(scheduled() + [item], key=lambda entry: entry["at"])})
    return item


def unschedule(name: str) -> dict:
    items = scheduled()
    if not any(item["file"] == name for item in items):
        raise LaterError("That scheduled email is gone; it may have been sent already.")
    save("scheduled.json", {"items": [item for item in items if item["file"] != name]})
    (path("scheduled") / Path(name).name).unlink(missing_ok=True)
    return {"cancelled": name}


def send_scheduled(item: dict) -> None:
    file = path("scheduled") / Path(item["file"]).name
    result = subprocess.run(
        ["msmtp", "-C", str(sync.config_dir() / "msmtprc"), "-a", item["account"], "-t"], input=file.read_bytes(), capture_output=True
    )
    if result.returncode != 0:
        raise LaterError(result.stderr.decode("utf-8", "replace").strip() or "msmtp failed")
    file.unlink(missing_ok=True)


def send_now(name: str) -> dict:
    item = next((item for item in scheduled() if item["file"] == name), None)
    if item is None:
        raise LaterError("That scheduled email is gone; it may have been sent already.")
    send_scheduled(item)
    save("scheduled.json", {"items": [entry for entry in scheduled() if entry["file"] != name]})
    return {"sent": name}


# Retention ------------------------------------------------------------------------


def retention() -> dict:
    return load("retention.json", {"emails": {}})["emails"]


def set_retention(message_id: str, period: str, subject: str = "") -> dict:
    """Keep this email for `period` from now, then delete it; "" keeps it."""
    emails = retention()
    if not period:
        emails.pop(message_id, None)
        save("retention.json", {"emails": emails})
        return {"id": message_id, "period": ""}
    if period not in PERIODS:
        raise LaterError(f"Unknown period {period!r}.")
    until = time.time() + PERIODS[period] * 86400
    emails[message_id] = {"period": period, "until": until, "subject": subject}
    save("retention.json", {"emails": emails})
    return {"id": message_id, "period": period, "until": until}


# Rules ----------------------------------------------------------------------------


def rules() -> list[dict]:
    return load("rules.json", {"rules": []})["rules"]


def checked_rule(rule: dict) -> dict:
    kind = rule.get("kind", "")
    if kind not in RULE_KINDS:
        raise LaterError("A rule archives, deletes or moves.")
    category = rule.get("category", "")
    if category not in RULE_CATEGORIES:
        raise LaterError(f"Unknown category {category!r}.")
    sender, subject = str(rule.get("from", "")).strip(), str(rule.get("subject", "")).strip()
    if not (category or sender or subject):
        # Never a rule over all mail.
        raise LaterError("Say which emails: a category, a sender or words in the subject.")
    days = int(rule.get("afterDays", 0))
    if days < 0 or (kind == "delete" and days < 1):
        raise LaterError("Deleting needs at least a day's wait.")
    label = str(rule.get("label", "")).strip()
    if kind == "move" and not label:
        raise LaterError("Pick a label to move them to.")
    return {
        "id": rule.get("id") or f"rule-{int(time.time() * 1000)}",
        "kind": kind,
        "enabled": bool(rule.get("enabled", False)),
        "category": category,
        "from": sender,
        "subject": subject,
        "afterDays": days,
        "label": label,
    }


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def rule_query(rule: dict, now: float | None = None) -> str:
    """The notmuch query for what a rule acts on right now."""
    parts = []
    if rule["category"]:
        parts.append(f"tag:{rule['category']}")
    if rule["from"]:
        parts.append(f"from:{quoted(rule['from'])}")
    if rule["subject"]:
        parts.append(f"subject:{quoted(rule['subject'])}")
    if rule["kind"] in {"archive", "move"}:
        parts.append("tag:inbox")
    if rule["afterDays"] > 0:
        cutoff = int((now or time.time()) - rule["afterDays"] * 86400)
        parts.append(f"date:..@{cutoff}")
    # Never your starred mail, mail you sent, or a draft (deleting one would
    # delete it in Gmail).
    parts.append("not tag:flagged and not tag:sent and not tag:unsent and not tag:draft")
    return " and ".join(parts)


def describe(rule: dict) -> str:
    what = {"people": "mail from people", "updates": "updates", "newsletters": "newsletters", "dev": "dev updates",
            "college": "college mail", "meeting": "meeting invites", "": "emails"}[rule["category"]]
    if rule["from"]:
        what += f" from {rule['from']}"
    if rule["subject"]:
        what += f" with “{rule['subject']}” in the subject"
    verb = {"archive": "Archive", "delete": "Delete", "move": f"Move to {rule['label']}"}[rule["kind"]]
    wait = f" after {rule['afterDays']} day{'s' if rule['afterDays'] != 1 else ''}" if rule["afterDays"] else ""
    return f"{verb} {what}{wait}"


def save_rule(rule: dict) -> dict:
    checked = checked_rule(rule)
    kept = [existing for existing in rules() if existing["id"] != checked["id"]]
    position = next((n for n, existing in enumerate(rules()) if existing["id"] == checked["id"]), len(kept))
    kept.insert(position, checked)
    save("rules.json", {"rules": kept, "lastRun": load("rules.json", {}).get("lastRun", 0)})
    return checked


def delete_rule(rule_id: str) -> dict:
    save("rules.json", {"rules": [rule for rule in rules() if rule["id"] != rule_id], "lastRun": load("rules.json", {}).get("lastRun", 0)})
    return {"deleted": rule_id}


def matching(index, query: str, limit: int | None = None) -> list[str]:
    found = []
    for message in index.newest_first(query):
        found.append(message.messageid)
        if limit and len(found) >= limit:
            break
    return found


def rule_count(index, rule: dict) -> int:
    return index.db.count_messages(f"({rule_query(rule)}) and {sync.HIDDEN}")


# The clock ------------------------------------------------------------------------


def due(now: float) -> dict:
    return {
        "snoozed": [item for item in snoozed() if item["until"] <= now],
        "reminders": [item for item in reminders() if item["at"] <= now],
        "scheduled": [item for item in scheduled() if item["at"] <= now],
        "retention": [(message_id, item) for message_id, item in retention().items() if item["until"] <= now],
    }


def tick(act, open_index, now: float | None = None) -> dict:
    """Does everything that has come due. `act(action, ids)` changes Gmail;
    `open_index()` opens the mail index for the rules."""
    now = now or time.time()
    report = {"woke": 0, "reminded": 0, "sent": 0, "deleted": 0, "ruled": 0, "problems": []}
    work = due(now)

    if work["snoozed"]:
        ids = [item["id"] for item in work["snoozed"]]
        try:
            act("inbox", ids)
            save("snoozed.json", {"items": [item for item in snoozed() if item["id"] not in ids]})
            report["woke"] = len(ids)
            names = [item["subject"] or "An email" for item in work["snoozed"]]
            notify("Back in your inbox", names[0] if len(names) == 1 else f"{len(names)} snoozed emails", "mail-unread")
        except Exception as error:  # Gmail unreachable: try again next minute.
            report["problems"].append(f"snooze: {error}")

    for item in work["reminders"]:
        notify("Reminder", item["subject"] or "An email you asked about", "appointment-soon")
        report["reminded"] += 1
    if work["reminders"]:
        done = {item["id"] for item in work["reminders"]}
        save("reminders.json", {"items": [item for item in reminders() if item["id"] not in done]})

    for item in work["scheduled"]:
        try:
            send_scheduled(item)
            save("scheduled.json", {"items": [entry for entry in scheduled() if entry["file"] != item["file"]]})
            report["sent"] += 1
            notify("Sent", item["subject"] or "Your scheduled email", "mail-send")
        except Exception as error:
            report["problems"].append(f"send: {error}")

    if work["retention"]:
        ids = [message_id for message_id, _ in work["retention"]]
        try:
            act("trash", ids)
            emails = retention()
            for message_id in ids:
                emails.pop(message_id, None)
            save("retention.json", {"emails": emails})
            report["deleted"] = len(ids)
        except Exception as error:
            report["problems"].append(f"retention: {error}")

    state = load("rules.json", {"rules": [], "lastRun": 0})
    if any(rule["enabled"] for rule in state["rules"]) and now - state.get("lastRun", 0) >= RULE_EVERY:
        index = open_index()
        try:
            batches = [(rule, matching(index, rule_query(rule, now), RULE_BATCH)) for rule in state["rules"] if rule["enabled"]]
        finally:
            index.close()
        for rule, ids in batches:
            if not ids:
                continue
            action = {"archive": "archive", "delete": "trash", "move": "move"}[rule["kind"]]
            try:
                act(action, ids, rule.get("label", ""))
                report["ruled"] += len(ids)
            except Exception as error:
                report["problems"].append(f"rule {describe(rule)}: {error}")
        save("rules.json", {"rules": rules(), "lastRun": now})

    # Auto-expiry sweep (SQLite-backed): runs at most hourly when idle via a
    # single indexed query; zero work when expiry.db doesn't exist yet.
    try:
        import courier_expiry as expiry

        db_path = expiry.default_db_path()
        if db_path.exists():
            conn = expiry.open_db(db_path)
            try:
                sweep = expiry.sweep_due(
                    conn,
                    lambda action, ids: act(action, ids),
                    open_index=open_index,
                    dry_run=False,
                    now=now,
                    force=False,
                    min_interval_seconds=RULE_EVERY,
                )
                report["expired"] = sweep["executed_count"]
                report["problems"].extend(f"expiry: {p}" for p in sweep["problems"])
            finally:
                conn.close()
    except Exception as error:  # noqa: BLE001
        report["problems"].append(f"expiry: {error}")

    return report
