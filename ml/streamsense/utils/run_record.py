"""Record resolved inputs and completion status even when a run fails."""

import hashlib
import json
import platform
import subprocess
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from hydra.core.hydra_config import HydraConfig
from omegaconf import DictConfig, OmegaConf

from streamsense.config import validate_config
from streamsense.utils.io import write_json, write_text
from streamsense.utils.seed import seed_everything


@dataclass
class RunContext:
    output_dir: Path
    record: dict[str, Any]


def git_state(root: Path) -> dict[str, Any]:
    """Report an unborn or absent repository without pretending a commit exists."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )

    try:
        commit = git("rev-parse", "HEAD")
        status = git("status", "--porcelain")
    except FileNotFoundError:
        return {"commit": None, "dirty": None}
    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout) if status.returncode == 0 else None,
    }


@contextmanager
def recorded_run(cfg: DictConfig, task: str) -> Iterator[RunContext]:
    """Create a local record and finish it on success or exception."""
    validate_config(cfg)
    seed_everything(
        cfg.seed,
        cudnn_deterministic=cfg.run.cudnn_deterministic,
        deterministic_algorithms=cfg.run.deterministic_algorithms,
    )
    resolved = OmegaConf.to_container(cfg, resolve=True, enum_to_str=True)
    canonical = json.dumps(resolved, sort_keys=True, allow_nan=False)
    config_hash = hashlib.sha256(canonical.encode()).hexdigest()
    started = datetime.now(UTC)
    if HydraConfig.initialized():
        output = Path(HydraConfig.get().runtime.output_dir)
    else:
        output = (
            Path(cfg.run.output_root)
            / cfg.experiment_id
            / (f"{started:%Y%m%dT%H%M%S%f}_{config_hash[:8]}")
        )
    output.mkdir(parents=True, exist_ok=True)
    write_text(output / ".hydra" / "resolved.yaml", OmegaConf.to_yaml(cfg, resolve=True))
    overrides = list(HydraConfig.get().overrides.task) if HydraConfig.initialized() else []
    record = {
        "task": task,
        "overrides": overrides,
        "status": "running",
        "experiment_id": cfg.experiment_id,
        "started_at": started.isoformat(),
        "git": git_state(Path(cfg.run.project_root).resolve()),
        "seed": cfg.seed,
        "config_sha256": config_hash,
        "split_file": cfg.split.manifest_path,
        "locked_test_file": cfg.split.locked_test_path,
        "manifest_sha256": None,
        "model": {
            "name": cfg.model.name,
            "id": cfg.model.model_id,
            "revision": cfg.model.revision,
            "adapter_path": cfg.model.adapter_path,
            "loaded": False,
        },
        "prompt_version": cfg.prompt.version,
        "preprocessing": {"image_size": cfg.data.image_size, "resize": cfg.data.resize_policy},
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "requested_device": cfg.hardware.device,
            "target_gpu": cfg.hardware.target_gpu,
            "observed_gpu": None,
            "gpu_count": None,
            "driver": None,
            "cuda": None,
            "peak_memory_bytes": None,
            "note": "Label inspection does not load a model or probe CUDA.",
        },
        "packages": {d.metadata["Name"]: d.version for d in metadata.distributions()},
        "resolved_config": resolved,
    }
    context = RunContext(output, record)
    start = time.monotonic()
    try:
        write_json(output / "run_record.json", record)
        yield context
    except BaseException as exc:
        record["status"] = "failed"
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    else:
        record["status"] = "completed"
    finally:
        record["wall_time_s"] = time.monotonic() - start
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_json(output / "run_record.json", record)
        if cfg.logging.mlflow and task in {"train", "evaluate"}:
            mirror_to_mlflow(cfg, output)


def mirror_to_mlflow(cfg: DictConfig, output: Path) -> None:
    """Best effort: a tracking problem must never fail or alter an experiment."""
    try:
        from streamsense.utils.tracking import log_run_dir

        Path(cfg.logging.mlflow_artifacts).mkdir(parents=True, exist_ok=True)
        Path(cfg.logging.mlflow_uri.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
        log_run_dir(output, cfg.logging.mlflow_uri, Path(cfg.logging.mlflow_artifacts))
    except Exception as exc:  # noqa: BLE001 - tracking is optional
        warnings.warn(f"MLflow logging skipped: {exc!r}", stacklevel=2)
