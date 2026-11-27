.pragma library

// Junco Command Palette (Ctrl+K): command parsing, shorthand time/duration
// parsing, fuzzy scoring/ranking, and tab completion shared by Mail & Calendar.
//
// Pure functions with explicit `nowDate` parameters so every path is fast (<1 ms,
// zero subprocess spawn per keystroke) and deterministically unit-testable.

// Date & time helpers ---------------------------------------------------------

function pad2(n) {
    return String(Math.floor(n)).padStart(2, "0");
}

function formatDay(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function formatIsoLocal(d) {
    return `${formatDay(d)}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function parseIsoDay(str) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((str || "").trim());
    if (!m)
        return null;
    const year = Number(m[1]);
    const month = Number(m[2]);
    const day = Number(m[3]);
    if (month < 1 || month > 12 || day < 1 || day > 31)
        return null;
    const d = new Date(year, month - 1, day);
    if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day)
        return null;
    return d;
}

function addDaysDate(base, count) {
    const d = new Date(base.getFullYear(), base.getMonth(), base.getDate(), base.getHours(), base.getMinutes(), 0, 0);
    d.setDate(d.getDate() + count);
    return d;
}

function addMonthsDate(base, months) {
    const total = base.getFullYear() * 12 + base.getMonth() + months;
    const year = Math.floor(total / 12);
    const month = ((total % 12) + 12) % 12;
    const maxDay = new Date(year, month + 1, 0).getDate();
    const day = Math.min(base.getDate(), maxDay);
    return new Date(year, month, day, base.getHours(), base.getMinutes(), 0, 0);
}

function formatClock(totalMinutes) {
    const wrapped = ((totalMinutes % 1440) + 1440) % 1440;
    const hour = Math.floor(wrapped / 60);
    const minute = wrapped % 60;
    const h12 = hour % 12 === 0 ? 12 : hour % 12;
    const ampm = hour < 12 ? "am" : "pm";
    return `${h12}:${pad2(minute)} ${ampm}`;
}

function formatShortDay(dayStr, todayStr) {
    if (!dayStr)
        return "";
    if (dayStr === todayStr)
        return "Today";
    const todayDate = parseIsoDay(todayStr);
    const targetDate = parseIsoDay(dayStr);
    if (!todayDate || !targetDate)
        return dayStr;
    const diff = Math.round((targetDate.getTime() - todayDate.getTime()) / 86400000);
    if (diff === 1)
        return "Tomorrow";
    if (diff === -1)
        return "Yesterday";
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const base = `${days[targetDate.getDay()]} ${targetDate.getDate()} ${months[targetDate.getMonth()]}`;
    return targetDate.getFullYear() === todayDate.getFullYear() ? base : `${base} ${targetDate.getFullYear()}`;
}

function formatWhenLabel(targetDate, nowDate) {
    const todayStr = formatDay(nowDate);
    const targetStr = formatDay(targetDate);
    const dayLabel = formatShortDay(targetStr, todayStr);
    return `${dayLabel}, ${pad2(targetDate.getHours())}:${pad2(targetDate.getMinutes())}`;
}

const WEEKDAYS = {
    sun: 0, sunday: 0,
    mon: 1, monday: 1,
    tue: 2, tues: 2, tuesday: 2,
    wed: 3, weds: 3, wednesday: 3,
    thu: 4, thur: 4, thurs: 4, thursday: 4,
    fri: 5, friday: 5,
    sat: 6, saturday: 6
};

// Parse clock time string like "9am", "4:30pm", "16:00", "noon", "midnight".
// Returns minutes from midnight (0..1439) or -1 if invalid.
function parseClockMinutes(token) {
    const raw = (token || "").trim().toLowerCase();
    if (!raw)
        return -1;
    if (raw === "noon")
        return 12 * 60;
    if (raw === "midnight")
        return 0;

    const ampmMatch = /^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$/.exec(raw);
    if (ampmMatch) {
        let hour = Number(ampmMatch[1]);
        const minute = ampmMatch[2] !== undefined ? Number(ampmMatch[2]) : 0;
        const suffix = ampmMatch[3];
        if (hour < 1 || hour > 12 || minute < 0 || minute > 59)
            return -1;
        if (suffix === "am")
            hour = hour === 12 ? 0 : hour;
        else
            hour = hour === 12 ? 12 : hour + 12;
        return hour * 60 + minute;
    }

    const milMatch = /^(\d{1,2}):(\d{2})$/.exec(raw);
    if (milMatch) {
        const hour = Number(milMatch[1]);
        const minute = Number(milMatch[2]);
        if (hour < 0 || hour > 23 || minute < 0 || minute > 59)
            return -1;
        return hour * 60 + minute;
    }

    return -1;
}

function nextWeekdayDate(nowDate, targetDow, forceNextWeek) {
    const currentDow = nowDate.getDay();
    let delta = (targetDow - currentDow + 7) % 7;
    if (delta === 0)
        delta = 7;
    if (forceNextWeek && delta < 7)
        delta += 7;
    return addDaysDate(nowDate, delta);
}

// Fuzzy matching & scoring ----------------------------------------------------

function isWordBoundary(text, index) {
    if (index === 0)
        return true;
    const prev = text.charAt(index - 1);
    return prev === " " || prev === "-" || prev === "_" || prev === "/" || prev === "." || prev === ":" || prev === "@" || prev === "(" || prev === "[";
}

function fuzzyScoreToken(needle, haystack) {
    if (!needle)
        return 1;
    if (!haystack)
        return 0;

    const nLen = needle.length;
    const hLen = haystack.length;
    if (nLen > hLen)
        return 0;

    if (haystack === needle)
        return 220;

    if (haystack.startsWith(needle))
        return 165 - Math.min(30, hLen - nLen);

    const substrIdx = haystack.indexOf(needle);
    if (substrIdx !== -1) {
        const boundaryBonus = isWordBoundary(haystack, substrIdx) ? 35 : 0;
        return 120 + boundaryBonus - Math.min(35, substrIdx) - Math.min(18, Math.floor((hLen - nLen) / 4));
    }

    // Subsequence match with word-boundary and streak bonuses.
    let score = 0;
    let hi = 0;
    let firstMatch = -1;
    let prevMatch = -2;
    let streak = 0;
    let maxGap = 0;
    let boundaryHits = 0;

    for (let ni = 0; ni < nLen; ni++) {
        const ch = needle.charAt(ni);
        let found = -1;
        // Prefer a word-boundary occurrence if available.
        for (let scan = hi; scan < hLen; scan++) {
            if (haystack.charAt(scan) === ch) {
                if (found === -1)
                    found = scan;
                if (isWordBoundary(haystack, scan)) {
                    found = scan;
                    break;
                }
            }
        }
        if (found === -1)
            return 0;

        if (firstMatch === -1)
            firstMatch = found;
        if (isWordBoundary(haystack, found))
            boundaryHits++;
        if (prevMatch >= 0) {
            const gap = found - prevMatch - 1;
            if (gap > maxGap)
                maxGap = gap;
        }

        if (found === prevMatch + 1) {
            streak++;
            score += 12 + Math.min(12, streak * 3);
        } else {
            streak = 0;
            score += 6;
            if (isWordBoundary(haystack, found))
                score += 14;
            if (prevMatch >= 0)
                score -= Math.min(8, found - prevMatch - 1);
        }
        prevMatch = found;
        hi = found + 1;
    }

    // Reject accidental ultra-sparse matches across unrelated words unless
    // it's an acronym/initialism (most chars hit word boundaries).
    const span = prevMatch - firstMatch + 1;
    const isAcronym = boundaryHits >= Math.ceil(nLen * 0.65);
    if (!isAcronym && nLen >= 4 && (span > nLen * 3 || maxGap > 7))
        return 0;

    return Math.max(1, score - Math.min(20, Math.floor((hLen - nLen) / 5)));
}

function fuzzyScore(rawQuery, target) {
    const q = (rawQuery || "").trim().toLowerCase();
    const t = (target || "").toLowerCase();
    if (!q)
        return { matched: true, score: 1 };
    if (!t)
        return { matched: false, score: 0 };

    const tokens = q.split(/\s+/).filter(Boolean);
    let total = 0;
    for (let i = 0; i < tokens.length; i++) {
        const s = fuzzyScoreToken(tokens[i], t);
        if (s <= 0)
            return { matched: false, score: 0 };
        total += s;
    }
    return { matched: true, score: Math.round(total / tokens.length) + (tokens.length > 1 ? 10 : 0) };
}

function fuzzyScoreFields(rawQuery, fields) {
    const q = (rawQuery || "").trim().toLowerCase();
    if (!q)
        return { matched: true, score: 1 };

    // First check best single-field weighted score.
    let best = 0;
    const parts = [];
    for (let i = 0; i < fields.length; i++) {
        const entry = fields[i];
        const text = (entry.text || "").trim();
        if (!text)
            continue;
        parts.push(text);
        const res = fuzzyScore(q, text);
        if (res.matched) {
            const weighted = Math.round(res.score * (entry.weight || 1));
            if (weighted > best)
                best = weighted;
        }
    }
    if (best > 0)
        return { matched: true, score: best };

    // Multi-word queries can span multiple fields (e.g. sender + subject).
    const combined = parts.join(" ");
    const combinedRes = fuzzyScore(q, combined);
    if (combinedRes.matched)
        return { matched: true, score: Math.max(1, Math.round(combinedRes.score * 0.85)) };
    return { matched: false, score: 0 };
}

// Mail smart command parsers --------------------------------------------------

const EXPIRY_UNITS = {
    h: { short: "h", singular: "hour", plural: "hours" },
    hr: { short: "h", singular: "hour", plural: "hours" },
    hrs: { short: "h", singular: "hour", plural: "hours" },
    hour: { short: "h", singular: "hour", plural: "hours" },
    hours: { short: "h", singular: "hour", plural: "hours" },
    d: { short: "d", singular: "day", plural: "days" },
    day: { short: "d", singular: "day", plural: "days" },
    days: { short: "d", singular: "day", plural: "days" },
    w: { short: "w", singular: "week", plural: "weeks" },
    wk: { short: "w", singular: "week", plural: "weeks" },
    wks: { short: "w", singular: "week", plural: "weeks" },
    week: { short: "w", singular: "week", plural: "weeks" },
    weeks: { short: "w", singular: "week", plural: "weeks" },
    m: { short: "m", singular: "month", plural: "months" },
    mo: { short: "m", singular: "month", plural: "months" },
    mos: { short: "m", singular: "month", plural: "months" },
    month: { short: "m", singular: "month", plural: "months" },
    months: { short: "m", singular: "month", plural: "months" },
    y: { short: "y", singular: "year", plural: "years" },
    yr: { short: "y", singular: "year", plural: "years" },
    yrs: { short: "y", singular: "year", plural: "years" },
    year: { short: "y", singular: "year", plural: "years" },
    years: { short: "y", singular: "year", plural: "years" }
};

function parseDurationSpec(specText, nowDate) {
    const now = nowDate || new Date();
    const trimmed = (specText || "").trim();
    if (!trimmed)
        return null;

    // Explicit ISO date: YYYY-MM-DD
    const dateObj = parseIsoDay(trimmed);
    if (dateObj) {
        const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        if (dateObj.getTime() <= todayMidnight.getTime()) {
            return { error: "Pick a future date (YYYY-MM-DD)." };
        }
        return {
            spec: formatDay(dateObj),
            canonical: formatDay(dateObj),
            human: formatDay(dateObj),
            badge: formatDay(dateObj),
            previewDate: formatDay(dateObj),
            isDate: true
        };
    }

    const durMatch = /^(\d+)\s*([a-zA-Z]+)$/.exec(trimmed);
    if (!durMatch)
        return null;
    const amount = Number(durMatch[1]);
    const unitInfo = EXPIRY_UNITS[durMatch[2].toLowerCase()];
    if (!unitInfo)
        return null;
    if (amount <= 0)
        return { error: "Duration must be greater than zero." };

    let target;
    if (unitInfo.short === "h")
        target = new Date(now.getTime() + amount * 3600000);
    else if (unitInfo.short === "d")
        target = addDaysDate(now, amount);
    else if (unitInfo.short === "w")
        target = addDaysDate(now, amount * 7);
    else if (unitInfo.short === "m")
        target = addMonthsDate(now, amount);
    else
        target = addMonthsDate(now, amount * 12);

    const canonical = `${amount}${unitInfo.short}`;
    const human = `${amount} ${amount === 1 ? unitInfo.singular : unitInfo.plural}`;
    return {
        spec: canonical,
        canonical: canonical,
        human: human,
        badge: `${canonical} expiry`,
        previewDate: formatDay(target),
        isDate: false
    };
}

function parseExpiryCommand(rawQuery, nowDate) {
    const now = nowDate || new Date();
    const match = /^\s*(exp|expire)(?:\s+(.*))?$/i.exec(rawQuery || "");
    if (!match)
        return null;

    const rest = (match[2] || "").trim();
    if (!rest) {
        return { kind: "expiry", mode: "suggest" };
    }

    const clearWord = rest.toLowerCase();
    if (clearWord === "clear" || clearWord === "cancel" || clearWord === "off" || clearWord === "none" || clearWord === "remove") {
        return { kind: "expiry", mode: "clear" };
    }

    // Support both "exp 2y college" and "exp 2 years college".
    const tokens = rest.split(/\s+/);
    let parsed = parseDurationSpec(tokens[0], now);
    let noteTokens = tokens.slice(1);

    if (!parsed && tokens.length >= 2 && /^\d+$/.test(tokens[0])) {
        parsed = parseDurationSpec(`${tokens[0]}${tokens[1]}`, now);
        if (parsed)
            noteTokens = tokens.slice(2);
    }

    if (!parsed) {
        return {
            kind: "expiry",
            mode: "invalid",
            error: "Try 7d, 30d, 6m, 1y, 2y, YYYY-MM-DD, or clear."
        };
    }
    if (parsed.error) {
        return { kind: "expiry", mode: "invalid", error: parsed.error };
    }

    return {
        kind: "expiry",
        mode: "set",
        spec: parsed.spec,
        canonical: parsed.canonical,
        human: parsed.human,
        badge: parsed.badge,
        previewDate: parsed.previewDate,
        isDate: parsed.isDate,
        note: noteTokens.join(" ").trim()
    };
}

function parseSnoozeCommand(rawQuery, nowDate) {
    const now = nowDate || new Date();
    const match = /^\s*(snooze|later)(?:\s+(.*))?$/i.exec(rawQuery || "");
    if (!match)
        return null;

    const rest = (match[2] || "").trim();
    if (!rest) {
        return { kind: "snooze", mode: "suggest" };
    }

    const lower = rest.toLowerCase().replace(/\s+/g, " ");
    let target = null;

    // 1. Relative shorthand: "2h", "30m", "3d", "1w", "2 hours", "45 mins"
    const relMatch = /^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks)$/i.exec(lower);
    if (relMatch) {
        const amount = Number(relMatch[1]);
        const unit = relMatch[2].toLowerCase();
        if (amount <= 0)
            return { kind: "snooze", mode: "invalid", error: "Pick a future duration (e.g. 30m, 2h, 3d)." };
        if (unit.startsWith("m"))
            target = new Date(now.getTime() + amount * 60000);
        else if (unit.startsWith("h"))
            target = new Date(now.getTime() + amount * 3600000);
        else if (unit.startsWith("d"))
            target = new Date(now.getTime() + amount * 86400000);
        else
            target = new Date(now.getTime() + amount * 7 * 86400000);
    }

    // 2. Named presets: "later today", "tonight", "next week", "weekend"
    if (!target) {
        if (lower === "today" || lower === "later today") {
            const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 18, 0, 0, 0);
            target = now.getHours() < 15 ? candidate : new Date(now.getTime() + 2 * 3600000);
        } else if (lower === "tonight" || lower === "evening" || lower === "this evening") {
            const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 19, 0, 0, 0);
            target = candidate.getTime() > now.getTime() + 15 * 60000 ? candidate : addDaysDate(candidate, 1);
        } else if (lower === "next week" || lower === "nextweek") {
            const mon = nextWeekdayDate(now, 1, false);
            target = new Date(mon.getFullYear(), mon.getMonth(), mon.getDate(), 9, 0, 0, 0);
        } else if (lower === "weekend" || lower === "this weekend") {
            const sat = nextWeekdayDate(now, 6, false);
            target = new Date(sat.getFullYear(), sat.getMonth(), sat.getDate(), 9, 0, 0, 0);
        }
    }

    // 3. "tomorrow [at] [time]" / "tmr [time]"
    if (!target) {
        const tmrMatch = /^(?:tomorrow|tmr)(?:\s+(?:at\s+)?(.+))?$/i.exec(lower);
        if (tmrMatch) {
            const base = addDaysDate(now, 1);
            const mins = tmrMatch[1] ? parseClockMinutes(tmrMatch[1]) : 9 * 60;
            if (mins < 0)
                return { kind: "snooze", mode: "invalid", error: `Couldn't read time "${tmrMatch[1]}". Try "tomorrow 9am".` };
            target = new Date(base.getFullYear(), base.getMonth(), base.getDate(), Math.floor(mins / 60), mins % 60, 0, 0);
        }
    }

    // 4. "[next] <weekday> [at] [time]"
    if (!target) {
        const wdMatch = /^(?:(next)\s+)?([a-z]+)(?:\s+(?:at\s+)?(.+))?$/i.exec(lower);
        if (wdMatch && WEEKDAYS[wdMatch[2]] !== undefined) {
            const forceNext = Boolean(wdMatch[1]);
            const base = nextWeekdayDate(now, WEEKDAYS[wdMatch[2]], forceNext);
            const mins = wdMatch[3] ? parseClockMinutes(wdMatch[3]) : 9 * 60;
            if (mins < 0)
                return { kind: "snooze", mode: "invalid", error: `Couldn't read time "${wdMatch[3]}". Try "${wdMatch[2]} 9am".` };
            target = new Date(base.getFullYear(), base.getMonth(), base.getDate(), Math.floor(mins / 60), mins % 60, 0, 0);
        }
    }

    // 5. Explicit ISO date "[YYYY-MM-DD] [time]"
    if (!target) {
        const isoMatch = /^(\d{4}-\d{2}-\d{2})(?:\s+(?:at\s+)?(.+))?$/i.exec(lower);
        if (isoMatch) {
            const base = parseIsoDay(isoMatch[1]);
            if (!base)
                return { kind: "snooze", mode: "invalid", error: "Invalid date. Use YYYY-MM-DD." };
            const mins = isoMatch[2] ? parseClockMinutes(isoMatch[2]) : 9 * 60;
            if (mins < 0)
                return { kind: "snooze", mode: "invalid", error: `Couldn't read time "${isoMatch[2]}".` };
            target = new Date(base.getFullYear(), base.getMonth(), base.getDate(), Math.floor(mins / 60), mins % 60, 0, 0);
        }
    }

    // 6. Bare clock time: "5pm", "17:30", "at 4pm" -> today, or tomorrow if already passed.
    if (!target) {
        const stripped = lower.replace(/^at\s+/, "");
        const mins = parseClockMinutes(stripped);
        if (mins >= 0) {
            const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), Math.floor(mins / 60), mins % 60, 0, 0);
            target = candidate.getTime() > now.getTime() + 60000 ? candidate : addDaysDate(candidate, 1);
        }
    }

    if (!target) {
        return {
            kind: "snooze",
            mode: "invalid",
            error: "Try 2h, tomorrow 9am, next week, or Fri 10am."
        };
    }

    if (target.getTime() <= now.getTime()) {
        return {
            kind: "snooze",
            mode: "invalid",
            error: "Pick a snooze time in the future."
        };
    }

    return {
        kind: "snooze",
        mode: "set",
        untilIso: formatIsoLocal(target),
        label: formatWhenLabel(target, now),
        epochMs: target.getTime()
    };
}

