pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Your to-dos, kept on this PC in ~/.local/share/courier/tasks.json. Each has
// a day; unfinished ones from earlier days carry over into today.
Singleton {
    id: root

    readonly property string path: Quickshell.env("COURIER_TASKS") || `${Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share"}/courier/tasks.json`
    property var tasks: []

    function dayKey(offset: int): string {
        const day = new Date();
        day.setDate(day.getDate() + offset);
        return Qt.formatDate(day, "yyyy-MM-dd");
    }

    // A day's to-dos; today also carries every unfinished one from before.
    function forDay(day: string): var {
        const today = dayKey(0);
        return tasks.filter(task => task.day === day || (day === today && task.day < today && !task.done));
    }

    function addOn(title: string, day: string): void {
        const text = title.trim();
        if (text === "")
            return;
        tasks = tasks.concat([{ id: `${Date.now()}`, title: text, day: day, done: false }]);
        save();
    }

    function toggle(id: string): void {
        // A to-do carried over from an earlier day is finished today.
        tasks = tasks.map(task => task.id === id ? Object.assign({}, task, { done: !task.done, day: task.done ? task.day : (task.day < dayKey(0) ? dayKey(0) : task.day) }) : task);
        save();
    }

    function remove(id: string): void {
        tasks = tasks.filter(task => task.id !== id);
        save();
    }

    function save(): void {
        file.setText(JSON.stringify({ tasks: root.tasks }, null, 1) + "\n");
    }

    FileView {
        id: file

        path: root.path
        atomicWrites: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                root.tasks = JSON.parse(text()).tasks ?? [];
            } catch (e) {
                console.warn("Courier: couldn't read tasks.json:", e);
            }
        }
        onSaveFailed: error => console.warn("Courier: couldn't save to-dos:", error)
    }
}
