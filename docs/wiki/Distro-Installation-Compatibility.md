# Linux distribution installation compatibility

This is an **installer compatibility matrix**. It shows the Linux distributions that
`install_linux.sh` recognizes and the dependencies it installs for each one.

It is not a runtime display compatibility matrix. A recognized distribution means the
installer has a package profile for it; it does not mean every desktop, compositor, or
display session on that distribution is validated. See [[Backend Compatibility]] for
runtime display status.

## What every Linux install needs

- Python 3.10 or newer.
- `pip` and virtual-environment support.
- An installer-recognized distribution profile below, or the equivalent packages installed
  manually.
- A client virtual environment which the installer creates.
- Host-installed Tkinter/Tcl/Tk support for the Python interpreter used by the client virtual environment (for example, `python3-tk` on Debian/Ubuntu).

The installer installs these shared Python dependencies across all distribution profiles:

| Package | Installed into | When installed |
| --- | --- | --- |
| `PyQt6>=6.5` | Client virtual environment | Every Linux install |
| `PyQt6-Qt6` | Client virtual environment | Installed with `PyQt6` on every Linux install; also explicitly requested as `PyQt6-Qt6>=6.5` for detected Wayland sessions |
| `pydbus>=0.6.0` | Client virtual environment | Detected Wayland session |
| `pywayland>=0.4.15` | Client virtual environment | Detected Wayland session |

The installer adds the profile's Wayland system packages only when it detects a Wayland
session; an unknown session skips those packages.

`install_matrix.json` has no distribution-version limits. A version is eligible when it
matches a profile and provides the required packages and Python version.

The installer uses these profile-specific package names for the common Python tooling:

| Distribution profile | Python, pip, and virtual-environment packages |
| --- | --- |
| Debian / Ubuntu | `python3`, `python3-venv`, `python3-pip` |
| Fedora / RHEL / CentOS Stream | `python3`, `python3-pip`, `python3-virtualenv` |
| Bazzite (Fedora rpm-ostree) | `python3`, `python3-pip`, `python3-virtualenv` |
| openSUSE / SLE | `python3`, `python3-pip`, `python3-virtualenv` |
| Arch / Manjaro / SteamOS | `python`, `python-pip` |

## Distribution profiles

Host package names below match `install_matrix.json`. **Base** and
**Qt/X11** packages are installed for every recognized Linux session. **Wayland**
packages are added only for a detected Wayland session. **Flatpak requirements / installer action**
applies only when EDMC is installed as a Flatpak.

For detected GNOME Wayland sessions, the installer also offers to install the bundled
GNOME Shell helper extension, as described under **GNOME Wayland helper** below.

| Distribution profile | Recognized `/etc/os-release` IDs | Package manager | Other base packages | Qt/X11 packages | Wayland packages | Flatpak requirements / installer action |
| --- | --- | --- | --- | --- | --- | --- |
| Debian / Ubuntu | `debian`, `ubuntu`, `pop`, `linuxmint`, `neon`, `zorin`, `kali`, `parrot`; compatible `ID_LIKE=debian` or `ubuntu` | `apt-get` | `rsync`, `curl`, `wmctrl` | `libxcb-cursor0`, `libxkbcommon-x11-0` | `x11-utils` | No additional host package installed; requires `flatpak-spawn` inside EDMC’s sandbox. |
| Fedora / RHEL / CentOS Stream | `fedora`, `rhel`, `centos`, `rocky`, `almalinux`; compatible `ID_LIKE=fedora` or `rhel` | `dnf` | `rsync`, `curl`, `wmctrl` | `libxkbcommon`, `libxkbcommon-x11`, `xcb-util-cursor` | `xwininfo`, `xprop` | Installer requests host package `flatpak-spawn`; sandbox command also required. |
| Bazzite (Fedora rpm-ostree) | `bazzite` | `rpm-ostree` | `rsync`, `curl`, `wmctrl` | `libxkbcommon`, `libxkbcommon-x11`, `xcb-util-cursor` | `xwininfo`, `xprop`, `plasma-wayland-protocols`, `wayland-devel`, `python3.<minor>-devel` | Installer requests host package `flatpak-spawn`; sandbox command also required. |
| openSUSE / SLE | `opensuse`, `opensuse-leap`, `opensuse-tumbleweed`, `sles`; compatible `ID_LIKE=suse` | `zypper` | `rsync`, `curl`, `wmctrl` | `libxcb-cursor0`, `libxkbcommon-x11-0` | `xprop`, `xwininfo` | No additional host package installed; requires `flatpak-spawn` inside EDMC’s sandbox. |
| Arch / Manjaro / SteamOS | `arch`, `manjaro`, `endeavouros`, `steamos`; compatible `ID_LIKE=arch` | `pacman` | `rsync`, `curl`, `wmctrl` | `libxcb`, `xcb-util-cursor`, `libxkbcommon` | `xorg-xprop`, `xorg-xwininfo` | No additional host package installed; requires `flatpak-spawn` inside EDMC’s sandbox. |

`python3.<minor>-devel` in the Bazzite profile is expanded to match the detected Python
minor version. On rpm-ostree systems, package changes can require a reboot before the
new deployment is active.

## GNOME Wayland helper

Across distribution profiles, a detected GNOME Wayland session triggers an offer to
install or update the bundled GNOME Shell helper extension and enable it. This applies
to both host and Flatpak EDMC installs; the extension is installed into the host user's
GNOME Shell environment.

| Condition or action | Installer behavior |
| --- | --- |
| Prerequisites | Requires a GNOME Wayland session, user session D-Bus, `gnome-extensions`, `gjs`, `gdbus`, and the bundled helper source. Missing prerequisites are reported and helper installation is skipped. |
| Approval | Prompts to install/update and enable the helper, defaulting to **No**. `--assume-yes` approves this prompt automatically. |
| Installation | Copies the extension into `$XDG_DATA_HOME/gnome-shell/extensions/`, or `~/.local/share/gnome-shell/extensions/` when `XDG_DATA_HOME` is unset. |
| Enablement | Attempts `gnome-extensions enable` when GNOME recognizes the extension and user extensions are allowed. Otherwise, reports the activation steps needed. |
| Activation | Advises logging out and back in, then rerunning the installer with `--gnome-helper-action status` to check extension state and D-Bus health. |
| Skip | `--gnome-helper-action skip` skips helper installation and management. |

## Flatpak EDMC

Flatpak is an installation context, not a separate overlay backend. The overlay client
runs on the host through `flatpak-spawn --host`, so the EDMC Flatpak must have session
bus permission for `org.freedesktop.Flatpak`. The installer checks for this and provides
the command if it is missing:

```bash
flatpak override --user io.edcd.EDMarketConnector --talk-name=org.freedesktop.Flatpak
```

Grant this only if you trust the plugin and the host system: host launch runs the overlay
client outside the Flatpak sandbox.

## What this matrix does not claim

This page does not validate a particular desktop/compositor, display session, game
configuration, monitor layout, or scaling arrangement. Use [[Backend Compatibility]]
for those claims.
