/*
    Bright OS Edition Profiles
    Copyright (C) 2025 Bright OS Project

    Defines three distinct desktop profiles — Home, Developer, and Lite —
    that share the same Bright Design System but configure different layouts,
    default applications, dock items, launcher categories, and behavior.

    All editions share the same brand identity (logo, colors, typography,
    window chrome, settings design); only the layout and default apps differ.
*/

// Home Edition - friendly, polished everyday desktop
var Home = {
    id: "home",
    displayName: "Bright OS Home",
    tagline: "Everyday computing, made simple",

    // Layout
    panelHeight: 40,
    panelPosition: "top",
    dockPosition: "bottom",
    dockIconSize: 48,
    dockCentered: true,
    dockMaxIcons: 9,

    // Visual effects
    animations: true,
    animationFactor: 1.0,
    dockPillShape: true,     // rounded pill dock
    showShadow: true,
    blurPanel: false,         // semi-transparent panel (no blur for compatibility)

    // Dock applications - everyday user essentials
    dockApps: [
        { id: "firefox-esr",         name: "Firefox",         command: "firefox-esr",      category: "web" },
        { id: "bright-files",        name: "Files",           command: "bright-files",     category: "system" },
        { id: "thunderbird",         name: "Thunderbird",     command: "thunderbird",      category: "web" },
        { id: "libreoffice-writer",  name: "LibreOffice",     command: "libreoffice --writer", category: "office" },
        { id: "bright-terminal",     name: "Terminal",        command: "bright-terminal",  category: "system" },
        { id: "vlc",                 name: "VLC",             command: "vlc",              category: "media" },
        { id: "bright-settings",     name: "Settings",        command: "bright-settings",  category: "system" },
        { id: "org.kde.discover",    name: "Software",        command: "plasma-discover",  category: "system" },
    ],

    // Launcher application grid - everyday productivity apps
    launcherApps: [
        { name: "Firefox",        icon: "\uD83E\uDD8A", cmd: "firefox-esr",        category: "web" },
        { name: "Files",          icon: "\uD83D\uDCC1", cmd: "bright-files",       category: "system" },
        { name: "Settings",       icon: "\u2699\uFE0F", cmd: "bright-settings",    category: "system" },
        { name: "Thunderbird",    icon: "\uD83D\uDCE7", cmd: "thunderbird",        category: "web" },
        { name: "Software",       icon: "\uD83D\uDED2", cmd: "plasma-discover",    category: "system" },
        { name: "LibreOffice",    icon: "\uD83D\uDCC4", cmd: "libreoffice",        category: "office" },
        { name: "VLC",            icon: "\u25B6\uFE0F", cmd: "vlc",                category: "media" },
        { name: "GIMP",           icon: "\uD83C\uDFA8", cmd: "gimp",               category: "graphics" },
        { name: "Calculator",     icon: "\uD83E\uDDEE", cmd: "gnome-calculator",   category: "utilities" },
        { name: "Text Editor",    icon: "\uD83D\uDCDD", cmd: "kwrite",             category: "utilities" },
        { name: "Terminal",       icon: "\uD83D\uDDA5", cmd: "bright-terminal",    category: "system" },
        { name: "Monitor",        icon: "\uD83D\uDCCA", cmd: "bright-monitor",     category: "system" },
        { name: "Updates",        icon: "\uD83D\uDD04", cmd: "bright-update",      category: "system" },
        { name: "Calendar",       icon: "\uD83D\uDCC5", cmd: "gnome-calendar",     category: "office" },
        { name: "About",          icon: "\u2139\uFE0F", cmd: "bright-about",       category: "system" },
    ],

    // Launcher categories shown in sidebar
    launcherCategories: [
        { id: "all",       label: "All Apps",    icon: "\u25A6" },
        { id: "web",       label: "Web",         icon: "\uD83C\uDF10" },
        { id: "office",    label: "Office",      icon: "\uD83D\uDCC4" },
        { id: "media",     label: "Media",       icon: "\uD83C\uFAC6" },
        { id: "graphics",  label: "Graphics",    icon: "\uD83C\uDFA8" },
        { id: "utilities", label: "Utilities",   icon: "\uD83D\uDD27" },
        { id: "system",    label: "System",      icon: "\u2699\uFE0F" },
    ],

    // Quick settings toggles visible in notification center
    quickSettings: ["wifi", "bluetooth", "nightlight", "dnd"],

    // Wallpaper set
    wallpapers: {
        dark:  "/usr/share/bright-os/wallpapers/bright-default-dark.svg",
        light: "/usr/share/bright-os/wallpapers/bright-default-light.svg",
    },

    // Panel items (left to right order)
    panelLeft:   ["launcher", "activities"],
    panelCenter: ["clock"],
    panelRight:  ["network", "audio", "battery", "power"],

    // Desktop icons shown
    desktopIcons: ["install-bright-os.desktop", "user-home"],

    // Default theme
    defaultTheme: "dark",
}

