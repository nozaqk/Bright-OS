import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "design/DesignTokens.js" as Tokens
import "profiles/EditionProfiles.js" as Profiles

/*
    Bright Desktop Shell - Main QML UI
    Copyright (C) 2025 Bright OS Project

    Architecture:
    - WallpaperWindow: Fullscreen background (behind everything)
    - PanelWindow:     Panel at top (home/dev) or bottom (lite), always on top
    - DockWindow:      Dock (not shown in Lite edition)
    - Overlay windows: Launcher, notification center, power menu

    Uses the shared Bright Design System (Tokens) and edition profiles (Profiles)
    so all editions share the same visual identity but have different layouts.

    NOTE: Uses plain Rectangle with semi-transparent backgrounds instead of
    MultiEffect (QtQuick.Effects is Qt 6.5+, Debian Bookworm ships Qt 6.4).
*/

// ---------- Edition Profile (resolved at startup) ----------
var profile = Profiles.getProfile(EditionId)
var colors = Tokens.colors(Shell.initialTheme)

// ---------- Wallpaper ----------
Window {
    id: wallpaperWindow
    visible: true
    width: Screen.width
    height: Screen.height
    x: 0; y: 0
    color: colors.bgBase
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool
    z: 0

    property string currentWallpaper: Shell.initialWallpaper || profile.wallpapers.dark
    property string currentTheme: Shell.initialTheme
    property bool animationsEnabled: profile.animations

    // Expose design tokens as readonly properties for child windows
    readonly property color accent: Tokens.Brand.accent
    readonly property int cornerRadius: Tokens.Radius.lg
    readonly property int fontBase: Tokens.Font.sizeLg

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
        console.log("Edition:", Shell.edition, "| Theme:", wallpaperWindow.currentTheme)
    }
}

// ---------- Helper: color accessor for current theme ----------
function c(key) {
    var dark = wallpaperWindow.currentTheme === "dark"
    switch (key) {
        case "panelBg":    return dark ? Tokens.Dark.bgPanel     : Tokens.Light.bgPanel
        case "panelFg":    return dark ? Tokens.Dark.textPrimary  : Tokens.Light.textPrimary
        case "text2":      return dark ? Tokens.Dark.textSecondary: Tokens.Light.textSecondary
        case "hover":      return dark ? Tokens.Dark.bgHover      : Tokens.Light.bgHover
        case "border":     return dark ? Tokens.Dark.borderDefault: Tokens.Light.borderDefault
        case "cardBg":     return dark ? Tokens.Dark.bgCard       : Tokens.Light.bgCard
        case "cardBorder": return dark ? Tokens.Dark.borderDefault: Tokens.Light.borderDefault
        case "overlayBg":  return dark ? Tokens.Dark.bgOverlay    : Tokens.Light.bgOverlay
        case "dockBg":     return dark ? "#d00f172a"              : "#d0e2e8f0"
        case "dockBorder": return dark ? Tokens.Dark.borderDefault: Tokens.Light.borderDefault
        case "error":      return dark ? Tokens.Dark.error        : Tokens.Light.error
        case "success":    return dark ? Tokens.Dark.success      : Tokens.Light.success
        case "inputBg":    return dark ? Tokens.Dark.bgInput      : Tokens.Light.bgInput
        default:           return dark ? Tokens.Dark.textPrimary  : Tokens.Light.textPrimary
    }
}

