# ruff: noqa: E501  (embedded HTML/CSS template lines)
"""Prototype issue heat maps (E-13) on selected validation frames, from a trained VLM adapter.

Two model-agnostic maps, both from the adapter's P(issue) score (one forward pass per image):
- crops:     P(issue) of overlapping crops cut from the full-resolution frame (each crop is
             near native resolution, so cropping does not add blur); pixel heat = mean over
             the crops that cover it.
- occlusion: drop in log-odds of P(issue) when a grid tile is greyed out (log-odds, not
             probability, so a saturated P = 0.999 still shows which tiles matter). Caveat for quality detection:
             a grey block can itself look like an obstruction, so drops can be understated.

Validation frames only (the locked test set is never read). Output stays in outputs/ (NDA).

    python scripts/heatmap_probe.py outputs/E-07c/<run_dir> +experiment=e07c_lora_explore model=qwen3_5_4b
"""

import argparse
import base64
import dataclasses
import html
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
from hydra import compose, initialize_config_dir
from matplotlib import colormaps
from PIL import Image

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.eval.predict import frames_from_manifest, read_predictions
from streamsense.models.registry import build_adapter

FRAMES = Path("data/extracted/partition_1")
SIDE = 896
CROP_GRID = (3, 3)  # crops of half width/height, stride a quarter frame
OCC_GRID = (6, 4)  # occlusion tiles (cols, rows)


def select(man: pd.DataFrame, scores: dict[str, float], threshold: float) -> list[tuple[str, str]]:
    """(key, group) pairs: detected local defects, confident false alarms, global defects, clean."""
    val = man[man.split == "val"].copy()
    val["score"] = val.key.map(scores)
    has = lambda term: val.terms.apply(lambda ts: term in ts)  # noqa: E731
    picks = []
    for term, n in (("stitching artifacts", 4), ("lens flare", 3), ("glare", 2)):
        rows = val[has(term) & (val.score >= threshold)].nlargest(n, "score")
        picks += [(k, f"local: {term}") for k in rows.key]
    picks += [
        (k, "false alarm (labelled clean)")
        for k in val[~val.quality_issue].nlargest(2, "score").key
    ]
    picks += [
        (k, "global: fog")
        for k in val[has("fog") & (val.score >= threshold)].nlargest(2, "score").key
    ]
    picks += [(k, "clean, low score") for k in val[~val.quality_issue].nsmallest(2, "score").key]
    seen, out = set(), []
    for k, g in picks:
        if k not in seen:
            seen.add(k)
            out.append((k, g))
    return out


def logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return float(np.log(p / (1 - p)))


def resized(im: Image.Image) -> Image.Image:
    s = SIDE / max(im.size)
    return im.resize((round(im.width * s), round(im.height * s)), Image.Resampling.LANCZOS)


def crop_boxes(w: int, h: int) -> list[tuple[int, int, int, int]]:
    cw, ch = w // 2, h // 2
    cols, rows = CROP_GRID
    xs = np.linspace(0, w - cw, cols).astype(int)
    ys = np.linspace(0, h - ch, rows).astype(int)
    return [(x, y, x + cw, y + ch) for y in ys for x in xs]


