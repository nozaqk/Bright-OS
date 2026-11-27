# First Successful Debian 13 Trixie Bright OS ISO Build

## Branch
`arena/d6b955d1-bright-os` (draft PR #54 against `main`)

## Latest successful CI run
- Run ID: 46065926382
- Date: 2026-11-27
- Duration: 19m21s
- Edition: home
- Codename: trixie
- Build env: privileged debian:trixie container (GH Actions)

## ISO details
- Filename: `bright-os-0.1.0-alpha-home-amd64.iso`
- Size: 3.4 GiB (3.4GiB reported by CI; exact bytes TBD from artifact)
- SHA-256: `2548205320ba8b806197cd594f7946417bd59c7103c8596a20875c3fcb82da92`
- Volume ID: "Bright OS 0.1.0-alpha home"
- Type: ISO 9660 CD-ROM, hybrid MBR, bootable (per `file` command)
- Total paths in ISO: 584
- Top-level layout: `/.DISK`, `/BOOT`, `/BOOT.CATALOG`, `/EFI`, `/EFI.IMG`, `/LIVE`, `/SHA256SUM.README`, `/SHA256SUM.TXT`
- Tool versions (from container): live-build 1:20230502+, debootstrap 1.0.140+, xorriso 1.5.7-, mksquashfs 4.6.1

## Fixed issues
1. **Cross-build 404s**: Switched to privileged debian:trixie container with native live-build; auto/config now detects host codename and doesn't double-apply security workarounds on native builds.
2. **Package incompatibilities (exit 123)**: Removed packages not present in Trixie:
   - firmware-intelwimax (EOL)
   - policykit-1, policykit-1-gnome → polkitd, pkexec, polkit-kde-agent-1
   - software-properties-common (removed, Debian bug #1038747)
   - waydroid, binder-linux-module-dkms (not in Trixie; kernel 6.12 has BINDER_IPC built-in)
   - breeze-gtk → breeze-gtk-theme (package rename)
3. **Hook failures**: systemd-cat pipes failed inside chroot under set -e; replaced with _log helper that falls back to stdout.
4. **SIGPIPE/pipefail (exit 141)**: Removed tee|grep pipeline; redirect build output directly to log file.
5. **Case-insensitive ISO path matching**: ISO9660 uses UPPERCASE paths with ;1 version suffixes; fixed isoinfo parsing to normalize before grep.

## Features preserved
- ✅ Home/Developer/Lite editions (build.sh supports all three)
- ✅ Optional-profile flags (bluetooth, printing, network-extras, wine, devtools, recovery-kwin, secureboot, plymouth, qemu)
- ✅ Secure Boot (shim-signed, --uefi-secure-boot auto)
- ✅ Calamares installer
- ✅ Firmware packages (nonfree, realtek, iwlwifi, atheros, brcm80211)
- ✅ Networking (NetworkManager, wpasupplicant, iwd, firewalld, OpenSSH)
- ✅ AURA (dbus policy, systemd service, source tree copied to /usr/lib/aura)
- ✅ Bright Android (gui, dbus policy, source tree copied to /usr/lib/bright-android; waydroid install from repo on first run)
- ✅ KWin recovery (sddm + kwin-wayland in optional-recovery-kwin profile)
- ✅ labwc default compositor + greetd DM (Phase 6.3 lightweight core)

## Not yet validated
- ❌ QEMU boot (TCG, no KVM in CI)
- ❌ Idle RAM at 120s
- ❌ Developer/lite editions (only home in CI so far)
- ❌ Secure Boot shim actually loading
- ❌ dpkg/package manifest extraction (unsquashfs path issue, non-blocking)
- ❌ 250 MiB idle target (NOT claimed without measurement)
