#!/usr/bin/env python3
"""Google sign-in for Courier, kept on this PC.

You approve each Google account once in the browser. Its refresh token goes
into the desktop keyring (Secret Service, gnome-keyring here) and nowhere
else. Mail and calendar sync ask this command for a short-lived access token
each time they connect:

    courier-auth setup ~/Downloads/client_secret_XXXX.json   once: the Desktop client
    courier-auth add personal                                once per Google account
    courier-auth token personal                              mbsync PassCmd, msmtp passwordeval
    courier-auth list
    courier-auth remove personal                             revokes at Google, clears the keyring

Exit status 2 means Google stopped accepting an account's saved sign-in.
Run `courier-auth add <account>` again.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# IMAP and SMTP over XOAUTH2 accept only the full-mailbox scope.
MAIL_SCOPE = "https://mail.google.com/"
# Read-only: Courier copies Google events locally and reminds you; events you
# create live on this PC. Widening it later means signing in again.
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
SCOPES = ["openid", "email", MAIL_SCOPE, CALENDAR_SCOPE]
# Google's consent screen lets you untick individual permissions.
REQUIRED_SCOPES = [MAIL_SCOPE, CALENDAR_SCOPE]

KEYRING_APP = "courier"
SIGN_IN_TIMEOUT = 300
# An access token is reused only while it has at least this many seconds left.
REFRESH_MARGIN = 120
ACCOUNT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class UsageError(RuntimeError):
    pass


class KeyringError(RuntimeError):
    pass


class GoogleError(RuntimeError):
    def __init__(self, status: int, error: str, description: str):
        super().__init__(f"Google refused the request ({status} {error}): {description}")
        self.error = error


class SignInExpired(RuntimeError):
    def __init__(self, account: str):
        super().__init__(account)
        self.account = account


# Keyring --------------------------------------------------------------------


def _attributes(kind: str, account: str | None) -> list[str]:
    attributes = ["app", KEYRING_APP, "kind", kind]
    if account is not None:
        attributes += ["account", account]
    return attributes


def _secret_tool(args: list[str], secret: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["secret-tool", *args], input=secret, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise KeyringError("secret-tool is missing (it ships with libsecret).") from None
    except subprocess.TimeoutExpired:
        raise KeyringError("The keyring did not answer. Is it locked behind a prompt?") from None


def keyring_get(kind: str, account: str | None = None) -> str | None:
    result = _secret_tool(["lookup", *_attributes(kind, account)])
    if result.returncode != 0:
        # Not found exits 1 silently; a broken keyring says why on stderr.
        if result.stderr.strip():
            raise KeyringError(result.stderr.strip())
        return None
    return result.stdout.strip() or None


def keyring_set(kind: str, account: str | None, secret: str, label: str) -> None:
    result = _secret_tool(["store", f"--label={label}", *_attributes(kind, account)], secret)
    if result.returncode != 0:
        raise KeyringError(result.stderr.strip() or "secret-tool store failed")


def keyring_clear(kind: str, account: str | None = None) -> None:
    result = _secret_tool(["clear", *_attributes(kind, account)])
    if result.returncode != 0 and result.stderr.strip():
        raise KeyringError(result.stderr.strip())


# Accounts (no secrets: which ids exist and which address each one is) --------


def accounts_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "courier" / "accounts.json"


def load_accounts() -> list[dict]:
    try:
        return json.loads(accounts_path().read_text())["accounts"]
    except FileNotFoundError:
        return []


def save_accounts(accounts: list[dict]) -> None:
    path = accounts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump({"accounts": accounts}, handle, indent=2)
        handle.write("\n")
    os.replace(handle.name, path)


# Google ---------------------------------------------------------------------


def post_form(url: str, fields: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as error:
        payload = error.read().decode(errors="replace")
        try:
            data = json.loads(payload)
        except ValueError:
            data = {}
        raise GoogleError(error.code, data.get("error", ""), data.get("error_description", payload[:200])) from None
    except urllib.error.URLError as error:
        raise UsageError(f"Can't reach Google: {error.reason}") from None
    return json.loads(body) if body.strip() else {}


def load_client() -> dict:
    raw = keyring_get("client")
    if raw is None:
        raise UsageError("No Google client yet. Run: courier-auth setup <client_secret.json>")
    return json.loads(raw)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def open_browser(url: str) -> None:
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sign_in(client: dict, login_hint: str | None) -> dict:
    """Runs Google's loopback flow with PKCE and returns the token response."""
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(24)
    outcome: dict[str, str] = {}

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get("state", [""])[0] != state:
                self.reply(400, "This sign-in link is stale. Start again from Junco.")
                return
            if "code" in query:
                outcome["code"] = query["code"][0]
                self.reply(200, "Junco is signed in. You can close this tab.")
            else:
                outcome["error"] = query.get("error", ["unknown"])[0]
                self.reply(200, "Sign-in was cancelled. You can close this tab.")

        def reply(self, status: int, message: str) -> None:
            body = (
                "<!doctype html><meta charset=utf-8><title>Junco</title>"
                f'<p style="font:18px Rubik,sans-serif;margin:4em auto;max-width:28em">{message}</p>'
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
        # offline + consent: Google returns a refresh token on every sign-in,
        # not only the first one.
        "access_type": "offline",
        "prompt": "consent select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print(f"Opening Google sign-in in your browser. If nothing opens, visit:\n{url}", file=sys.stderr)
    open_browser(url)

    deadline = time.monotonic() + SIGN_IN_TIMEOUT
    try:
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if "error" in outcome:
        raise UsageError(f"Google sign-in did not finish ({outcome['error']}).")
    if "code" not in outcome:
        raise UsageError("Timed out waiting for Google sign-in.")
    return post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": outcome["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
        },
    )


