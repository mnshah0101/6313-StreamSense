"""Defect vocabulary shared with the UI, and the mapping from the model's crew classes."""

DEFECT_TYPES = ["Blur", "Overexposure", "Low light", "Miscalibration", "Stitching", "Weather"]

# Spatial defects can show a heat map; global ones (lighting, weather) cannot.
SPATIAL_DEFECTS = {"Miscalibration", "Stitching", "Blur"}

# playonsports crew classes (conf/data/taxonomy.yaml) -> UI defect types.
# white_balance_saturation has no UI type yet; it is closest to Overexposure.
# "other" has no UI type: the frame is still flagged by its score, with no named defect.
CREW_TO_DEFECT: dict[str, str | None] = {
    "blur_lens_smear": "Blur",
    "overexposure": "Overexposure",
    "white_balance_saturation": "Overexposure",
    "low_light": "Low light",
    "miscalibration": "Miscalibration",
    "stitching_black_patch": "Stitching",
    "weather": "Weather",
    "other": None,
}


def merge_detections(dets: list[dict]) -> list[dict]:
    """One detection per defect type, keeping the worst severity."""
    worst: dict[str, int] = {}
    for d in dets:
        worst[d["type"]] = max(worst.get(d["type"], 0), int(d["severity"]))
    return [{"type": t, "severity": s} for t, s in sorted(worst.items(), key=lambda x: -x[1])]
