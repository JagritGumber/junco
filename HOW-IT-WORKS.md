# How Junco works

Junco is two desktop apps for one Gmail account (or several) and the small
engine behind them:

- **Junco** (`shell/`): a mail app whose inbox reads like a chat app
  (people as conversations, machine mail in lists of its own), written in
  QML on Quickshell.
- **Calendar** (`calendar/`): Google calendars, calendars kept on this PC,
  and to-dos.
- **The engine** (`engine/`): Python command-line tools that sync mail and
  calendars, read the local mail index, and make every change to Gmail. The
  apps only ever talk to the engine; the engine prints JSON.

Nothing runs in a browser engine and no mail goes through anyone's server:
mail is copied to this PC over IMAP and read from there.

## The big picture

```
                 Gmail (IMAP / SMTP)                 Google Calendar API
        ┌──────────┬──────────┬──────────┐                    │
        │ IDLE     │ pull     │ send     │ change             │ read-only
        ▼          ▼          ▲          ▲                    ▼
  courier-push  mbsync      msmtp   courier_gmail      courier-calendar sync
        │          │          ▲          ▲                    │
        └─► courier-sync ─► Maildir ─► notmuch index ◄─┐      ▼
                  (tags: inbox, people/updates/        │   google.json + local.json
                   newsletters, meeting/dev/college)   │      │
                                   │                   │      │
                                   ▼                   │      ▼
                         courier-mail (JSON) ──────────┘   courier-calendar (JSON)
                          ▲          ▲                        ▲
                          │          │ every minute           │
               Junco window     courier-mail tick     Calendar window
              (shell/, QML)     (snooze, reminders,   (calendar/, QML)
                                 scheduled, rules)
```

- **Mail comes in** through `mbsync`, which copies Gmail's Inbox and All Mail
  into a local Maildir. `notmuch` indexes it. `courier-sync` then tags every
  new email: whether it's in the inbox, its lane (people, updates,
  newsletters) and its categories (meeting, dev, college).
- **New mail arrives within seconds** because `courier-push` holds an IMAP
  IDLE connection open. Gmail announces new mail on it, and a sync starts.
- **The apps read** by running `courier-mail` and `courier-calendar`
  commands, which answer in JSON. They don't touch the Maildir themselves.
- **Changes to Gmail** (archive, delete, spam, labels) go straight to Gmail
  over IMAP from `courier_gmail.py`. The local copy updates at once and the
  next sync confirms it. Sync itself only pulls, plus read and starred flags.
- **Sending** goes through `msmtp` to Gmail's SMTP. Gmail files the sent copy,
  and the next sync brings it back.
- **Things that happen later** (snoozed mail coming back, reminders,
  scheduled sends, emails set to delete themselves, automation rules) live in
  small JSON files. `courier-mail tick` runs every minute and does whatever
  has come due, with the window open or not.

## One click, end to end

Archiving an email:

1. The Archive button calls `Inbox.act("archive", [id])` in
   `shell/services/Inbox.qml`, which takes the row off the list at once.
