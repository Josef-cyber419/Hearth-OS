"""How hard the PC is working, and whether it's running hot: for the Quick
Menu's Performance tab.

Everything comes from the kernel, read a couple of times a second while the
tab is open: CPU load (/proc/stat), CPU clock (cpufreq), memory
(/proc/meminfo), temperatures (hwmon: k10temp for AMD CPUs, coretemp for
Intel, amdgpu for the GPU's edge and junction), and the AMD GPU's load,
clock, power and VRAM (/sys/class/drm).

"Slowing down" (throttling) is what it looks like from outside: a chip at
its temperature limit, or busy yet running well under its top clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Temperatures (°C) where things get warm, and where chips protect themselves.
CPU_WARM, CPU_HOT = 80, 89  # a 5800X3D's limit is 90 °C
GPU_WARM, GPU_HOT = 95, 105  # junction (hotspot); RDNA2 cards hold 110 °C at most
BUSY = 70  # % load above which a low clock means throttling
SLOW = 0.6  # "well under its top clock": below this fraction of it


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


@dataclass
class Reading:
    cpu_load: float | None = None  # %
    cpu_mhz: float | None = None
    cpu_max_mhz: float | None = None
    cpu_temp: float | None = None
    gpu_load: float | None = None
    gpu_mhz: float | None = None
    gpu_max_mhz: float | None = None
    gpu_temp: float | None = None  # edge
    gpu_hotspot: float | None = None  # junction
    gpu_watts: float | None = None
    gpu_cap_watts: float | None = None
    ram_used: int | None = None  # bytes
    ram_total: int | None = None
    vram_used: int | None = None
    vram_total: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any("slowing" in w for w in self.warnings):
            return "Slowing down to cool off"
        if self.warnings:
            return "Running hot"
        temps = [t for t in (self.cpu_temp, self.gpu_hotspot or self.gpu_temp) if t is not None]
        if not temps:
            return "No sensors found"
        warm = (self.cpu_temp or 0) >= CPU_WARM or (self.gpu_hotspot or self.gpu_temp or 0) >= GPU_WARM
        return "Warm, but fine" if warm else "Cool"


class Monitor:
    def __init__(self, proc: Path = Path("/proc"), sys: Path = Path("/sys")) -> None:
        self.proc, self.sys = proc, sys
        self._last_cpu: tuple[int, int] | None = None

    # -- CPU ---------------------------------------------------------------

    def _cpu_load(self) -> float | None:
        line = _read(self.proc / "stat").splitlines()[:1]
        if not line or not line[0].startswith("cpu "):
            return None
        values = [int(v) for v in line[0].split()[1:] if v.isdigit()]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        last, self._last_cpu = self._last_cpu, (idle, total)
        if last is None or total == last[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (1 - (idle - last[0]) / (total - last[1]))))

    def _cpu_clock(self) -> tuple[float | None, float | None]:
        cur, top = [], []
        for d in sorted((self.sys / "devices/system/cpu").glob("cpu[0-9]*/cpufreq")):
            c, m = _int(_read(d / "scaling_cur_freq")), _int(_read(d / "cpuinfo_max_freq"))
            if c:
                cur.append(c / 1000)
            if m:
                top.append(m / 1000)
        return (sum(cur) / len(cur) if cur else None), (max(top) if top else None)

    # -- sensors -------------------------------------------------------------

    def _hwmon(self) -> dict[str, dict[str, float]]:
        """{chip name: {temp label: °C, "power": W, "cap": W}} (first chip of each name)."""
        out: dict[str, dict[str, float]] = {}
        for hw in sorted((self.sys / "class/hwmon").glob("hwmon*")):
            name = _read(hw / "name")
            if not name or name in out:
                continue
            chip: dict[str, float] = {}
            for t in sorted(hw.glob("temp*_input")):
                v = _int(_read(t))
                if v is None:
                    continue
                label = _read(t.with_name(t.name.replace("_input", "_label"))).lower() or t.name.split("_")[0]
                chip[label] = v / 1000
            p = _int(_read(hw / "power1_average")) or _int(_read(hw / "power1_input"))
            if p:
                chip["power"] = p / 1e6
            cap = _int(_read(hw / "power1_cap"))
            if cap:
                chip["cap"] = cap / 1e6
            out[name] = chip
        return out

    # -- GPU ---------------------------------------------------------------

    def _gpu(self, r: Reading) -> None:
        for card in sorted((self.sys / "class/drm").glob("card[0-9]")):
            dev = card / "device"
            busy = _int(_read(dev / "gpu_busy_percent"))
            if busy is None:
                continue
            r.gpu_load = float(busy)
            levels = _read(dev / "pp_dpm_sclk").splitlines()
            # "1: 1800Mhz *": the star marks the clock it's running at now.
            mhz = [int(m.group(1)) if (m := re.search(r":\s*(\d+)\s*mhz", line, re.I)) else None
                   for line in levels]
            for line, v in zip(levels, mhz):
                if "*" in line and v:
                    r.gpu_mhz = float(v)
            known = [v for v in mhz if v]
            r.gpu_max_mhz = float(max(known)) if known else None
            used, total = _int(_read(dev / "mem_info_vram_used")), _int(_read(dev / "mem_info_vram_total"))
            r.vram_used, r.vram_total = used, total
            return

    # -- all of it --------------------------------------------------------------

    def read(self) -> Reading:
        r = Reading()
        r.cpu_load = self._cpu_load()
        r.cpu_mhz, r.cpu_max_mhz = self._cpu_clock()
        chips = self._hwmon()
        cpu = chips.get("k10temp") or chips.get("zenpower") or chips.get("coretemp") or {}
        r.cpu_temp = cpu.get("tctl") or cpu.get("tdie") or cpu.get("package id 0") or cpu.get("temp1")
        gpu = chips.get("amdgpu") or {}
        r.gpu_temp = gpu.get("edge") or gpu.get("temp1")
        r.gpu_hotspot = gpu.get("junction") or gpu.get("temp2")
        r.gpu_watts, r.gpu_cap_watts = gpu.get("power"), gpu.get("cap")
        self._gpu(r)
        mem = {}
        for line in _read(self.proc / "meminfo").splitlines():
            k, _, v = line.partition(":")
            if v.strip().endswith("kB"):
                mem[k] = int(v.split()[0]) * 1024
        if "MemTotal" in mem and "MemAvailable" in mem:
            r.ram_total, r.ram_used = mem["MemTotal"], mem["MemTotal"] - mem["MemAvailable"]
        r.warnings = warnings(r)
        return r


def warnings(r: Reading) -> list[str]:
    out = []
    if r.cpu_temp is not None and r.cpu_temp >= CPU_HOT:
        out.append(f"CPU at {r.cpu_temp:.0f}°C: at its limit, slowing down")
    elif r.cpu_load is not None and r.cpu_load >= BUSY and r.cpu_mhz and r.cpu_max_mhz \
            and r.cpu_mhz < r.cpu_max_mhz * SLOW:
        out.append("CPU busy but running slow: slowing down (heat or power limit)")
    hot = r.gpu_hotspot if r.gpu_hotspot is not None else r.gpu_temp
    if hot is not None and hot >= GPU_HOT:
        out.append(f"GPU hotspot {hot:.0f}°C: slowing down")
    elif r.gpu_load is not None and r.gpu_load >= BUSY + 20 and r.gpu_mhz and r.gpu_max_mhz \
            and r.gpu_mhz < r.gpu_max_mhz * SLOW and (hot or 0) >= GPU_WARM:
        out.append("GPU busy but running slow and hot: slowing down")
    return out