function parseFromQuery(rawQuery) {
    const match = /^\s*from:\s*(.*)$/i.exec(rawQuery || "");
    if (!match)
        return null;
    const body = match[1].trim();
    if (!body)
        return { kind: "from", senderNeedle: "", extraNeedle: "" };

    // Support quoted sender: from:"Alex Rivera" budget
    const quotedMatch = /^"([^"]+)"(?:\s+(.*))?$/.exec(body);
    if (quotedMatch) {
        return {
            kind: "from",
            senderNeedle: quotedMatch[1].trim(),
            extraNeedle: (quotedMatch[2] || "").trim()
        };
    }

    const parts = body.split(/\s+/);
    return {
        kind: "from",
        senderNeedle: parts[0] || "",
        extraNeedle: parts.slice(1).join(" ").trim()
    };
}

// Calendar smart command parsers ----------------------------------------------

function parseTodoCommand(rawQuery) {
    const match = /^\s*(todo|task|add)(?:\s+(.*))?$/i.exec(rawQuery || "");
    if (!match)
        return null;
    const text = (match[2] || "").trim();
    return {
        kind: "todo",
        mode: text ? "add" : "prompt",
        keyword: match[1].toLowerCase(),
        text: text
    };
}

function parseTimeRangeExpression(expr) {
    // Matches "4pm-5pm", "4-5:30pm", "14:00-15:30", "9:30am to 11am"
    const m = /^(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|–|to)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)$/i.exec((expr || "").trim());
    if (!m)
        return null;
    let leftRaw = m[1].trim().toLowerCase();
    const rightRaw = m[2].trim().toLowerCase();

    // Inherit am/pm from right side if left has none (e.g. "4-5pm" -> "4pm", "5pm").
    const rightAmPm = /(am|pm)$/.exec(rightRaw);
    if (rightAmPm && !/(am|pm)$/.test(leftRaw) && !leftRaw.includes(":")) {
        leftRaw = leftRaw + rightAmPm[1];
    } else if (rightAmPm && !/(am|pm)$/.test(leftRaw)) {
        leftRaw = leftRaw + rightAmPm[1];
    }

    const startMin = parseClockMinutes(leftRaw);
    const endMin = parseClockMinutes(rightRaw);
    if (startMin < 0 || endMin < 0)
        return null;
    const adjustedEnd = endMin <= startMin ? endMin + 1440 : endMin;
    return { startMinutes: startMin, endMinutes: adjustedEnd };
}

