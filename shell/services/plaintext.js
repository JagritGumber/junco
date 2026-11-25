.pragma library

// Plain-text mail as rich text, for the chat bubbles and the text view.
//
// Links become clickable and short. The conventions mail apps use when they
// turn formatted mail into plain text become formatting again: *bold*,
// _italic_, and "address <address>" (Gmail writes each link twice) said once.
// Everything else is escaped, so mail can't inject markup.

function escape(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// The same address, give or take scheme, www. and a trailing slash.
function sameAddress(a, b) {
    const plain = url => url.toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/+$/, "");
    return plain(a) === plain(b);
}

// What a link shows: the whole address when short (a Meet code), else the site.
function shown(url) {
    const bare = url.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/+$/, "");
    return bare.length <= 32 ? bare : bare.split(/[\/?#]/)[0];
}

// Web addresses, with or without http(s)://: www.…, or a site with a path
// on a common ending (meet.google.com/abc-defg-hij).
const ADDRESS = /(?:https?:\/\/|www\.)[^\s<>"'`]+|\b(?:[a-z0-9-]+\.)+(?:com|in|org|net|io|dev|app|co|edu|gov|me|ai)\/[^\s<>"'`]*/gi;

// "address <address>" said once, and "words <address>" without the brackets.
function unbracketed(text) {
    let source = (text || "").replace(/\r\n/g, "\n");
    // "address <address>" → "address"; a different second address stays.
    source = source.replace(/(https?:\/\/[^\s<>]+)\s*<((?:https?:\/\/|mailto:)[^\s<>]+)>/g,
        (all, first, second) => sameAddress(first, second) ? first : `${first} ${second}`);
    // "words <address>" → "words address".
    return source.replace(/<((?:https?:\/\/|mailto:)[^\s<>]+)>/g, "$1");
}

// Text with its web addresses as links; `plain(segment)` escapes (and may
// format) what's between them. Links show the site unless `wholeLinks`
// (teach mode, which must map a selection back to the text).
function linkify(source, color, wholeLinks, plain) {
    let out = "";
    let last = 0;
    ADDRESS.lastIndex = 0;
    let match;
    while ((match = ADDRESS.exec(source)) !== null) {
        // Sentence punctuation (and a closing *) after an address isn't part of it.
        const url = match[0].replace(/[.,;:!?*)\]'"]+$/, "");
        if (!url)
            continue;
        const href = /^https?:\/\//i.test(url) ? url : `https://${url}`;
        const text = escape(wholeLinks ? url : shown(url));
        const label = color ? `<font color="${color}">${text}</font>` : text;
        out += plain(source.slice(last, match.index)) + `<a href="${escape(href)}">${label}</a>`;
        last = match.index + url.length;
        ADDRESS.lastIndex = last;
    }
    return out + plain(source.slice(last));
}

function linked(text, color, wholeLinks) {
    let out = linkify(unbracketed(text), color, !!wholeLinks, escape);
    out = out.replace(/\n/g, "<br>");

    // *bold*: opens before a non-space, closes after one (spaces before the
    // closing * are allowed: Gmail writes "text  *"), may span lines but not
    // a blank line, and never sits inside a word or between numbers.
    out = out.replace(/(^|[\s(>;])\*([^\s*](?:(?!<br><br>)[^*]){0,400}?)\s*\*(?=$|[\s).,;:!?<&])/g, "$1<b>$2</b>");
    // _italic_: one line, no underscores or tags inside (snake_case stays).
    out = out.replace(/(^|[\s(>;])_([^\s_<](?:[^_<\n]{0,200}?[^\s_<])?)_(?=$|[\s).,;:!?<&])/g, "$1<i>$2</i>");
    return out;
}

// Text without its HTML comments, in one pass (an unclosed one ends it).
function uncommented(text) {
    let out = "";
    let at = 0;
    for (;;) {
        const open = text.indexOf("<!--", at);
        if (open < 0)
            return out + text.slice(at);
        out += text.slice(at, open);
        const close = text.indexOf("-->", open + 4);
        if (close < 0)
            return out;
        at = close + 3;
    }
}

// Whether a link's label reads as a web address, and a link's site.
function looksLikeAddress(label) {
    return /^\s*(?:https?:\/\/|www\.)\S+|^\s*[\w-]+(?:\.[\w-]+)+(?:[\/?#]\S*)?\s*$/i.test(label);
}

// The authority part (user:pass@host:port) of an address.
function authority(address) {
    return address.trim().toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split(/[\/?#\\]/)[0];
}

// The host, after any user:password@ (which a link can use to look like
// another site) and without the port.
function host(address) {
    const part = authority(address);
    return part.slice(part.lastIndexOf("@") + 1).split(":")[0].replace(/^www\./, "");
}

// Whether a link's address could pass for another: a user:password@ or a
// backslash in front of the host.
function disguised(address) {
    return authority(address).includes("@") || address.includes("\\");
}

// HTML entities some senders leave in their text part (&#x27;, &quot;).
function decoded(text) {
    const named = { quot: '"', amp: "&", apos: "'", lt: "<", gt: ">", nbsp: " " };
    return text.replace(/&(#x[0-9a-f]{1,6}|#[0-9]{1,7}|quot|amp|apos|lt|gt|nbsp);/gi, (all, name) => {
        const key = name.toLowerCase();
        if (key[0] !== "#")
            return named[key];
        const code = key[1] === "x" ? parseInt(key.slice(2), 16) : parseInt(key.slice(1), 10);
        return code > 0 && code < 0x110000 ? String.fromCodePoint(code) : all;
    });
}

// The plain view: a notification's text part drawn natively, in the app's
// fonts and colours. Links work (shortened unless `wholeLinks`); quotes,
// lists and code-ish text (indented or diff lines, `code`, commit hashes,
// file paths) are formatted lightly; with `footer` (an offset into the text,
// from the engine) the footer folds into one small line. Teach mode reads
// this view by its visible characters, so formatting may drop markers
// freely; it turns `footer` off (-1) and `wholeLinks` on.
//
// colors: { text, muted, link, code } (code: the tint behind code)
function formatted(text, colors, options) {
    const opts = options || {};
    const c = colors || {};
    let source = (text || "").replace(/\r\n/g, "\n");
    let footer = "";
    if (typeof opts.footer === "number" && opts.footer >= 0) {
        // The engine's offset counts characters (code points); a JS index
        // counts UTF-16 units, and an emoji is two of them. (Counted by
        // hand: QML's engine iterates strings by units.)
        let unit = 0;
        for (let seen = 0; unit < source.length && seen < opts.footer; seen++) {
            const code = source.charCodeAt(unit);
            unit += code >= 0xD800 && code <= 0xDBFF && unit + 1 < source.length ? 2 : 1;
        }
        if (unit < source.length) {
            footer = source.slice(unit);
            source = source.slice(0, unit);
        }
    }
    // GitHub sends a comment's Markdown as its text: HTML comments go, and
    // so do the few tags it allows (outside code), <br> becoming a line.
    // (The link placeholders below can't come from the email.)
    source = uncommented(unbracketed(decoded(source)).replace(/[\uE000\uE001]/g, "")).replace(/\s+$/, "");
    footer = decoded(footer);
    const untagged = line => line.replace(/<br\s*\/?>/gi, " ").replace(/<\/?(?:details|summary|sub|sup|p|div|span|b|strong|i|em|kbd|code|img|picture|source|a)\b[^<>]*>/gi, "");
    // Declared before use (QML warns otherwise): inline code, then code spans.
    const tt = code => `<code style="background-color:${c.code || "transparent"}">${code}</code>`;
    const codeSpans = segment => escape(segment)
        .replace(/\*\*([^*\n]+?)\*\*/g, "<b>$1</b>")
        .replace(/`([^`\n]+)`/g, (all, code) => tt(code))
        // Commit hashes (7–40 hex, a digit and a letter) and file paths.
        .replace(/(^|[\s(\[])((?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40})(?=$|[\s).,;:\]])/g, (all, before, hash) => before + tt(hash))
        .replace(/(^|[\s(\[])((?:[\w.-]+\/)+[\w.-]+\.[a-z0-9]{1,8})(?=$|[\s).,;:\]])/gi, (all, before, path) => before + tt(path));
    // [label](address) shows its label as the link; ![image](address) goes.
    const inline = line => {
        const marked = [];
        const text = untagged(line)
            .replace(/!\[[^\]\n]*\]\([^)\s]+\)/g, "")
            .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, (all, label, href) => {
                marked.push({ label, href });
                return `\uE000${marked.length - 1}\uE001`;
            });
        return linkify(text, c.link, !!opts.wholeLinks, codeSpans).replace(/\uE000(\d+)\uE001/g, (all, n) => {
            const link = marked[Number(n)];
            if (!link)
                return "";
            // A label that reads as an address but leads elsewhere says where.
            const spoof = disguised(link.href) || (looksLikeAddress(link.label) && host(link.label) !== host(link.href));
            const label = opts.wholeLinks ? `${link.label} (${link.href})` : spoof ? `${link.label} (${shown(link.href)})` : link.label;
            return `<a href="${escape(link.href)}"><font color="${c.link || ""}">${escape(label)}</font></a>`;
        });
    };

    const lines = source.split("\n");
    const blocks = [];
    let index = 0;
    const run = test => {
        const taken = [];
        while (index < lines.length && test(lines[index]))
            taken.push(lines[index++]);
        return taken;
    };
    const isQuote = line => /^\s*>/.test(line);
    const isItem = line => /^\s{0,3}(?:[-*•]|\d{1,3}[.)])\s+\S/.test(line);
    const isFence = line => /^\s*```/.test(line);
    const isCode = line => /^(?: {4}|\t)\S/.test(line) || /^(?:@@ |\+\+\+ |--- |diff --git )/.test(line);
    while (index < lines.length) {
        const line = lines[index];
        // A line of nothing but tags (<br/>, </details>) is a blank line.
        if (!untagged(line).trim()) {
            index++;
            blocks.push("");
            continue;
        }
        if (isFence(line)) {
            // A fenced block (```suggestion too): code, as written.
            index++;
            const code = run(l => !isFence(l));
            index++;
            blocks.push(`<table width="100%" cellspacing="0" cellpadding="8" bgcolor="${c.code || "transparent"}"><tr><td>`
                + `<pre style="white-space:pre-wrap;margin:0">${code.map(escape).join("\n")}</pre></td></tr></table>`);
            continue;
        }
        if (isQuote(line)) {
            const quoted = run(isQuote).map(q => q.replace(/^\s*>\s?/, ""));
            blocks.push(`<blockquote style="margin-left:12px"><font color="${c.muted || ""}">${quoted.map(inline).join("<br>")}</font></blockquote>`);
            continue;
        }
        if (isItem(line)) {
            const items = run(l => isItem(l) || (/^\s{2,}\S/.test(l) && !isCode(l) && !isFence(l)));
            const ordered = /^\s*\d/.test(items[0]);
            const merged = [];
            for (const item of items) {
                if (isItem(item))
                    merged.push(item.replace(/^\s*(?:[-*•+]|\d{1,3}[.)])\s+/, ""));
                else
                    merged[merged.length - 1] += " " + item.trim();
            }
            const tag = ordered ? "ol" : "ul";
            blocks.push(`<${tag} style="margin-top:2px;margin-bottom:2px">${merged.map(item => `<li>${inline(item)}</li>`).join("")}</${tag}>`);
            continue;
        }
        if (isCode(line)) {
            const code = run(l => isCode(l) || /^[+-]/.test(l) && /^(?: {4}|\t|[+-])/.test(l));
            // Indented code loses the indent that marked it.
            const indent = Math.min(...code.map(l => l.match(/^ */)[0].length));
            const shown = code.map(l => l.slice(indent));
            blocks.push(`<table width="100%" cellspacing="0" cellpadding="8" bgcolor="${c.code || "transparent"}"><tr><td>`
                + `<pre style="white-space:pre-wrap;margin:0">${shown.map(escape).join("\n")}</pre></td></tr></table>`);
            continue;
        }
        const heading = line.match(/^#{1,6}\s+(.*)$/);
        if (heading) {
            index++;
            blocks.push(`<b>${inline(heading[1])}</b>`);
            continue;
        }
        const paragraph = run(l => l.trim() !== "" && !isQuote(l) && !isItem(l) && !isCode(l) && !isFence(l) && !/^#{1,6}\s/.test(l));
        blocks.push(paragraph.map(inline).join("<br>"));
    }
    // Blank lines between blocks: one gap, however many there were.
    let out = "";
    let gap = false;
    for (const block of blocks) {
        if (block === "") {
            gap = out !== "";
            continue;
        }
        const isBlock = /^<(?:ul|ol|table|blockquote)/.test(block);
        out += (out && !isBlock ? (gap ? "<br><br>" : "<br>") : "") + block;
        gap = false;
    }
    if (footer.trim()) {
        const folded = unbracketed(footer).split("\n").map(l => l.trim())
            .filter(l => l && !/^(?:—|–|--|-- |_{3,}|-{3,}|={3,}|\*{3,})$/.test(l) && !/^Message ID:/i.test(l)).join(" · ");
        out += `<p style="margin-top:14px;font-size:12px"><font color="${c.muted || ""}">${linkify(folded, c.muted, !!opts.wholeLinks, escape)}</font></p>`;
    }
    return out;
}
