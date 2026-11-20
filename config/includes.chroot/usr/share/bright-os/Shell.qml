import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Window

/*
    Bright Desktop Shell - Main QML UI
    Provides: wallpaper, top panel, bottom dock, launcher overlay, notification center
*/

ApplicationWindow {
    id: root
    visible: true
    visibility: Window.FullScreen
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool

    // Properties
    property string currentTheme: Shell.initialTheme
    property string currentWallpaper: Shell.initialWallpaper
    property bool launcherVisible: false
    property bool notifCenterVisible: false
    property bool menuVisible: false
    property bool powerMenuVisible: false
    property var dockAppList: JSON.parse(DockApps)
    property int panelH: Shell.panelHeight
    property int dockIconSize: Shell.dockIconSize

    // Theme colors
    readonly property color panelBg: currentTheme === "dark" ? "#cc0a0e1a" : "#ccf0f4ff"
    readonly property color panelFg: currentTheme === "dark" ? "#e2e8f0" : "#1e293b"
    readonly property color accentColor: "#3b82f6"
    readonly property color accentColorLight: "#60a5fa"
    readonly property color dockBg: currentTheme === "dark" ? "#b30f172a" : "#b3e2e8f0"
    readonly property color launcherBg: currentTheme === "dark" ? "#e60a0e1a" : "#e6f0f4ff"
    readonly property color cardBg: currentTheme === "dark" ? "#1e293b" : "#ffffff"
    readonly property color cardBorder: currentTheme === "dark" ? "#334155" : "#cbd5e1"
    readonly property color textPrimary: currentTheme === "dark" ? "#f1f5f9" : "#0f172a"
    readonly property color textSecondary: currentTheme === "dark" ? "#94a3b8" : "#64748b"
    readonly property color hoverOverlay: currentTheme === "dark" ? "#ffffff15" : "#00000010"
    readonly property color activeIndicator: accentColor
    readonly property int cornerRadius: 12

    Shortcut { sequence: "Super+T"; onActivated: Shell.openTerminal() }
    Shortcut { sequence: "Super+E"; onActivated: Shell.openFiles() }
    Shortcut { sequence: "Super+S"; onActivated: Shell.openSettings() }
    Shortcut { sequence: "Super+L"; onActivated: Shell.lockScreen() }
    Shortcut { sequence: "Super"; onActivated: launcherVisible = !launcherVisible }
    Shortcut { sequence: "Alt+F2"; onActivated: launcherVisible = !launcherVisible }
    Shortcut { sequence: "Escape"; onActivated: { launcherVisible=false; notifCenterVisible=false; menuVisible=false; powerMenuVisible=false } }

    // Wallpaper layer
    Item {
        anchors.fill: parent
        z: 0
        Image {
            id: wallpaper
            anchors.fill: parent
            source: currentWallpaper
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
        }
        // Shade overlay for readability
        Rectangle {
            anchors.fill: parent
            color: currentTheme === "dark" ? "#00000000" : "#00000000"
        }
    }

    // Top panel
    Rectangle {
        id: topPanel
        z: 10
        width: parent.width
        height: panelH
        color: panelBg
        border.color: "transparent"

        // Blur effect
        layer.enabled: true
        layer.effect: MultiEffect {
            blurMax: 32
            blur: 0.7
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 8

            // Left: Activities/Menu button
            ToolButton {
                id: menuBtn
                Layout.preferredWidth: panelH - 8
                Layout.preferredHeight: panelH - 8
                anchors.verticalCenter: parent.verticalCenter

                contentItem: Item {
                    Canvas {
                        anchors.fill: parent
                        anchors.margins: 8
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            ctx.fillStyle = panelFg
                            var w = width, h = height
                            var barH = 2
                            ctx.fillRect(0, h*0.25, w, barH)
                            ctx.fillRect(0, h*0.5 - barH/2, w*0.7, barH)
                            ctx.fillRect(0, h*0.75 - barH, w*0.85, barH)
                        }
                    }
                }

                background: Rectangle {
                    radius: 8
                    color: menuBtn.hovered ? hoverOverlay : "transparent"
                }
                onClicked: menuVisible = !menuVisible
            }

            // Launcher button (Bright logo)
            ToolButton {
                id: launcherBtn
                Layout.preferredWidth: panelH - 4
                Layout.preferredHeight: panelH - 4

                contentItem: Image {
                    source: "file:///usr/share/bright-os/icons/bright-os-logo.svg"
                    sourceSize.width: panelH - 12
                    sourceSize.height: panelH - 12
                    fillMode: Image.PreserveAspectFit
                    anchors.centerIn: parent
                }

                background: Rectangle {
                    radius: 8
                    color: launcherBtn.hovered ? hoverOverlay : "transparent"
                }
                onClicked: launcherVisible = !launcherVisible
            }

            // Spacer
            Item { Layout.fillWidth: true }

            // Center: Clock
            Item {
                Layout.preferredWidth: 180
                Layout.fillHeight: true
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: notifCenterVisible = !notifCenterVisible
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 0
                    Text {
                        id: clockText
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "00:00"
                        color: panelFg
                        font.pixelSize: 15
                        font.weight: Font.Medium
                        font.family: "DejaVu Sans"
                    }
                    Text {
                        id: dateText
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Loading..."
                        color: textSecondary
                        font.pixelSize: 10
                        font.family: "DejaVu Sans"
                    }
                }
            }

            Item { Layout.fillWidth: true }

            // System tray area
            Row {
                spacing: 4
                anchors.verticalCenter: parent.verticalCenter

                // Network
                ToolButton {
                    id: netBtn
                    implicitWidth: panelH - 8
                    implicitHeight: panelH - 8
                    background: Rectangle { radius: 8; color: netBtn.hovered ? hoverOverlay : "transparent" }
                    contentItem: Text {
                        text: "\uD83D\uDD0C"
                        anchors.centerIn: parent
                        font.pixelSize: 14
                        opacity: parent.checked ? 1 : 0.5
                    }
                }

                // Volume
                ToolButton {
                    id: volBtn
                    implicitWidth: panelH - 8
                    implicitHeight: panelH - 8
                    background: Rectangle { radius: 8; color: volBtn.hovered ? hoverOverlay : "transparent" }
                    contentItem: Text {
                        text: "\uD83D\uDD0A"
                        anchors.centerIn: parent
                        font.pixelSize: 14
                    }
                }

                // Battery
                ToolButton {
                    id: batBtn
                    implicitWidth: panelH - 8
                    implicitHeight: panelH - 8
                    background: Rectangle { radius: 8; color: batBtn.hovered ? hoverOverlay : "transparent" }
                    contentItem: Text {
                        text: "\uD83D\uDD0B"
                        anchors.centerIn: parent
                        font.pixelSize: 14
                    }
                }

                // Power menu
                ToolButton {
                    id: powerBtn
                    implicitWidth: panelH - 8
                    implicitHeight: panelH - 8
                    background: Rectangle { radius: 8; color: powerBtn.hovered ? hoverOverlay : "transparent" }
                    contentItem: Text {
                        text: "\u23FB"
                        anchors.centerIn: parent
                        font.pixelSize: 16
                        color: panelFg
                    }
                    onClicked: powerMenuVisible = !powerMenuVisible
                }
            }
        }
    }

    // Dock (bottom center)
    Rectangle {
        id: dock
        z: 10
        height: dockIconSize + 24
        width: Math.min(parent.width - 100, dockIconSize * dockAppList.length + 48 + dockAppList.length * 6)
        radius: height / 2
        color: dockBg
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12

        layer.enabled: true
        layer.effect: MultiEffect {
            blurMax: 32
            blur: 0.6
        }

        Row {
            anchors.centerIn: parent
            spacing: 6
            Repeater {
                model: dockAppList
                delegate: Item {
                    width: dockIconSize
                    height: dockIconSize
                    Button {
                        anchors.centerIn: parent
                        width: dockIconSize
                        height: dockIconSize
                        flat: true
                        background: Rectangle {
                            radius: 12
                            color: mouseArea.containsMouse ? hoverOverlay : "transparent"
                            border.width: runningDot.visible ? 2 : 0
                            border.color: activeIndicator
                        }
                        contentItem: Item {
                            Text {
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
                                        "bright-monitor": "\uD83D\uDCCA"
                                    }
                                    return icons[modelData.id] || "\u25A1"
                                }
                                font.pixelSize: dockIconSize * 0.5
                            }
                            Rectangle {
                                id: runningDot
                                visible: index < 3  // Show indicator for running apps
                                width: 4
                                height: 4
                                radius: 2
                                color: activeIndicator
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 2
                            }
                        }
                        MouseArea {
                            id: mouseArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: Shell.launchApplication(modelData.id, modelData.command)
                        }
                        ToolTip.visible: mouseArea.containsMouse
                        ToolTip.text: modelData.name
                        ToolTip.delay: 400
                    }
                }
            }
        }
    }

    // Launcher Overlay
    Rectangle {
        id: launcherOverlay
        z: 100
        anchors.fill: parent
        color: launcherBg
        visible: launcherVisible
        opacity: launcherVisible ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 200 } }

        MouseArea {
            anchors.fill: parent
            onClicked: launcherVisible = false
        }

        Column {
            anchors.centerIn: parent
            width: Math.min(parent.width - 100, 720)
            spacing: 24

            // Search
            Rectangle {
                width: parent.width
                height: 56
                radius: 16
                color: cardBg
                border.color: cardBorder
                border.width: 1

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 12
                    Text {
                        text: "\uD83D\uDD0D"
                        font.pixelSize: 20
                        anchors.verticalCenter: parent.verticalCenter
                        color: textSecondary
                    }
                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        anchors.verticalCenter: parent.verticalCenter
                        placeholderText: "Type to search applications..."
                        font.pixelSize: 16
                        color: textPrimary
                        background: Item {}
                    }
                }
            }

            // App grid
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
                        {"name": "Terminal (Root)", "icon": "\uD83D\uDD10", "cmd": "pkexec bright-terminal"},
                        {"name": "Disks", "icon": "\uD83D\uDCBE", "cmd": "gnome-disk-utility"},
                        {"name": "About Bright", "icon": "\u2139\uFE0F", "cmd": "bright-about"}
                    ]
                    delegate: Item {
                        width: (parent.width - 4 * 16) / 5
                        height: width
                        Button {
                            anchors.fill: parent
                            flat: true
                            background: Rectangle {
                                radius: cornerRadius
                                color: appMouse.containsMouse ? cardBg : "transparent"
                                border.color: appMouse.containsMouse ? cardBorder : "transparent"
                                border.width: 1
                            }
                            contentItem: Column {
                                anchors.centerIn: parent
                                spacing: 6
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.icon
                                    font.pixelSize: width * 0.35
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.name
                                    color: textPrimary
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
                                onClicked: { Shell.launchApplication("", modelData.cmd); launcherVisible = false }
                            }
                        }
                    }
                }
            }

            // Footer: user & power
            Row {
                width: parent.width
                spacing: 12
                Button {
                    width: (parent.width - 12) / 2
                    height: 44
                    flat: true
                    text: "\uD83D\uDC64  User"
                    font.pixelSize: 13
                    color: textSecondary
                    background: Rectangle { radius: 12; color: cardBg; border.color: cardBorder; border.width: 1 }
                }
                Button {
                    width: (parent.width - 12) / 2
                    height: 44
                    flat: true
                    text: "\u23FB  Power"
                    font.pixelSize: 13
                    color: "#ef4444"
                    background: Rectangle { radius: 12; color: cardBg; border.color: cardBorder; border.width: 1 }
                    onClicked: { powerMenuVisible = true; launcherVisible = false }
                }
            }
        }
    }

    // Power Menu
    Rectangle {
        id: powerMenu
        z: 200
        visible: powerMenuVisible
        width: 200
        height: contentCol.height + 24
        radius: cornerRadius
        color: cardBg
        border.color: cardBorder
        border.width: 1
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: topPanel.bottom
        anchors.topMargin: 8
        opacity: powerMenuVisible ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 150 } }

        Column {
            id: contentCol
            anchors.fill: parent
            anchors.margins: 12
            spacing: 4

            Text {
                text: "System"
                color: textSecondary
                font.pixelSize: 11
                font.weight: Font.Bold
                leftPadding: 8
                bottomPadding: 4
            }
            Repeater {
                model: [
                    {label: "Lock Screen", icon: "\uD83D\uDD12", action: () => Shell.lockScreen()},
                    {label: "Log Out", icon: "\uD83D\uDEAA", action: () => Shell.logout()},
                    {label: "Suspend", icon: "\uD83D\uDCA4", action: () => Shell.reboot()},
                    {label: "Reboot", icon: "\uD83D\uDD04", action: () => Shell.reboot()},
                    {label: "Shut Down", icon: "\u23FC", action: () => Shell.shutdown()}
                ]
                delegate: Button {
                    width: powerMenu.width - 24
                    height: 38
                    flat: true
                    text: modelData.icon + "  " + modelData.label
                    font.pixelSize: 13
                    color: index === 4 ? "#ef4444" : textPrimary
                    contentItem: Text {
                        text: parent.text
                        color: parent.color
                        font.pixelSize: 13
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    background: Rectangle {
                        radius: 8
                        color: btnMouse.containsMouse ? hoverOverlay : "transparent"
                    }
                    MouseArea {
                        id: btnMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: { modelData.action(); powerMenuVisible = false }
                    }
                }
            }
        }

        MouseArea { anchors.fill: parent; propagateComposedEvents: true }
    }

    // Notification Center (right panel)
    Rectangle {
        id: notifCenter
        z: 150
        visible: notifCenterVisible
        width: 360
        height: parent.height - panelH - 12
        radius: 16
        color: cardBg
        border.color: cardBorder
        border.width: 1
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.top: topPanel.bottom
        anchors.topMargin: 8
        opacity: notifCenterVisible ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 200 } }

        Column {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Text {
                text: "Notifications"
                font.pixelSize: 18
                font.weight: Font.Bold
                color: textPrimary
            }

            Text {
                text: "No new notifications"
                color: textSecondary
                font.pixelSize: 13
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.topMargin: 20
            }

            Item { height: 20; width: 1 }

            Text {
                text: "Quick Settings"
                font.pixelSize: 18
                font.weight: Font.Bold
                color: textPrimary
                anchors.topMargin: 20
            }

            Grid {
                width: parent.width
                columns: 2
                spacing: 8
                Repeater {
                    model: [
                        {"name": "Wi-Fi", "icon": "\uD83D\uDCF6", "active": true},
                        {"name": "Bluetooth", "icon": "\uD83D\uDD37", "active": false},
                        {"name": "Night Light", "icon": "\uD83C\uDF19", "active": false},
                        {"name": "Do Not Disturb", "icon": "\uD83D\uDD15", "active": false}
                    ]
                    delegate: Button {
                        width: (parent.width - 8) / 2
                        height: 56
                        flat: true
                        background: Rectangle {
                            radius: 12
                            color: modelData.active ? accentColor : cardBg
                            border.color: modelData.active ? accentColor : cardBorder
                            border.width: 1
                        }
                        contentItem: Row {
                            anchors.centerIn: parent
                            spacing: 8
                            Text { text: modelData.icon; font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                text: modelData.name
                                font.pixelSize: 12
                                font.weight: Font.Medium
                                color: modelData.active ? "white" : textPrimary
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                }
            }

            // Volume slider
            Column {
                width: parent.width
                spacing: 4
                Text { text: "Volume"; color: textSecondary; font.pixelSize: 12 }
                Slider {
                    width: parent.width
                    from: 0; to: 100; value: 50
                    onMoved: Shell.setVolume(value)
                }
            }

            // Brightness slider
            Column {
                width: parent.width
                spacing: 4
                Text { text: "Brightness"; color: textSecondary; font.pixelSize: 12 }
                Slider {
                    width: parent.width
                    from: 10; to: 100; value: 75
                    onMoved: Shell.setBrightness(value)
                }
            }

            // Theme toggle
            Button {
                width: parent.width
                height: 40
                flat: true
                text: "Switch to " + (currentTheme === "dark" ? "Light" : "Dark") + " Theme"
                font.pixelSize: 12
                color: textPrimary
                background: Rectangle { radius: 10; color: hoverOverlay; border.color: cardBorder; border.width: 1 }
                contentItem: Text {
                    text: parent.text
                    anchors.centerIn: parent
                    color: parent.color
                    font.pixelSize: 12
                }
                onClicked: Shell.setTheme(currentTheme === "dark" ? "light" : "dark")
            }
        }

        MouseArea { anchors.fill: parent; propagateComposedEvents: true }
    }

    // Click-outside catch for popups
    MouseArea {
        z: 90
        anchors.fill: parent
        visible: powerMenuVisible || notifCenterVisible || menuVisible
        onClicked: { powerMenuVisible = false; notifCenterVisible = false; menuVisible = false }
    }

    // Clock signal handler
    Connections {
        target: Shell
        function onClockUpdated(time, date) {
            clockText.text = time
            dateText.text = date
        }
        function onThemeChanged(theme) {
            currentTheme = theme
        }
    }

    Component.onCompleted: {
        // Start KWin window management if not running
        console.log("Bright Desktop Shell", Shell.version, "started")
        console.log("Theme:", currentTheme)
    }
}