def id_token_email(id_token: str) -> str:
    # The token came straight from Google's token endpoint over TLS, in
    # exchange for our client secret, so its signature needs no re-check.
    payload = id_token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return claims["email"]


def cache_access(account: str, tokens: dict) -> None:
    entry = {"token": tokens["access_token"], "expires": int(time.time()) + int(tokens.get("expires_in", 0))}
    keyring_set("access", account, json.dumps(entry), label=f"Junco: Google access token ({account})")


def access_token(account: str) -> str:
    cached = keyring_get("access", account)
    if cached:
        entry = json.loads(cached)
        if entry["expires"] - time.time() > REFRESH_MARGIN:
            return entry["token"]
    refresh = keyring_get("refresh", account)
    if refresh is None:
        raise UsageError(f"No account named '{account}'. Run: courier-auth add {account}")
    client = load_client()
    try:
        tokens = post_form(
            TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
            },
        )
    except GoogleError as error:
        if error.error == "invalid_grant":
            keyring_clear("access", account)
            raise SignInExpired(account) from None
        raise
    cache_access(account, tokens)
    return tokens["access_token"]


def on_signin_expired(account: str) -> None:
    """Google rejected this account's saved sign-in: you revoked it, changed
    the password, or the Google project is still in Testing (7-day limit).

    Sync runs in the background every few minutes, so stderr alone goes
    unseen, and a desktop notification on every run would nag.
    """
    # TODO: decide how Courier tells you: notify once, notify every run, or
    # stay quiet and let the app show a banner. For now it only writes to
    # stderr.
    print(
        f"courier-auth: Google no longer accepts the saved sign-in for '{account}'. "
        f"Run: courier-auth add {account}",
        file=sys.stderr,
    )


# Commands -------------------------------------------------------------------


def cmd_setup(path: str) -> None:
    try:
        data = json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError) as error:
        raise UsageError(f"Can't read {path}: {error}") from None
    info = data.get("installed")
    if not info or "client_id" not in info or "client_secret" not in info:
        raise UsageError("That file is not a Desktop app client. In Google Cloud, create an OAuth client of type 'Desktop app'.")
    client = {"client_id": info["client_id"], "client_secret": info["client_secret"]}
    keyring_set("client", None, json.dumps(client), label="Junco: Google OAuth client")
    print(f"Saved the Google client to the keyring. You can delete {path} now.")


def cmd_add(account: str, login_hint: str | None) -> None:
    if not ACCOUNT_ID.match(account):
        raise UsageError("Account names are short and lowercase, like 'personal' or 'work'.")
    client = load_client()
    tokens = sign_in(client, login_hint)

    granted = set(tokens.get("scope", "").split())
    missing = [scope for scope in REQUIRED_SCOPES if scope not in granted]
    refresh = tokens.get("refresh_token")
    if missing or not refresh:
        if refresh:
            # Don't leave a half-permitted sign-in alive at Google.
            post_form(REVOKE_URL, {"token": refresh})
        names = ", ".join("mail" if scope == MAIL_SCOPE else "calendar" for scope in missing) or "offline access"
        raise UsageError(f"Google left out: {names}. Run add again and keep every box ticked.")

    email = id_token_email(tokens["id_token"])
    keyring_set("refresh", account, refresh, label=f"Junco: Google sign-in for {email}")
    cache_access(account, tokens)
    accounts = [entry for entry in load_accounts() if entry["id"] != account]
    accounts.append({"id": account, "email": email})
    save_accounts(accounts)
    print(f"Signed in {email} as '{account}'.")


def cmd_list() -> None:
    accounts = load_accounts()
    if not accounts:
        print("No accounts yet. Run: courier-auth add <name>")
    for entry in accounts:
        state = "" if keyring_get("refresh", entry["id"]) else "  (signed out)"
        print(f"{entry['id']:<12}{entry['email']}{state}")


def cmd_remove(account: str) -> None:
    refresh = keyring_get("refresh", account)
    if refresh:
        try:
            post_form(REVOKE_URL, {"token": refresh})
        except GoogleError:
            pass  # Already revoked at Google; clearing locally is what's left.
    keyring_clear("refresh", account)
    keyring_clear("access", account)
    save_accounts([entry for entry in load_accounts() if entry["id"] != account])
    print(f"Removed '{account}'.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="courier-auth", description="Google sign-in for Junco.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="store the Desktop OAuth client").add_argument("client_json")
    add = commands.add_parser("add", help="sign in a Google account")
    add.add_argument("account")
    add.add_argument("--email", help="preselect this Google account")
    commands.add_parser("token", help="print a fresh access token").add_argument("account")
    commands.add_parser("list", help="show signed-in accounts")
    commands.add_parser("remove", help="sign out and revoke").add_argument("account")
    args = parser.parse_args(argv)

    try:
        if args.command == "setup":
            cmd_setup(args.client_json)
        elif args.command == "add":
            cmd_add(args.account, args.email)
        elif args.command == "token":
            print(access_token(args.account))
        elif args.command == "list":
            cmd_list()
        elif args.command == "remove":
            cmd_remove(args.account)
    except SignInExpired as expired:
        on_signin_expired(expired.account)
        return 2
    except (UsageError, KeyringError, GoogleError) as error:
        print(f"courier-auth: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
