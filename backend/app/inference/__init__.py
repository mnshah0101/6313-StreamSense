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
            settings.batch_size,
            settings.binary_threshold,
            settings.max_new_tokens,
        )
    raise ValueError(f"Unknown backend {settings.backend!r}")
