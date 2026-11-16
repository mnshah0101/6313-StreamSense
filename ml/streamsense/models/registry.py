"""The only model-selection boundary used by orchestration code."""

from dataclasses import dataclass
from importlib import import_module

from omegaconf import DictConfig

from streamsense.models.base import ModelAdapter


@dataclass(frozen=True)
class AdapterSpec:
    import_path: str
    delivery_stage: int
    implemented: bool = False


REGISTRY: dict[str, AdapterSpec] = {
    "brisque_niqe": AdapterSpec(
        "streamsense.models.classical:ClassicalAdapter", 3, implemented=True
    ),
    "cnn_resnet18": AdapterSpec("streamsense.models.cnn:CNNAdapter", 3, implemented=True),
    "qwen3_5_0_8b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 4, implemented=True),
    "qwen2_5_vl_3b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 4, implemented=True),
    "qwen3_5_2b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "qwen3_5_4b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "qwen3_5_9b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "qwen3_vl_2b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "qwen3_vl_4b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "qwen3_vl_8b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "internvl3_5_2b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
    "internvl3_5_4b": AdapterSpec("streamsense.models.vlm:VLMAdapter", 5, implemented=True),
}


def build_adapter(cfg: DictConfig) -> ModelAdapter:
    """Resolve a configured adapter without importing other model stacks."""
    if cfg.model.name not in REGISTRY:
        raise ValueError(f"Unknown model {cfg.model.name!r}; registered: {sorted(REGISTRY)}")
    spec = REGISTRY[cfg.model.name]
    if not spec.implemented:
        raise NotImplementedError(
            f"{cfg.model.name} is configured but not implemented yet "
            f"(delivery stage {spec.delivery_stage}). See docs/DECISIONS.md."
        )
    module, name = spec.import_path.split(":")
    adapter = getattr(import_module(module), name)(cfg)
    if not isinstance(adapter, ModelAdapter):
        raise TypeError(f"{spec.import_path} must implement ModelAdapter")
    return adapter