function parseDurationMinutes(token) {
    const m = /^(\d+(?:\.\d+)?)\s*(m|min|mins|h|hr|hrs)$/i.exec((token || "").trim());
    if (!m)
        return -1;
    const val = Number(m[1]);
    if (!Number.isFinite(val) || val <= 0)
        return -1;
    const unit = m[2].toLowerCase();
    return unit.startsWith("h") ? Math.round(val * 60) : Math.round(val);
}

function parseQuickEventCommand(rawQuery, nowDate, selectedDay) {
    const now = nowDate || new Date();
    const todayStr = formatDay(now);
    const match = /^\s*(new|event)(?:\s+(.*))?$/i.exec(rawQuery || "");
    if (!match)
        return null;

    const rest = (match[2] || "").trim();
    if (!rest) {
        return { kind: "event", mode: "prompt", keyword: match[1].toLowerCase() };
    }

    const tokens = rest.split(/\s+/);
    let day = selectedDay || todayStr;
    let hasExplicitDay = false;
    let startMinutes = -1;
    let endMinutes = -1;
    let durationMinutes = -1;
    const kept = [];

    for (let i = 0; i < tokens.length; i++) {
        const tok = tokens[i];
        const low = tok.toLowerCase();
        const nextTok = i + 1 < tokens.length ? tokens[i + 1] : "";
        const nextLow = nextTok.toLowerCase();

        // Duration: "for 30m", "for 1h"
        if (low === "for" && nextTok && durationMinutes < 0) {
            const dur = parseDurationMinutes(nextTok);
            if (dur > 0) {
                durationMinutes = dur;
                i++;
                continue;
            }
        }

        // Time range spanning 3 tokens: "9am to 10:30am" or "4 - 5pm"
        if (startMinutes < 0 && i + 2 < tokens.length && (nextLow === "to" || nextLow === "-" || nextLow === "–")) {
            const range = parseTimeRangeExpression(`${tok} ${nextTok} ${tokens[i + 2]}`);
            if (range) {
                startMinutes = range.startMinutes;
                endMinutes = range.endMinutes;
                i += 2;
                continue;
            }
        }

        // Single-token time range: "4pm-5pm", "14:00-15:30", "4-5:30pm"
        if (startMinutes < 0 && /[-–]/.test(tok)) {
            const range = parseTimeRangeExpression(tok);
            if (range) {
                startMinutes = range.startMinutes;
                endMinutes = range.endMinutes;
                continue;
            }
        }

        // "at 4pm" / "at 16:00"
        if (low === "at" && nextTok && startMinutes < 0) {
            const mins = parseClockMinutes(nextTok);
            if (mins >= 0) {
                startMinutes = mins;
                i++;
                continue;
            }
        }

        // Standalone clock time: "4pm", "10:30am", "16:00", "noon"
        if (startMinutes < 0) {
            const mins = parseClockMinutes(tok);
            if (mins >= 0) {
                startMinutes = mins;
                continue;
            }
        }

        // Trailing duration right after a parsed time (e.g. "4pm 30m")
        if (startMinutes >= 0 && endMinutes < 0 && durationMinutes < 0) {
            const dur = parseDurationMinutes(tok);
            if (dur > 0) {
                durationMinutes = dur;
                continue;
            }
        }

        // Day tokens: "today", "tomorrow", "tmr", "YYYY-MM-DD", "next mon", "fri"
        if (!hasExplicitDay) {
            if (low === "today") {
                day = todayStr;
                hasExplicitDay = true;
                continue;
            }
            if (low === "tomorrow" || low === "tmr") {
                day = formatDay(addDaysDate(now, 1));
                hasExplicitDay = true;
                continue;
            }
            const parsedDay = parseIsoDay(tok);
            if (parsedDay) {
                day = formatDay(parsedDay);
                hasExplicitDay = true;
                continue;
            }
            if (low === "next" && nextLow && WEEKDAYS[nextLow] !== undefined) {
                day = formatDay(nextWeekdayDate(now, WEEKDAYS[nextLow], true));
                hasExplicitDay = true;
                i++;
                continue;
            }
            if (WEEKDAYS[low] !== undefined && (i > 0 || tokens.length > 1)) {
                day = formatDay(nextWeekdayDate(now, WEEKDAYS[low], false));
                hasExplicitDay = true;
                continue;
            }
        }

        kept.push(tok);
    }

    const title = kept.join(" ").trim();
    if (!title) {
        return { kind: "event", mode: "prompt", keyword: match[1].toLowerCase() };
    }

    const hasExplicitTime = startMinutes >= 0;
    if (!hasExplicitTime) {
        startMinutes = day === todayStr ? Math.min(23, now.getHours() + 1) * 60 : 9 * 60;
    }
    if (endMinutes < 0) {
        endMinutes = startMinutes + (durationMinutes > 0 ? durationMinutes : 60);
    }

    const dayLabel = formatShortDay(day, todayStr);
    const summary = `${dayLabel} · ${formatClock(startMinutes)} – ${formatClock(endMinutes)}`;

    return {
        kind: "event",
        mode: "create",
        title: title,
        day: day,
        startMinutes: startMinutes,
        endMinutes: endMinutes,
        hasExplicitTime: hasExplicitTime,
        hasExplicitDay: hasExplicitDay,
        summary: summary
    };
}

