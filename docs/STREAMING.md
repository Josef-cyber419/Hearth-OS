# Streaming apps and your TV remote

The goal: everything on the home screen works with a TV remote or controller,
like a smart TV or console. No keyboard, no mouse, no browser.

## What each tile opens

| Tile | App | Remote/controller? |
|---|---|---|
| YouTube | [VacuumTube](https://github.com/shy1132/VacuumTube): YouTube's own TV interface (the one on consoles and smart TVs), packaged as an app, with controller support and ad blocking | Yes. Sign in with a code on your phone, like on a TV. |
| Kodi | Kodi media center, for your own files | Yes, built for remotes. Understands HDMI-CEC natively. |
| Jellyfin | Jellyfin Desktop in `--tv` mode | Yes. Needs a Jellyfin server (your NAS or another PC). |
| Plex | Plex HTPC, Plex's TV app | Yes. |
| Moonlight | Stream games from another PC | Yes. |
| Twitch | [VacuumStream](https://github.com/eliottness/VacuumStream): a controller-first Twitch app (live channels, follows, categories, past broadcasts) with Twitch's own player, in the spirit of VacuumTube. Not on Flathub: Hearth installs it into `~/Applications` and checks for updates weekly (`hearth-twitch-update`), verifying each download's checksum | Yes. Watch as a guest, or sign in with a code on your phone for your follows. Early-stage software, so expect rough edges. |
| Emulation | ES-DE + emulators, see [EMULATION.md](EMULATION.md) | Yes. |
| Android | Android apps in a container (Waydroid) | Partly. See below. |

## Why no Netflix, Disney+, Prime Video, Max…

These services use DRM (Widevine), and they only send HD and 4K to
devices they've certified: smart TVs, streaming sticks, consoles, phones.
A home-built Linux PC isn't certified, whatever you install on it:

| Route on Linux | Best quality | Remote? | Reliability |
|---|---|---|---|
| Browser (Chrome) | 720p to 1080p | No, it's the desktop website | Good |
| Kodi add-ons (community-made) | Often SD, per their own docs | Yes | Breaks when the service changes things |
| Android container (Waydroid) | SD at best | Phone-style apps, partly | Many apps refuse to run on uncertified Android |
| Native Linux app | Doesn't exist | | |

The DRM is the limit here, not the software. No setup of this PC fixes it.

## Recommended: a streaming stick on another HDMI input

For Netflix and the other paid services, the simple, reliable answer is a
**$30–$50 streaming stick** on another HDMI input on the same TV. It's a
certified Android TV box in hardware, which is what the software container can't be.
Options: Google TV Streamer or Chromecast with Google TV, Fire TV Stick 4K, Roku.

- Full **4K, HDR, Dolby Vision/Atmos**, every app, always up to date.
- The **TV remote controls it natively** over HDMI-CEC.
- The PC handles games, emulation, YouTube and your own media.

With the Pulse-Eight CEC adapter from [HARDWARE.md](HARDWARE.md), Hearth can
get a **"Netflix / Streaming" tile that switches the TV to the stick's input**.
It feels like one device. (Not built yet, since it needs the hardware to test.)

## The Android tile (experimental)

Bazzite includes Waydroid, a full Android system running in a container, and a
launcher that runs it inside Game Mode. The **Android** tile uses it and stays
hidden until Android is set up:

1. In Desktop Mode, open a terminal and run `ujust setup-waydroid`.
   Choose to initialize, and install Google Play if you want the Play Store.
2. Return to Hearth. The **Android** tile appears in the Watch row.

What to expect:
- It's regular Android (phone/tablet style), **not Android TV**. Apps built for
  touch are awkward with a remote. Apps with TV or gamepad support work well.
- Good for: free/ad-supported streaming apps, IPTV players, Android games,
  apps that don't exist on Linux.
- Not good for: Netflix, Disney+ and similar, for the DRM reasons above.
- Hold the Guide button (or the remote's Home key) to return to Hearth.
