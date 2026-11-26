# Building Bright OS ISOs with GitHub Actions

This document describes how Bright OS ISO images are built automatically by
GitHub Actions, how to trigger manual builds, how to create a release, and how
to download, verify and boot the resulting ISO.

> **Phase:** Sub-phase 6.2 (first automated ISO build). The CI produces a
> structural ISO (passes ISO9660/boot-signature/kernel/initrd/squashfs checks)
> but real-hardware boot and installation validation still require manual
> testing in QEMU/KVM or on a physical machine. See the status table below.

## How the build works

The build uses **Debian live-build** (`lb build`) running on a GitHub-hosted
`ubuntu-24.04` runner:

1. The runner frees up disk space by removing preinstalled toolchains it does
   not need (Android SDK, .NET, hosted tool caches).
2. It installs `live-build`, `debootstrap`, `debian-archive-keyring`,
   `squashfs-tools`, `xorriso`, `isolinux`, `syslinux-common`, `syslinux-efi`,
   `mtools`, `dosfstools`, `grub-pc-bin`, `grub-efi-amd64-bin`,
   `grub-efi-amd64-signed`, `shim-signed`, `genisoimage`, and `qemu-system-x86`.
3. It invokes `build/scripts/build.sh` which:
   - Copies the live-build `auto/` scripts and `config/` tree to a working
     directory.
   - Selects the desktop package list (full KDE Plasma for home/developer,
     LXQt/Openbox for lite).
   - Copies the AURA and Bright Android Python source trees into the chroot.
   - Runs `lb config` (via `build/live-build/auto/config`, which auto-detects
     the host's live-build capabilities so it works on both Debian Trixie and
     Ubuntu 24.04).
   - Runs `lb build`, producing a hybrid ISO with BIOS (isolinux/GRUB) and
     UEFI (GRUB/shim) boot paths.
4. The resulting ISO is renamed to `bright-os-<version>-<edition>-amd64.iso`,
   its SHA-256 checksum is computed, and `build/scripts/validate-iso.sh`
   performs structural validation.
5. The workflow extracts `/live/filesystem.squashfs` from the ISO, reads the
   dpkg package database, and produces `manifest/packages.txt`.
6. A JSON measurement record is written (ISO size, SHA-256, package count,
   runner metadata).
7. Optionally, a QEMU TCG software-emulation boot smoke test runs the ISO for
   up to 6 minutes and watches the serial log for a login prompt / display
   manager target.
8. The ISO, checksum, build log, validation log, manifest, measurement JSON,
   and QEMU serial log are uploaded as workflow artifacts.

The build is fully reproducible: every push to a Phase 6.2 branch or every
pull request triggers a fresh ISO build from the Debian Trixie archive.

## Workflows

Two workflows are provided:

| Workflow | File | Triggers | Purpose |
|---|---|---|---|
| **ISO Build** | `.github/workflows/iso-build.yml` | push to `arena/phase6-2*` branches, pull requests to `main`, manual `workflow_dispatch` | Build and validate an ISO on every code change. Does NOT publish releases. |
| **Release** | `.github/workflows/release.yml` | push of a tag matching `v[0-9]*`, manual `workflow_dispatch` | Build, validate, QEMU smoke-test, then create a **DRAFT** GitHub Release with assets. |

The original CI workflow (`ci.yml`) continues to run static checks, Python
tests, shell test suites and a static baseline measurement. The ISO build is a
separate workflow because it takes 30–90 minutes.

## Triggering a manual ISO build

You can trigger a build of any branch/edition from the GitHub web UI:

1. Navigate to the repository: https://github.com/nozaqk/Bright-OS
2. Click **Actions → ISO Build**.
3. Click **Run workflow**.
4. Choose:
   - **Branch**: the branch you want to build (default `arena/phase6-2-iso-build`).
   - **Edition**: `home` (default, full Plasma/KWin), `developer`, or `lite`.
   - **Version**: any valid version string (default `0.1.0-alpha`).
   - **Debian codename**: `trixie` (recommended) or `bookworm`.
   - **QEMU smoke test**: adds ~10 minutes of TCG software boot testing.
5. Click **Run workflow**.

The build will appear in the Actions list within a few seconds.

## Downloading build artifacts

Every successful ISO build uploads artifacts. To download:

1. Open the workflow run page (from the Actions tab).
2. Scroll to the **Artifacts** section at the bottom of the summary page.
3. Two artifacts are produced:
   - `bright-os-<version>-<edition>-amd64` — the ISO file and its `.sha256`
     checksum.
   - `build-logs-<edition>-<run-id>` — `build.log`, `validation.log`,
     `build-measurement.json`, `manifest/packages.txt`, and `qemu-serial.log`
     (if QEMU was enabled).
4. Click an artifact to download a zip.

Artifacts are retained for 30 days.

## Creating an experimental release

Alpha/beta/RC releases are produced by pushing a version tag:

```bash
# On main (after merging the implementation PR):
git checkout main
git pull
git tag -a v0.1.0-alpha1 -m "Bright OS 0.1.0-alpha1"
git push origin v0.1.0-alpha1
```

The Release workflow will:

1. Build the `home` edition ISO against Debian Trixie.
2. Run the full structural validation.
3. Run the QEMU TCG boot smoke test (enabled by default for releases).
4. Create a **draft** GitHub Release. Tags containing `alpha`, `beta`, `rc`,
   `pre`, or `dev` are marked as prereleases automatically.
