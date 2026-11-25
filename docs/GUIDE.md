# Courier: the full guide

A mail app whose inbox reads like a chat app, and a separate Calendar app with to-dos and
desktop reminders, for Gmail. Built to sit in a Caelestia desktop: same
fonts, shapes and live wallpaper colours, but its own process, so a mail bug
never takes the shell down. For how the pieces fit together and how to set it
up, read [HOW-IT-WORKS.md](../HOW-IT-WORKS.md).

**Native only.** QML on Quickshell (the same toolkit as the Caelestia shell),
C mail tools (`mbsync`, `notmuch`, `msmtp`). No Electron, no embedded
browser engine: designed emails are drawn by Qt's own rich-text engine
(HTML 4 tables and CSS 2, no scripting), and "Open in browser" shows any one
email exactly as sent, on request.

Status: **real Gmail** (one account so far). Read, write, reply, reply all,
forward, archive, delete, spam, star, search, with new mail pushed the moment
it lands and sender logos. Open "Courier" or "Calendar" from the app
launcher, or:

    courier            # bin/courier: the mail app (shell/)
    calendar           # bin/calendar: the Calendar app (calendar/)

Each shows its running window or starts one; closing the window quits it.
`qs ipc -p shell call courier open <Message-ID>` opens an email from outside
(e.g. a notification); `calendar 2026-12-11` opens Calendar on a day.

The two apps share the engine (`engine/`), the theme and the basic components:
`calendar/services/Theme.qml` and the generic files in `calendar/components`
are symlinks into `shell/`.

It runs on Quickshell or the `noctalia-qs` fork (no fork-specific pragmas).

## Google sign-in

`engine/courier_auth.py` (linked as `~/.local/bin/courier-auth`) signs each
Google account in once through the browser: OAuth with PKCE and a loopback
redirect, no app passwords. The refresh token lives only in the keyring;
sync tools call `courier-auth token <account>` for a one-hour access token.
Scopes: full mail (IMAP and SMTP accept nothing narrower) and read-only
calendar.

One-time Google Cloud setup, in a project of its own:

1. Create a project named Courier. Enable the Gmail API and the Google
   Calendar API.
2. Google Auth Platform: Branding (app name Courier), Audience External, then
   **Publish app** so it is *In production*. Testing would expire the
   sign-in every 7 days.
3. Clients → Create client → **Desktop app** → download the JSON.
4. `courier-auth setup ~/Downloads/client_secret_….json`, delete the file,
   then `courier-auth add personal` and `courier-auth add work`. Google warns
   the app is unverified: Advanced → Go to Courier. Personal use needs no
   verification.
5. If the Workspace account blocks it: Admin console → Security → API
   controls → Manage third-party app access → add the client ID as Trusted.

## Mail sync

`engine/courier_sync.py` (linked as `~/.local/bin/courier-sync`, run every
3 minutes by `courier-sync.timer`, a systemd user timer) writes mbsync,
msmtp and notmuch configs from the account list into `~/.config/courier/`,
pulls each account's Inbox, All Mail and Drafts into
`~/.local/share/courier/mail/`, indexes it, and tags new mail with a lane
(`people`, `updates`, `newsletters`), `account/<id>` and `sent`. The `inbox`
tag mirrors Gmail's Inbox on every run. Status for the app:
`~/.local/state/courier/sync.json`.