// Tab completion helper -------------------------------------------------------

const MAIL_PREFIXES = [
    { prefix: "exp", completion: "exp " },
    { prefix: "expire", completion: "expire " },
    { prefix: "snooze", completion: "snooze " },
    { prefix: "later", completion: "later " },
    { prefix: "from:", completion: "from:" }
];

const CALENDAR_PREFIXES = [
    { prefix: "todo", completion: "todo " },
    { prefix: "task", completion: "task " },
    { prefix: "add", completion: "add " },
    { prefix: "new", completion: "new " },
    { prefix: "event", completion: "event " }
];

function tabCompleteQuery(rawQuery, selectedItem, appMode) {
    if (selectedItem && selectedItem.tabComplete) {
        if ((rawQuery || "") !== selectedItem.tabComplete)
            return selectedItem.tabComplete;
    }

    const trimmed = (rawQuery || "").trim().toLowerCase();
    if (!trimmed || /\s/.test(trimmed))
        return rawQuery || "";

    const prefixes = appMode === "calendar" ? CALENDAR_PREFIXES : MAIL_PREFIXES;
    for (let i = 0; i < prefixes.length; i++) {
        if (prefixes[i].prefix.startsWith(trimmed) && trimmed !== prefixes[i].completion.trim()) {
            return prefixes[i].completion;
        }
    }
    return rawQuery || "";
}

// Mail palette ranking --------------------------------------------------------

