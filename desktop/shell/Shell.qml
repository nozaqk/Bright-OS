import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

/*
    Bright Desktop Shell - Main QML UI

    Architecture:
    - WallpaperWindow: Fullscreen background (behind everything)
    - PanelWindow:     Top panel (always on top, no focus)
    - DockWindow:      Bottom dock (centered, always on top)
    - Overlay windows: Launcher, notification center, power menu

    NOTE: Uses plain Rectangle with semi-transparent backgrounds instead of
    MultiEffect (QtQuick.Effects is Qt 6.5+, Debian Bookworm ships Qt 6.4).
*/

// ---------- Wallpaper ----------
Window {
    id: wallpaperWindow
    visible: true
    width: Screen.width
    height: Screen.height
    x: 0; y: 0
    color: "#0a0e1a"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool
    z: 0

    property string currentWallpaper: Shell.initialWallpaper
    property string currentTheme: Shell.initialTheme
    readonly property color accentColor: "#3b82f6"

    Image {
        id: wp
        anchors.fill: parent
        source: wallpaperWindow.currentWallpaper
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
    }

    Component.onCompleted: {
        console.log("Bright Desktop Shell", Shell.version, "- wallpaper layer")
    }
}

// ---------- Top Panel ----------
Window {
    id: panelWindow
    visible: true
    width: Screen.width
    height: panelH
    x: 0; y: 0
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 10

    readonly property int panelH: Shell.panelHeight
    readonly property color panelBg: wallpaperWindow.currentTheme === "dark" ? "#e00a0e1a" : "#e0f0f4ff"
    readonly property color panelFg: wallpaperWindow.currentTheme === "dark" ? "#e2e8f0" : "#1e293b"
    readonly property color textSecondary: wallpaperWindow.currentTheme === "dark" ? "#94a3b8" : "#64748b"
    readonly property color hoverOverlay: wallpaperWindow.currentTheme === "dark" ? "#ffffff18" : "#00000010"
    readonly property color borderLine: wallpaperWindow.currentTheme === "dark" ? "#1e293b" : "#cbd5e1"

    Rectangle {
        anchors.fill: parent
        color: panelWindow.panelBg
        // Simple 1px bottom border
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: panelWindow.borderLine
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 6

        ToolButton {
            id: launcherBtn
            Layout.preferredWidth: panelWindow.panelH - 4
            Layout.preferredHeight: panelWindow.panelH - 4
            contentItem: Text {
                text: "\u2600"
                anchors.centerIn: parent
                font.pixelSize: 18
                color: panelWindow.panelFg
            }
            background: Rectangle { radius: 8; color: launcherBtn.hovered ? panelWindow.hoverOverlay : "transparent" }
            onClicked: { launcherWindow.visible = !launcherWindow.visible; if (launcherWindow.visible) launcherWindow.activate() }
        }

        Item { Layout.fillWidth: true }

        Column {
            spacing: 0
            Text {
                id: clockText
                anchors.horizontalCenter: parent.horizontalCenter
                text: "00:00"
                color: panelWindow.panelFg
                font.pixelSize: 14
                font.weight: Font.Medium
            }
            Text {
                id: dateText
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Loading..."
                color: panelWindow.textSecondary
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: notifWindow.visible = !notifWindow.visible
            }
        }

        Item { Layout.fillWidth: true }

        Row {
            spacing: 2
            anchors.verticalCenter: parent.verticalCenter
            ToolButton {
                implicitWidth: panelWindow.panelH - 8
                implicitHeight: panelWindow.panelH - 8
                background: Rectangle { radius: 8; color: parent.hovered ? panelWindow.hoverOverlay : "transparent" }
                contentItem: Text { text: "\uD83D\uDD0C"; anchors.centerIn: parent; font.pixelSize: 14; color: panelWindow.panelFg }
            }
            ToolButton {
                implicitWidth: panelWindow.panelH - 8
                implicitHeight: panelWindow.panelH - 8
                background: Rectangle { radius: 8; color: parent.hovered ? panelWindow.hoverOverlay : "transparent" }
                contentItem: Text { text: "\uD83D\uDD0A"; anchors.centerIn: parent; font.pixelSize: 14; color: panelWindow.panelFg }
            }
            ToolButton {
                implicitWidth: panelWindow.panelH - 8
                implicitHeight: panelWindow.panelH - 8
                background: Rectangle { radius: 8; color: parent.hovered ? panelWindow.hoverOverlay : "transparent" }
                contentItem: Text { text: "\u23FB"; anchors.centerIn: parent; font.pixelSize: 16; color: panelWindow.panelFg }
                onClicked: powerWindow.visible = !powerWindow.visible
            }
        }
    }
}