Gmail keeps a draft in All Mail too, marked only by its Draft label (no IMAP
flag), so a copy there can't tell it is one. Drafts are pulled (never pushed)
into `<account>/drafts`; a message with a copy there is tagged `unsent`,
never `sent`, and shows nowhere: not in a chat, a list, Sent or a rule. When
the draft is sent or discarded in Gmail its copy goes and the tag with it.
(Not notmuch's own `draft` tag: that follows the maildir D flag.)

A new account's first download (Inbox and All Mail, each up to `HISTORY`)
can be thousands of emails. Gmail is asked once how many, and while mbsync
runs, what has arrived is indexed every minute and `sync.json` says
`downloading`, `have` and `expected`, so mail shows as it comes. A run stops
only when neither new mail nor mbsync's own journal has moved for 3 minutes
(or after 2 hours), asked to stop first so it finishes what it is writing; the next
one carries on. `~/.local/state/courier/downloaded-<id>` marks an account
whose first download finished.

Lanes, in order (`lane()` in `courier_sync.py`):
1. Mail you sent is People, unless it only went to robots (Gmail's
   Unsubscribe button mails the list for you).
2. GitHub and Linear are Updates.
3. Anything with list headers (unsubscribe link, List-Id) is a Newsletter.
4. Anyone you've written to is People, unless their address is a no-reply box.
5. Machine signs make it Updates: no-reply or role addresses (`hello@`,
   `support@`), sending-service headers (SES, Mailgun, SendGrid,
   Feedback-ID), a bounce address on another domain, a sending subdomain
   (`notifications.`, `alerts.`, `e.`; never `mail.`), or the brand's own
   name in the mailbox (`microsoftanswers@microsoft.com`).
6. Everyone else is People.

Writing to someone new moves their earlier mail to People on the next sync.
After changing the rule, `courier-sync --relane` sorts everything again.

## New mail, instantly

`engine/courier_push.py` (`courier-push.service`, always running) keeps one
IMAP IDLE connection per account; Gmail announces new mail on it and a sync
starts within seconds. New mail from people (never newsletters or machine
mail) raises a desktop notification. The 3-minute timer stays as a safety net.

## Sender and account pictures

`engine/courier_avatars.py` (`courier-avatars.service`, started after each
sync) finds each sender's picture once: the brand's BIMI logo (the DNS record
Gmail reads), else its website's app icon; for people, their Gravatar. Each is
stored as a round PNG on a white disc in `~/.cache/courier/avatars`.
Downloads stop at 512 KB, but a few KB of PNG can claim to be enormous, so
no picture is decoded past 4096 px a side, judged from its header first
(and Pillow's own limit tightened to match, for the icon frames it decodes
as it opens them). Each file is opened only as the type its bytes show; a
BIMI logo (SVG) is drawn by `rsvg-convert` under `prlimit` (512 MB).

Each connected account wears its own picture the same way: the Google
account's profile photo, else its address's Gravatar, else its initial. The
photo comes from Google's OpenID userinfo with the sign-in Courier already
has (`openid email`; no new permission). It is looked up once, checked to be
a real image and kept as `~/.local/share/courier/accounts/<id>.default.png`;
a Gravatar or "none" is checked again weekly, a failed lookup (offline,
signed out) after an hour, and a moment offline never counts as "no
picture". The window looks up a new account's picture when it opens or adds
one; `courier-avatars accounts --again` looks every account up anew. The
state is in `~/.local/state/courier/account-pictures.json`.

## Calendar

`engine/courier_calendar.py`: `courier-calendar.timer` copies every visible
Google calendar (60 days back, a year ahead) to
`~/.local/share/courier/calendar/google.json` every 5 minutes;
`courier-remind.timer` checks each minute and raises a desktop notification
for every pop-up reminder that comes due, Courier open or not. Events made
only on this PC go in `local.json` beside it.

The Calendar app (`calendar/`, its page is `views/CalendarPage.qml`) has
three columns:

- **Left:** Create event, a month to jump around in (always six weeks tall,
  so nothing below it moves), "My calendars" grouped by account (each Google
  account's address over its calendars, then Birthdays from all accounts,
  then This PC; same-named calendars are numbered; checkboxes show or hide
  each; ⋯ has "Show only this"; + adds a calendar on this PC), and the
  connected Google accounts with their sync state.

The month view is always six weeks, so rows keep their height. An event in
two visible calendars (a meeting both accounts are invited to, or two
subscriptions to the same holidays) shows once: same title, start and end.
Hidden calendars drop out first, so hiding one copy never hides the event.
- **Middle:** Day, Week, Month and Agenda views, with search across every
  copied event. Double-click a day or an empty hour to start an event there.
- **Right:** the picked day's events, its to-dos (unfinished ones from
  earlier days carry over into today), what's coming up after it, and a way
  to add one more event.

Google birthdays show as their own "Birthdays" calendar. Which view and
calendars you left on is kept in `~/.local/state/courier/calendar-view.json`.
To-dos live in `~/.local/share/courier/tasks.json`.