function mailStaticCommands(ctx) {
    const cmds = [];
    const hasThread = Boolean(ctx.hasActiveThread);
    const activeLabel = (ctx.activeTitle || "").trim();

    if (hasThread) {
        cmds.push({
            id: "mail:reply",
            group: "Current thread",
            icon: "reply",
            title: "Reply",
            subtitle: activeLabel ? `Reply to ${activeLabel}` : "Reply to active thread",
            keywords: "reply respond answer",
            badge: "Action",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "reply" }
        });
        cmds.push({
            id: "mail:star",
            group: "Current thread",
            icon: "star",
            title: ctx.activeStarred ? "Unstar thread" : "Star thread",
            subtitle: activeLabel || "Toggle star on active thread",
            keywords: "star unstar flag favorite",
            badge: ctx.activeStarred ? "Starred" : "",
            badgeTone: "complement",
            shortcut: "",
            action: { type: "toggle_star" }
        });
        cmds.push({
            id: "mail:read",
            group: "Current thread",
            icon: ctx.activeUnread ? "drafts" : "mark_email_unread",
            title: ctx.activeUnread ? "Mark read" : "Mark unread",
            subtitle: activeLabel || "Toggle read state on active thread",
            keywords: "read unread mark seen unseen",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "toggle_read" }
        });
        cmds.push({
            id: "mail:archive",
            group: "Current thread",
            icon: "archive",
            title: "Archive",
            subtitle: activeLabel ? `Archive ${activeLabel}` : "Archive active thread",
            keywords: "archive done hide inbox",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "archive" }
        });
        cmds.push({
            id: "mail:schedule_delete",
            group: "Current thread",
            icon: "auto_delete",
            title: ctx.activeHasExpiry ? "Change scheduled delete…" : "Schedule delete…",
            subtitle: activeLabel ? `Auto-delete popover · or type "exp 2y"` : `Open Schedule Delete · or type "exp 2y"`,
            keywords: "schedule delete expire expiry auto-delete trash retention",
            badge: ctx.activeHasExpiry ? "Scheduled" : "exp 2y",
            badgeTone: "complement",
            shortcut: "",
            tabComplete: "exp ",
            action: { type: "open_schedule_delete" }
        });
    }

    // Core App & Navigation actions
    cmds.push(
        {
            id: "mail:compose",
            group: "Quick actions",
            icon: "edit",
            title: "Compose",
            subtitle: "Write a new email",
            keywords: "compose write new email draft send",
            badge: "",
            badgeTone: "",
            shortcut: "Ctrl N",
            action: { type: "compose" }
        },
        {
            id: "mail:sync",
            group: "Quick actions",
            icon: "sync",
            title: "Sync now",
            subtitle: "Fetch new mail and refresh folders",
            keywords: "sync refresh fetch check mail reload",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "sync" }
        },
        {
            id: "mail:toggle_sidebar",
            group: "Quick actions",
            icon: ctx.compactSidebar ? "left_panel_open" : "left_panel_close",
            title: "Toggle sidebar",
            subtitle: ctx.compactSidebar ? "Expand folder sidebar" : "Collapse sidebar to icon rail",
            keywords: "toggle sidebar collapse expand rail panel",
            badge: "",
            badgeTone: "",
            shortcut: "Ctrl \\",
            action: { type: "toggle_sidebar" }
        },
        {
            id: "mail:expiry_settings",
            group: "Quick actions",
            icon: "auto_delete",
            title: "Open Auto-Expiry Settings",
            subtitle: "Manage per-provider auto-delete rules",
            keywords: "auto expiry settings rules delete providers retention",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "open_expiry_settings" }
        },
        {
            id: "mail:open_calendar",
            group: "Quick actions",
            icon: "calendar_today",
            title: "Open Calendar",
            subtitle: "Switch to Junco Calendar",
            keywords: "open calendar schedule agenda events meetings",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "open_calendar" }
        },
        {
            id: "mail:toggle_glass",
            group: "Quick actions",
            icon: ctx.dark ? "light_mode" : "dark_mode",
            title: "Toggle Light / Dark glass",
            subtitle: ctx.dark ? "Switch to Light frosted glass" : "Switch to Dark frosted glass",
            keywords: "toggle theme light dark glass mode polarity appearance",
            badge: ctx.dark ? "Dark" : "Light",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "toggle_glass" }
        },
        // Navigation
        {
            id: "mail:jump_inbox",
            group: "Jump to",
            icon: "inbox",
            title: "Jump to Inbox",
            subtitle: "All conversations",
            keywords: "jump go inbox smart all",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "smart", lane: "all" }
        },
        {
            id: "mail:jump_people",
            group: "Jump to",
            icon: "person",
            title: "Jump to People",
            subtitle: "Human conversations lane",
            keywords: "jump go people chats humans lane",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "smart", lane: "people" }
        },
        {
            id: "mail:jump_updates",
            group: "Jump to",
            icon: "notifications",
            title: "Jump to Updates",
            subtitle: "Automated notifications & receipts",
            keywords: "jump go updates notifications receipts lane",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "smart", lane: "updates" }
        },
        {
            id: "mail:jump_newsletters",
            group: "Jump to",
            icon: "newspaper",
            title: "Jump to Newsletters",
            subtitle: "Subscriptions & digests",
            keywords: "jump go newsletters digests subscriptions",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "smart", lane: "newsletters" }
        },
        {
            id: "mail:jump_sent",
            group: "Jump to",
            icon: "send",
            title: "Jump to Sent",
            subtitle: "Messages you sent",
            keywords: "jump go sent outgoing",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "sent" }
        },
        {
            id: "mail:jump_starred",
            group: "Jump to",
            icon: "star",
            title: "Jump to Starred",
            subtitle: "Flagged and protected mail",
            keywords: "jump go starred flagged",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "starred" }
        },
        {
            id: "mail:jump_expiring",
            group: "Jump to",
            icon: "schedule",
            title: "Jump to Expiring",
            subtitle: "Threads scheduled for auto-deletion",
            keywords: "jump go expiring expiry scheduled delete",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "expiring" }
        },
        {
            id: "mail:jump_all",
            group: "Jump to",
            icon: "all_inbox",
            title: "Jump to All Mail",
            subtitle: "Every synced message",
            keywords: "jump go all mail everything",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "all" }
        },
        {
            id: "mail:jump_archive",
            group: "Jump to",
            icon: "archive",
            title: "Jump to Archive",
            subtitle: "Archived mail out of Inbox",
            keywords: "jump go archive archived",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump", folder: "archive" }
        }
    );

    return cmds;
}

function buildConversationRowItem(conv, groupName) {
    const subj = (conv.subject || "").trim() || (conv.preview || "").trim();
    const snip = (conv.snippet || conv.preview || "").trim();
    const subtitleParts = [];
    if (subj)
        subtitleParts.push(subj);
    if (snip && snip !== subj)
        subtitleParts.push(snip);
    const subtitle = subtitleParts.join(" · ") || conv.address || "";

    let badge = "";
    let badgeTone = "";
    if (conv.expiry && conv.expiry.remaining) {
        badge = conv.expiry.note ? `${conv.expiry.remaining} · ${conv.expiry.note}` : `Deletes ${conv.expiry.remaining}`;
        badgeTone = "complement";
    } else if (conv.unread > 0) {
        badge = conv.unread > 1 ? `${conv.unread} unread` : "Unread";
        badgeTone = "complement";
    }

    return {
        id: `conv:${conv.id}`,
        group: groupName || "Threads",
        icon: conv.kind === "person" ? "chat" : (conv.lane === "newsletters" ? "newspaper" : "mail"),
        title: conv.name || conv.address || "Conversation",
        subtitle: subtitle,
        badge: badge,
        badgeTone: badgeTone,
        shortcut: conv.time || "",
        action: { type: "open_conversation", id: conv.id }
    };
}

