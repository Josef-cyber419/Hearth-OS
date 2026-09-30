#!/usr/bin/bash
# Runs inside the image build (see Containerfile). Fails loudly on anything
# unexpected, so a Bazzite change breaks the build instead of your TV.
set -euxo pipefail

# --- packages -----------------------------------------------------------------
#   python3-pygame     Hearth's UI (SDL2: gamepads, fullscreen, fonts)
#   python3-evdev      Guide button gestures, controller-as-mouse (uinput)
#   python3-xlib       gamescope window properties: focus, overlay, app tags
#   v4l-utils          cec-ctl, for HDMI-CEC TV control
#   linuxconsoletools  inputattach, for the Pulse-Eight USB-CEC adapter
#   mpv                low-latency full-screen view of an HDMI capture card
#   gh                 GitHub's CLI: the field session files field reports with it
dnf5 -y install python3-pygame python3-evdev python3-xlib v4l-utils linuxconsoletools mpv gh

# --- check that Game Mode will actually start Hearth ------------------------
# Hearth hooks in through /etc/gamescope-session-plus/sessions.d/<session>,
# which gamescope-session-plus layers over the stock config. Make sure the
# session SDDM auto-logs into is one we ship an override for.
autologin=$(grep -hs '^Session=' /usr/lib/sddm/sddm.conf.d/*.conf /etc/sddm.conf.d/*.conf | tail -n1 | cut -d= -f2)
desktop_file=/usr/share/wayland-sessions/$autologin
if [[ -z $autologin || ! -f $desktop_file ]]; then
    echo "build.sh: can't find the Game Mode autologin session ('$autologin')" >&2
    exit 1
fi
hooked=no
for client in /etc/gamescope-session-plus/sessions.d/*; do
    client=$(basename "$client")
    [[ -f /usr/share/gamescope-session-plus/sessions.d/$client ]] || continue
    if grep -E '^Exec=' "$desktop_file" | grep -qw -- "$client"; then
        hooked=yes
    fi
done
if [[ $hooked != yes ]]; then
    echo "build.sh: Game Mode session $autologin isn't one Hearth overrides:" >&2
    grep -E '^Exec=' "$desktop_file" >&2
    echo "Add an override for it under image/system_files/etc/gamescope-session-plus/sessions.d/" >&2
    exit 1
fi

# --- services -----------------------------------------------------------------
systemctl enable hearth-flatpak-setup.service hearth-cec-poweroff.service
systemctl --global enable hearth-esde-update.timer
systemctl --global enable hearth-twitch-update.timer

# --- automatic updates --------------------------------------------------------
# Bazzite's deck images turn off their updater and leave updates to Steam's
# "System Update" button. Hearth runs first instead of Steam, so turn
# Bazzite's regular updater back on (OS image + Flatpaks, in the background).
if [[ -e /usr/lib/systemd/system/uupd.timer ]]; then
    systemctl enable uupd.timer
else
    echo "build.sh: uupd.timer not found; enabling bootc's update timer instead" >&2
    systemctl enable bootc-fetch-apply-updates.timer
fi

# --- version ------------------------------------------------------------------
cat > /usr/share/hearth/version.json <<JSON
{"version": "${HEARTH_VERSION:-dev}", "built": "$(date -u +%Y-%m-%dT%H:%MZ)"}
JSON

# --- sanity checks ------------------------------------------------------------
visudo -cf /etc/sudoers.d/hearth
# Settings → Storage (hearth-storage) needs these to set up added drives.
for tool in lsblk findmnt blkid wipefs sfdisk mkfs.ext4 udevadm swapon; do
    command -v "$tool" >/dev/null || { echo "build.sh: $tool missing (needed by hearth-storage)" >&2; exit 1; }
done
if udevadm verify --help >/dev/null 2>&1; then
    udevadm verify --resolve-names=never /usr/lib/udev/rules.d/70-hearth-*.rules
fi
python3 -m compileall -q /usr/lib/hearth/python
PYTHONPATH=/usr/lib/hearth/python python3 -c \
    'import hearth.config as c; c.load(c.SYSTEM_CONFIG)'
