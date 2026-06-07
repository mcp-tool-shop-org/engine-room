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


def _nvidia_smi() -> dict:
    out = {}
    exe = shutil.which("nvidia-smi")
    if not exe:
        return out
    try:
        q = subprocess.run([exe, "--query-gpu=name,memory.total,driver_version",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        if q.returncode == 0 and q.stdout.strip():
            name, mem, drv = [x.strip() for x in q.stdout.strip().splitlines()[0].split(",")]
            out["gpu"] = name
            out["vram_gb"] = round(float(mem) / 1024, 1)
            out["driver"] = drv
        # CUDA runtime (UMD) from `nvidia-smi` header
        h = subprocess.run([exe], capture_output=True, text=True, timeout=15)
        cm = re.search(r"CUDA Version:\s*([\d.]+)", h.stdout or "")
        if cm:
            out["cuda_runtime"] = cm.group(1)
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


def _sm_for(gpu: str | None) -> str | None:
    if not gpu:
        return None
    g = gpu.lower()
    if "5090" in g or "5080" in g or "blackwell" in g:
        return "sm_120"          # desktop Blackwell GB202
    return None


def _wsl2_version() -> str | None:
    exe = shutil.which("wsl") or shutil.which("wsl.exe")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"WSL version:\s*([\d.]+)", r.stdout or "")
        return m.group(1) if m else None
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