function rankMailItems(rawQuery, ctx, nowDate) {
    const context = ctx || {};
    const now = nowDate || new Date();
    const trimmed = (rawQuery || "").trim();
    const hasThread = Boolean(context.hasActiveThread);
    const activeName = (context.activeTitle || "active thread").trim();

    // 1. Empty query: context-aware suggestions
    if (!trimmed) {
        const all = mailStaticCommands(context);
        const top = [];
        // Keep current thread actions + top navigation & utilities concise and scannable
        const preferredIds = [
            "mail:reply", "mail:star", "mail:read", "mail:archive", "mail:schedule_delete",
            "mail:compose", "mail:sync", "mail:expiry_settings", "mail:open_calendar", "mail:toggle_glass", "mail:toggle_sidebar",
            "mail:jump_inbox", "mail:jump_people", "mail:jump_updates", "mail:jump_sent", "mail:jump_starred", "mail:jump_expiring"
        ];
        for (let i = 0; i < preferredIds.length; i++) {
            const found = all.find(c => c.id === preferredIds[i]);
            if (found)
                top.push(found);
        }
        return { modeBadge: "", modeBadgeTone: "", items: top };
    }

    // 2. Smart command: Auto-Expiry ("exp ...", "expire ...")
    const exp = parseExpiryCommand(trimmed, now);
    if (exp) {
        const items = [];
        if (exp.mode === "suggest") {
            const presets = [
                { spec: "7d", label: "Delete in 7 days", note: "" },
                { spec: "30d", label: "Delete in 30 days", note: "" },
                { spec: "1y", label: "Delete in 1 year", note: "" },
                { spec: "2y", label: "Delete in 2 years", note: "" }
            ];
            for (let i = 0; i < presets.length; i++) {
                const p = presets[i];
                const parsed = parseDurationSpec(p.spec, now);
                items.push({
                    id: `exp:preset:${p.spec}`,
                    group: "Smart command",
                    icon: "auto_delete",
                    title: `${p.label}${hasThread ? ` · ${activeName}` : ""}`,
                    subtitle: hasThread ? `Moves to Trash on ${parsed.previewDate} · or add a note like "exp ${p.spec} college"` : "Select or open a thread first",
                    badge: parsed.badge,
                    badgeTone: "complement",
                    shortcut: hasThread ? "↵" : "",
                    tabComplete: `exp ${p.spec} `,
                    disabled: !hasThread,
                    action: { type: "expiry_set", spec: p.spec, note: "", isDate: false }
                });
            }
            if (hasThread && context.activeHasExpiry) {
                items.push({
                    id: "exp:clear",
                    group: "Smart command",
                    icon: "undo",
                    title: `Clear scheduled delete · ${activeName}`,
                    subtitle: "Keep this thread permanently",
                    badge: "Cancel",
                    badgeTone: "primary",
                    shortcut: "↵",
                    action: { type: "expiry_clear" }
                });
            }
        } else if (exp.mode === "clear") {
            items.push({
                id: "exp:clear",
                group: "Smart command",
                icon: "undo",
                title: hasThread ? `Clear scheduled delete · ${activeName}` : "Clear scheduled delete",
                subtitle: hasThread ? "Cancel pending auto-deletion on this thread" : "Select or open a thread first",
                badge: "Clear",
                badgeTone: "complement",
                shortcut: hasThread ? "↵" : "",
                disabled: !hasThread,
                action: { type: "expiry_clear" }
            });
        } else if (exp.mode === "set") {
            const notePart = exp.note ? ` · note: ${exp.note}` : "";
            items.push({
                id: `exp:set:${exp.spec}:${exp.note}`,
                group: "Smart command",
                icon: "auto_delete",
                title: hasThread
                    ? `Delete "${activeName}" after ${exp.human}`
                    : `Schedule delete after ${exp.human}`,
                subtitle: hasThread
                    ? `Moves to Trash on ${exp.previewDate}${notePart}`
                    : "Select or open a thread first",
                badge: exp.note ? `${exp.canonical} · ${exp.note}` : exp.badge,
                badgeTone: "complement",
                shortcut: hasThread ? "↵" : "",
                disabled: !hasThread,
                action: { type: "expiry_set", spec: exp.spec, note: exp.note, isDate: exp.isDate }
            });
        } else {
            items.push({
                id: "exp:invalid",
                group: "Smart command",
                icon: "auto_delete",
                title: "Schedule thread auto-delete",
                subtitle: exp.error,
                badge: "Syntax",
                badgeTone: "error",
                disabled: true,
                tabComplete: "exp 2y ",
                action: { type: "noop" }
            });
        }
        return { modeBadge: "Auto-Expiry", modeBadgeTone: "complement", items: items };
    }

    // 3. Smart command: Snooze / Later ("snooze ...", "later ...")
    const snz = parseSnoozeCommand(trimmed, now);
    if (snz) {
        const items = [];
        if (snz.mode === "suggest") {
            const presets = [
                { expr: "2h", label: "Snooze 2 hours" },
                { expr: "tomorrow 9am", label: "Snooze until tomorrow 9am" },
                { expr: "next week", label: "Snooze until next week" }
            ];
            for (let i = 0; i < presets.length; i++) {
                const parsed = parseSnoozeCommand(`snooze ${presets[i].expr}`, now);
                items.push({
                    id: `snooze:preset:${presets[i].expr}`,
                    group: "Smart command",
                    icon: "snooze",
                    title: `${presets[i].label}${hasThread ? ` · ${activeName}` : ""}`,
                    subtitle: hasThread ? `Archives now, returns ${parsed.label}` : "Select or open a thread first",
                    badge: parsed.label,
                    badgeTone: "complement",
                    shortcut: hasThread ? "↵" : "",
                    tabComplete: `snooze ${presets[i].expr}`,
                    disabled: !hasThread,
                    action: { type: "snooze", untilIso: parsed.untilIso, label: parsed.label }
                });
            }
        } else if (snz.mode === "set") {
            items.push({
                id: `snooze:set:${snz.untilIso}`,
                group: "Smart command",
                icon: "snooze",
                title: hasThread ? `Snooze "${activeName}"` : "Snooze thread",
                subtitle: hasThread ? `Archives now, returns to Inbox ${snz.label}` : "Select or open a thread first",
                badge: snz.label,
                badgeTone: "complement",
                shortcut: hasThread ? "↵" : "",
                disabled: !hasThread,
                action: { type: "snooze", untilIso: snz.untilIso, label: snz.label }
            });
        } else {
            items.push({
                id: "snooze:invalid",
                group: "Smart command",
                icon: "snooze",
                title: "Snooze active thread",
                subtitle: snz.error,
                badge: "Syntax",
                badgeTone: "error",
                disabled: true,
                tabComplete: "snooze tomorrow 9am",
                action: { type: "noop" }
            });
        }
        return { modeBadge: "Snooze", modeBadgeTone: "complement", items: items };
    }

    // 4. Sender filter: "from:<query>"
    const fromParsed = parseFromQuery(trimmed);
    if (fromParsed) {
        const conversations = context.conversations || [];
        const scored = [];
        for (let i = 0; i < conversations.length; i++) {
            const c = conversations[i];
            const senderRes = fuzzyScoreFields(fromParsed.senderNeedle, [
                { text: c.name, weight: 1.3 },
                { text: c.address, weight: 1.2 }
            ]);
            if (!senderRes.matched)
                continue;
            let score = senderRes.score;
            if (fromParsed.extraNeedle) {
                const extraRes = fuzzyScoreFields(fromParsed.extraNeedle, [
                    { text: c.subject, weight: 1.2 },
                    { text: c.snippet || c.preview, weight: 1.0 }
                ]);
                if (!extraRes.matched)
                    continue;
                score += extraRes.score;
            }
            scored.push({ score: score, item: buildConversationRowItem(c, "From sender") });
        }
        scored.sort((a, b) => b.score - a.score);
        const results = scored.slice(0, 12).map(s => s.item);
        if (fromParsed.senderNeedle) {
            results.push({
                id: "mail:search_all_from",
                group: "Search all mail",
                icon: "search",
                title: `Search all mail for "${trimmed}"`,
                subtitle: "Run full notmuch search in All Mail",
                badge: "All Mail",
                badgeTone: "primary",
                shortcut: "↵",
                action: { type: "search_all", query: trimmed }
            });
        }
        return { modeBadge: "From filter", modeBadgeTone: "primary", items: results };
    }

    // 5. General fuzzy search across commands + loaded conversations + folder rows
    const scoredCmds = [];
    const commands = mailStaticCommands(context);
    for (let i = 0; i < commands.length; i++) {
        const cmd = commands[i];
        const res = fuzzyScoreFields(trimmed, [
            { text: cmd.title, weight: 1.5 },
            { text: cmd.keywords, weight: 1.15 },
            { text: cmd.subtitle, weight: 0.85 }
        ]);
        if (res.matched) {
            scoredCmds.push({ score: res.score + (cmd.group === "Current thread" ? 10 : 0), item: cmd });
        }
    }
    scoredCmds.sort((a, b) => b.score - a.score);

    const scoredThreads = [];
    const conversations = context.conversations || [];
    for (let i = 0; i < conversations.length; i++) {
        const c = conversations[i];
        const res = fuzzyScoreFields(trimmed, [
            { text: c.name, weight: 1.35 },
            { text: c.subject, weight: 1.25 },
            { text: c.address, weight: 1.1 },
            { text: c.snippet || c.preview, weight: 0.95 }
        ]);
        if (res.matched) {
            scoredThreads.push({ score: res.score, item: buildConversationRowItem(c, "Threads") });
        }
    }

    // Also include loaded folder rows if viewing Sent / Starred / Expiring / All Mail
    const flatRows = context.flatRows || [];
    const seenRowIds = {};
    for (let i = 0; i < flatRows.length; i++) {
        const row = flatRows[i];
        if (!row || row.type !== "row" || !row.open || seenRowIds[row.open])
            continue;
        seenRowIds[row.open] = true;
        const res = fuzzyScoreFields(trimmed, [
            { text: row.title, weight: 1.3 },
            { text: row.subtitle, weight: 1.2 }
        ]);
        if (res.matched) {
            scoredThreads.push({
                score: res.score,
                item: {
                    id: `row:${row.id}`,
                    group: "Emails in folder",
                    icon: row.icon || "mail",
                    title: row.title || "(no sender)",
                    subtitle: row.subtitle || "(no subject)",
                    badge: row.unread > 0 ? "Unread" : "",
                    badgeTone: row.unread > 0 ? "complement" : "",
                    shortcut: row.time || "",
                    action: { type: "open_message", id: row.open }
                }
            });
        }
    }
    scoredThreads.sort((a, b) => b.score - a.score);

    const topCmds = scoredCmds.slice(0, 6).map(s => s.item);
    const topThreads = scoredThreads.slice(0, 8).map(s => s.item);

    // Put commands first when a command is a strong match, or threads first if threads clearly dominate.
    const bestCmdScore = scoredCmds.length > 0 ? scoredCmds[0].score : 0;
    const bestThreadScore = scoredThreads.length > 0 ? scoredThreads[0].score : 0;
    const combined = bestThreadScore > bestCmdScore + 45
        ? topThreads.concat(topCmds)
        : topCmds.concat(topThreads);

    combined.push({
        id: "mail:search_all",
        group: "Search all mail",
        icon: "search",
        title: `Search all mail for "${trimmed}"`,
        subtitle: "Find older threads across every folder",
        badge: "All Mail",
        badgeTone: "primary",
        shortcut: "",
        action: { type: "search_all", query: trimmed }
    });

    return { modeBadge: "", modeBadgeTone: "", items: combined };
}

