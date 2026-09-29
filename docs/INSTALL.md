# Installing Hearth OS

About 30 minutes. You'll need:

- A PC with **AMD or Intel graphics** (NVIDIA isn't supported yet). Check
  [COMPATIBILITY.md](COMPATIBILITY.md) first.
- A **USB stick of 8 GB or more**. It gets erased.
- A **keyboard** for the install (a controller works for everything after).
- **Internet**, wired if you can.

The drive you install to is **erased**. Copy anything you want to keep first.

## Step 1: Make the install USB stick

1. Go to [bazzite.gg](https://bazzite.gg) and pick:
   - Hardware: **Desktop / Laptop**
   - GPU: **AMD** (also the right choice for **Intel**)
   - Desktop: either one
   - **Steam Gaming Mode: Yes** (the download is named `bazzite-deck`)
2. Download the ISO.
3. Write it to the USB stick with [Fedora Media Writer](https://fedoraproject.org/workstation/download)
   or [balenaEtcher](https://etcher.balena.io) (on Windows, Mac or Linux).

## Step 2: Firmware (BIOS) settings

Restart the PC and open the firmware setup (usually **Del** or **F2** at
power-on). Check:

- **Boot mode: UEFI** (turn off CSM / Legacy if it's on).
- **Secure Boot**: easiest **off**. If you keep it on, the installer asks you
  to enroll a key: follow [Bazzite's Secure Boot steps](https://docs.bazzite.gg/General/Installation_Guide/secure_boot/).

Save and exit.

## Step 3: Install Bazzite

1. Plug in the USB stick and boot from it (the boot menu key is usually
   **F12**, **F11** or **F8**).
2. Choose **Install Bazzite**.
3. Pick your language, keyboard and time zone, then the **drive to install
   to**. Choose to use the whole drive.
4. Create your user and password. Wait for it to finish, then restart and
   take out the USB stick.

Bazzite starts in Steam's Game Mode. That's expected.

## Step 4: Switch to Hearth

1. Go to Desktop Mode: in Steam, **Steam button → Power → Switch to Desktop**.
2. Open **Konsole** (the terminal) from the app menu.
3. Type these two lines, pressing Enter after each (your password is asked
   for; nothing shows as you type it):

   ```sh
   sudo bootc switch ghcr.io/josef-cyber419/hearth-os:latest
   systemctl reboot
   ```

   The first line downloads Hearth (a few GB), so it takes a while.

After the restart, you're on the Hearth home screen. From now on, updates
download by themselves.

> **"unauthorized" or "denied" error?** The image isn't public on GitHub
> yet. Run `sudo podman login ghcr.io` (your GitHub username and a token with
> `read:packages`), then the `bootc switch` line again.

## Step 5: First start

Everything from here works with a controller.

- **Apps install themselves** in the background on first start (Kodi,
  Moonlight, the emulators, YouTube, Jellyfin). Their tiles appear as each
  one finishes.
- **Wi-Fi and Bluetooth controllers**: the **Settings** tile (System row).
  You can type a Wi-Fi password with the controller.
- **Steam**: open the Steam tile and sign in.
- **YouTube and Twitch**: sign in with a code from your phone, like on a smart
  TV.
- **Emulation**: the Emulation tile appears once ES-DE has installed. Add
  your games as described in [EMULATION.md](EMULATION.md).
- **A second drive** for games or ROMs: Settings → Storage; see
  [STORAGE.md](STORAGE.md).
- **Epic Games and Battle.net**: see [GAME_STORES.md](GAME_STORES.md).
- **TV remote**: see [HARDWARE.md](HARDWARE.md). A Pulse-Eight CEC adapter
  is set up automatically when it's plugged in.
- **Netflix, Disney+ and other paid services**: not included; see
  [STREAMING.md](STREAMING.md) for why and what to do instead.

## Updating

Updates download in the background. The home screen tells you when one is
ready; restart to finish it. To check now: **Guide button → System → Check
for updates**, or `hearthctl update` in a terminal. After an update, the home
screen shows once what's new.

## If something goes wrong

- **The update broke something**: pick the previous entry in the boot menu,
  or run `sudo bootc rollback` and restart. Every update can be undone.
- **Go back to plain Bazzite**:
  `sudo bootc switch ghcr.io/ublue-os/bazzite-deck:stable`, then restart.
- **Boot straight into Steam instead of Hearth**: `hearthctl disable`, then
  restart (`hearthctl enable` to undo).
- **Find out what's wrong**: `hearthctl doctor`. More in
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
- **Report a problem**: Guide button → System → Report a problem.

## Update channels (for testing)

A PC follows one of two builds:

- **live** (`:latest`, from `main`): what's released. The default.
- **staging** (`:staging`, from the `staging` branch): new work to try before
  it goes live. For now it mirrors live.

`hearthctl channel` shows which one this PC is on; `hearthctl channel
staging` or `hearthctl channel live` switches it (restart to finish). A
specific version can also be installed by its number:
`sudo bootc switch ghcr.io/josef-cyber419/hearth-os:0.21.0`.

## Building your own image (for developers)

To run your own copy: fork the repository and keep `main` as the default
branch. The [`build` workflow](../.github/workflows/build.yml) publishes
`ghcr.io/<your-github-user>/hearth-os` (`:latest` from `main`, `:staging`
from `staging`, and each version number), and rebuilds daily to pick up
Bazzite updates. GitHub packages start out private: make it public
(your profile → Packages → hearth-os → Package settings → Change visibility)
or log in with `sudo podman login ghcr.io` on the PC. Then use your image in
Step 4.
