# Casting from your phone

Like a smart TV, the PC shows up on the home network as a screen and a
speaker. Nothing to install on the phone; nothing leaves your network.
Settings → **Casting** turns each part on or off and sets the name phones
see (the PC's host name unless you change it).

| From | How | What you get |
|---|---|---|
| iPhone, iPad, Mac | **AirPlay**: the AirPlay button in a video or photo app, or Control Centre → Screen Mirroring, then pick the PC's name | Videos, photos, music, or the whole screen, full screen on the TV |
| Spotify on any phone | The speaker icon in the Spotify app, then pick the PC's name | Music through the TV or soundbar, with the Quick Menu's volume and *Now playing* controls. Needs Spotify Premium |
| YouTube on any phone | Once: link the phone with a TV code (below). Then the cast button in the YouTube app, while the YouTube tile is open | YouTube's own TV app plays what you picked on the phone |

## AirPlay

When a picture arrives, Hearth brings it to the front over whatever was
there (the home screen, a film, a game) and goes back when the phone stops.
Music on its own has no picture: it just plays.

- **Hold Guide** to come back to Hearth while the phone carries on casting
  (it's still playing, just not shown).
- **Quick Menu → System → Stop casting** drops the phone. It can cast again
  any time.
- A second phone takes over from the first.

Under the hood this is [UxPlay](https://github.com/FDH2/UxPlay), an open
AirPlay receiver, started in the background with the home screen. Apple's
own protected video (Apple TV+, films bought on iTunes) won't mirror from
any receiver that isn't Apple's; everything else does.

## Spotify Connect

[spotifyd](https://github.com/Spotifyd/spotifyd) is installed per user into
`~/Applications` from its GitHub releases (checked against the release's
SHA-512, like the Twitch app) and kept up to date weekly
(`hearth-spotify-update.timer`). It needs the network once, shortly after
the first login. No Spotify sign-in on the PC: the phone finds it over the
network and plays through it. Spotify only allows this with Premium.

## YouTube

The YouTube tile is YouTube's own TV app, so it links to a phone the way a
smart TV does:

1. Open the **YouTube** tile (Settings → Casting → *Open YouTube to link it*
   does the same).
2. In YouTube: **Settings → Link with TV code**. A code shows.
3. On the phone's YouTube app: your picture → **Settings → Watch on TV →
   Enter TV code**.

From then on, with the YouTube tile open, the cast button in the phone's
YouTube app lists the TV. Automatic discovery (the TV appearing without a
code) needs Google's Cast protocol, which isn't open; the code does the
same job once.

## If a phone can't see the PC

- Same Wi-Fi? Guest networks usually keep devices apart.
- `hearthctl check` → **Network** says whether each receiver is running,
  whether AirPlay's discovery service (avahi) is up, and whether a video
  decoder is there.
- AirPlay uses ports 7000, 7001 and 7100 (TCP) and 6000, 6001 and 7011 (UDP);
  Spotify Connect uses 5354 (TCP) plus mDNS. Bazzite's firewall zone leaves
  these open; `hearthctl check` warns if the zone has been changed.
