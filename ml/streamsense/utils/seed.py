"""One seed controls Python, NumPy, and optional PyTorch RNGs."""

import importlib.util
import random

import numpy as np


def seed_everything(
    seed: int, *, cudnn_deterministic: bool, deterministic_algorithms: bool
) -> None:
    """Seed available runtimes without making PyTorch a CPU-audit dependency."""
    random.seed(seed)
    np.random.seed(seed % (2**32))
    if importlib.util.find_spec("torch") is not None:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = cudnn_deterministic
        torch.backends.cudnn.benchmark = not cudnn_deterministic
        torch.use_deterministic_algorithms(deterministic_algorithms)


def seed_worker(worker_id: int, *, base_seed: int) -> None:
    """Initialize a dataloader worker from the top-level seed and its worker ID."""
    seed = (base_seed + worker_id) % (2**32)
    random.seed(seed)
    np.random.seed(seed)
    if importlib.util.find_spec("torch") is not None:
        import torch

        torch.manual_seed(seed)
