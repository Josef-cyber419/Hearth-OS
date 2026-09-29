"""How much of the PC is in use, and by what: `hearthctl footprint`.

Memory is each program's fair share (PSS: shared libraries split between the
programs using them), so the numbers add up. CPU is sampled over a few
seconds. Programs are grouped by name, so a game's many processes (or Wine's)
count as one line.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path



@dataclass
class Usage:
    name: str
    memory: int = 0  # bytes (PSS)
    cpu: float = 0.0  # percent of one core
    processes: int = 0


@dataclass
class Footprint:
    total: int  # bytes of RAM
    used: int  # bytes in use (total minus what's available)
    cores: int
    programs: list[Usage]  # biggest memory first

    @property
    def hearth(self) -> Usage:
        mine = [p for p in self.programs if p.name.split(".")[0] == "hearth" and p.name != "hearth.ctl"]
        return Usage("Hearth", sum(p.memory for p in mine), sum(p.cpu for p in mine), sum(p.processes for p in mine))

    @property
    def cpu(self) -> float:
        return sum(p.cpu for p in self.programs)


def meminfo(proc: Path = Path("/proc")) -> tuple[int, int]:
    """(total, used) bytes."""
    info = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0]) * 1024
    return info["MemTotal"], info["MemTotal"] - info.get("MemAvailable", info.get("MemFree", 0))


def program_name(cmdline: bytes, comm: str) -> str:
    """A readable name: `python -m hearth.overlay` is "hearth.overlay", a
    Windows game under Wine is its .exe, anything else its program name."""
    args = [a.decode(errors="replace") for a in cmdline.split(b"\0") if a]
    if not args:
        return comm or "?"
    if "-m" in args[:-1] and os.path.basename(args[0]).startswith("python"):
        return args[args.index("-m") + 1]
    for a in args:
        if a.lower().endswith(".exe"):
            return a.replace("\\", "/").rsplit("/", 1)[-1]
    return os.path.basename(args[0]) or comm


def _ticks(stat: str) -> int:
    fields = stat.rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])  # utime + stime


def _pss(pid_dir: Path) -> int:
    try:
        for line in (pid_dir / "smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def _processes(proc: Path) -> dict[str, tuple[str, int, int]]:
    """pid -> (name, cpu ticks, memory)."""
    out = {}
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            comm = (d / "comm").read_text().strip()
            name = program_name((d / "cmdline").read_bytes(), comm)
            out[d.name] = (name, _ticks((d / "stat").read_text()), _pss(d))
        except (OSError, ValueError, IndexError):
            continue  # gone, or a kernel thread we can't read
    return out


def measure(seconds: float = 3.0, proc: Path = Path("/proc"), sleep=time.sleep) -> Footprint:
    before = _processes(proc)
    t0 = time.monotonic()
    sleep(seconds)
    elapsed = max(time.monotonic() - t0, seconds, 1e-3)
    after = _processes(proc)
    hz = os.sysconf("SC_CLK_TCK")
    programs: dict[str, Usage] = {}
    for pid, (name, ticks, memory) in after.items():
        u = programs.setdefault(name, Usage(name))
        u.memory += memory
        u.processes += 1
        if pid in before and before[pid][0] == name:
            u.cpu += max(0, ticks - before[pid][1]) / hz / elapsed * 100
    total, used = meminfo(proc)
    ranked = sorted(programs.values(), key=lambda u: (u.memory, u.cpu), reverse=True)
    return Footprint(total, used, os.cpu_count() or 1, ranked)


def gib(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


def report(f: Footprint, top: int = 12) -> str:
    h = f.hearth
    lines = [
        f"Memory in use: {gib(f.used)} of {gib(f.total)}",
        f"Processor: {f.cpu / f.cores:.1f}% of {f.cores} cores",
        f"Hearth itself: {gib(h.memory)}, {h.cpu:.1f}% of one core ({h.processes} processes)",
        "",
        f"{'Program':<32} {'Memory':>8} {'CPU':>7}",
    ]
    for u in [u for u in f.programs if u.memory or u.cpu >= 0.05][:top]:
        count = f" ×{u.processes}" if u.processes > 1 else ""
        lines.append(f"{(u.name + count)[:32]:<32} {gib(u.memory):>8} {u.cpu:6.1f}%")
    lines.append("")
    lines.append("Memory is each program's fair share; CPU is % of one core over the last few seconds.")
    lines.append("(System services you can't read without sudo count in the total, not the list.)")
    return "\n".join(lines)