// ---------- Dock ----------
Window {
    id: dockWindow
    visible: true
    width: Math.min(Screen.width - 80, Shell.dockIconSize * 9 + 60)
    height: Shell.dockIconSize + 20
    x: (Screen.width - width) / 2
    y: Screen.height - height - 8
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 10

    property int dockIconSize: Shell.dockIconSize
    readonly property color dockBg: wallpaperWindow.currentTheme === "dark" ? "#d00f172a" : "#d0e2e8f0"
    readonly property color panelFg: wallpaperWindow.currentTheme === "dark" ? "#e2e8f0" : "#1e293b"
    readonly property color hoverOverlay: wallpaperWindow.currentTheme === "dark" ? "#ffffff18" : "#00000010"
    readonly property color activeIndicator: "#3b82f6"
    readonly property color dockBorder: wallpaperWindow.currentTheme === "dark" ? "#334155" : "#cbd5e1"

    Rectangle {
        anchors.fill: parent
        radius: parent.height / 2
        color: dockWindow.dockBg
        border.color: dockWindow.dockBorder
        border.width: 1
    }

    Row {
        anchors.centerIn: parent
        spacing: 4
        Repeater {
            model: JSON.parse(DockApps)
            delegate: Item {
                width: dockWindow.dockIconSize
                height: dockWindow.dockIconSize
                Button {
                    anchors.centerIn: parent
                    width: dockWindow.dockIconSize
                    height: dockWindow.dockIconSize
                    flat: true
                    background: Rectangle {
                        radius: 12
                        color: mouseArea.containsMouse ? dockWindow.hoverOverlay : "transparent"
                    }
                    contentItem: Text {
                        anchors.centerIn: parent
                        text: {
                            var icons = {
                                "firefox-esr": "\uD83E\uDD8A",
                                "bright-files": "\uD83D\uDCC1",
                                "bright-terminal": "\uD83D\uDDA5\uFE0F",
                                "bright-settings": "\u2699\uFE0F",
                                "org.kde.discover": "\uD83D\uDED2",
                                "libreoffice-writer": "\uD83D\uDCDD",
                                "vlc": "\u25B6\uFE0F",
                                "bright-monitor": "\uD83D\uDCCA",
                                "wine": "\U0001F377"
                            }
                            return icons[modelData.id] || "\u25A1"
                        }
                        font.pixelSize: dockWindow.dockIconSize * 0.5
                    }
                    MouseArea {
                        id: mouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: Shell.launchApplication(modelData.id, modelData.command)
                    }
                    ToolTip.visible: mouseArea.containsMouse
                    ToolTip.text: modelData.name
                    ToolTip.delay: 500
                }
            }
        }
    }
}

