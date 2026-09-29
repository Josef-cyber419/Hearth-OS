# Hardware compatibility

Hearth supports PCs with **AMD or Intel graphics**. NVIDIA graphics cards
aren't supported yet. They may be later, but not for now.

Check the **Graphics** row first. That's the one that decides it.

| Part | Supported | Works, less tested | Not supported |
|---|---|---|---|
| **Graphics** | AMD Radeon RX 5000 series and newer (RDNA 1–4), e.g. RX 6600, RX 6750 XT, RX 7800 XT, RX 9070 | AMD RX 400/500 and Vega (Polaris, GCN 5); Intel Arc A- and B-series; Intel Iris Xe and newer integrated graphics (11th gen Core and later); AMD Ryzen integrated graphics (Radeon 680M/780M and similar) | **NVIDIA (any GeForce/RTX)**; Intel HD/UHD graphics older than Iris Xe; AMD cards older than the RX 400 series |
| **Processor** | Any 64-bit AMD Ryzen or Intel Core from the last ~8 years (e.g. Ryzen 5 3600, Ryzen 7 5800X3D, Core i5-8400) | Older 64-bit x86 processors | ARM (Raspberry Pi, Apple Silicon, Snapdragon); 32-bit processors |
| **Memory** | 16 GB or more | 8 GB (fine for apps and older games) | Under 8 GB |
| **System drive** | SSD, 256 GB or more (NVMe or SATA) | 128 GB SSD; a hard drive (slow) | Under 64 GB; SD cards and USB sticks as the system drive |
| **Firmware** | UEFI | UEFI with Secure Boot (enroll Bazzite's key when installing) | Legacy BIOS / CSM only |
| **Display** | Any TV or monitor over HDMI or DisplayPort | 4K120 over HDMI on AMD needs a DisplayPort → HDMI 2.1 adapter (see [HARDWARE.md](HARDWARE.md#gpu-amd)) | |
| **Network** | Wired Ethernet; Intel Wi-Fi (AX200/AX210/AX211, BE200) | Most other Wi-Fi cards (Realtek, MediaTek) | Some very new or no-name USB Wi-Fi adapters without Linux drivers |
| **Controllers** | Xbox (Bluetooth or Microsoft's dongle), DualSense / DualShock 4, 8BitDo, Switch Pro | Most other USB and Bluetooth gamepads | |
| **Remotes** | Pulse-Eight USB-CEC adapter, FLIRC, Wii Remote on a Mayflash DolphinBar (mode 4), keyboards | TV remotes through CEC on some TVs | CEC straight from the graphics card (PC cards don't have it) |
| **Capture cards** | Elgato HD60 S+, HD60 X, 4K X, 4K S (USB) | Other USB (UVC) capture cards | Elgato PCIe cards (4K60 Pro, 4K Pro) |

## What "supported" means

- **Supported**: what Hearth is built and tested on. It should just work.
- **Works, less tested**: people run it, and it's expected to work, but
  fewer things have been checked. Report anything that doesn't work (Quick
  Menu → System → Report a problem).
- **Not supported**: won't work, or works too poorly to recommend.

## Why not NVIDIA (yet)?

Hearth runs on Bazzite's AMD/Intel image. NVIDIA needs a different image
with NVIDIA's own driver, and the TV-mode session (gamescope) has more rough
edges there: sleep, HDR and screen-capture problems are more common. Rather
than half-support it, Hearth focuses on AMD and Intel for now. If your PC has
an NVIDIA card, plain Bazzite's NVIDIA edition is the closest option today.

## Check your PC before installing

- **On Windows**: Settings → System → About shows the processor and memory;
  Device Manager → Display adapters shows the graphics card.
- **On Linux**: `lspci | grep -iE 'vga|3d|display'` shows the graphics.
- **After installing**: `hearthctl doctor` checks the graphics, drives,
  controllers and remotes, and says what's wrong in plain words.

## The reference PC

What Hearth is developed and tested on day to day:

| Part | Model |
|---|---|
| Processor | AMD Ryzen 7 5800X3D |
| Graphics | AMD Radeon RX 6750 XT |
| Memory | 24 GB |
| System drive | 256 GB SATA SSD |
| Controllers | Xbox Wireless Controller; Wii Remotes on a Mayflash DolphinBar |
