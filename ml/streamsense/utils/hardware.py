"""Device selection and observed-hardware fields for run records."""

import subprocess
from typing import Any

from omegaconf import DictConfig


def resolve_device(cfg: DictConfig) -> str:
    """hardware.device is cpu, cuda, or auto (cuda when available)."""
    import torch

    wanted = cfg.hardware.device
    if wanted == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("hardware.device=cuda but CUDA is not available")
    if wanted == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return wanted


def observed_hardware() -> dict[str, Any]:
    """GPU name/count, driver, CUDA and peak memory; None when there is no GPU."""
    import torch

    if not torch.cuda.is_available():
        return {"observed_gpu": None, "gpu_count": 0, "driver": None, "cuda": None,
                "peak_memory_bytes": None}  # fmt: skip
    try:
        driver = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, check=False,
        ).stdout.strip().splitlines()[0]  # fmt: skip
    except (FileNotFoundError, IndexError):
        driver = None
    return {
        "observed_gpu": torch.cuda.get_device_name(0),
        "gpu_count": torch.cuda.device_count(),
        "driver": driver,
        "cuda": torch.version.cuda,
        "peak_memory_bytes": torch.cuda.max_memory_allocated(),
    }


def release_accelerator_memory() -> None:
    """Collect unreferenced objects and return cached CUDA blocks to the driver."""
    import gc

    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