// ---------- Launcher Overlay ----------
Window {
    id: launcherWindow
    visible: false
    width: Screen.width
    height: Screen.height
    x: 0; y: 0
    color: "#00000000"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    z: 100

    property var dockAppList: JSON.parse(DockApps)
    readonly property color launcherBg: wallpaperWindow.currentTheme === "dark" ? "#e60a0e1a" : "#e6f0f4ff"
    readonly property color cardBg: wallpaperWindow.currentTheme === "dark" ? "#1e293b" : "#ffffff"
    readonly property color cardBorder: wallpaperWindow.currentTheme === "dark" ? "#334155" : "#cbd5e1"
    readonly property color textPrimary: wallpaperWindow.currentTheme === "dark" ? "#f1f5f9" : "#0f172a"
    readonly property color textSecondary: wallpaperWindow.currentTheme === "dark" ? "#94a3b8" : "#64748b"
    readonly property color hoverOverlay: wallpaperWindow.currentTheme === "dark" ? "#ffffff18" : "#00000010"
    readonly property color accentColor: "#3b82f6"
    readonly property int cornerRadius: 12

    Shortcut { sequence: "Escape"; onActivated: launcherWindow.visible = false }

    Rectangle {
        anchors.fill: parent
        color: launcherWindow.launcherBg
    }
    MouseArea { anchors.fill: parent; onClicked: launcherWindow.visible = false }

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 100, 720)
        spacing: 24

        Rectangle {
            width: parent.width
            height: 56
            radius: 16
            color: launcherWindow.cardBg
            border.color: launcherWindow.cardBorder
            border.width: 1
            Row {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12
                Text { text: "\uD83D\uDD0D"; font.pixelSize: 20; anchors.verticalCenter: parent.verticalCenter; color: launcherWindow.textSecondary }
                TextField {
                    id: searchField
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 50
                    placeholderText: "Type to search..."
                    font.pixelSize: 16
                    color: launcherWindow.textPrimary
                    background: Item {}
                    focus: true
                    onVisibleChanged: if (visible) searchField.forceActiveFocus()
                }
            }
        }

        Grid {
            width: parent.width
            columns: 5
            spacing: 16
            Repeater {
                model: [
                    {"name": "Terminal", "icon": "\uD83D\uDDA5\uFE0F", "cmd": "bright-terminal"},
                    {"name": "Files", "icon": "\uD83D\uDCC1", "cmd": "bright-files"},
                    {"name": "Settings", "icon": "\u2699\uFE0F", "cmd": "bright-settings"},
                    {"name": "Firefox", "icon": "\uD83E\uDD8A", "cmd": "firefox-esr"},
                    {"name": "Software", "icon": "\uD83D\uDED2", "cmd": "plasma-discover"},
                    {"name": "Monitor", "icon": "\uD83D\uDCCA", "cmd": "bright-monitor"},
                    {"name": "Control Center", "icon": "\uD83C\uDF9B\uFE0F", "cmd": "bright-control-center"},
                    {"name": "Text Editor", "icon": "\uD83D\uDCDD", "cmd": "kwrite"},
                    {"name": "Calculator", "icon": "\uD83E\uDDEE", "cmd": "kcalc"},
                    {"name": "VLC", "icon": "\u25B6\uFE0F", "cmd": "vlc"},
                    {"name": "GIMP", "icon": "\uD83C\uDFA8", "cmd": "gimp"},
                    {"name": "LibreOffice", "icon": "\uD83D\uDCC4", "cmd": "libreoffice"},
                    {"name": "Updates", "icon": "\uD83D\uDD04", "cmd": "bright-update"},
                    {"name": "Disks", "icon": "\uD83D\uDCBE", "cmd": "gnome-disk-utility"},
                    {"name": "About", "icon": "\u2139\uFE0F", "cmd": "bright-about"}
                ]
                delegate: Item {
                    width: (parent.width - 4 * 16) / 5
                    height: width
                    Button {
                        anchors.fill: parent
                        flat: true
                        background: Rectangle {
                            radius: launcherWindow.cornerRadius
                            color: appMouse.containsMouse ? launcherWindow.cardBg : "transparent"
                            border.color: appMouse.containsMouse ? launcherWindow.cardBorder : "transparent"
                            border.width: 1
                        }
                        contentItem: Column {
                            anchors.centerIn: parent
                            spacing: 6
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.icon; font.pixelSize: width * 0.35 }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.name
                                color: launcherWindow.textPrimary
                                font.pixelSize: 11
                                font.weight: Font.Medium
                                elide: Text.ElideRight
                                maximumLineCount: 1
                                width: parent.width - 8
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                        MouseArea {
                            id: appMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: { Shell.launchApplication("", modelData.cmd); launcherWindow.visible = false }
                        }
                    }
                }
            }
        }

        Row {
            width: parent.width; spacing: 12
            Button {
                width: (parent.width - 12) / 2; height: 44; flat: true
                contentItem: Text { text: "\uD83D\uDC64  User Settings"; anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter; color: launcherWindow.textSecondary; font.pixelSize: 13 }
                background: Rectangle { radius: 12; color: launcherWindow.cardBg; border.color: launcherWindow.cardBorder; border.width: 1 }
                onClicked: { Shell.openSettings(); launcherWindow.visible = false }
            }
            Button {
                width: (parent.width - 12) / 2; height: 44; flat: true
                contentItem: Text { text: "\u23FB  Power"; anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter; color: "#ef4444"; font.pixelSize: 13 }
                background: Rectangle { radius: 12; color: launcherWindow.cardBg; border.color: launcherWindow.cardBorder; border.width: 1 }
                onClicked: { powerWindow.visible = true; launcherWindow.visible = false }
            }
        }
    }
}