// ---------- Top/Bottom Panel ----------
Window {
    id: panelWindow
    visible: true
    width: Screen.width
    height: Shell.panelHeight > 0 ? Shell.panelHeight : profile.panelHeight
    x: 0
    y: profile.panelPosition === "bottom" ? Screen.height - height : 0
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 10

    readonly property bool isBottom: Shell.panelPosition === "bottom" || profile.panelPosition === "bottom"
    readonly property int panelH: height
    readonly property int btnSize: panelH - 6

    Rectangle {
        anchors.fill: parent
        color: c("panelBg")
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: panelWindow.isBottom ? parent.top : parent.bottom
            anchors.topMargin: panelWindow.isBottom ? 0 : -1
            height: 1
            color: c("border")
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Tokens.Space.base
        anchors.rightMargin: Tokens.Space.base
        spacing: Tokens.Space.sm

        // --- Left: Launcher button ---
        ToolButton {
            id: launcherBtn
            Layout.preferredWidth: panelWindow.btnSize
            Layout.preferredHeight: panelWindow.btnSize
            contentItem: Text {
                // Bright OS sun logo glyph (matches brand mark)
                text: EditionId === "lite" ? "\u2630" : "\u2600"
                anchors.centerIn: parent
                font.pixelSize: EditionId === "lite" ? 14 : 16
                color: c("panelFg")
                font.weight: Font.Medium
            }
            background: Rectangle { radius: Tokens.Radius.md; color: launcherBtn.hovered ? c("hover") : "transparent" }
            onClicked: { launcherWindow.visible = !launcherWindow.visible; if (launcherWindow.visible) launcherWindow.activate() }
        }

        // Lite edition: quick launch icons next to menu
        Repeater {
            model: EditionId === "lite" ? profile.panelLaunchers.slice(1) : []
            delegate: ToolButton {
                Layout.preferredWidth: panelWindow.btnSize
                Layout.preferredHeight: panelWindow.btnSize
                contentItem: Text {
                    text: modelData.icon
                    anchors.centerIn: parent
                    font.pixelSize: 13
                    color: c("panelFg")
                }
                background: Rectangle { radius: Tokens.Radius.md; color: parent.hovered ? c("hover") : "transparent" }
                onClicked: Shell.launchApplication(modelData.id, modelData.command)
                ToolTip.visible: mouseArea2.containsMouse
                ToolTip.text: modelData.name
                ToolTip.delay: 600
                MouseArea { id: mouseArea2; anchors.fill: parent; hoverEnabled: true; propagateComposedEvents: true }
            }
        }

        // Developer edition: workspace indicator
        Text {
            visible: EditionId === "developer"
            text: "\u25A3 1"
            color: c("text2")
            font.pixelSize: Tokens.Font.sizeBase
            font.family: Tokens.Font.familyMono
            Layout.leftMargin: Tokens.Space.md
        }

        Item { Layout.fillWidth: true }

        // --- Center: Clock ---
        Column {
            spacing: 0
            Text {
                id: clockText
                anchors.horizontalCenter: parent.horizontalCenter
                text: "00:00"
                color: c("panelFg")
                font.pixelSize: Tokens.Font.sizeClock
                font.weight: Font.Medium
            }
            Text {
                id: dateText
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Loading..."
                color: c("text2")
                font.pixelSize: Tokens.Font.sizeDate
                visible: !panelWindow.isBottom
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: notifWindow.visible = !notifWindow.visible
            }
        }

        Item { Layout.fillWidth: true }

        // --- Developer: CPU/Mem metrics ---
        Text {
            visible: Shell.showMetrics && EditionId === "developer"
            text: "CPU " + Math.round(Shell.cpuPercent) + "%  MEM " + Math.round(Shell.memPercent) + "%"
            color: c("text2")
            font.pixelSize: Tokens.Font.sizeSm
            font.family: Tokens.Font.familyMono
        }

        // --- Right: System tray icons ---
        Row {
            spacing: Tokens.Space.xs
            anchors.verticalCenter: parent.verticalCenter

            ToolButton {
                implicitWidth: panelWindow.btnSize
                implicitHeight: panelWindow.btnSize
                background: Rectangle { radius: Tokens.Radius.md; color: parent.hovered ? c("hover") : "transparent" }
                contentItem: Text { text: "\uD83D\uDD0C"; anchors.centerIn: parent; font.pixelSize: 12; color: c("panelFg") }
                ToolTip.text: "Network"; ToolTip.visible: mm1.containsMouse; ToolTip.delay: 500
                MouseArea { id: mm1; anchors.fill: parent; hoverEnabled: true }
            }
            ToolButton {
                implicitWidth: panelWindow.btnSize
                implicitHeight: panelWindow.btnSize
                background: Rectangle { radius: Tokens.Radius.md; color: parent.hovered ? c("hover") : "transparent" }
                contentItem: Text { text: "\uD83D\uDD0A"; anchors.centerIn: parent; font.pixelSize: 12; color: c("panelFg") }
                ToolTip.text: "Volume"; ToolTip.visible: mm2.containsMouse; ToolTip.delay: 500
                MouseArea { id: mm2; anchors.fill: parent; hoverEnabled: true }
            }
            ToolButton {
                implicitWidth: panelWindow.btnSize
                implicitHeight: panelWindow.btnSize
                background: Rectangle { radius: Tokens.Radius.md; color: parent.hovered ? c("hover") : "transparent" }
                contentItem: Text { text: "\u23FB"; anchors.centerIn: parent; font.pixelSize: 14; color: c("panelFg") }
                onClicked: powerWindow.visible = !powerWindow.visible
            }
        }
    }
}

