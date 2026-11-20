/*
    Bright Design System - Shared Design Tokens
    Copyright (C) 2025 Bright OS Project

    Centralized color palette, typography, spacing, radii, and animation tokens
    used across all Bright Desktop components and all three editions.
    This is the single source of truth for the Bright OS visual identity.

    Import in QML: import "design/DesignTokens.js" as Tokens
*/

/*
    Bright OS Brand Colors
    The brand uses a blue-violet gradient (blue → indigo → violet) as the
    primary accent, consistent across all editions.
*/
var Brand = {
    // Primary gradient stops
    blue:        "#3b82f6",   // Bright Blue (primary)
    blueLight:   "#60a5fa",   // Light Blue
    indigo:      "#6366f1",   // Indigo
    violet:      "#8b5cf6",   // Violet
    violetLight: "#c4b5fd",   // Light Violet
    blueDark:    "#2563eb",   // Dark Blue (pressed)

    // Semantic accent (used as the primary interactive color)
    accent:      "#3b82f6",
    accentHover: "#2563eb",
    accentLight: "#93c5fd",
    accentGlow:  "#3b82f6",
}

// Dark theme color tokens
var Dark = {
    // Surfaces
    bgBase:       "#0a0e1a",   // Deepest background (wallpaper area, overlays)
    bgElevated:   "#0f172a",   // Elevated surfaces (cards, menus)
    bgPanel:      "#e00a0e1a", // Panel background (semi-transparent)
    bgCard:       "#1e293b",   // Cards (launcher items, notif center)
    bgButton:     "#1e293b",   // Button resting state
    bgButtonAlt:  "#334155",   // Secondary buttons
    bgHover:      "#ffffff18", // Hover overlay (~9%)
    bgActive:     "#ffffff24", // Active/pressed overlay (~14%)
    bgInput:      "#0f172a",   // Input field background
    bgOverlay:    "#e60a0e1a", // Modal/launcher overlay (~90%)

    // Borders
    borderDefault: "#334155",
    borderSubtle:  "#1e293b",
    borderFocus:   Brand.blue,

    // Text
    textPrimary:   "#f1f5f9",
    textSecondary: "#94a3b8",
    textTertiary:  "#64748b",
    textInverse:   "#0f172a",
    textLink:      Brand.blueLight,
    textVisited:   Brand.violetLight,

    // Semantic colors
    success:       "#22c55e",
    warning:       "#eab308",
    error:         "#ef4444",
    info:          Brand.blue,

    // Accent (from brand)
    accent:        Brand.accent,
    accentHover:   Brand.accentHover,
    accentText:    "#ffffff",
}

// Light theme color tokens
var Light = {
    // Surfaces
    bgBase:       "#f8fafc",
    bgElevated:   "#ffffff",
    bgPanel:      "#e0f0f4ff",
    bgCard:       "#ffffff",
    bgButton:     "#f1f5f9",
    bgButtonAlt:  "#e2e8f0",
    bgHover:      "#00000010",
    bgActive:     "#00000018",
    bgInput:      "#ffffff",
    bgOverlay:    "#e6f0f4ff",

    // Borders
    borderDefault: "#cbd5e1",
    borderSubtle:  "#e2e8f0",
    borderFocus:   Brand.blue,

    // Text
    textPrimary:   "#0f172a",
    textSecondary: "#64748b",
    textTertiary:  "#94a3b8",
    textInverse:   "#ffffff",
    textLink:      Brand.blueDark,
    textVisited:   Brand.violet,

    // Semantic colors
    success:       "#16a34a",
    warning:       "#ca8a04",
    error:         "#dc2626",
    info:          Brand.blueDark,

    // Accent (from brand)
    accent:        Brand.accent,
    accentHover:   Brand.accentHover,
    accentText:    "#ffffff",
}

/*
    Typography scale
    Uses DejaVu Sans as the primary UI font (available in Debian base).
    Monospace uses Hack.
*/
var Font = {
    family:        "DejaVu Sans",
    familyMono:    "Hack, DejaVu Sans Mono, monospace",
    // Sizes in pixels (good default for 96 DPI)
    sizeXs:        10,
    sizeSm:        11,
    sizeBase:      12,
    sizeMd:        13,
    sizeLg:        14,
    sizeXl:        16,
    size2xl:       18,
    size3xl:       24,
    size4xl:       28,
    sizeClock:     14,
    sizeDate:      10,
    // Weights
    weightNormal:  400,
    weightMedium:  500,
    weightBold:    700,
}

/*
    Spacing scale (in pixels)
*/
var Space = {
    xs:    2,
    sm:    4,
    md:    8,
    base:  12,
    lg:   16,
    xl:   24,
    xxl:  32,
    xxxl: 48,
}

/*
    Corner radii (in pixels)
*/
var Radius = {
    sm:    4,
    md:    8,
    lg:   12,
    xl:   16,
    pill: 999,    // Fully rounded pill/dock shape
}

/*
    Window and element sizing
*/
var Size = {
    panelHeight:       40,
    panelHeightLite:   32,   // Slimmer panel for Lite
    dockIconSizeHome:  48,
    dockIconSizeDev:   48,
    dockIconSizeLite:  36,   // Smaller dock icons for Lite
    dockPadding:       10,
    launcherWidth:     720,
    launcherGridCols:  5,
    powerMenuWidth:    220,
    notifWidth:        360,
    notifMaxHeight:    620,
}

/*
    Animation durations (milliseconds)
    Lite edition uses reduced animations.
*/
var Animation = {
    fast:     100,
    normal:   200,
    slow:     300,
    // Reduced motion multiplier (0 = no animations, 1 = full)
    motionFactorHome:      1.0,
    motionFactorDeveloper: 1.0,
    motionFactorLite:      0.0, // Lite disables heavy animations
}

/*
    Shadow definitions (CSS-compatible strings, used where effects possible)
    Simplified for use with Rectangle borders on older Qt.
*/
var Shadow = {
    sm: "0 1px 2px rgba(0,0,0,0.15)",
    md: "0 4px 8px rgba(0,0,0,0.2)",
    lg: "0 8px 24px rgba(0,0,0,0.3)",
    glow: "0 0 20px rgba(59,130,246,0.3)",
}

// Helper: return color set for given theme name
function colors(theme) {
    if (theme === "light") return Light;
    return Dark;
}

// Helpers for font/text style objects
function clockTextStyle(theme) {
    var c = colors(theme);
    return { color: c.textPrimary, pixelSize: Font.sizeClock, weight: Font.weightMedium };
}

function dateTextStyle(theme) {
    var c = colors(theme);
    return { color: c.textSecondary, pixelSize: Font.sizeDate };
}

function bodyTextStyle(theme) {
    var c = colors(theme);
    return { color: c.textPrimary, pixelSize: Font.sizeLg };
}

function secondaryTextStyle(theme) {
    var c = colors(theme);
    return { color: c.textSecondary, pixelSize: Font.sizeBase };
}
