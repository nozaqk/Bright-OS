# Bright Desktop Architecture

## Overview

Bright Desktop is the original desktop environment for Bright OS, built with Qt 6 / QML and Python. It uses KWin as its Wayland compositor and provides a panel, dock, application launcher, notification center, and power controls through separate overlay windows.

The desktop supports three editions — **Home**, **Developer**, and **Lite** — that share one unified visual identity through the **Bright Design System**. Only the layout, default applications, and performance settings differ between editions.

## Directory Structure

```
desktop/shell/
├── Shell.qml                    # Main QML UI (panel, dock, launcher, overlays)
├── bright-desktop-shell.py      # Python backend (system integration, edition detection)
├── bright-desktop-session.sh    # Session startup script (sets env, launches KWin + shell)
├── bright-kwin-rules.kwinrule   # KWin window rules
├── design/
│   └── DesignTokens.js          # Shared design tokens (colors, typography, spacing, radii)
└── profiles/
    └── EditionProfiles.js       # Edition profile definitions (home, developer, lite)
```

## Bright Design System

The design system is defined in `design/DesignTokens.js` and imported by Shell.qml and all QML components. It is the single source of truth for the Bright OS visual identity.

### Brand Colors

| Token | Value | Usage |
|-------|-------|-------|
| `Brand.blue` | `#3b82f6` | Primary interactive accent (buttons, links, highlights) |
| `Brand.blueLight` | `#60a5fa` | Hover states, secondary accents |
| `Brand.indigo` | `#6366f1` | Gradient midpoint |
| `Brand.violet` | `#8b5cf6` | Secondary accent, visited links |

### Theme Colors

Both dark and light themes are defined with matching semantic tokens:

- **Surfaces**: `bgBase`, `bgElevated`, `bgPanel`, `bgCard`, `bgOverlay`
- **Borders**: `borderDefault`, `borderSubtle`, `borderFocus`
- **Text**: `textPrimary`, `textSecondary`, `textTertiary`, `textLink`
- **Semantic**: `success` (`#22c55e`), `warning` (`#eab308`), `error` (`#ef4444`), `info`

Dark theme base is `#0a0e1a` / `#0f172a`; light theme base is `#f8fafc` / `#ffffff`.

### Typography

- **UI font**: DejaVu Sans (available in Debian base, no extra package needed)
- **Monospace**: Hack (for terminal and code displays)
- Scale: XS (10px), SM (11px), Base (12px), MD (13px), LG (14px clock), XL (16px), 2XL (18px), 3XL (24px), 4XL (28px)

### Spacing

Based on a 4px grid: XS (2px), SM (4px), MD (8px), Base (12px), LG (16px), XL (24px), XXL (32px), XXXL (48px).

### Radii

SM (4px), MD (8px), LG (12px), XL (16px), Pill (999px for dock/buttons).

### Sizing

- Panel: 40px (Home), 36px (Developer), 28px (Lite)
- Dock icons: 48px (Home), 40px (Developer), 32px (Lite)
- Launcher: 720px × 5 columns

## Edition Profiles

Defined in `profiles/EditionProfiles.js`. The backend detects the edition from `/etc/bright-os/edition` and exposes `EditionId` to QML.

### Home

- **Tagline**: "Everyday computing, made simple"
- **Panel**: Top, 40px
- **Dock**: Bottom-centered pill dock, 48px icons, 8 apps (Firefox, Files, Thunderbird, LibreOffice, Terminal, VLC, Settings, Software)
- **Animations**: Full
- **Launcher categories**: All, Web, Office, Media, Graphics, Utilities, System

### Developer

- **Tagline**: "Built for creators, engineers, and makers"
- **Panel**: Top, 36px
- **Dock**: Left side dock, 40px icons, 11 apps (Firefox, Terminal, Files, Code, Git, VMs, Docker, Monitor, KiCad, Arduino, Settings)
- **Animations**: Snappy (0.7× speed)
- **Panel extras**: CPU/Mem percentage display, workspace indicator
- **Launcher categories**: All, Development, Electronics, Web, System, Utilities

### Lite

- **Tagline**: "Fast and responsive on older hardware"
- **Panel**: Bottom, 28px
- **Dock**: Disabled (no dock; uses panel menu launcher)
- **Quick launch**: 5 panel buttons (Menu, Firefox, Files, Terminal, Settings)
- **Animations**: Disabled entirely (motionFactor=0)
- **Rendering**: Qt Quick Basic style, basic scene graph render loop
- **Cursor**: Smaller 16px
- **Monitor interval**: 10s (vs 5s)
- **Fallbacks**: qterminal instead of bright-terminal, pcmanfm-qt instead of bright-files, Openbox for X11, Picom compositor with light settings
- **Launcher categories**: All, Internet, System, Tools, Media

## How Edition is Detected

1. The build script writes the edition name to `/etc/bright-os/edition` during ISO creation.
2. At session startup, `bright-desktop-session.sh` reads this file and sets edition-appropriate environment variables (Qt style, cursor size, compositor).
3. The Python backend reads `/etc/bright-os/edition` in `detect_edition()`, selects the matching profile, and exposes `EditionId` to QML.
4. Shell.qml calls `Profiles.getProfile(EditionId)` to get the profile object, which drives all layout and app decisions.
5. If the edition file is missing or invalid, the shell falls back to Home edition.

## Graceful Application Handling

The shell never crashes if an application is missing:
- `command_exists()` checks PATH before launching.
- Missing commands log a warning to stderr instead of raising exceptions.
- Dock app filtering removes unavailable commands from the list.
- Lite edition falls back to lighter alternatives (qterminal, pcmanfm-qt) when Bright apps are not installed.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Super` | Toggle application launcher |
| `Alt+F2` | Toggle application launcher |
| `Super+T` | Open terminal |
| `Super+E` | Open files |
| `Super+S` | Open settings |
| `Super+L` | Lock screen |
| `Escape` | Close active overlay (launcher, notifications, power) |

## Theme Switching

Users can switch between dark and light themes from the notification center. This:
1. Calls `Shell.setTheme(theme)` which updates the config file and persists the preference.
2. Updates all color references in QML via the `Tokens.colors(theme)` helper.
3. Switches the wallpaper to the matching variant.
4. Settings persist to `~/.config/bright-os/shell.conf` across reboots.

## Boot-to-Desktop Branding

The same Bright OS identity is applied consistently across the entire boot experience:

1. **GRUB** — Dark background (#0a0e1a), brand blue (#3b82f6) progress bar and accent, "BRIGHT OS" title in DejaVu Sans Bold
2. **Plymouth** — Dark background, geometric sun logo rendered in brand blue, animated loading dots, progress bar
3. **SDDM/Login** — Breeze theme matching dark palette (cursor, colors)
4. **Desktop** — Bright wallpaper matching theme, branded launcher with edition tagline
5. **Installer (Calamares)** — Dark sidebar (#0f172a), brand blue selection, Bright OS logo
6. **About dialog** — Shows edition name, version, tagline, system information