// Developer Edition - same brand, developer-focused layout
var Developer = {
    id: "developer",
    displayName: "Bright OS Developer",
    tagline: "Built for creators, engineers, and makers",

    // Layout - slightly more compact, info-dense
    panelHeight: 36,
    panelPosition: "top",
    dockPosition: "left",    // Side dock for developer workflow
    dockIconSize: 40,
    dockCentered: false,
    dockMaxIcons: 12,

    // Visual effects
    animations: true,
    animationFactor: 0.7,    // Slightly snappier animations
    dockPillShape: true,
    showShadow: true,

    // Dock applications - developer tool focused
    dockApps: [
        { id: "firefox-esr",      name: "Firefox",        command: "firefox-esr",      category: "web" },
        { id: "bright-terminal",  name: "Terminal",       command: "bright-terminal",  category: "development" },
        { id: "bright-files",     name: "Files",          command: "bright-files",     category: "system" },
        { id: "code",             name: "Code",           command: "code",             category: "development" },
        { id: "git-gui",          name: "Git",            command: "git gui",          category: "development" },
        { id: "virt-manager",     name: "Virtual Machines", command: "virt-manager",   category: "development" },
        { id: "docker-io",        name: "Docker",         command: "docker.io",        category: "development" },
        { id: "bright-monitor",   name: "System Monitor", command: "bright-monitor",   category: "system" },
        { id: "kicad",            name: "KiCad",          command: "kicad",            category: "electronics" },
        { id: "arduino",          name: "Arduino",        command: "arduino",          category: "electronics" },
        { id: "bright-settings",  name: "Settings",       command: "bright-settings",  category: "system" },
    ],

    // Launcher apps - developer focused
    launcherApps: [
        { name: "Terminal",       icon: "\uD83D\uDDA5", cmd: "bright-terminal",   category: "development" },
        { name: "Code Editor",    icon: "\uD83D\uDCDD", cmd: "code",              category: "development" },
        { name: "Files",          icon: "\uD83D\uDCC1", cmd: "bright-files",      category: "system" },
        { name: "Firefox",        icon: "\uD83E\uDD8A", cmd: "firefox-esr",       category: "web" },
        { name: "Git",            icon: "\uD83D\uDD00", cmd: "git-gui",           category: "development" },
        { name: "Virtual Machines", icon: "\uD83D\uDDA5", cmd: "virt-manager",     category: "development" },
        { name: "Docker",         icon: "\uD83D\uDCE6", cmd: "x-terminal-emulator -e docker", category: "development" },
        { name: "KiCad (EDA)",    icon: "\u26A1",       cmd: "kicad",             category: "electronics" },
        { name: "Arduino IDE",    icon: "\uD83D\uDD0C", cmd: "arduino",           category: "electronics" },
        { name: "System Monitor", icon: "\uD83D\uDCCA", cmd: "bright-monitor",    category: "system" },
        { name: "Serial Terminal", icon: "\uD83D\uDD0C", cmd: "picocom",          category: "electronics" },
        { name: "Wireshark",      icon: "\uD83D\uDD78", cmd: "wireshark",         category: "development" },
        { name: "Calculator",     icon: "\uD83E\uDDEE", cmd: "gnome-calculator",  category: "utilities" },
        { name: "Settings",       icon: "\u2699\uFE0F", cmd: "bright-settings",   category: "system" },
        { name: "About",          icon: "\u2139\uFE0F", cmd: "bright-about",      category: "system" },
    ],

    // Developer-specific categories
    launcherCategories: [
        { id: "all",          label: "All Apps",     icon: "\u25A6" },
        { id: "development",  label: "Development",  icon: "\uD83D\uDCBB" },
        { id: "electronics",  label: "Electronics",  icon: "\u26A1" },
        { id: "web",          label: "Web",          icon: "\uD83C\uDF10" },
        { id: "system",       label: "System",       icon: "\u2699\uFE0F" },
        { id: "utilities",    label: "Utilities",    icon: "\uD83D\uDD27" },
    ],

    quickSettings: ["wifi", "bluetooth", "nightlight", "dnd", "workspaces"],

    wallpapers: {
        dark:  "/usr/share/bright-os/wallpapers/bright-default-dark.svg",
        light: "/usr/share/bright-os/wallpapers/bright-default-light.svg",
    },

    panelLeft:   ["launcher", "workspaces"],
    panelCenter: ["clock"],
    panelRight:  ["network", "cpu", "mem", "audio", "battery", "power"],

    desktopIcons: ["install-bright-os.desktop"],

    defaultTheme: "dark",

    // Developer extras: workspace count, sysmon defaults
    workspaces: 4,
    showSystemTrayMetrics: true,  // CPU/Mem in panel
}