// ---------- Power Menu ----------
Window {
    id: powerWindow
    visible: false
    width: 220
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 200
    x: Screen.width - width - 12
    y: panelWindow.height + 8
    height: contentCol.height + 24

    readonly property color cardBg: wallpaperWindow.currentTheme === "dark" ? "#1e293b" : "#ffffff"
    readonly property color cardBorder: wallpaperWindow.currentTheme === "dark" ? "#334155" : "#cbd5e1"
    readonly property color textPrimary: wallpaperWindow.currentTheme === "dark" ? "#f1f5f9" : "#0f172a"
    readonly property color hoverOverlay: wallpaperWindow.currentTheme === "dark" ? "#ffffff18" : "#00000010"

    Shortcut { sequence: "Escape"; onActivated: powerWindow.visible = false }

    Rectangle {
        anchors.fill: parent
        radius: 12
        color: powerWindow.cardBg
        border.color: powerWindow.cardBorder
        border.width: 1
    }

    Column {
        id: contentCol
        anchors.fill: parent
        anchors.margins: 12
        spacing: 2

        Text { text: "System"; color: "#64748b"; font.pixelSize: 11; font.weight: Font.Bold; leftPadding: 8; bottomPadding: 4 }
        Repeater {
            model: [
                {label: "Lock Screen", icon: "\uD83D\uDD12", color: "#e2e8f0", action: () => Shell.lockScreen()},
                {label: "Log Out", icon: "\uD83D\uDEAA", color: "#e2e8f0", action: () => Shell.logout()},
                {label: "Suspend", icon: "\uD83D\uDCA4", color: "#e2e8f0", action: () => Shell.reboot()},
                {label: "Reboot", icon: "\uD83D\uDD04", color: "#e2e8f0", action: () => Shell.reboot()},
                {label: "Shut Down", icon: "\u23FC", color: "#ef4444", action: () => Shell.shutdown()}
            ]
            delegate: Button {
                width: powerWindow.width - 24; height: 38; flat: true
                contentItem: Text {
                    text: modelData.icon + "  " + modelData.label
                    anchors.left: parent.left; anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData.color; font.pixelSize: 13
                }
                background: Rectangle { radius: 8; color: pMouse.containsMouse ? powerWindow.hoverOverlay : "transparent" }
                MouseArea {
                    id: pMouse; anchors.fill: parent; hoverEnabled: true
                    onClicked: { modelData.action(); powerWindow.visible = false }
                }
            }
        }
    }
}

