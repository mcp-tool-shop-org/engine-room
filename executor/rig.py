"""Detect the live rig fingerprint — the thing a recipe is resolved AGAINST.

Read-only (queries nvidia-smi + the environment). The fingerprint splits into a COMPATIBILITY
BAND (the semantic predicates a baseline holds across — driver>=R570, cuda_toolkit, sm) and the
EXACT build (driver build number) recorded as drift-tolerant metadata. Per the design: hash the
BAND for the baseline join, not the literal driver, so a routine driver bump triggers a re-probe
rather than invalidating every baseline.
"""
from __future__ import annotations
import os, re, shutil, subprocess
from dataclasses import dataclass


@dataclass
class Rig:
    gpu: str; vram_gb: float | None; sm: str | None
    driver: str | None; cuda_runtime: str | None; cuda_toolkit: str | None
    os_surface: str; wsl2_version: str | None

    def compat_band(self) -> dict:
        """Semantic predicates a measurement holds across (the baseline join key inputs)."""
        return {
            "gpu_arch": self.sm,
            "cuda_toolkit": self.cuda_toolkit,
            "os_surface": self.os_surface,
            "driver_floor": "R570" if self._driver_major() and self._driver_major() >= 570 else self.driver,
        }

    def _driver_major(self) -> int | None:
        m = re.match(r"(\d+)", self.driver or "")
        return int(m.group(1)) if m else None


def _parse_smi_query(line: str | None) -> dict | None:
    """Parse one `--query-gpu=name,memory.total,driver_version` CSV row.

    The GPU name can itself contain commas (e.g. "NVIDIA RTX 5000, Ada Generation"), so split
    from the RIGHT: the last two fields are always memory + driver; everything before is the name.
    Returns gpu/vram_gb/driver, or None if the row's SHAPE is unparseable (so the caller stays
    honest instead of recording a blind fingerprint).

    Degrades PER-FIELD (BACKEND-B-003): a non-numeric memory.total (e.g. '[N/A]', which nvidia-smi
    emits for some virtualized / MIG / older-driver paths) does NOT drop the whole row. We keep the
    name + driver we DID read and set vram_gb=None — partial truth beats discarding a usable
    fingerprint. Only an unparseable row SHAPE (wrong field count, blank line) returns None.
    """
    if not line or not line.strip():
        return None
    parts = [x.strip() for x in line.strip().splitlines()[0].rsplit(",", 2)]
    if len(parts) != 3:
        return None
    name, mem, drv = parts
    try:
        vram = round(float(mem) / 1024, 1)
    except ValueError:
        # memory.total was non-numeric ('[N/A]') — keep name+driver, degrade vram only.
        vram = None
    return {"gpu": name, "vram_gb": vram, "driver": drv}


def _parse_cuda_runtime(header: str | None) -> str | None:
    """Pull the CUDA runtime (UMD) version from the `nvidia-smi` header.

    Matches BOTH the classic 'CUDA Version: 12.8' token and the live-rig
    'CUDA UMD Version: 13.3' token (the UMD wording the conflict check reads).
    """
    if not header:
        return None
    m = re.search(r"CUDA(?:\s+UMD)?\s+Version:\s*([\d.]+)", header)
    return m.group(1) if m else None


def _nvidia_smi() -> dict:
    out = {}
    exe = shutil.which("nvidia-smi")
    if not exe:
        return out
    try:
        q = subprocess.run([exe, "--query-gpu=name,memory.total,driver_version",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        if q.returncode == 0:
            parsed = _parse_smi_query(q.stdout)
            if parsed:
                out.update(parsed)
        # CUDA runtime (UMD) from `nvidia-smi` header
        h = subprocess.run([exe], capture_output=True, text=True, timeout=15)
        cr = _parse_cuda_runtime(h.stdout)
        if cr:
            out["cuda_runtime"] = cr
    except Exception:
        pass
    return out


def _cuda_toolkit() -> str | None:
    exe = shutil.which("nvcc")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"release\s+([\d.]+)", r.stdout or "")
        return m.group(1) if m else None
    except Exception:
        return None


# Architecture map: (lowercased name substring -> sm tag). Ordered, first hit wins. Moving the
# mapping out of an if-ladder (BACKEND-B-005) makes adding a SKU a one-line table entry. The
# desktop Blackwell (RTX 50-series, GB20x) family all reports compute capability sm_120 — the
# 5090/5080 plus the 5070, 5070 Ti, and 5060 / 5060 Ti the original ladder omitted.
_SM_TABLE: list[tuple[str, str]] = [
    ("5090", "sm_120"),   # GB202
    ("5080", "sm_120"),   # GB203
    ("5070", "sm_120"),   # GB205 / GB203 (covers '5070' and '5070 ti' via substring)
    ("5060", "sm_120"),   # GB206 (covers '5060' and '5060 ti')
    ("blackwell", "sm_120"),
]


def _sm_for(gpu: str | None) -> str | None:
    if not gpu:
        return None
    g = gpu.lower()
    for needle, sm in _SM_TABLE:
        if needle in g:
            return sm
    return None


def _parse_wsl2_version(raw: bytes | str | None) -> str | None:
    """Pull the WSL version from `wsl --version` output.

    `wsl --version` emits UTF-16-LE; capturing with text=True garbled it and the regex never
    matched (-> wsl2_version=None despite a live WSL2, mis-firing the defect_floor + wsl2-docker
    provider). Decode from bytes here: try utf-16-le first, then strip NUL bytes as a fallback.
    """
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            text = raw.replace(b"\x00", b"").decode("utf-8", "ignore")
        if "WSL version" not in text:
            # not UTF-16 after all (e.g. an already-utf-8 stub) — decode straight
            text = raw.replace(b"\x00", b"").decode("utf-8", "ignore")
    else:
        text = raw
    m = re.search(r"WSL version:\s*([\d.]+)", text)
    return m.group(1) if m else None


def _wsl2_version() -> str | None:
    exe = shutil.which("wsl") or shutil.which("wsl.exe")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, timeout=10)
        return _parse_wsl2_version(r.stdout)
    except Exception:
        return None


def detect() -> Rig:
    smi = _nvidia_smi()
    gpu = smi.get("gpu", "unknown GPU")
    return Rig(
        gpu=gpu,
        vram_gb=smi.get("vram_gb"),
        sm=_sm_for(gpu),
        driver=smi.get("driver"),
        cuda_runtime=smi.get("cuda_runtime"),
        cuda_toolkit=_cuda_toolkit(),
        os_surface="windows" if os.name == "nt" else "linux",
        wsl2_version=_wsl2_version(),
    )