// Lite Edition - same brand identity, lightweight profile
var Lite = {
    id: "lite",
    displayName: "Bright OS Lite",
    tagline: "Fast and responsive on older hardware",

    // Layout - compact, minimal
    panelHeight: 28,
    panelPosition: "bottom",   // Bottom panel (like traditional lightweight desktops)
    dockPosition: "none",      // No dock in Lite; use launcher menu only
    dockIconSize: 32,
    dockCentered: false,
    dockMaxIcons: 0,

    // Visual effects - reduced for performance
    animations: false,
    animationFactor: 0.0,
    dockPillShape: false,
    showShadow: false,
    compositorOpacity: false,

    // Dock/panel apps - essentials only (panel launchers instead of dock)
    dockApps: [
        // Lite uses a simpler taskbar; essential launchers shown in panel menu
    ],

    // Panel quick launch (left-click items in panel for Lite)
    panelLaunchers: [
        { id: "bright-launcher", name: "Menu",     command: "bright-launcher",  icon: "\u2630" },
        { id: "firefox-esr",     name: "Firefox",  command: "firefox-esr",      icon: "\uD83E\uDD8A" },
        { id: "bright-files",    name: "Files",    command: "pcmanfm-qt",       icon: "\uD83D\uDCC1" },
        { id: "bright-terminal", name: "Terminal", command: "qterminal",        icon: "\uD83D\uDDA5" },
        { id: "bright-settings", name: "Settings", command: "bright-settings",  icon: "\u2699\uFE0F" },
    ],

    // Launcher apps - essentials only
    launcherApps: [
        { name: "Firefox",     icon: "\uD83E\uDD8A", cmd: "firefox-esr",     category: "web" },
        { name: "Files",       icon: "\uD83D\uDCC1", cmd: "pcmanfm-qt",      category: "system" },
        { name: "Terminal",    icon: "\uD83D\uDDA5", cmd: "qterminal",       category: "system" },
        { name: "Text Editor", icon: "\uD83D\uDCDD", cmd: "featherpad",      category: "utilities" },
        { name: "Calculator",  icon: "\uD83E\uDDEE", cmd: "galculator",      category: "utilities" },
        { name: "Settings",    icon: "\u2699\uFE0F", cmd: "bright-settings", category: "system" },
        { name: "Monitor",     icon: "\uD83D\uDCCA", cmd: "qps",             category: "system" },
        { name: "VLC/MPV",     icon: "\u25B6\uFE0F", cmd: "mpv",             category: "media" },
        { name: "Archiver",    icon: "\uD83D\uDDC3", cmd: "engrampa",        category: "utilities" },
        { name: "About",       icon: "\u2139\uFE0F", cmd: "bright-about",    category: "system" },
    ],

    launcherCategories: [
        { id: "all",       label: "All Apps",  icon: "\u25A6" },
        { id: "web",       label: "Internet", icon: "\uD83C\uDF10" },
        { id: "system",    label: "System",   icon: "\u2699\uFE0F" },
        { id: "utilities", label: "Tools",    icon: "\uD83D\uDD27" },
        { id: "media",     label: "Media",    icon: "\uD83C\uFAC6" },
    ],

    quickSettings: ["wifi"],

    wallpapers: {
        dark:  "/usr/share/bright-os/wallpapers/bright-default-dark.svg",
        light: "/usr/share/bright-os/wallpapers/bright-default-light.svg",
    },

    panelLeft:   ["launcher", "quicklaunch"],
    panelCenter: ["clock"],
    panelRight:  ["network", "audio", "battery", "power"],

    desktopIcons: ["install-bright-os.desktop"],

    defaultTheme: "dark",

    // Lite resource-saving settings
    disableAnimations: true,
    disableCompositor: false,   // Picom with very light settings
    reduceRefreshRate: false,
    singleClickLaunch: true,
}

// Get profile by edition id string
function getProfile(editionId) {
    if (editionId === "developer") return Developer;
    if (editionId === "lite") return Lite;
    return Home;
}

// Default fallback profile
var Default = Home;