def occluded(base: Image.Image) -> list[tuple[tuple[int, int, int, int], Image.Image]]:
    w, h = base.size
    cols, rows = OCC_GRID
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (c * w // cols, r * h // rows, (c + 1) * w // cols, (r + 1) * h // rows)
            im = base.copy()
            im.paste((128, 128, 128), box)
            out.append((box, im))
    return out


def overlay(base: Image.Image, heat: np.ndarray, vmax: float) -> str:
    rgba = colormaps["inferno"](np.clip(heat / vmax, 0, 1))
    hm = Image.fromarray((rgba[..., :3] * 255).astype(np.uint8)).resize(base.size)
    mix = Image.blend(base.convert("RGB"), hm, 0.45).resize(
        (448, round(448 * base.height / base.width))
    )
    buf = io.BytesIO()
    mix.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("overrides", nargs="+", help="Hydra overrides used to train the run")
    ap.add_argument("--threshold", type=float, default=0.843)
    ap.add_argument(
        "--out", type=Path, default=Path("outputs/client_report/heatmaps/heatmap_probe.html")
    )
    args = ap.parse_args()

    register_configs()
    with initialize_config_dir(version_base="1.3", config_dir=str(CONFIG_DIR)):
        cfg = compose(config_name="config", overrides=args.overrides)
    man = pd.read_parquet("data/data_manifest.parquet")
    scores = {k: v[1]["quality_issue"] for k, v in read_predictions(args.run, "val").items()}
    picks = select(man, scores, args.threshold)
    frames = {
        f.key: f for f in frames_from_manifest(man[man.key.isin([k for k, _ in picks])], FRAMES)
    }
    assert all(man.set_index("key").loc[k, "split"] == "val" for k, _ in picks)

    adapter = build_adapter(cfg)
    adapter.load(args.run / "adapter")
    images: dict[str, Image.Image] = {}
    adapter._image = lambda f: images[f.key]  # score variants built here, bypassing the disk cache

    cards = []
    for key, group in picks:
        full = Image.open(frames[key].image_path).convert("RGB")
        base = resized(full)
        jobs = [("base", None, base)]
        jobs += [("crop", b, resized(full.crop(b))) for b in crop_boxes(*full.size)]
        jobs += [("occ", b, im) for b, im in occluded(base)]
        recs = []
        for i, (_, _, im) in enumerate(jobs):
            images[f"{key}#{i}"] = im
            recs.append(dataclasses.replace(frames[key], key=f"{key}#{i}", image_sha256=None))
        s = adapter.score(recs)
        p0 = float(s[0])
        crop_heat, cover = np.zeros((full.height, full.width)), np.zeros((full.height, full.width))
        occ_heat = np.zeros((base.height, base.width))
        for (kind, box, _), sc in zip(jobs, s, strict=True):
            if kind == "crop":
                x0, y0, x1, y1 = box
                crop_heat[y0:y1, x0:x1] += sc
                cover[y0:y1, x0:x1] += 1
            elif kind == "occ":
                x0, y0, x1, y1 = box
                occ_heat[y0:y1, x0:x1] = max(logit(p0) - logit(sc), 0.0)
        crop_heat /= np.maximum(cover, 1)
        crops = s[1 : 1 + CROP_GRID[0] * CROP_GRID[1]]
        f = frames[key]
        label = ", ".join(f.terms) or "none"
        cards.append(f"""<figure class="card"><div class="pair">
<div><img src="data:image/jpeg;base64,{overlay(base, crop_heat, 1.0)}"><span>crop scores (max {crops.max():.2f}, min {crops.min():.2f})</span></div>
<div><img src="data:image/jpeg;base64,{overlay(base, occ_heat, max(occ_heat.max(), 0.5))}"><span>occlusion log-odds drop (max {occ_heat.max():.2f})</span></div></div>
<figcaption><b>{html.escape(group)}</b> · full-frame P(issue) {p0:.3f} · label: {html.escape(label)} · <span class="muted">{html.escape(key)}</span></figcaption></figure>""")
        print(
            f"{group:30s} P {p0:.3f} crops {crops.min():.2f}-{crops.max():.2f} occ max {occ_heat.max():.3f}  {key}",
            flush=True,
        )

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StreamSense Heat Map Probe</title><style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e4e3df;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1a1a19;--ink:#f2f1ee;--ink2:#a09f9b;--line:#3a3936;--card:#232322}}}}
body{{background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:24px 16px}}
.card{{margin:0 0 16px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .pair img{{width:100%;display:block;border-radius:4px}}
.pair span{{font-size:12px;color:var(--ink2)}} figcaption{{margin-top:6px;font-size:13px}} .muted{{color:var(--ink2)}}
@media (max-width:640px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><h1>Heat map probe (prototype, E-13)</h1>
<p class="muted">Model: trained adapter at {html.escape(str(args.run))}. Validation frames only. Brighter = more issue-like.
Left: P(issue) of 9 overlapping half-size crops from the full-resolution frame. Right: drop in log-odds of P(issue) when a tile is greyed out (6x4 grid; 1.0 = odds fall by e).</p>
{"".join(cards)}</body></html>"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