Courier has read-only access to Google Calendar (`calendar.readonly`). So
events you create, edit or delete here live in calendars on this PC, and
"Edit in Google" opens a Google event in the browser. Writing to Google
would need a new consent with the `calendar.events` scope.

`courier-calendar` commands, all printing JSON:

| Command | What it does |
| --- | --- |
| `calendars` | List every calendar. |
| `range FIRST AFTER` | Events on days from FIRST up to, not including, AFTER. |
| `add JSON` | Create an event on this PC. |
| `update ID JSON` | Change an event on this PC. |
| `delete ID` | Delete an event on this PC. |
| `add-calendar NAME` | Add a calendar on this PC. |

Errors come back as `{"error": …}` with exit code 1.

## Reading

`engine/courier_mail.py` (linked as `courier-mail`) is what the app runs; every
command prints JSON. `message <id>` is one whole email for the reader: the new
text (quoted history one click away), the designed version, sender,
recipients, date, attachments and the meeting from its invite.

Designed mail (newsletters, receipts, notifications) shows as designed, on its
own background; mail from people reads as text, with links shortened to their
site and the quoted history folded. Text (the reader's text view and chat
bubbles, `shell/services/plaintext.js`) turns plain-text conventions back into
formatting: `*bold*`, `_italic_`, Gmail's "address <address>" said once, and
bare addresses like `meet.google.com/abc-defg-hij` made clickable; everything
else is escaped. ⋮ switches either way. `courier_html.py`
makes the designed version safe for Qt's rich text first:

- Only tags and attributes Qt draws are kept; scripts, forms, frames,
  stylesheets from the web and `javascript:` links are dropped. Links are
  web or mailto only.
- What mail apps hide stays hidden: preview text (`display:none`, also by
  class), Outlook-only blocks, tracking pixels (1×1, or URLs that are pages
  or say open/track/pixel/beacon, never fetched).
- Images become local files with their exact size, so the layout is right the
  first time: those sent inside the email go to `$XDG_RUNTIME_DIR/courier/inline`,
  web images are downloaded by the engine (8 at once, waiting at most 2.5 s;
  no cookies) into `~/.cache/courier/images` and kept 30 days. Qt itself
  never goes to the web. Qt decodes every image it draws whole, so it only
  gets PNG, JPEG, GIF, WebP and BMP (sized from their headers, never
  decoded by the engine), each at most 50 megapixels and one email's at
  most 100 in all; past that an image shows its description.
