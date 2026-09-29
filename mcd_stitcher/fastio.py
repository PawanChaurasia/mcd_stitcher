from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

TILE = (512, 512)
ZSTD_LEVEL = 1
_WORKER_BYTES_DEFAULT = 1_100 * 2 ** 20
MEMORY_ENV_VAR = "MCD_STITCHER_MAX_MEM"
_declared_limit: Optional[int] = None

def parse_size(text) -> int:
    if isinstance(text, int):
        return text
    t = str(text).strip().upper().rstrip("B")
    if not t:
        raise ValueError("empty memory size")
    unit = t[-1]
    mult = {"K": 2 ** 10, "M": 2 ** 20, "G": 2 ** 30, "T": 2 ** 40}.get(unit)
    num = t[:-1] if mult else t
    try:
        value = float(num)
    except ValueError:
        raise ValueError(f"not a memory size: {text!r} (try 8G, 512M)") from None
    if value <= 0:
        raise ValueError(f"memory size must be positive: {text!r}")
    return int(value * (mult or 1))

def set_memory_limit(value) -> None:
    global _declared_limit
    _declared_limit = None if value is None else parse_size(value)

def _cgroup_limit() -> Optional[int]:
    for path, unlimited in (("/sys/fs/cgroup/memory.max", "max"),
                            ("/sys/fs/cgroup/memory/memory.limit_in_bytes", None)):
        try:
            raw = open(path).read().strip()
        except OSError:
            continue
        if raw == unlimited:
            continue
        try:
            n = int(raw)
        except ValueError:
            continue
        if 0 < n < 2 ** 62:
            return n
    return None

def _slurm_limit() -> Optional[int]:
    for var, per_cpu in (("SLURM_MEM_PER_NODE", False), ("SLURM_MEM_PER_CPU", True)):
        raw = os.environ.get(var)
        if not raw:
            continue
        try:
            mb = int(raw)
        except ValueError:
            continue
        if per_cpu:
            mb *= int(os.environ.get("SLURM_CPUS_ON_NODE", "1") or 1)
        return mb * 2 ** 20
    return None

def memory_limit() -> tuple:
    if _declared_limit is not None:
        return _declared_limit, "--max-memory"
    env = os.environ.get(MEMORY_ENV_VAR)
    if env:
        return parse_size(env), MEMORY_ENV_VAR
    for fn, name in ((_cgroup_limit, "cgroup"), (_slurm_limit, "slurm")):
        n = fn()
        if n:
            return n, name
    try:
        import psutil
    except ImportError:
        raise RuntimeError(
            "Cannot determine available memory: psutil is not installed and no memory limit "
            f"was declared. Install psutil, or pass --max-memory (or set {MEMORY_ENV_VAR}), "
            "e.g. --max-memory 8G."
        ) from None
    return int(psutil.virtual_memory().available), "measured"

def available_bytes() -> int:
    return memory_limit()[0]

def total_bytes() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except ImportError:
        return available_bytes()

def work_budget() -> int:
    n, source = memory_limit()
    if source != "measured":
        return n
    reserve = max(1 * 2 ** 30, int(n * 0.15))
    floor = min(512 * 2 ** 20, max(0, n) // 2)
    return max(floor, n - reserve)

def plan_workers(n_tasks: int, bytes_per_task: int = _WORKER_BYTES_DEFAULT,
                 cap: Optional[int] = None) -> int:
    if n_tasks <= 1:
        return 1
    by_mem = max(1, int(work_budget() // max(bytes_per_task, 1)))
    by_cpu = max(1, (os.cpu_count() or 4))
    if cap is None:
        cap = min(by_cpu, max(4, int(total_bytes() // (4 * 2 ** 30))))
    return max(1, min(n_tasks, by_cpu, by_mem, cap))

_GROUPS_IN_FLIGHT = 2

def channel_group(total_channels: int, bytes_per_channel: int,
                  budget: Optional[int] = None) -> int:
    if bytes_per_channel <= 0:
        return total_channels
    usable = (budget if budget is not None else work_budget()) // _GROUPS_IN_FLIGHT
    fits = int(usable // bytes_per_channel)
    return max(1, min(total_channels, fits))


@contextmanager
def atomic_write(path):
    part = Path(f"{path}.part")
    try:
        yield part
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

def write_planes_fast(output_path, ome_xml: str, planes: Iterable[np.ndarray],
                      compression: str, output_type: str,
                      tile=TILE, maxworkers: Optional[int] = None) -> None:
    import tifffile as tiff

    if maxworkers is None:
        maxworkers = max(1, min(24, (os.cpu_count() or 4)))

    kw = {"tile": tile, "photometric": "minisblack", "metadata": None,
          "maxworkers": maxworkers}
    if compression == "zstd":
        kw["compression"] = "zstd"
        kw["compressionargs"] = {"level": ZSTD_LEVEL}
    elif compression in (None, "None"):
        kw["compression"] = None
    else:
        kw["compression"] = compression

    with atomic_write(output_path) as part, tiff.TiffWriter(part, bigtiff=True) as writer:
        for i, plane in enumerate(planes):
            writer.write(_cast(plane, output_type),
                         description=ome_xml if i == 0 else None, **kw)

def _cast(arr: np.ndarray, output_type: str) -> np.ndarray:
    if output_type == "uint16":
        if arr.dtype == np.uint16:
            return arr
        return np.clip(arr, 0, 65535).astype(np.uint16)
    if arr.dtype == np.float32:
        return arr
    return arr.astype(np.float32, copy=False)