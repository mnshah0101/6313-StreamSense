"""Structured Hydra schema. Experiment values live in conf/, not model logic."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydra.core.config_store import ConfigStore
from omegaconf import MISSING, DictConfig, OmegaConf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "conf"
if not CONFIG_DIR.is_dir():
    CONFIG_DIR = Path(__file__).resolve().parent / "conf"


class SeverityMissing(str, Enum):
    mask = "mask"
    drop_row = "drop_row"
    impute_median_by_term = "impute_median_by_term"


class SourceFilter(str, Enum):
    all = "all"
    user_only = "user_only"


class UnknownFields(str, Enum):
    fatal = "fatal"
    preserve = "preserve"


@dataclass
class DecisionMap:
    valid: str = "positive"
    not_: str = "negative"
    duplicate: str = "drop"


@dataclass
class LabelConfig:
    # A typed dictionary permits the literal YAML key "not" (a Python keyword).
    decision_map: dict[str, str] = field(default_factory=dict)
    duplicate_policy: str = "drop"
    severity_missing: SeverityMissing = SeverityMissing.mask
    source_filter: SourceFilter = SourceFilter.all
    source_weight: dict[str, float] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    unknown_fields: UnknownFields = UnknownFields.fatal
    valid_empty_term_fatal: bool = True
    negative_annotation_fatal: bool = True
    severity_min: int = 1
    severity_max: int = 5
    key_pattern: str = MISSING
    description_as_explanation: bool = True


@dataclass
class TaxonomyMapping:
    crew_class: str = MISSING
    weather_related: bool = False
    confirmed: bool = False


@dataclass
class TaxonomyConfig:
    terms: list[str] = field(default_factory=list)
    min_term_count: int = 5
    vocabulary_fit_split: str = "train"
    other_term: str = "other"
    crew_classes: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    mapping: dict[str, TaxonomyMapping] = field(default_factory=dict)
    crew_mapping_before_rare_fold: bool = True


@dataclass
class DataConfig:
    zip_path: str | None = None
    extract_dir: str = MISSING
    root_subdir: str = ""
    labels_file: str | None = None
    input_mode: str = "zip"
    image_extensions: list[str] = field(default_factory=list)
    image_size: int = 384
    resize_policy: str = "letterbox"
    description_as_input: bool = False
    manifest_path: str = MISSING
    schema_report: str = MISSING
    max_labels_bytes: int = 20_000_000
    phash_distance: int = 4
    phash_size: int = 8
    canvas_aspect: float = 16 / 9
    synthetic_fixture: bool = False
    cache_dir: str = "data/cache"


@dataclass
class SplitConfig:
    ratios: dict[str, float] = field(default_factory=dict)
    seed: int = MISSING
    group_key: str = "game_id"
    stratify: bool = True
    method: str = "seeded_search"
    n_trials: int = 2000
    manifest_path: str = MISSING
    locked_test_path: str = MISSING
    cross_game_duplicates: str = "group_connected_games"
    lock_test: bool = True


@dataclass
class ModelConfig:
    name: str = MISSING
    model_id: str = MISSING
    revision: str = MISSING
    adapter_path: str | None = None
    pretrained: bool = True
    dtype: str = "float32"
    trust_remote_code: bool = False
    max_new_tokens: int = 256
    do_sample: bool = False
    thinking: bool = False
    fallback: str | None = None
    fallback_scope: str = "smoke_only"
    classical_metrics: list[str] = field(default_factory=list)
    classical_estimator: str = "logistic_regression"
    severity_head: str = "regression"
    quantization: str | None = None
    binary_threshold: float = 0.5
    term_threshold: float = 0.5
    classical_max_side: int | None = None
    batch_size: int = 32
    image_max_side: int | None = None
    answer_prefix: str = ""


@dataclass
class LoraConfig:
    style: str = "lora"  # lora | dora | rslora | loha | lokr
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: list[str] = field(default_factory=list)
    freeze_vision: bool = True
    train_projector: bool = False
    language_scope: str = "model.language_model"
    layers: list[int] | None = None  # [first, last] language layer indices; None = all
    vision_target_modules: list[str] = field(default_factory=list)
    vision_scope: str = "model.visual.blocks"
    projector_module: str = "model.visual.merger"


@dataclass
class TrainConfig:
    name: str = "none"
    lr: float = 0.0001
    epochs: int = 10
    batch_size: int = 8
    grad_accum: int = 1
    bf16: bool = False
    gradient_checkpointing: bool = False
    warmup_ratio: float = 0.05
    scheduler: str = "cosine"
    weight_decay: float = 0.01
    eval_every_steps: int = 50
    max_steps: int | None = None
    subset_size: int | None = None
    num_workers: int = 0
    early_stopping_patience: int = 3
    # Checkpoints before this fraction of training are logged but never selected (and don't
    # count toward early stopping): a lucky recall spike at the first eval can't win.
    selection_start_fraction: float = 0.0
    selection_metric: str = "recall_at_precision_target"
    class_balanced_sampling: bool = False
    loss_weights: dict[str, float] = field(default_factory=dict)
    max_grad_norm: float = 1.0
    decision_loss_weight: float = 1.0
    class_loss_weight: float = 0.0  # extra CE weight on crew-class name tokens (0 = off)
    verify_reload: bool = False
    lora: LoraConfig = field(default_factory=LoraConfig)


@dataclass
class PromptConfig:
    version: str = MISSING
    system: str = MISSING
    user: str = MISSING
    confidence_semantics: str = "probability_quality_issue"
    missing_severity: str = "null"
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalConfig:
    split: str = "val"
    final_test: bool = False
    run_dir: str | None = None
    precision_targets: list[float] = field(default_factory=list)
    selection_precision_target: float = 0.90
    threshold_grid: list[float] = field(default_factory=list)
    threshold_fit_split: str = "val"
    bootstrap_samples: int = 1000
    bootstrap_unit: str = "game_id"
    confidence_bins: int = 10
    top_k_errors: int = 20
    parse_failure_policy: str = "negative_and_report"
    user_subset: bool = True
    zero_support_policy: str = "omit_metrics_report_support"
    severity_mos: dict[int, float] = field(default_factory=dict)
    threshold_candidates: str = "unique_scores"


@dataclass
class BenchConfig:
    backend: str = "hf"
    batch_sizes: list[int] = field(default_factory=list)
    concurrency: list[int] = field(default_factory=list)
    n_frames: int = 200
    warmup: int = 10
    image_size: int = MISSING
    sample_interval_s: float = 5.0
    latency_limit_s: float = 5.0
    include_queue_time: bool = True


@dataclass
class HardwareConfig:
    device: str = "cpu"
    target_gpu: str = "NVIDIA L4"
    requested_gpu_type: str | None = None
    gpu_count: int = 0
    cpus: int = 4
    memory_gb: int = 16
    time_limit: str = "01:00:00"
    account: str | None = None
    qos: str | None = None
    modules: list[str] = field(default_factory=list)
    cache_dir: str | None = None


@dataclass
class LoggingConfig:
    csv: bool = True
    tensorboard: bool = True
    cloud: bool = False
    upload_images: bool = False
    mlflow: bool = True  # local store only; mirrors finished train/evaluate runs
    mlflow_uri: str = MISSING
    mlflow_artifacts: str = MISSING


@dataclass
class PrivacyConfig:
    protected_dirs: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)
    blocked_extensions: list[str] = field(default_factory=list)
    scan_json_contents: bool = True


@dataclass
class ReportConfig:
    runs: list[str] = field(default_factory=list)  # empty: latest completed run per experiment
    experiments: list[str] = field(default_factory=list)
    output: str = "outputs/friday_report.md"
    followup_top_k: int = 2
    notebook: str = "notebooks/streamsense_report.ipynb"
    standalone_dir: str = "outputs/client_report"
    followup_seeds: list[int] = field(default_factory=lambda: [0, 1, 2])


@dataclass
class RunConfig:
    project_root: str = MISSING
    output_root: str = MISSING
    cudnn_deterministic: bool = True
    deterministic_algorithms: bool = False


@dataclass
class AppConfig:
    seed: int = 42
    experiment_id: str = "development"
    experiment_note: str = ""
    stage: int = 1
    data: DataConfig = field(default_factory=DataConfig)
    labels: LabelConfig = field(default_factory=LabelConfig)
    taxonomy: TaxonomyConfig = field(default_factory=TaxonomyConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)
    bench: BenchConfig = field(default_factory=BenchConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    run: RunConfig = field(default_factory=RunConfig)
    report: ReportConfig = field(default_factory=ReportConfig)


def register_configs() -> None:
    """Register the root schema before Hydra composes YAML config groups."""
    ConfigStore.instance().store(name="streamsense_schema", node=AppConfig)
    if not OmegaConf.has_resolver("run_token"):
        OmegaConf.register_new_resolver("run_token", lambda: uuid4().hex[:8], use_cache=True)


def validate_config(cfg: DictConfig) -> None:
    """Reject unsupported semantics before reading data or starting a run."""
    OmegaConf.to_container(cfg, resolve=True, throw_on_missing=True)
    if cfg.seed < 0:
        raise ValueError("seed must be nonnegative")
    ratios = cfg.split.ratios
    if set(ratios) != {"train", "val", "test"} or any(x <= 0 for x in ratios.values()):
        raise ValueError("split.ratios must contain positive train, val and test ratios")
    if abs(sum(ratios.values()) - 1.0) > 1e-8:
        raise ValueError("split.ratios must sum to 1")
    if cfg.split.seed < 0:
        raise ValueError("split.seed must be nonnegative")
    if dict(cfg.labels.decision_map) != {
        "valid": "positive",
        "not": "negative",
        "duplicate": "drop",
    }:
        raise ValueError("Unsupported decision map; confirm label semantics before changing it")
    if cfg.labels.duplicate_policy != "drop":
        raise ValueError("Duplicate rows must never enter training or evaluation")
    if set(cfg.labels.source_weight) != {"prefill", "user"} or any(
        w <= 0 for w in cfg.labels.source_weight.values()
    ):
        raise ValueError("Source weights must be positive for prefill and user")
    if cfg.data.input_mode not in {"zip", "extracted"}:
        raise ValueError("data.input_mode must be zip or extracted")
    if cfg.data.input_mode == "zip" and not cfg.data.zip_path:
        raise ValueError("data.zip_path is required in zip mode")
    if cfg.data.max_labels_bytes <= 0 or cfg.data.image_size <= 0:
        raise ValueError("Label size limit and image size must be positive")
    if cfg.taxonomy.min_term_count < 1:
        raise ValueError("taxonomy.min_term_count must be positive")
    classes = set(cfg.taxonomy.crew_classes)
    if cfg.taxonomy.other_term not in classes:
        raise ValueError("The taxonomy must include its other bucket")
    if any(m.crew_class not in classes for m in cfg.taxonomy.mapping.values()):
        raise ValueError("Every taxonomy mapping must target a configured crew class")
    if cfg.train.selection_metric != "recall_at_precision_target":
        raise ValueError("Model selection must maximize recall at the precision target")
    if cfg.taxonomy.vocabulary_fit_split != "train" or cfg.eval.threshold_fit_split != "val":
        raise ValueError("Fit the vocabulary on train and thresholds on val only")
    if cfg.eval.split not in {"val", "test"}:
        raise ValueError("Evaluation split must be val or test")
    if cfg.eval.split == "test" and not cfg.eval.final_test:
        raise ValueError("Test evaluation requires eval.final_test=true")
    if any(not 0 < p <= 1 for p in cfg.eval.precision_targets):
        raise ValueError("Precision targets must be in (0, 1]")
    if not 0 < cfg.eval.selection_precision_target <= 1:
        raise ValueError("Selection precision target must be in (0, 1]")
    if any(not 0 <= t <= 1 for t in cfg.eval.threshold_grid):
        raise ValueError("Thresholds must be in [0, 1]")
    if not cfg.logging.mlflow_uri.startswith(("sqlite:", "file:")):
        raise ValueError("MLflow tracking must stay local (sqlite: or file: URI)")
    if cfg.logging.cloud or cfg.logging.upload_images:
        raise ValueError("Cloud logging and image uploads are not implemented")
    if cfg.split.method != "seeded_search" or cfg.split.n_trials < 1:
        raise ValueError("split.method must be seeded_search with n_trials >= 1")
    if cfg.eval.threshold_candidates not in {"unique_scores", "grid"}:
        raise ValueError("eval.threshold_candidates must be unique_scores or grid")
    if cfg.labels.severity_missing.value == "impute_median_by_term":
        raise NotImplementedError("impute_median_by_term is not implemented; use mask or drop_row")
    if not cfg.train.lora.freeze_vision:
        raise NotImplementedError("Training the vision encoder is not implemented")
    if cfg.model.name.startswith("qwen") and (
        len(cfg.model.revision) != 40
        or any(c not in "0123456789abcdef" for c in cfg.model.revision)
    ):
        raise ValueError("HF model.revision must be an immutable 40-character commit SHA")


def project_path(cfg: DictConfig, value: str) -> Path:
    """Resolve dataset and report paths independently of Hydra's run directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(cfg.run.project_root) / path