// Calendar palette ranking ----------------------------------------------------

function calendarStaticCommands(ctx) {
    const cmds = [];
    const next = ctx.nextMeeting || null;

    if (next) {
        const hasVideo = /^https?:\/\//i.test(next.video || "");
        const isLive = Boolean(ctx.nextMeetingLive);
        const countdown = (ctx.nextMeetingCountdown || "").trim();
        cmds.push({
            id: "cal:join_next",
            group: "Next up",
            icon: hasVideo ? "videocam" : "event",
            title: hasVideo ? `Join next meeting · ${next.title || "Meeting"}` : `Focus next meeting · ${next.title || "Meeting"}`,
            subtitle: [next.time || "", next.where || next.calendar || ""].filter(Boolean).join(" · "),
            keywords: `join next meeting call video zoom meet ${next.title || ""}`,
            badge: countdown || (isLive ? "Live now" : "Up next"),
            badgeTone: isLive ? "complement" : "primary",
            shortcut: "↵",
            action: { type: "join_next_meeting", event: next }
        });
    }

    cmds.push(
        {
            id: "cal:add_todo_hint",
            group: "Quick actions",
            icon: "add_task",
            title: "Add Today Actionable",
            subtitle: `Type "todo <task>" to save directly to Today's checklist`,
            keywords: "add today actionable todo task checklist",
            badge: "todo …",
            badgeTone: "complement",
            shortcut: "Tab",
            tabComplete: "todo ",
            action: { type: "prefill", text: "todo " }
        },
        {
            id: "cal:new_event_hint",
            group: "Quick actions",
            icon: "add",
            title: "New Event",
            subtitle: `Open event dialog · or type "new Design Review 4pm"`,
            keywords: "new event create schedule meeting appointment",
            badge: "new …",
            badgeTone: "primary",
            shortcut: "",
            tabComplete: "new ",
            action: { type: "new_event_dialog" }
        },
        {
            id: "cal:today",
            group: "Quick actions",
            icon: "today",
            title: "Jump to Today",
            subtitle: "Focus today's schedule & actionables",
            keywords: "jump go today now current day",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "jump_today" }
        },
        {
            id: "cal:sync",
            group: "Quick actions",
            icon: "sync",
            title: "Sync calendars now",
            subtitle: "Refresh connected Google calendars",
            keywords: "sync refresh calendars google reload",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "sync" }
        },
        {
            id: "cal:open_mail",
            group: "Quick actions",
            icon: "mail",
            title: "Open Mail",
            subtitle: "Switch to Junco Mail",
            keywords: "open mail inbox courier email",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "open_mail" }
        },
        {
            id: "cal:toggle_glass",
            group: "Quick actions",
            icon: ctx.dark ? "light_mode" : "dark_mode",
            title: "Toggle Light / Dark glass",
            subtitle: ctx.dark ? "Switch to Light frosted glass" : "Switch to Dark frosted glass",
            keywords: "toggle theme light dark glass mode polarity appearance",
            badge: ctx.dark ? "Dark" : "Light",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "toggle_glass" }
        },
        // Views & Layout
        {
            id: "cal:view_day",
            group: "Views",
            icon: "calendar_view_day",
            title: "Day view",
            subtitle: "Single-day timeline",
            keywords: "day view timeline schedule",
            badge: ctx.view === "day" ? "Active" : "",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "set_view", view: "day" }
        },
        {
            id: "cal:view_week",
            group: "Views",
            icon: "calendar_view_week",
            title: "Week view",
            subtitle: "Seven-day grid",
            keywords: "week view weekly grid",
            badge: ctx.view === "week" ? "Active" : "",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "set_view", view: "week" }
        },
        {
            id: "cal:view_month",
            group: "Views",
            icon: "calendar_view_month",
            title: "Month view",
            subtitle: "Full month overview",
            keywords: "month view monthly calendar",
            badge: ctx.view === "month" ? "Active" : "",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "set_view", view: "month" }
        },
        {
            id: "cal:view_agenda",
            group: "Views",
            icon: "view_agenda",
            title: "Agenda view",
            subtitle: "Chronological event list",
            keywords: "agenda view list upcoming",
            badge: ctx.view === "agenda" ? "Active" : "",
            badgeTone: "primary",
            shortcut: "",
            action: { type: "set_view", view: "agenda" }
        },
        {
            id: "cal:toggle_sidebar",
            group: "Views",
            icon: ctx.sidebarShown ? "left_panel_close" : "left_panel_open",
            title: "Toggle sidebar",
            subtitle: ctx.sidebarShown ? "Hide calendars sidebar" : "Show calendars sidebar",
            keywords: "toggle sidebar calendars left panel",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "toggle_sidebar" }
        },
        {
            id: "cal:toggle_day_panel",
            group: "Views",
            icon: ctx.dayShown ? "right_panel_close" : "right_panel_open",
            title: "Toggle Today panel",
            subtitle: ctx.dayShown ? "Hide Today & Actionables panel" : "Show Today & Actionables panel",
            keywords: "toggle today day panel right actionables",
            badge: "",
            badgeTone: "",
            shortcut: "",
            action: { type: "toggle_day_panel" }
        }
    );

    return cmds;
}

