"""Backend factory: one process-wide backend, chosen by settings."""

from app.config import Settings
from app.inference.base import Backend, FrameResult

__all__ = ["Backend", "FrameResult", "build_backend"]


def build_backend(settings: Settings) -> Backend:
    if settings.backend == "dummy":
        from app.inference.dummy import DummyBackend

        return DummyBackend()
    if settings.backend == "streamsense":
        if not settings.run_dir:
            raise ValueError("STREAMSENSE_API_RUN_DIR is required for the streamsense backend")
        from app.inference.streamsense_vlm import StreamSenseBackend

        return StreamSenseBackend(
            settings.run_dir,
            settings.streamsense_repo,
            settings.device,
            auto_batch_size(settings.batch_size),
            settings.binary_threshold,
            settings.max_new_tokens,
        )
    raise ValueError(f"Unknown backend {settings.backend!r}")


def auto_batch_size(configured: int = 0) -> int:
    """Frames per inference call. An explicit setting wins; otherwise sized to the GPU with
    headroom (Qwen3-VL-4B at batch 16 peaks ~11.4 GB, so 32 stays well under 40 GB). The worker
    also halves a batch that runs out of memory, so a wrong guess costs time, not the job."""
    if configured > 0:
        return configured
    try:
        import torch

        if torch.cuda.is_available():
            gb = torch.cuda.get_device_properties(0).total_memory / 2**30
            return 32 if gb >= 40 else 16 if gb >= 20 else 8
    except ImportError:
        pass
    return 8
