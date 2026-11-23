# Bright Android

Bright Android is the native Android application compatibility layer for Bright OS, powered by [Waydroid](https://waydro.id). It allows users to install, launch, and manage compatible Android applications alongside their normal Linux applications.

## Architecture

```
┌─────────────────────────────────────────────┐
│  Bright Android GUI (PyQt6)                 │
│  • Home (status, controls)                  │
│  • Applications (install/launch/uninstall)  │
│  • Settings (startup, integration, dev)     │
│  • Compatibility checker                    │
└──────────┬──────────────────────────────────┘
           │ D-Bus (session bus)
┌──────────▼──────────────────────────────────┐
│  bright-android-service                     │
│  • org.bright_os.BrightAndroid interface    │
│  • Polkit authorization for privileged ops  │
│  • Manages Waydroid container lifecycle     │
│  • APK installation/validation              │
│  • Launcher integration (.desktop files)    │
│  • Config management                        │
└──────────┬──────────────────────────────────┘
           │ pkexec / lxc
┌──────────▼──────────────────────────────────┐
│  Waydroid (Android container)               │
│  • LXC container with Android 11/13 images  │
│  • Wayland-based window compositing         │
│  • Clipboard sharing, notifications         │
│  • Full Android app runtime                 │
└─────────────────────────────────────────────┘
```

## Supported Hardware Requirements

### Minimum
- **CPU:** x86_64 dual-core
- **RAM:** 2 GB (4 GB recommended)
- **Storage:** 6 GB free for Android image + apps
- **GPU:** OpenGL ES 3.0 capable (Mesa, Intel, AMD, NVIDIA)
- **Kernel:** Binder IPC (`/dev/binder` or binderfs) and memfd support
  - Debian 13 (Trixie) kernels include binder; the `binder-linux-module-dkms` package
    provides binder_linux.ko as a fallback.
  - memfd_create(2) is available on all Linux kernels >= 3.17 (ashmem is NOT required
    for Waydroid 1.4+).
- **Session:** Wayland (KWin, Weston, Sway)

### Recommended
- 8+ GB RAM (see note below about 8 GB systems)
- SSD storage
- Intel/AMD GPU with Mesa drivers and >= 1 GB VRAM
- Wayland session (KWin on Bright OS Home/Developer)

### 8 GB RAM Systems
Bright Android runs on 8 GB RAM systems (like the AMD A10-8700P), but with
caveats:
- Android auto-start is **disabled by default** to preserve RAM.
- The GUI shows a prominent warning about resource contention.
- Running Android + a full desktop + browser simultaneously may cause pressure.
- Adding 2-4 GB compressed swap (zram) is strongly recommended:
  `sudo apt install zram-tools`
- Close heavy desktop apps before starting Android.
- Systems with integrated GPUs (like AMD Radeon R6) share VRAM with system RAM,
  reducing available memory further.

See `docs/PHASE-BRIGHT-ANDROID-HARDWARE-READINESS.md` for a full assessment
of the AMD A10-8700P target system.

### Binder Module Loading
The compatibility checker reports whether binder is available but **does not**
load kernel modules automatically (that requires root). If binder is not loaded,
the recommended remediation is:
```
pkexec modprobe binder_linux
echo 'binder_linux' | pkexec tee /etc/modules-load.d/binder.conf
```
Polkit will prompt for administrator authorization.

## Installation

Bright Android is included by default in Bright OS Home and Developer editions. For Lite, it is optional and can be installed via:

```bash
sudo apt install waydroid
bright-android  # Launch the GUI to initialize
```

### First Setup

1. Open **Bright Android** from the application launcher
2. Go to **Android Home** → click **Initialize Runtime**
3. Authenticate with your administrator password when prompted
4. Wait for the Android system image to download (~400-700 MB)
5. Click **Start Android** to start the runtime

## APK Installation

### From the GUI
1. Open Bright Android → **Applications**
2. Click **Install APK...**
3. Select your `.apk` file
4. The system will verify compatibility before installation

### From the file manager
Right-click an `.apk` file and choose "Install with Bright Android" or open it directly.

### Compatibility Notes

Bright Android runs the **x86_64** Android image. Applications are:
- **x86_64 / x86 native apps:** ✅ Full speed, works natively
- **Pure Java/Kotlin apps:** ✅ Work universally (no native code)
- **ARM-only apps (arm64-v8a / armeabi-v7a):** ❌ Not supported by default

ARM translation (libndk_translation / Houdini) is NOT bundled by default due to licensing restrictions. Some ARM apps may work if you manually install a translation layer, but this is not supported out of the box.

## Google Services

Bright Android ships with the **VANILLA** Android image (no Google Play Services or Google Play Store). This avoids:
- Licensing complications
- Google certification requirements
- Background telemetry
- Increased resource usage

You can install open-source app stores like F-Droid manually, or install the GApps variant through the initialization options (at your own risk; not all apps will pass SafetyNet).

## Application Launcher Integration

Android applications automatically appear in the Bright OS launcher (and any XDG-compliant application menu) alongside native Linux applications. They use their actual Android icons and names, and launch as individual Wayland windows where supported.

- Applications are in the **Android** category
- Launching an app automatically starts the Android runtime if `start_on_demand` is enabled
- Uninstalling an app removes its `.desktop` entry

## Window Management

Android applications open as individual Wayland windows when Waydroid's multi-window (freeform) mode is enabled. This supports:
- Window focus and task switching
- Minimize/maximize
- Window resizing
- Closing windows

Some applications require full-screen mode (games, video players) and will use the full Android display surface.

## Edition Behavior

### Bright OS Home
- Android runtime installed by default
- Full GUI management
- APK installation
- Launcher integration

### Bright OS Developer
- Everything in Home, plus:
- ADB debugging (port 5555)
- Runtime log viewer
- APK installation diagnostics
- Developer options (GPU disable, nogpu mode)

### Bright OS Lite
- Android is **not installed by default**
- Waydroid package is available but not pre-installed
- Clear warning about RAM/storage requirements before installation
- User must explicitly install the Android runtime
- Does not consume resources until enabled

## Security Model

- Android runs inside an LXC container managed by Waydroid
- Android applications do NOT run as root on the host
- Privileged operations (initialization, APK installation, data removal) use Polkit for authorization
- APK path validation prevents path traversal
- Subprocess calls use argument lists (no shell string construction)
- Credentials are not stored; Google account integration is not pre-configured
- Shared folders are opt-in (Downloads by default; others must be explicitly enabled)

## AURA AI Integration

AURA can interact with Bright Android through D-Bus:

- ✅ **Allowed without confirmation:**
  - Check runtime status
  - List installed apps
  - Diagnose errors
  - Recommend installation
  - Launch already-installed apps (when running)

- 🔒 **Requires user confirmation:**
  - Installing Android runtime
  - Installing APKs
  - Uninstalling apps
  - Removing Android data
  - Changing privileged settings

Example requests:
- "Install this Android application" → AURA will ask for confirmation before installing
- "Launch WhatsApp" → AURA starts it if already installed; suggests installation if not
- "Show my Android apps" → Lists installed applications
- "Stop the Android environment" → Requires confirmation
- "Why won't my Android app open?" → Runs diagnostics

## Configuration File

User configuration: `~/.config/bright-android/config.ini`
System defaults: `/usr/share/bright-android/config.ini.default`

### Key Options

```ini
[runtime]
auto_start = false       # Start Android on login
start_on_demand = true   # Start when app is launched

[integration]
clipboard_share = true
notification_forward = true
app_integration = true   # Create .desktop files
freeform_windows = true  # Multi-window mode

[storage]
shared_downloads = true
shared_documents = false

[developer]
adb_enabled = false
nogpu_mode = false
```

## Troubleshooting

### Android won't start
1. Open **Bright Android → Compatibility Check**
2. Verify `/dev/binder` exists (run `sudo modprobe binder_linux`)
3. Ensure you're in a Wayland session (not X11)
4. Check logs: `bright-android` → Settings → View Runtime Logs

### Apps don't appear in launcher
1. Ensure Android is running
2. Click **Refresh** on the Applications page
3. Check `~/.local/share/applications/bright-android-app-*.desktop` files exist

### ARM apps won't install
This is expected. Only x86_64 and universal APKs work without additional translation layers.

### Black screen when starting Android
- Try disabling GPU acceleration: Settings → Developer → Disable GPU acceleration
- Ensure your GPU supports OpenGL ES 3.0

## Uninstallation

To completely remove Android support:
1. Open Bright Android → Settings → Remove Android Data
2. `sudo apt remove waydroid`
3. `sudo rm -rf /var/lib/waydroid ~/.local/share/applications/bright-android-app-* ~/.config/bright-android`

## Limitations

- ARM-only apps do not work without manual ARM translation
- Google Play Services / Play Store not included
- Some apps that require SafetyNet/Play Integrity will not work
- Camera/microphone passthrough may require additional configuration
- Bluetooth inside Android is not fully supported on all hardware
- Performance depends on host hardware; games may run slower than on a native Android device
- Lite edition requires manual installation of the waydroid package

## Dependencies

- `waydroid` - Android container runtime
- `lxc` - Linux containers
- `python3-pyqt6` - GUI framework
- `python3-dbus` - D-Bus communication
- `python3-gi` - Polkit authorization
- `wl-clipboard` - Wayland clipboard integration
- `desktop-file-utils` - Launcher integration
- `adb` / `fastboot` - Developer tools (optional)