function rankCalendarItems(rawQuery, ctx, nowDate) {
    const context = ctx || {};
    const now = nowDate || new Date();
    const todayStr = context.todayDay || formatDay(now);
    const selectedDay = context.selectedDay || todayStr;
    const trimmed = (rawQuery || "").trim();

    // 1. Empty query: context-aware suggestions
    if (!trimmed) {
        return { modeBadge: "", modeBadgeTone: "", items: calendarStaticCommands(context) };
    }

    // 2. Smart command: Today Actionables ("todo ...", "task ...", "add ...")
    const todo = parseTodoCommand(trimmed);
    if (todo) {
        if (todo.mode === "prompt") {
            return {
                modeBadge: "Actionable",
                modeBadgeTone: "complement",
                items: [{
                    id: "cal:todo_prompt",
                    group: "Smart command",
                    icon: "add_task",
                    title: "Add Today Actionable",
                    subtitle: `Type a task title (e.g. "${todo.keyword} Send slides before 5pm")`,
                    badge: "Today",
                    badgeTone: "complement",
                    tabComplete: `${todo.keyword} `,
                    disabled: true,
                    action: { type: "noop" }
                }]
            };
        }
        return {
            modeBadge: "Actionable",
            modeBadgeTone: "complement",
            items: [{
                id: `cal:todo:${todo.text}`,
                group: "Smart command",
                icon: "add_task",
                title: `Add actionable: "${todo.text}"`,
                subtitle: "Saves to Today's Actionables and refreshes Day Panel",
                badge: "Add task",
                badgeTone: "complement",
                shortcut: "↵",
                action: { type: "add_actionable", title: todo.text, dueDate: todayStr }
            }]
        };
    }

    // 3. Smart command: Quick Event ("new ...", "event ...")
    const ev = parseQuickEventCommand(trimmed, now, selectedDay);
    if (ev) {
        if (ev.mode === "prompt") {
            return {
                modeBadge: "Quick Event",
                modeBadgeTone: "primary",
                items: [{
                    id: "cal:event_prompt",
                    group: "Smart command",
                    icon: "event",
                    title: "Create Quick Event",
                    subtitle: `Try "new Design Review 4pm" or "new Standup tomorrow 10:30am"`,
                    badge: "Event",
                    badgeTone: "primary",
                    tabComplete: `${ev.keyword} `,
                    action: { type: "new_event_dialog" }
                }]
            };
        }

        const items = [{
            id: `cal:event_dialog:${ev.title}:${ev.day}:${ev.startMinutes}`,
            group: "Smart command",
            icon: "event",
            title: `New event: ${ev.title}`,
            subtitle: `${ev.summary} · opens Event Dialog prefilled`,
            badge: ev.hasExplicitTime ? formatClock(ev.startMinutes) : "Prefill",
            badgeTone: "primary",
            shortcut: "↵",
            action: {
                type: "create_event_prefilled",
                title: ev.title,
                day: ev.day,
                startMinutes: ev.startMinutes,
                endMinutes: ev.endMinutes
            }
        }];

        if (ev.hasExplicitTime) {
            items.push({
                id: `cal:event_quick:${ev.title}:${ev.day}:${ev.startMinutes}`,
                group: "Smart command",
                icon: "bolt",
                title: `Save immediately: ${ev.title}`,
                subtitle: `${ev.summary} · saves directly to local calendar`,
                badge: "Quick save",
                badgeTone: "complement",
                shortcut: "",
                action: {
                    type: "create_event_direct",
                    title: ev.title,
                    day: ev.day,
                    startMinutes: ev.startMinutes,
                    endMinutes: ev.endMinutes
                }
            });
        }
        return { modeBadge: "Quick Event", modeBadgeTone: "primary", items: items };
    }

    // 4. General fuzzy search across commands + events + actionables
    const scoredCmds = [];
    const commands = calendarStaticCommands(context);
    for (let i = 0; i < commands.length; i++) {
        const cmd = commands[i];
        const res = fuzzyScoreFields(trimmed, [
            { text: cmd.title, weight: 1.5 },
            { text: cmd.keywords, weight: 1.15 },
            { text: cmd.subtitle, weight: 0.85 }
        ]);
        if (res.matched) {
            scoredCmds.push({ score: res.score + (cmd.group === "Next up" ? 18 : 0), item: cmd });
        }
    }
    scoredCmds.sort((a, b) => b.score - a.score);

    const scoredEvents = [];
    const events = context.events || [];
    const seenEvents = {};
    for (let i = 0; i < events.length; i++) {
        const e = events[i];
        if (!e)
            continue;
        const key = `${(e.title || "").toLowerCase()}|${e.start}|${e.end}`;
        if (seenEvents[key])
            continue;
        seenEvents[key] = true;
        const res = fuzzyScoreFields(trimmed, [
            { text: e.title, weight: 1.4 },
            { text: e.where, weight: 1.05 },
            { text: e.calendar, weight: 0.95 },
            { text: e.notes, weight: 0.8 }
        ]);
        if (res.matched) {
            const whenStr = [formatShortDay(e.startDay, todayStr), e.allDay ? "All day" : (e.time || "")].filter(Boolean).join(" · ");
            const subtitle = [whenStr, e.where || e.calendar || ""].filter(Boolean).join(" · ");
            scoredEvents.push({
                score: res.score,
                item: {
                    id: `event:${e.id || key}`,
                    group: "Events",
                    icon: (e.video || "") !== "" ? "videocam" : (e.kind === "birthday" ? "cake" : "event"),
                    title: e.title || "(Untitled event)",
                    subtitle: subtitle,
                    badge: (e.video || "") !== "" ? "Meet" : "",
                    badgeTone: (e.video || "") !== "" ? "complement" : "",
                    shortcut: formatShortDay(e.startDay, todayStr),
                    action: { type: "focus_event", event: e }
                }
            });
        }
    }
    scoredEvents.sort((a, b) => b.score - a.score);

    const scoredTasks = [];
    const actionables = context.actionables || [];
    for (let i = 0; i < actionables.length; i++) {
        const t = actionables[i];
        if (!t)
            continue;
        const res = fuzzyScoreFields(trimmed, [
            { text: t.title, weight: 1.35 }
        ]);
        if (res.matched) {
            scoredTasks.push({
                score: res.score,
                item: {
                    id: `task:${t.id}`,
                    group: "Actionables",
                    icon: t.completed ? "check_circle" : "radio_button_unchecked",
                    title: t.title || "",
                    subtitle: t.completed ? "Completed · press Enter to reopen" : (t.carryOver ? "Carried over · press Enter to complete" : "Today's actionable · press Enter to complete"),
                    badge: t.completed ? "Done" : (t.carryOver ? "Carry over" : "Open"),
                    badgeTone: t.completed ? "primary" : "complement",
                    shortcut: "",
                    action: { type: "toggle_actionable", id: t.id, title: t.title }
                }
            });
        }
    }
    scoredTasks.sort((a, b) => b.score - a.score);

    const buckets = [
        { score: scoredCmds.length > 0 ? scoredCmds[0].score : -1, items: scoredCmds.slice(0, 6).map(s => s.item) },
        { score: scoredEvents.length > 0 ? scoredEvents[0].score : -1, items: scoredEvents.slice(0, 8).map(s => s.item) },
        { score: scoredTasks.length > 0 ? scoredTasks[0].score : -1, items: scoredTasks.slice(0, 6).map(s => s.item) }
    ];
    buckets.sort((a, b) => b.score - a.score);
    let results = [];
    for (let i = 0; i < buckets.length; i++) {
        if (buckets[i].items.length > 0)
            results = results.concat(buckets[i].items);
    }

    return { modeBadge: "", modeBadgeTone: "", items: results };
}