- Code and quotes look like GitHub's (most Markdown arrives this way, as
  GitHub's HTML): a code block sits in a shaded, padded box and its long
  lines wrap instead of being clipped, inline code is tinted, a quote has a
  bar (light or dark palette by the email's background).
- Plain-text email written in Markdown (no HTML part, and at least two kinds
  of Markdown in it: headings, code, bold, links, lists, tables) is rendered
  with markdown-it-py (CommonMark plus tables and strikethrough, raw HTML
  kept as text, line breaks kept, bare links clickable outside code), then
  cleaned like any designed email. It shows rendered even from people.
- Qt quirks are worked around: line heights become px (Qt scales a whole line,
  image included, by a unitless or % line height, and 0 collapses it), cell
  backgrounds move onto an inner table (Qt paints a cell's colour only behind
  its text), and links styled as buttons become padded one-cell tables.

Opening an email takes about 0.2 s, plus up to 2.5 s the first time its web
images download.

Attachments save to Downloads (`attachment <id> <n>`, never overwriting) or
open in the system viewer from a private copy (`preview <id> <n>`). "View
original" (`original <id>`) writes the email's HTML, embedded images
included, to a private file under `$XDG_RUNTIME_DIR` and opens it in the
browser; a Content-Security-Policy at its top blocks every script, form and
frame.

Sync itself only pulls: new mail, Gmail-side deletions and read/starred
state come down, and only read/starred state goes up. Everything else Courier
changes in Gmail (archive, delete, spam, labels) goes through
`courier_gmail.py`, below, and only when you ask. Only the newest 10,000
messages per folder download (`HISTORY`).

Tests (fake Google, real keyring under `app=courier-selftest`; a hand-built
Maildir for sync):

    cd engine && python3 -m unittest discover tests

## The mail window

Three columns:

- **Sidebar:** the title with Pip, Courier's icon, before it
  (`assets/icons/courier-pip.svg`; Calendar's has Tab); Compose; Inbox, All
  Mail, Starred, Sent, Archive, Trash, with
  what's unread or waiting in each; at the foot, the account bar: the account
  shown as a big circle, the others small (click to switch; every list,
  count and Trash follows; the row wraps when there are many), and + to add
  one (`courier-mail account-add <name>` signs in through the browser,
  rewrites the sync configs, restarts push and starts the first sync;
  Cancel stops it). Each account wears its own picture (its Google photo or
  Gravatar, above). All (every account together) is one circle split
  between the accounts' pictures: halves for two, a half and two quarters
  for three, quarters for four, and "+N" in the last quarter beyond that.
  Hover a circle a moment (or click the big one) for its card: picture,
  name and address, storage as a bar (the exact numbers in its tooltip),
  Change picture…, and "Show only its mail"; All's card lists the accounts
  and adds one. Right-click opens the same actions as a menu. Change
  picture… (or the camera on the card's picture): pick an image, then drag
  and zoom it in the circle, as Caelestia's profile picture cropper does,
  and Use this picture (`courier-mail account-picture <id> <file> --crop
  X,Y,SIZE`, saved round as `~/.local/share/courier/accounts/<id>.png`;
  PNG, JPEG, WebP, GIF or BMP, decoded at most 64 megapixels, a big JPEG at
  1/2 to 1/8 scale).
  Yours always wins, and fetching never writes it; "Use Google photo" (or
  Gravatar) on the card goes back (`account-picture <id> --clear`). A circle
  without a picture is the account's initial on its colour. The picture
  also shows on each email's corner,
  the conversation's account tag, the reply bar, the reader's "to me" line
  and compose's From. A first download shows as a ring on its circle and a
  progress line above the bar.
- **Inbox** (Beeper-style): conversations, newest first. Each person is a
  chat; each machine sender (Cloudflare, Google…) is a list of its emails,
  and the newsletters are one list. Chips: All, People, Updates (with unread
  counts); Newsletters is under the filter button. Typing narrows the list;
  Enter searches every email (in All Mail). Hover a row to archive the whole
  conversation; it comes back when someone writes again.
- **Right:** the open conversation. A person reads as chat bubbles with a
  reply box (Enter sends); a sender's list is grouped Today, Yesterday,
  Earlier, with select, star, search and sort. While emails are picked,
  the list's header becomes the selection's bar (Material's contextual top
  bar): close, the count, Archive, Delete, Read, Unread, Star and Select all,
  as icons or in a ⋮ menu when the pane is narrow; nothing covers the list.
  Opening an email shows the
  reader in its place (back or Escape returns): archive, delete, unread,
  more (star, plain text / designed version, open in browser, report spam);
  the meeting card (Join, Add to calendar); the email, designed mail as
  designed; files (preview or save); Reply / Reply all / Forward; a reply
  bar.
- **Other folders** are email lists under Today, Yesterday and Earlier, with
  filters (unread, attachments) and search. Machine mail folds per sender per
  day (a morning of GitHub is one row, with its PR numbers as chips) and
  opens in place.

Categories come from sync (`courier_sync.categorize`): `meeting` (carries a
calendar invite), `dev` (DEV_DOMAINS), `college` (.ac.in, .edu…). Run
`courier-sync --relane` after changing them.

## Gmail changes and later

`engine/courier_gmail.py` changes Gmail itself over IMAP (the sign-in sync
uses): archive removes the `\Inbox` label, delete and spam MOVE into the
folders Gmail marks `\Trash` and `\Junk`, Move to adds a label and leaves
the inbox. The local copy hides the email at once; the next sync confirms.
Every change has Undo.

Actions show at once: the row leaves the list, the bar says "Deleting…",
then "Deleted · Undo" once Gmail has it (about 2–3 s, mostly Gmail's sign-in;
Gmail's folder names are cached for a day). Rows stay hidden until the next
sync shows the same, so a list that loads in between can't bring them back.
An action never waits for the mail index: if a sync holds it, the tag change
goes to `~/.local/state/courier/retag/` and the sync applies it.

Trash isn't synced (Gmail empties it after 30 days), so the Trash folder and
any email opened from it are read straight from Gmail (`trash`,
`trash-open <id>`), with Restore in the reader. Asking Gmail takes ~2.5 s,
most of it Gmail's sign-in, so Trash opens on the list as last seen
(`trash --cached`, `~/.local/state/courier/trash.json`, kept in step with
deletes and restores made here) and Gmail's answer replaces it.

Scheduled sending, snooze, reminders, retention and rules are engine commands
only (`compose --at`, `snooze`, …); the window doesn't show them. Gmail has none of them over IMAP, so
`engine/courier_later.py` keeps them in `~/.local/state/courier/*.json` and
`courier-tick.timer` runs `courier-mail tick` each minute, window open or
not: snoozed emails come back, reminders notify, scheduled emails send,
retention deletes, and the rules run (hourly, at most 300 emails a rule per
run). Rules never touch starred or sent mail, need a category, sender or
subject, and deleting needs at least a day's wait. A new rule starts off and
shows how many emails it would touch now.

    courier-mail conversations                    # the inbox the app shows
    courier-mail list sent [--search WORDS]       # a folder, by day
    courier-mail act archive|inbox|trash|untrash|spam|unspam|move <ids…> [--label L]
    courier-mail snooze <ids…> --until 2026-11-22T08:00
    courier-mail remind <id> --at 2026-11-22T08:00
    courier-mail compose … [--at 2026-11-22T09:00]   # schedule instead of sending
    courier-mail retention <id> 5y                   # "" keeps it
    courier-mail rule-save '{"kind":"archive","category":"newsletters","afterDays":14}'
    courier-mail tick

## Teach fields

Automated mail says the same few things every time: a forge's push names
who pushed, how many commits and which, and links to them. Teach Courier
once and it reads those out of every email like it.

Teach fields' screens are for developers for now: run Courier with
`COURIER_DEV=1` to see them. Templates already taught keep working either
way.

1. Open one (a push, a CI failure, a PR comment) and press **Teach fields**
   (the grid button in the reader's toolbar, or ⋯ → Teach fields).
2. Courier switches the email to its text (the designed version when it has
   no text) and opens a panel: select text in the email or its subject,
   type a name or pick one (Repo, PR, Title, Author, Action, Link, Status),
   then **Add field**. Tick **Every row** for a list (commits, jobs),
   **Link address** to keep where a link goes, **Optional** for a field not
   every email has.
3. Under the fields, the template's other emails are read as you go, so you
   see the pattern working (or which email it doesn't fit) before saving.
   Rename or delete fields there, rename the template, **Save**, or
   **Delete template**.

Then every email of that template opens with a **field card** at the top,
and the sidebar's **Tables** list opens it as a table: a row per email, a
column per field, a click on a header sorts, the filter keeps rows that say
what you type, and a row opens its email beside the table. New mail of the
template has its fields read as it syncs.

When an email doesn't fit any more (the sender changed the template, or a
field isn't where it was), its card and its row say **Needs re-teaching**
and show no values, never a wrong one; **Teach again** opens the panel on
it.

Templates are per account and per fingerprint (sender, subject frame and
the layout of the email's header and footer), kept in
`~/.local/state/courier/templates/<account>/`: the template (what you
selected, as Message-IDs and offsets, and what was learned) and its emails'
values. The mail is only ever read. `engine/courier_templates.py` keeps them,
and `engine/courier_fields.py` learns them.

    courier-mail teach-start <id> [--surface text|html]
    courier-mail teach-select|teach-preview|teach-save <id>    # JSON on stdin
    courier-mail templates | template-table <id> | template-delete <id>

## Writing

Compose (or Ctrl+N), Reply, Reply all and Forward open one window: To, Cc
and Bcc suggest people you write to, Attach uses the KDE file picker,
Ctrl+Enter sends. Replies thread under
the email and quote it; forwards carry its text and attachments. The reply
bar under an email replies to whoever Reply would pick. An email with no
text of yours asks first ("This email has no text": Keep writing or Send
anyway); the engine refuses one unless asked (`compose --empty-ok`), and a
reply in a chat or from the reply bar is never sent empty. A forward is
never empty: it carries the email it forwards. Errors from the engine come
back as `{"error": …}` and show in the bar at the bottom.