// ---------- Dock (hidden for Lite edition, side dock for Developer) ----------
Window {
    id: dockWindow
    visible: profile.dockPosition !== "none"
    // Dimensions depend on dock position
    width: profile.dockPosition === "left" || profile.dockPosition === "right"
        ? Shell.dockIconSize + Tokens.Space.lg
        : Math.min(Screen.width - 80, dockAppsModel.count * Shell.dockIconSize + Tokens.Space.xl)
    height: profile.dockPosition === "left" || profile.dockPosition === "right"
        ? Math.min(Screen.height - panelWindow.height * 2 - 40, dockAppsModel.count * Shell.dockIconSize + Tokens.Space.xl)
        : Shell.dockIconSize + Tokens.Space.lg
    x: profile.dockPosition === "left" ? 8
     : profile.dockPosition === "right" ? Screen.width - width - 8
     : (Screen.width - width) / 2
    y: profile.dockPosition === "left" || profile.dockPosition === "right"
        ? (Screen.height - height) / 2
        : panelWindow.isBottom ? panelWindow.height + 8 : Screen.height - height - 8
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 10

    property int dockIconSize: Shell.dockIconSize > 0 ? Shell.dockIconSize : profile.dockIconSize
    property bool verticalDock: profile.dockPosition === "left" || profile.dockPosition === "right"
    readonly property int radiusSize: profile.dockPillShape ? (dockWindow.verticalDock ? width / 2 : height / 2) : Tokens.Radius.xl

    property var dockAppsModel: JSON.parse(DockApps)

    Rectangle {
        anchors.fill: parent
        radius: dockWindow.radiusSize
        color: c("dockBg")
        border.color: c("dockBorder")
        border.width: 1
    }

    Column {
        anchors.centerIn: parent
        spacing: Tokens.Space.sm
        visible: dockWindow.verticalDock

        Repeater {
            model: dockWindow.dockAppsModel
            delegate: Item {
                width: dockWindow.dockIconSize
                height: dockWindow.dockIconSize
                Button {
                    anchors.centerIn: parent
                    width: dockWindow.dockIconSize
                    height: dockWindow.dockIconSize
                    flat: true
                    background: Rectangle {
                        radius: Tokens.Radius.lg
                        color: dockMouse.containsMouse ? c("hover") : "transparent"
                    }
                    contentItem: Text {
                        anchors.centerIn: parent
                        text: modelData.name.charAt(0)
                        font.pixelSize: dockWindow.dockIconSize * 0.4
                        color: c("panelFg")
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        id: dockMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: Shell.launchApplication(modelData.id, modelData.command)
                    }
                    ToolTip.visible: dockMouse.containsMouse
                    ToolTip.text: modelData.name
                    ToolTip.delay: 500
                }
            }
        }
    }

    Row {
        anchors.centerIn: parent
        spacing: Tokens.Space.sm
        visible: !dockWindow.verticalDock

        Repeater {
            model: dockWindow.dockAppsModel
            delegate: Item {
                width: dockWindow.dockIconSize
                height: dockWindow.dockIconSize
                Button {
                    anchors.centerIn: parent
                    width: dockWindow.dockIconSize
                    height: dockWindow.dockIconSize
                    flat: true
                    background: Rectangle {
                        radius: Tokens.Radius.lg
                        color: dockMouseH.containsMouse ? c("hover") : "transparent"
                    }
                    contentItem: Text {
                        anchors.centerIn: parent
                        text: modelData.name.charAt(0)
                        font.pixelSize: dockWindow.dockIconSize * 0.4
                        color: c("panelFg")
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        id: dockMouseH
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: Shell.launchApplication(modelData.id, modelData.command)
                    }
                    ToolTip.visible: dockMouseH.containsMouse
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
    property string currentCategory: "all"
    property var profileApps: profile.launcherApps
    property var categories: profile.launcherCategories

    Shortcut { sequence: "Escape"; onActivated: launcherWindow.visible = false }

    Rectangle {
        anchors.fill: parent
        color: c("overlayBg")
    }
    MouseArea { anchors.fill: parent; onClicked: launcherWindow.visible = false }

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 100, Tokens.Size.launcherWidth)
        spacing: Tokens.Space.xl

        // Brand header
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Tokens.Space.md
            Text {
                text: "\u2600"
                font.pixelSize: 32
                color: Tokens.Brand.accent
                anchors.verticalCenter: parent.verticalCenter
            }
            Column {
                Text {
                    text: Shell.editionDisplayName
                    color: c("panelFg")
                    font.pixelSize: Tokens.Font.size2xl
                    font.weight: Font.Bold
                }
                Text {
                    text: Shell.editionTagline
                    color: c("text2")
                    font.pixelSize: Tokens.Font.sizeSm
                }
            }
        }

        // Search bar
        Rectangle {
            width: parent.width
            height: 52
            radius: Tokens.Radius.xl
            color: c("cardBg")
            border.color: c("cardBorder")
            border.width: 1
            Row {
                anchors.fill: parent
                anchors.margins: Tokens.Space.lg
                spacing: Tokens.Space.md
                Text { text: "\uD83D\uDD0D"; font.pixelSize: Tokens.Font.sizeXl; anchors.verticalCenter: parent.verticalCenter; color: c("text2") }
                TextField {
                    id: searchField
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 50
                    placeholderText: "Search applications..."
                    font.pixelSize: Tokens.Font.sizeLg
                    color: c("panelFg")
                    background: Item {}
                    focus: true
                    onVisibleChanged: if (visible) searchField.forceActiveFocus()
                }
            }
        }

        // Application grid (filtered by category and search)
        Grid {
            id: appGrid
            width: parent.width
            columns: profile.launcherCategories.length > 5 ? 4 : 5
            spacing: Tokens.Space.md
            Repeater {
                id: appRepeater
                model: launcherWindow.profileApps
                delegate: Item {
                    width: (parent.width - (appGrid.columns - 1) * appGrid.spacing) / appGrid.columns
                    height: width
                    visible: launcherWindow.currentCategory === "all" || modelData.category === launcherWindow.currentCategory
                    Button {
                        anchors.fill: parent
                        flat: true
                        background: Rectangle {
                            radius: Tokens.Radius.lg
                            color: appMouse.containsMouse ? c("cardBg") : "transparent"
                            border.color: appMouse.containsMouse ? c("cardBorder") : "transparent"
                            border.width: 1
                        }
                        contentItem: Column {
                            anchors.centerIn: parent
                            spacing: Tokens.Space.sm
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.icon; font.pixelSize: width * 0.35 }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.name
                                color: c("panelFg")
                                font.pixelSize: Tokens.Font.sizeSm
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

        // Category pills
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Tokens.Space.sm
            Repeater {
                model: launcherWindow.categories
                delegate: Button {
                    flat: true
                    contentItem: Text {
                        text: modelData.icon + " " + modelData.label
                        color: launcherWindow.currentCategory === modelData.id ? "#ffffff" : c("panelFg")
                        font.pixelSize: Tokens.Font.sizeSm
                        font.weight: Font.Medium
                        anchors.centerIn: parent
                    }
                    background: Rectangle {
                        radius: Tokens.Radius.pill
                        color: launcherWindow.currentCategory === modelData.id ? Tokens.Brand.accent : "transparent"
                        border.color: c("cardBorder")
                        border.width: 1
                    }
                    onClicked: launcherWindow.currentCategory = modelData.id
                }
            }
        }

        // Footer buttons
        Row {
            width: parent.width; spacing: Tokens.Space.md
            Button {
                width: (parent.width - Tokens.Space.md) / 2; height: 44; flat: true
                contentItem: Text { text: "\uD83D\uDD27  Settings"; anchors.left: parent.left; anchors.leftMargin: Tokens.Space.lg; anchors.verticalCenter: parent.verticalCenter; color: c("text2"); font.pixelSize: Tokens.Font.sizeMd }
                background: Rectangle { radius: Tokens.Radius.lg; color: c("cardBg"); border.color: c("cardBorder"); border.width: 1 }
                onClicked: { Shell.openSettings(); launcherWindow.visible = false }
            }
            Button {
                width: (parent.width - Tokens.Space.md) / 2; height: 44; flat: true
                contentItem: Text { text: "\u23FB  Power"; anchors.left: parent.left; anchors.leftMargin: Tokens.Space.lg; anchors.verticalCenter: parent.verticalCenter; color: c("error"); font.pixelSize: Tokens.Font.sizeMd }
                background: Rectangle { radius: Tokens.Radius.lg; color: c("cardBg"); border.color: c("cardBorder"); border.width: 1 }
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
    y: panelWindow.isBottom ? Screen.height - panelWindow.height - height - 8 : panelWindow.height + 8
    height: contentCol.height + Tokens.Space.lg

    Shortcut { sequence: "Escape"; onActivated: powerWindow.visible = false }

    Rectangle {
        anchors.fill: parent
        radius: Tokens.Radius.lg
        color: c("cardBg")
        border.color: c("cardBorder")
        border.width: 1
    }

    Column {
        id: contentCol
        anchors.fill: parent
        anchors.margins: Tokens.Space.md
        spacing: Tokens.Space.xs

        Text { text: "System"; color: c("text2"); font.pixelSize: Tokens.Font.sizeXs; font.weight: Font.Bold; leftPadding: 8; bottomPadding: 4 }
        Repeater {
            model: [
                {label: "Lock Screen", icon: "\uD83D\uDD12", action: () => Shell.lockScreen()},
                {label: "Log Out", icon: "\uD83D\uDEAA", action: () => Shell.logout()},
                {label: "Suspend", icon: "\uD83D\uDCA4", action: () => Shell.reboot()},
                {label: "Reboot", icon: "\uD83D\uDD04", action: () => Shell.reboot()},
                {label: "Shut Down", icon: "\u23FC", isDestructive: true, action: () => Shell.shutdown()}
            ]
            delegate: Button {
                width: powerWindow.width - 24; height: 38; flat: true
                contentItem: Text {
                    text: modelData.icon + "  " + modelData.label
                    anchors.left: parent.left; anchors.leftMargin: Tokens.Space.md
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData.isDestructive ? c("error") : c("panelFg")
                    font.pixelSize: Tokens.Font.sizeMd
                }
                background: Rectangle { radius: Tokens.Radius.md; color: pMouse.containsMouse ? c("hover") : "transparent" }
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
    width: Tokens.Size.notifWidth
    height: Math.min(Screen.height - panelWindow.height - (dockWindow.visible ? dockWindow.height : 0) - 32, Tokens.Size.notifMaxHeight)
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    z: 150
    x: Screen.width - width - 8
    y: panelWindow.isBottom ? 8 : panelWindow.height + 8

    Shortcut { sequence: "Escape"; onActivated: notifWindow.visible = false }

    Rectangle {
        anchors.fill: parent
        radius: Tokens.Radius.xl
        color: c("cardBg")
        border.color: c("cardBorder")
        border.width: 1
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: Tokens.Space.lg
        clip: true
        Column {
            width: notifWindow.width - 44
            spacing: Tokens.Space.md

            Text { text: "Notifications"; font.pixelSize: Tokens.Font.size2xl; font.weight: Font.Bold; color: c("panelFg") }
            Text { text: "No new notifications"; color: c("text2"); font.pixelSize: Tokens.Font.sizeMd; topPadding: Tokens.Space.lg }
            Item { height: Tokens.Space.md; width: 1 }
            Text { text: "Quick Settings"; font.pixelSize: Tokens.Font.size2xl; font.weight: Font.Bold; color: c("panelFg"); topPadding: Tokens.Space.xl }

            Grid {
                width: parent.width; columns: 2; spacing: Tokens.Space.sm
                Repeater {
                    model: [
                        {"name": "Wi-Fi", "icon": "\uD83D\uDCF6", "active": true},
                        {"name": "Bluetooth", "icon": "\uD83D\uDD37", "active": false},
                        {"name": "Night Light", "icon": "\uD83C\uDF19", "active": false},
                        {"name": "Do Not Disturb", "icon": "\uD83D\uDD15", "active": false}
                    ]
                    delegate: Button {
                        width: (parent.width - Tokens.Space.sm) / 2; height: 48; flat: true
                        background: Rectangle {
                            radius: Tokens.Radius.lg
                            color: modelData.active ? Tokens.Brand.accent : c("cardBg")
                            border.color: modelData.active ? Tokens.Brand.accent : c("cardBorder")
                            border.width: 1
                        }
                        contentItem: Row {
                            anchors.centerIn: parent; spacing: Tokens.Space.sm
                            Text { text: modelData.icon; font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData.name; font.pixelSize: Tokens.Font.sizeSm; font.weight: Font.Medium; color: modelData.active ? "white" : c("panelFg"); anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }

            Column { width: parent.width; spacing: Tokens.Space.xs
                Text { text: "Volume"; color: c("text2"); font.pixelSize: Tokens.Font.sizeSm }
                Slider { width: parent.width; from: 0; to: 100; value: 50; onMoved: Shell.setVolume(value) }
            }
            Column { width: parent.width; spacing: Tokens.Space.xs
                Text { text: "Brightness"; color: c("text2"); font.pixelSize: Tokens.Font.sizeSm }
                Slider { width: parent.width; from: 10; to: 100; value: 75; onMoved: Shell.setBrightness(value) }
            }

            Button {
                width: parent.width; height: 40; flat: true
                contentItem: Text { text: "Switch to " + (wallpaperWindow.currentTheme === "dark" ? "Light" : "Dark") + " Theme"; anchors.centerIn: parent; color: c("panelFg"); font.pixelSize: Tokens.Font.sizeSm }
                background: Rectangle { radius: Tokens.Radius.md; color: c("hover"); border.color: c("cardBorder"); border.width: 1 }
                onClicked: {
                    var newTheme = wallpaperWindow.currentTheme === "dark" ? "light" : "dark"
                    Shell.setTheme(newTheme)
                    wallpaperWindow.currentTheme = newTheme
                    colors = Tokens.colors(newTheme)
                    var wpName = newTheme === "dark" ? "bright-default-dark.svg" : "bright-default-light.svg"
                    wallpaperWindow.currentWallpaper = "/usr/share/bright-os/wallpapers/" + wpName
                }
            }

            // Edition info footer
            Rectangle {
                width: parent.width; height: 1; color: c("border")
            }
            Text {
                text: Shell.editionDisplayName + "  \u2022  " + Shell.version
                color: c("text2")
                font.pixelSize: Tokens.Font.sizeXs
                anchors.horizontalCenter: parent.horizontalCenter
                topPadding: Tokens.Space.sm
            }
            Item { height: Tokens.Space.md; width: 1 }
        }
    }
}

// ---------- Signal handlers ----------
Connections {
    target: Shell
    function onClockUpdated(time, date) {
        clockText.text = time
        dateText.text = date
    }
    function onThemeChanged(theme) {
        wallpaperWindow.currentTheme = theme
        colors = Tokens.colors(theme)
        var wpName = theme === "dark" ? "bright-default-dark.svg" : "bright-default-light.svg"
        wallpaperWindow.currentWallpaper = "/usr/share/bright-os/wallpapers/" + wpName
    }
}

// ---------- Global keyboard shortcuts ----------
Shortcut { sequence: "Super+T"; onActivated: Shell.openTerminal() }
Shortcut { sequence: "Super+E"; onActivated: Shell.openFiles() }
Shortcut { sequence: "Super+S"; onActivated: Shell.openSettings() }
Shortcut { sequence: "Super+L"; onActivated: Shell.lockScreen() }
Shortcut { sequence: "Super"; onActivated: { launcherWindow.visible = !launcherWindow.visible; if (launcherWindow.visible) launcherWindow.activate() } }
Shortcut { sequence: "Alt+F2"; onActivated: { launcherWindow.visible = !launcherWindow.visible; if (launcherWindow.visible) launcherWindow.activate() } }

Component.onCompleted: {
    console.log("Bright Desktop Shell", Shell.version, "started successfully")
    console.log("Edition:", Shell.edition, "(" + Shell.editionDisplayName + ")")
    console.log("Theme:", wallpaperWindow.currentTheme)
    console.log("Resolution:", Screen.width, "x", Screen.height)
    console.log("Dock position:", profile.dockPosition, "| Panel:", profile.panelPosition)
}
