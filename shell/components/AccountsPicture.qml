import QtQuick
import qs.services

// Every account in one circle, the way Google Chat draws a group: two
// accounts as halves; three as a half and two quarters; four as quarters,
// and with more the last quarter counts the rest ("+2"). Each part shows the
// account's picture, centred and cut to its part, or its initial on its
// colour; a thin gap separates the parts.
//
// Drawn on a Canvas (QML here can't clip images round): straight clips cut
// each picture to its part; then the gaps and everything outside the circle
// are erased with "destination-out", so the background shows through and the
// edge stays smooth where a round clip would be jagged. (Not
// "destination-in": Qt applies it only where the circle is painted, so the
// corners would stay.) Painted at twice the size and shown at half, so it
// stays sharp on a scaled screen.
Item {
    id: root

    property int size: 44

    readonly property var shown: Inbox.accounts.slice(0, 4)
    readonly property bool overflow: Inbox.accounts.length > 4
    readonly property var urls: shown.map(a => a.picture ? `file://${a.picture}?v=${Inbox.pictureVersion}` : "")
    // Anything that changes the drawing.
    readonly property string look: [urls.join("|"), shown.map(a => a.id + "/" + (a.label ?? "")).join("|"), Inbox.accounts.length, Theme.m3primary, Theme.m3tertiary, Theme.m3error, Theme.m3success, Theme.m3popupHigh, Theme.m3onSurface, size].join(";")

    // The parts of an s × s square for n accounts: [x, y, width, height].
    function parts(n: int, s: real): var {
        const h = s / 2;
        if (n <= 1)
            return [[0, 0, s, s]];
        if (n === 2)
            return [[0, 0, h, s], [h, 0, h, s]];
        if (n === 3)
            return [[0, 0, h, s], [h, 0, h, h], [h, h, h, h]];
        return [[0, 0, h, h], [h, 0, h, h], [0, h, h, h], [h, h, h, h]];
    }

    function load(): void {
        for (const url of urls)
            if (url && !canvas.isImageLoaded(url) && !canvas.isImageLoading(url))
                canvas.loadImage(url);
        canvas.requestPaint();
    }

    implicitWidth: size
    implicitHeight: size
    onLookChanged: load()
    Component.onCompleted: load()

    Canvas {
        id: canvas

        width: root.size * 2
        height: root.size * 2
        scale: 0.5
        transformOrigin: Item.TopLeft
        onImageLoaded: requestPaint()
        onPaint: {
            const s = width;
            const context = getContext("2d");
            context.reset();
            const accounts = root.shown;
            const n = accounts.length;
            if (n === 0) {
                context.fillStyle = Theme.m3popupHigh;
                context.beginPath();
                context.arc(s / 2, s / 2, s / 2, 0, 2 * Math.PI);
                context.fill();
                return;
            }
            const letter = (text, x, y, w, h, ink) => {
                context.fillStyle = ink;
                context.font = `600 ${Math.round(Math.min(w, h) * (text.length > 1 ? 0.38 : 0.46))}px ${Theme.sans}`;
                context.textAlign = "center";
                context.textBaseline = "middle";
                context.fillText(text, x + w / 2, y + h / 2);
            };
            root.parts(n, s).forEach((part, i) => {
                const [x, y, w, h] = part;
                const account = accounts[i];
                const url = root.urls[i];
                context.save();
                context.beginPath();
                context.rect(x, y, w, h);
                context.clip();
                if (root.overflow && i === 3) {
                    context.fillStyle = Theme.m3popupHigh;
                    context.fillRect(x, y, w, h);
                    letter(`+${Inbox.accounts.length - 3}`, x, y, w, h, Theme.m3onSurface);
                } else if (url && isImageLoaded(url)) {
                    // Round pictures, scaled so the circle covers the whole part.
                    const d = w === s && h === s ? s : Math.hypot(w, h);
                    context.drawImage(url, x + (w - d) / 2, y + (h - d) / 2, d, d);
                } else {
                    const tint = Inbox.accountColor(account.id);
                    context.fillStyle = tint;
                    context.fillRect(x, y, w, h);
                    const name = account.label || account.email || account.id;
                    letter(name.charAt(0).toUpperCase(), x, y, w, h, Qt.color(tint).hslLightness > 0.55 ? "#1b1b1f" : "#ffffff");
                }
                context.restore();
            });
            // The gaps between the parts, cut through to what's behind.
            const gap = Math.max(2, Math.round(s * 0.04));
            context.globalCompositeOperation = "destination-out";
            context.fillStyle = "#000000";
            if (n >= 2)
                context.fillRect((s - gap) / 2, 0, gap, s);
            if (n === 3)
                context.fillRect(s / 2, (s - gap) / 2, s / 2, gap);
            if (n >= 4)
                context.fillRect(0, (s - gap) / 2, s, gap);
            // Round, with a smooth edge: erase the square around the circle.
            context.fillRule = Qt.OddEvenFill;
            context.beginPath();
            context.rect(0, 0, s, s);
            context.arc(s / 2, s / 2, s / 2, 0, 2 * Math.PI);
            context.fill();
            context.globalCompositeOperation = "source-over";
        }
    }
}