// ---------- Notification Center ----------
Window {
    id: notifWindow
    visible: false
    width: 360
    height: Math.min(Screen.height - panelWindow.height - dockWindow.height - 32, 620)
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 150
    x: Screen.width - width - 8
    y: panelWindow.height + 8

    readonly property color cardBg: wallpaperWindow.currentTheme === "dark" ? "#1e293b" : "#ffffff"
    readonly property color cardBorder: wallpaperWindow.currentTheme === "dark" ? "#334155" : "#cbd5e1"
    readonly property color textPrimary: wallpaperWindow.currentTheme === "dark" ? "#f1f5f9" : "#0f172a"
    readonly property color textSecondary: wallpaperWindow.currentTheme === "dark" ? "#94a3b8" : "#64748b"
    readonly property color accentColor: "#3b82f6"
    readonly property color hoverOverlay: wallpaperWindow.currentTheme === "dark" ? "#ffffff18" : "#00000010"

    Shortcut { sequence: "Escape"; onActivated: notifWindow.visible = false }

    Rectangle {
        anchors.fill: parent
        radius: 16
        color: notifWindow.cardBg
        border.color: notifWindow.cardBorder
        border.width: 1
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: 16
        clip: true
        Column {
            width: notifWindow.width - 44
            spacing: 12

            Text { text: "Notifications"; font.pixelSize: 18; font.weight: Font.Bold; color: notifWindow.textPrimary }
            Text { text: "No new notifications"; color: notifWindow.textSecondary; font.pixelSize: 13; topPadding: 20 }
            Item { height: 12; width: 1 }
            Text { text: "Quick Settings"; font.pixelSize: 18; font.weight: Font.Bold; color: notifWindow.textPrimary; topPadding: 20 }

            Grid {
                width: parent.width; columns: 2; spacing: 8
                Repeater {
                    model: [
                        {"name": "Wi-Fi", "icon": "\uD83D\uDCF6", "active": true},
                        {"name": "Bluetooth", "icon": "\uD83D\uDD37", "active": false},
                        {"name": "Night Light", "icon": "\uD83C\uDF19", "active": false},
                        {"name": "Do Not Disturb", "icon": "\uD83D\uDD15", "active": false}
                    ]
                    delegate: Button {
                        width: (parent.width - 8) / 2; height: 52; flat: true
                        background: Rectangle {
                            radius: 12
                            color: modelData.active ? notifWindow.accentColor : notifWindow.cardBg
                            border.color: modelData.active ? notifWindow.accentColor : notifWindow.cardBorder
                            border.width: 1
                        }
                        contentItem: Row {
                            anchors.centerIn: parent; spacing: 8
                            Text { text: modelData.icon; font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData.name; font.pixelSize: 12; font.weight: Font.Medium; color: modelData.active ? "white" : notifWindow.textPrimary; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }

            Column { width: parent.width; spacing: 4
                Text { text: "Volume"; color: notifWindow.textSecondary; font.pixelSize: 12 }
                Slider { width: parent.width; from: 0; to: 100; value: 50; onMoved: Shell.setVolume(value) }
            }
            Column { width: parent.width; spacing: 4
                Text { text: "Brightness"; color: notifWindow.textSecondary; font.pixelSize: 12 }
                Slider { width: parent.width; from: 10; to: 100; value: 75; onMoved: Shell.setBrightness(value) }
            }

            Button {
                width: parent.width; height: 40; flat: true
                contentItem: Text { text: "Switch to " + (wallpaperWindow.currentTheme === "dark" ? "Light" : "Dark") + " Theme"; anchors.centerIn: parent; color: notifWindow.textPrimary; font.pixelSize: 12 }
                background: Rectangle { radius: 10; color: notifWindow.hoverOverlay; border.color: notifWindow.cardBorder; border.width: 1 }
                onClicked: {
                    var newTheme = wallpaperWindow.currentTheme === "dark" ? "light" : "dark"
                    Shell.setTheme(newTheme)
                    wallpaperWindow.currentTheme = newTheme
                    var wpName = newTheme === "dark" ? "bright-default-dark.svg" : "bright-default-light.svg"
                    wallpaperWindow.currentWallpaper = "/usr/share/bright-os/wallpapers/" + wpName
                }
            }
            Item { height: 20; width: 1 }
        }
    }
}

// Signal handlers
Connections {
    target: Shell
    function onClockUpdated(time, date) {
        clockText.text = time
        dateText.text = date
    }
    function onThemeChanged(theme) {
        wallpaperWindow.currentTheme = theme
        var wpName = theme === "dark" ? "bright-default-dark.svg" : "bright-default-light.svg"
        wallpaperWindow.currentWallpaper = "/usr/share/bright-os/wallpapers/" + wpName
    }
}

// Global keyboard shortcuts
Shortcut { sequence: "Super+T"; onActivated: Shell.openTerminal() }
Shortcut { sequence: "Super+E"; onActivated: Shell.openFiles() }
Shortcut { sequence: "Super+S"; onActivated: Shell.openSettings() }
Shortcut { sequence: "Super+L"; onActivated: Shell.lockScreen() }
Shortcut { sequence: "Super"; onActivated: { launcherWindow.visible = !launcherWindow.visible; if (launcherWindow.visible) launcherWindow.activate() } }
Shortcut { sequence: "Alt+F2"; onActivated: { launcherWindow.visible = !launcherWindow.visible; if (launcherWindow.visible) launcherWindow.activate() } }

Component.onCompleted: {
    console.log("Bright Desktop Shell", Shell.version, "started successfully")
    console.log("Theme:", wallpaperWindow.currentTheme)
    console.log("Resolution:", Screen.width, "x", Screen.height)
}