5. Upload the ISO, `SHA256SUMS`, build log, validation log,
   `release-measurement.json`, and QEMU serial log as release assets.

**The release starts as a DRAFT. It is NOT visible publicly until you click
"Publish release"** from the GitHub Releases page. Always inspect the draft:

1. Open https://github.com/nozaqk/Bright-OS/releases.
2. Open the draft release (labeled "Draft").
3. Verify the SHA-256 matches the ISO you intend to distribute (download the
   ISO and run `sha256sum` locally to confirm).
4. Review the QEMU serial log and validation log attached to the release.
5. Edit the release notes if desired.
6. Click **Publish release** when you are satisfied.

**Never create a tag on a branch you have not personally tested.** The
workflow will happily build and draft a release for any tag; the human
decision to publish remains yours.

## Verifying the SHA-256 checksum

Every release includes a `SHA256SUMS` file. After downloading the ISO:

```bash
# From the directory containing both files:
sha256sum -c SHA256SUMS
# Expected output:
# bright-os-0.1.0-alpha1-home-amd64.iso: OK
```

You can also compute it manually:

```bash
sha256sum bright-os-0.1.0-alpha1-home-amd64.iso
```

and compare with the checksum shown in the release notes.

## Booting in VirtualBox

1. Open VirtualBox → **New**.
2. Name: Bright OS; Type: Linux; Version: Debian (64-bit).
3. Memory: ≥ 4096 MB (8192 MB recommended).
4. Hard disk: create a new virtual disk (≥ 25 GB for installation testing;
   you can skip this for live-only testing).
5. After creating the VM, open **Settings → Storage**:
   - Under "Controller: IDE", click the optical drive icon → **Choose a disk
     file** → select the Bright OS ISO.
   - Under **System → Motherboard**, ensure **Optical** is above **Hard Disk**
     in the boot order.
   - For UEFI: **System → Motherboard → Enable EFI (special OSes only)**.
6. Start the VM. You should see the GRUB menu "Start Bright OS Live (Default)".
7. After boot you will see the SDDM login screen; the live session user is
   `user` with password `live`.

## Writing to USB (Linux)

**WARNING:** This will irrevocably overwrite the target device. Double-check
the device path (it is `/dev/sdX`, NOT `/dev/sdX1` — a partition, not the whole
disk). Writing to the wrong device will destroy data.

```bash
# Identify your USB stick (look at size and mount points)
lsblk
sudo umount /dev/sdX*
sudo dd if=bright-os-0.1.0-alpha1-home-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

After `dd` completes, you can remove the USB stick (physically eject it if
your file manager offers that). Boot the target machine from USB; you may need
to press F12/F2/Del during POST to select the USB boot device.

**Do NOT** use `dd` on WSL2 (USB pass-through is unreliable). Use a native
Linux host, balenaEtcher on Windows/macOS, or `cp` on macOS.

## Known limitations (alpha)

- **Idle RAM, boot time, battery life** and other runtime performance metrics
  have NOT been measured on a booted Bright OS system yet. The Phase 6.0
  measurement harness can record these once the ISO boots in a VM or on
  hardware; CI alone cannot measure them.
- **QEMU TCG smoke test** uses software emulation (no KVM available on
  GitHub-hosted runners), which is ~10× slower than native. It only verifies
  the kernel boots and reaches a login/display-manager target; it does not
  exercise the desktop shell, AURA, Waydroid, or the installer.
- **Real-hardware boot, Wi-Fi, GPU acceleration, sound, and installation**
  testing is pending.
- **labwc is optional/experimental** and not included in the default home
  edition ISO. To try labwc, install the packages listed in
  `config/package-lists/labwc-experimental.list.chroot` and select "Bright
  Desktop (labwc experimental)" from SDDM.
- The ISO target size is under 2 GiB. Full Plasma desktop builds may exceed
  this; the actual size is reported by every build artifact and release
  measurement.
- Secure Boot support depends on the presence of `shim-signed` and
  `grub-efi-amd64-signed` and on whether live-build integrates them into the
  EFI binary. The 30-efi-boot-setup hook will attempt to produce an EFI image
  via `grub-mkstandalone` if live-build does not do so automatically.

## Validation status table

Definitions (from `docs/BUILDING.md`):

| Status | Meaning |
|---|---|
| NOT BUILT | ISO has not been built yet |
| BUILD FAILED | Build attempted but failed |
| BUILT | ISO produced but not validated |
| **ISO VALIDATED** | ISO passed structural validation (ISO9660, kernel, squashfs, BIOS/UEFI signatures, GRUB/isolinux, key packages) |
| BIOS BOOT TESTED | ISO boots in QEMU BIOS mode to a login prompt |
| UEFI BOOT TESTED | ISO boots in QEMU UEFI mode (OVMF) to a login prompt |
| LIVE DESKTOP TESTED | Live desktop loads with correct edition, shell renders |
| INSTALLATION TESTED | Calamares installer completes on a virtual disk |
| INSTALLED SYSTEM BOOT TESTED | Installed system reboots to login and desktop |
| HARDWARE TESTED | Booted and used on real hardware |

Status after the first automated build in GitHub Actions: see the
measurement JSON attached to each release artifact.