2. That runs `courier-mail act archive <id>`.
3. `courier_mail.act` finds which account the email belongs to and calls
   `courier_gmail.apply`. It signs in to Gmail's IMAP with the same OAuth
   token sync uses, finds the email by its Message-ID (Gmail's `X-GM-RAW
   rfc822msgid:` search), and removes the `\Inbox` label.
4. The engine removes the local `inbox` tag (or, if a sync is holding the
   index, queues that for the sync) and starts a sync.
5. The bar, which said "Archiving…" from the first moment, turns into
   "Archived · Undo". Undo runs `courier-mail act inbox <id>`.

More than one Gmail account: + in the sidebar's account bar runs
`courier-mail account-add <name>`. It signs in through the browser, rewrites
the sync configs, restarts the push service and starts the first sync, which
shows mail as it arrives (indexed every minute) with a progress ring. All
accounts' mail shows together, a coloured dot on each conversation and email
saying whose it is; clicking an account's circle shows only its mail
(`--account` on the engine's commands).

A new email arriving:

1. Gmail tells `courier-push` over IDLE; it starts `courier-sync.service`.
2. `mbsync` downloads the email; `notmuch new` indexes it.
3. `courier_sync.index` tags it (inbox, lane, categories). Mail a template
   makes (GitHub's notifications, built in, or one you taught) gets a
   notification written from its fields (`courier_notify`); other mail
   notifies you if it's from a person.
4. Sync rewrites `~/.local/state/courier/sync.json`. The app watches that
   file and reloads its list.

## What runs, and when

All are systemd user units in `engine/systemd/`.

| Unit | What it does | When |
| --- | --- | --- |
| `courier-push.service` | Keeps one IMAP IDLE connection per account and starts a sync when mail arrives | Always running |
| `courier-sync.service` + `.timer` | mbsync, notmuch, tagging, notifications | Every 3 minutes, and on push |
| `courier-notify.service` | Answers the buttons on Junco's notifications (Open on GitHub, Open in Junco, Mark read) | Always running in the graphical session |
| `courier-avatars.service` | Finds sender logos (BIMI, site icon, Gravatar) and each account's own picture (Google photo, Gravatar) | After each sync |
| `courier-tick.service` + `.timer` | Snoozes, reminders, scheduled sends, retention, rules | Every minute |
| `courier-calendar.service` + `.timer` | Copies Google calendars | Every 5 minutes |
| `courier-remind.service` + `.timer` | Calendar event reminders | Every minute |

## Where things live

| What | Where |
| --- | --- |
| OAuth client and refresh tokens | The system keyring (`secret-tool`, `app=courier`), never a file |
| Account list, generated mbsync/msmtp/notmuch configs | `~/.config/courier/` |
| Mail (Maildir) and the notmuch index | `~/.local/share/courier/mail/` |
| Calendars copied from Google, and calendars on this PC | `~/.local/share/courier/calendar/google.json`, `local.json` |
| To-dos | `~/.local/share/courier/tasks.json` |
| Sync status, snoozed, reminders, scheduled, retention, rules, cached labels and storage | `~/.local/state/courier/*.json` (scheduled emails in `scheduled/`) |
| Sender pictures | `~/.cache/courier/avatars/` |
| Account pictures: yours (`<id>.png`) and the account's own (`<id>.default.png`) | `~/.local/share/courier/accounts/`, looked up as recorded in `~/.local/state/courier/account-pictures.json` |
| Web images in designed emails (kept 30 days) | `~/.cache/courier/images/` |
| Taught templates (Teach fields) and their emails' fields | `~/.local/state/courier/templates/<account>/` |
| Images sent inside emails | `$XDG_RUNTIME_DIR/courier/inline/`, readable only by you |
| "View original" pages and attachment previews | `$XDG_RUNTIME_DIR/courier/`, readable only by you |

## The code

**Engine** (`engine/`). Each command prints JSON; errors come back as
`{"error": "…"}` with exit code 1.

| File | Role |
| --- | --- |
| `courier_auth.py` → `courier-auth` | Google sign-in (OAuth with PKCE, loopback redirect); hands out one-hour access tokens |
| `courier_sync.py` → `courier-sync` | Writes the mbsync/msmtp/notmuch configs, runs mbsync and notmuch, tags lanes and categories |
| `courier_push.py` → `courier-push` | IMAP IDLE (Python 3.14's `imaplib.idle`), triggers syncs |
| `courier_mail.py` → `courier-mail` | Everything the mail app asks: conversations, lists, one email, compose, send, act, tick |
| `courier_views.py` | Folder lists (grouping, Today / Yesterday / Earlier), folders and counts, invite parsing |
| `courier_html.py` | Designed (HTML) email made safe for Qt's rich text: allowed tags only, hidden and tracking bits dropped, images as local files with exact sizes |
| `courier_fields.py` | Teach fields' learner: an email as a page of text pieces with their paths, template fingerprints, fields learned from one or two taught emails (the template's other emails say what holds), read with a verdict (ok, or "needs re-teaching") |
| `courier_templates.py` | Teach fields' store: templates per account and fingerprint, the panel's calls (start, select, preview, save), the field card, the Updates table, and new mail read after each sync |
| `courier_gmail.py` | Changes in Gmail over IMAP: archive, inbox, trash, spam, move to a label, and their undo |
| `courier_later.py` | Snooze, reminders, scheduled sending, retention, automation rules, and `tick` |
| `courier_avatars.py` → `courier-avatars` | Sender logos and photos, and each account's own picture |
| `courier_calendar.py` → `courier-calendar` | Calendar sync, the agenda, events on this PC, reminders |
| `tests/` | Unit tests against a fake Google and a hand-built Maildir |

**Junco app** (`shell/`):

- `shell.qml`: the window: sidebar; the inbox's conversations or a folder's
  list; the open conversation or email.
- `services/Inbox.qml`: all state and every engine call.
- `services/Theme.qml`: colours from Caelestia's wallpaper scheme.
- `views/`: the panes (`MailSidebar`, `ConversationList`, `ConversationView`
  with `LaneView`, `MessageItem` and `Composer`, `MailList`, `MailReader`,
  `ComposeDialog`, `AddAccountDialog`, `PictureDialog`, `AccountBar` with
  its hover `AccountCard`, and Teach fields' `TeachPanel` and
  `TemplateTable`).
- `components/`: the pieces those panes are built from (buttons, rows, cards,
  menus, the reply bar, Teach fields' `FieldsCard`).

**Calendar app** (`calendar/`): `shell.qml`, `services/Calendar.qml` and
`Tasks.qml`, and the month, week, day and agenda views. It shares the theme
and basic components with Junco through symlinks into `shell/`, so keep the
two folders side by side.

**Launchers** (`bin/`): `courier` and `calendar` bring up the running window,
or start one. `calendar 2026-12-11` opens a day.

## Rules that keep mail safe

- Sync never deletes or moves anything in Gmail. Only explicit actions do,
  and each comes with Undo. Deleting goes to Gmail's Trash (30 days to
  restore).
- Automation rules and per-email retention start **off**. A rule shows how
  many emails it would touch before you turn it on. Rules never touch starred
  or sent mail, need a category, sender or subject (never "all mail"), and
  deleting needs at least a day's wait. They run hourly, at most 300 emails
  per rule per run.
- Mail from people is shown as escaped plain text with linkified URLs.
  Designed mail is drawn by Qt's rich text, which has no scripting, after
  `courier_html.py` keeps only what Qt draws and drops scripts, forms,
  frames, outside stylesheets, non-web links and tracking pixels. The engine
  downloads web images itself; Qt never fetches anything. "Open in browser"
  shows the original behind a Content-Security-Policy that blocks scripts,
  forms and frames.
- Calendar access is read-only (`calendar.readonly`). Events you create live
  on this PC.

## Setting it up on another machine

These steps are for Arch Linux; the package names will differ elsewhere.

1. **Install the tools.**

   ```
   sudo pacman -S quickshell isync notmuch msmtp libsecret librsvg kdialog libnotify \
                  python-pillow python-markdown-it-py ttf-material-symbols-variable
   yay -S cyrus-sasl-xoauth2-git ttf-rubik-vf
   ```

   Python 3.14 or newer is needed (for IMAP IDLE). `systemd-resolved` is
   used for logo lookups (BIMI over DNS).

2. **Put the folder somewhere permanent**, e.g. `~/Projects/junco`, and
   link the commands:

   ```
   git clone https://github.com/JagritGumber/junco ~/Projects/junco
   cd ~/Projects/junco
   mkdir -p ~/.local/bin
   ln -sf "$PWD/bin/courier" "$PWD/bin/calendar" ~/.local/bin/
   for tool in auth sync push mail calendar avatars notify; do
       ln -sf "$PWD/engine/courier_$tool.py" ~/.local/bin/courier-$tool
   done
   ```

3. **Create a Google sign-in client** in your own Google Cloud project. The
   steps are under "Google sign-in" in [docs/GUIDE.md](docs/GUIDE.md). Then:

   ```
   courier-auth setup ~/Downloads/client_secret_….json   # then delete that file
   courier-auth add personal                               # opens the browser
   courier-sync                                            # first sync (minutes)
   ```

4. **Install the background units:**

   ```
   mkdir -p ~/.config/systemd/user
   ln -sf "$PWD"/engine/systemd/* ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now courier-push.service courier-sync.timer courier-notify.service \
       courier-tick.timer courier-calendar.timer courier-remind.timer
   ```

5. **Add launcher entries.** Save these two files in
   `~/.local/share/applications/`, with your own home path:

   ```
   # courier.desktop
   [Desktop Entry]
   Type=Application
   Name=Junco
   Exec=/home/YOU/.local/bin/courier
   Icon=internet-mail
   StartupWMClass=courier
   Categories=Network;Email;

   # courier-calendar.desktop
   [Desktop Entry]
   Type=Application
   Name=Calendar
   Exec=/home/YOU/.local/bin/calendar
   Icon=office-calendar
   StartupWMClass=courier-calendar
   Categories=Office;Calendar;
   ```

   `StartupWMClass` matches the window class each app sets with
   `//@ pragma AppId` at the top of its `shell.qml`. Without it every
   Quickshell window is `org.quickshell`, and bars and docks show Quickshell's
   logo for both apps.

The colours follow the Caelestia shell's wallpaper scheme
(`~/.local/state/caelestia/scheme.json`). Without Caelestia, Junco uses its
built-in dark palette.

## Running the tests

```
cd engine && python3 -m unittest discover tests
```

The tests use temporary folders, a fake Google server and a separate keyring
entry (`app=courier-selftest`); they never touch your real mail or tokens.
