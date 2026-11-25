#!/usr/bin/env python3
"""New mail the moment it lands: one IMAP IDLE connection per account.

Gmail tells an idling connection about every change to the Inbox at once;
each notice starts courier-sync, which downloads, indexes and notifies.
The 3-minute timer stays as a safety net (mail filtered past the Inbox,
dropped connections). Runs as courier-push.service:

    courier-push            watch every signed-in account until stopped
"""

from __future__ import annotations

import imaplib
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courier_sync as sync  # noqa: E402

# Renew the idle command often: a quiet connection can be dropped silently
# by routers on the way, and every renewal is traffic that keeps it alive.
IDLE_SECONDS = 4 * 60
# A fresh login before the hour-long access token runs out.
RECONNECT_SECONDS = 45 * 60
CHANGES = {"EXISTS", "EXPUNGE", "FETCH", "RECENT"}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class SyncTrigger:
    """Runs courier-sync once per burst of notices; a notice that arrives
    while a sync is running queues exactly one more."""

    def __init__(self) -> None:
        self.wanted = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def pull(self) -> None:
        self.wanted.set()

    def run(self) -> None:
        while True:
            self.wanted.wait()
            time.sleep(1.5)  # Gmail sends a few notices per message.
            self.wanted.clear()
            subprocess.run(["systemctl", "--user", "start", "courier-sync.service"], capture_output=True)


def keep_alive(sock: socket.socket) -> None:
    """TCP keepalive probes each minute: they keep routers from forgetting the
    connection, and a dead one is noticed in about two minutes instead of at
    the end of the idle round."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)


def watch(account: dict, trigger: SyncTrigger) -> None:
    backoff = 5
    while True:
        try:
            token = sync.auth_token(account["id"])
            sasl = f"user={account['email']}\x01auth=Bearer {token}\x01\x01".encode()
            imap = imaplib.IMAP4_SSL(sync.IMAP_HOST, timeout=60)
            keep_alive(imap.sock)
            try:
                imap.authenticate("XOAUTH2", lambda challenge: b"" if challenge else sasl)
                imap.select("INBOX", readonly=True)
                log(f"{account['id']}: watching the inbox")
                trigger.pull()  # Catch whatever arrived while disconnected.
                backoff = 5
                started = time.monotonic()
                while time.monotonic() - started < RECONNECT_SECONDS:
                    with imap.idle(duration=IDLE_SECONDS) as idler:
                        for kind, _ in idler:
                            if kind in CHANGES:
                                trigger.pull()
            finally:
                try:
                    imap.logout()
                except (imaplib.IMAP4.error, OSError):
                    pass
        except sync.SignedOut:
            log(f"{account['id']}: signed out; run courier-auth add {account['id']}")
            time.sleep(600)
        except (imaplib.IMAP4.error, OSError, sync.SyncError) as error:
            log(f"{account['id']}: {error}; retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


def main() -> int:
    accounts = sync.load_accounts()
    if not accounts:
        log("No accounts yet. Run: courier-auth add <name>")
        return 0
    trigger = SyncTrigger()
    threads = [threading.Thread(target=watch, args=(account, trigger), daemon=True) for account in accounts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
