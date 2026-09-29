# Performance: keeping Hearth light

A living-room PC should spend its power on the game, not on the menu. This is
what Hearth itself costs, what it does to stay out of the way, and how to
check your own PC.

## What Hearth costs

Measured with the whole Hearth session running (home screen plus Quick Menu,
at 1080p in a virtual display), sitting idle on the home screen:

| | CPU (of one core) | Memory |
|---|--:|--:|
| Home screen, before 0.22.0 | 4.7% | 172 MB, about 275 MB after browsing a dozen tiles |
| Home screen, from 0.22.0 | **0.9%** | 169 MB, about 210 MB after browsing a dozen tiles |
| Quick Menu (always ready, hidden) | 0.9% | 128 MB |
| **All of Hearth, idle** | **1.8%** | **about 300 MB** |

While a game is in front, the home screen isn't drawn at all. The Quick Menu
only checks for the Guide button, notices and the game's state, a few times a
second.

## What it does to stay light

- **It stops drawing when nothing moves.** An unchanging home screen used to
  be redrawn 60 times a second. Now, three seconds after the last button
  press (and once any animation has finished), it only redraws when something
  on it changes: the clock, a controller's battery, the network, a message.
  The moment you press anything, it's back to full speed.
- **It draws at 1080p at most**, even on a 4K TV; the graphics card scales it
  up.
- **It keeps little in memory.** Each focused tile's blurred background is
  kept small (a tenth of the screen size) and only the last three full-size
  ones are kept, instead of up to thirteen (8 MB each).
- **Closed means closed.** Every app runs in its own systemd scope, so closing
  a game or a store app ends all of its processes, including Wine's helpers.
  A game paused for Quick Resume is frozen: it uses no CPU at all, only its
  memory, and at most three are kept.
- **Store apps don't start with the PC.** Heroic, Lutris, Battle.net, the EA
  app and Ubisoft Connect only run when you open their tile or one of their
  games, never at boot or in the background.
- **Background jobs are rare**: Hearth's own timers run weekly (ES-DE and
  Twitch app updates).

## Compared with Windows 11

Windows 11 needs 4 GB of memory just to install, and on a typical gaming PC
it has well over a hundred background processes and a couple of gigabytes in
use before you open anything: store launchers, updaters, overlays, antivirus,
indexing and telemetry. Hearth's whole interface is about 300 MB, and the
system under it (Bazzite, a lean Fedora) doesn't run most of those at all.

To see it on your own PC rather than take our word for it:

- **On Hearth**: in Desktop Mode, open a terminal and run `hearthctl footprint`.
  It shows memory in use, CPU load, what Hearth itself uses, and the biggest
  programs.
- **On Windows 11**: Task Manager → Performance → Memory ("In use"), and the
  Details tab for processes.

Compare both sitting idle on their home screens, a minute after starting.

## If a game runs worse than it should

1. `hearthctl footprint` while it's running: is something else using memory
   or CPU?
2. Quick Menu → Stats: is the processor or graphics card at its temperature
   limit (it says "slowing down")?
3. Report it (Quick Menu → System → Report a problem): the report includes
   frame times from the home screen and what was running.
