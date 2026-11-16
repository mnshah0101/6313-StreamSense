# ruff: noqa: E501  (embedded HTML/CSS template lines)
"""Visual calibration pack: what a model's P(issue) looks like on real validation frames.

Writes one self-contained HTML file (frames embedded) for walking the client through the
model's behaviour at the precision-first operating point. Validation split only; the locked
test set is never read. Client frames are under NDA: the output stays in outputs/ (git-ignored).

    python scripts/build_calibration_pack.py outputs/E-07c/<run_dir>
"""

import argparse
import base64
import html
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from streamsense.eval.predict import read_predictions
from streamsense.eval.thresholds import recall_at_precision

FRAMES = Path("data/extracted/partition_1")
MANIFEST = Path("data/data_manifest.parquet")
PER_SECTION = 6


def thumb(path: Path, width: int = 480) -> str:
    im = Image.open(path).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def reliability_png(y: np.ndarray, s: np.ndarray, threshold: float) -> str:
    edges = np.linspace(0, 1, 6)
    idx = np.clip(np.digitize(s, edges) - 1, 0, 4)
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.plot([0, 1], [0, 1], ls="--", lw=1, color="#a09f9b", zorder=1)
    for b in range(5):
        m = idx == b
        if not m.any():
            continue
        px, py = s[m].mean(), y[m].mean()
        ax.scatter(px, py, s=40 + 6 * m.sum(), color="#2a78d6", edgecolor="#fcfcfb", lw=2, zorder=3)
        ax.annotate(f"{py:.0%}\nn={m.sum()}", (px, py), textcoords="offset points",
                    xytext=(0, -30 if py > 0.5 else 14), ha="center", fontsize=8,
                    color="#2f2e2c")  # fmt: skip
    ax.axvline(threshold, color="#0b0b0b", lw=1)
    ax.text(
        threshold - 0.01,
        0.03,
        f"alert threshold\n{threshold:.3f}",
        ha="right",
        fontsize=8,
        color="#0b0b0b",
    )
    ax.set(
        xlim=(0, 1),
        ylim=(0, 1.02),
        xlabel="Model's P(issue), binned",
        ylabel="Share of frames with a real issue",
    )
    ax.set_title("When the model says X%, how often is there really an issue?\n"
                 "(dashed line = perfectly calibrated; dot size = number of frames)",
                 loc="left", fontsize=10)  # fmt: skip
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#c9c8c4")
    ax.tick_params(colors="#52514e", labelsize=8)
    ax.grid(color="#e4e3df", lw=0.6)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def card(row: pd.Series, threshold: float) -> str:
    alert = row.score >= threshold
    truth = bool(row.quality_issue)
    verdict = {(True, True): "Correct alert", (False, False): "Correctly quiet",
               (True, False): "False alarm", (False, True): "Missed issue"}[(alert, truth)]  # fmt: skip
    kind = "ok" if alert == truth else "bad"
    terms = ", ".join(row.terms) if truth and len(row.terms) else "none"
    sev = f", severity {int(row.severity)}" if truth and pd.notna(row.severity) else ""
    said = ", ".join(i["raw_term"] for i in row.pred_issues) or "no issue"
    return f"""<figure class="card {kind}">
  <img src="data:image/jpeg;base64,{thumb(FRAMES / row.image_path)}" alt="{html.escape(row.key)}" loading="lazy">
  <figcaption>
    <div class="row"><span class="score">P(issue) {row.score:.3f}</span><span class="verdict">{verdict}</span></div>
    <div><b>Label:</b> {html.escape(terms)}{sev} <span class="muted">({html.escape(row.source)})</span></div>
    <div><b>Model said:</b> {html.escape(said)}</div>
    <div class="muted key">{html.escape(row.key)}</div>
  </figcaption>
</figure>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--label", default="Qwen3.5-4B + LoRA")
    ap.add_argument(
        "--out", type=Path, default=Path("outputs/client_report/calibration/calibration_pack.html")
    )
    args = ap.parse_args()

    man = pd.read_parquet(MANIFEST).set_index("key")
    preds = read_predictions(args.run, "val")
    rows = []
    for key, (pred, scores) in preds.items():
        m = man.loc[key]
        assert m.split == "val", key  # never the locked test set
        rows.append({"key": key, "score": scores["quality_issue"], "pred_issues": pred["issues"],
                     **{c: m[c] for c in ("quality_issue", "terms", "severity", "source", "image_path")}})  # fmt: skip
    df = pd.DataFrame(rows)
    y, s = df.quality_issue.to_numpy(bool), df.score.to_numpy(float)
    op = recall_at_precision(y, s, 0.9)
    t = op.threshold
    alert = s >= t
    tp, fp = int((alert & y).sum()), int((alert & ~y).sum())
    fn, tn = int((~alert & y).sum()), int((~alert & ~y).sum())

    caught = df[df.quality_issue].assign(caught=lambda d: d.score >= t)
    by_sev = caught.groupby("severity").caught.agg(["count", "sum"])
    sev_rows = "".join(
        f"<tr><td>{int(sv)}</td><td>{int(r['count'])}</td><td>{int(r['sum'])}</td>"
        f"<td>{r['sum'] / r['count']:.0%}</td></tr>"
        for sv, r in by_sev.sort_index(ascending=False).iterrows()
    )
    pos, neg = df[df.quality_issue], df[~df.quality_issue]
    sections = [
        ("Confident alerts", "Highest-scoring frames that really have an issue.",
         pos.nlargest(PER_SECTION, "score")),
        ("Confidently quiet", "Lowest-scoring frames that really are clean.",
         neg.nsmallest(PER_SECTION, "score")),
        ("Borderline (P 0.35-0.65)", "Where the model is unsure; a sample of both kinds.",
         df[(df.score > 0.35) & (df.score < 0.65)].sample(
             min(PER_SECTION, int(((df.score > 0.35) & (df.score < 0.65)).sum())), random_state=0)
         .sort_values("score", ascending=False)),
        ("Confident false alarms", "Clean-labelled frames the model scored highest. Label noise or real misses?",
         neg.nlargest(PER_SECTION, "score")),
        ("Missed issues", "Issue-labelled frames the model scored lowest.",
         pos.nsmallest(PER_SECTION, "score")),
    ]  # fmt: skip
    body = "\n".join(
        f'<section><h2>{html.escape(h)}</h2><p class="muted">{html.escape(d)}</p><div class="grid">'
        + "".join(card(r, t) for _, r in part.iterrows()) + "</div></section>"
        for h, d, part in sections
    )  # fmt: skip
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StreamSense Calibration Frames</title>
<style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e4e3df;--ok:#1d7a4f;--bad:#b3261e;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1a1a19;--ink:#f2f1ee;--ink2:#a09f9b;--line:#3a3936;--ok:#5cc28c;--bad:#f08a80;--card:#232322}}}}
body{{background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:32px 0 2px}} .muted{{color:var(--ink2)}}
.stats{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}} .stat{{border:1px solid var(--line);border-radius:8px;padding:8px 12px;background:var(--card)}}
.stat b{{display:block;font-size:20px}} .chart{{max-width:100%;height:auto;border:1px solid var(--line);border-radius:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:8px}}
.card{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}}
.card img{{width:100%;display:block}} figcaption{{padding:8px 10px;font-size:13px}}
.row{{display:flex;justify-content:space-between;margin-bottom:4px}} .score{{font-weight:600}}
.ok .verdict{{color:var(--ok);font-weight:600}} .bad .verdict{{color:var(--bad);font-weight:600}}
.ok .verdict::before{{content:"✓ "}} .bad .verdict::before{{content:"✗ "}} .key{{font-size:11px;margin-top:4px}}
table.sev{{border-collapse:collapse;margin-top:8px}} .sev th,.sev td{{border-bottom:1px solid var(--line);padding:4px 14px;text-align:right}}
</style></head><body>
<h1>StreamSense: what the model's scores look like</h1>
<p class="muted">{html.escape(args.label)} on the validation split (184 frames, 22 games; not used for training).
Alerts fire at P(issue) &ge; {t:.3f}, the lowest threshold that keeps precision &ge; 90%. Preliminary, Dataset V1.</p>
<div class="stats">
<div class="stat"><b>{tp}</b>correct alerts</div><div class="stat"><b>{fp}</b>false alarms</div>
<div class="stat"><b>{fn}</b>missed issues</div><div class="stat"><b>{tn}</b>correctly quiet</div>
<div class="stat"><b>{op.precision:.0%}</b>precision</div><div class="stat"><b>{op.recall:.0%}</b>issues caught</div></div>
<h2>Issues caught at the alert threshold, by labelled severity</h2>
<table class="sev"><tr><th>Severity</th><th>Issue frames</th><th>Caught</th><th>Share caught</th></tr>{sev_rows}</table>
<p class="muted">Severity is labelled once per frame (1 = mild, 5 = severe). Small counts; validation only.</p>
<h2>Calibration</h2>
<img class="chart" src="data:image/png;base64,{reliability_png(y.astype(float), s, t)}" alt="Reliability chart">
{body}
</body></html>"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print(
        f"{args.out}  threshold {t:.3f}  TP {tp} FP {fp} FN {fn} TN {tn}  ({args.out.stat().st_size / 1e6:.1f} MB)"
    )


if __name__ == "__main__":
    main()
