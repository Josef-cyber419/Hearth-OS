# Installing Hearth OS

Hearth ships as a container image on top of Bazzite. You install Bazzite with its
normal installer, then point the system at the Hearth image. Updates arrive
automatically from then on.

## 1. Publish the image (one time)

1. Push this repo to GitHub with `main` as the default branch. The
   [`build` workflow](../.github/workflows/build.yml) builds and pushes to
   `ghcr.io/<your-github-user>/hearth-os` (for AMD/Intel graphics), and
   rebuilds daily to pick up Bazzite updates.
2. GHCR packages start out private. Either make the package public
   (GitHub → your profile → Packages → hearth-os → Package settings → Change
   visibility), or run `sudo podman login ghcr.io` on the PC before switching.

## 2. Install Bazzite

1. From [bazzite.gg](https://bazzite.gg), download the ISO for **AMD** graphics
   with **Steam Gaming Mode** selected (the "deck" edition, which boots to
   Game Mode).
2. In the firmware setup (BIOS): UEFI mode on. If you keep Secure Boot on,
   follow Bazzite's instructions to enroll its key during install.
3. Install Bazzite. It erases the drive you pick.

## 3. Switch to Hearth

In Bazzite's Desktop Mode, open a terminal (Konsole) and run:

```sh
sudo bootc switch ghcr.io/<your-github-user>/hearth-os:latest
systemctl reboot
```

After the reboot you land on the Hearth home screen. On first boot with
networking, `hearth-flatpak-setup.service` installs Kodi, Moonlight, the emulators,
VacuumTube (YouTube) and Jellyfin in the background. Their tiles appear as each install
finishes, the next time you return to the home screen.

Undo: `sudo bootc rollback` (or choose the previous entry in the boot menu),
or `sudo bootc switch ghcr.io/ublue-os/bazzite-deck:stable` to go back to
plain Bazzite.

## 4. First-run setup

- **Wi-Fi, Bluetooth controllers, the look**: the **Settings** tile (System
  row) does all of it with a controller, including typing a Wi-Fi password.
- **Steam**: open the Steam tile and sign in. Steam runs in the same console UI
  as Bazzite's normal Game Mode.
- **Emulation**: ES-DE installs itself in the background shortly after first
  login, then the Emulation tile appears. Add games from Desktop Mode. See
  [EMULATION.md](EMULATION.md).
- **YouTube**: opens YouTube's TV interface (via VacuumTube). Sign in with a
  code from your phone, the same way you would on a smart TV.
- **Netflix, Disney+ and other paid services**: not included by default. See
  [STREAMING.md](STREAMING.md) for why, and your options.
- **Streaming this PC to other screens**: Bazzite includes Sunshine. Run
  `ujust setup-sunshine` in Desktop Mode, then use Moonlight on a phone, tablet or
  another TV.
- **Remote/CEC**: see [HARDWARE.md](HARDWARE.md). With a Pulse-Eight adapter
  plugged in, it's configured automatically. Change the behaviour in
  `/etc/hearth/cec.conf`.

## Customising, updates and fixing things

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md): how updates work, `hearthctl`
(status, diagnostics, logs, rollback), and customising the home screen.

To boot straight into Steam instead of Hearth: `hearthctl disable`, then restart.
