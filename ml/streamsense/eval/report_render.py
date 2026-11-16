"""Tables and charts for the client report, from one plain-data dict.

Depends only on pandas and matplotlib: the standalone client notebook inlines this file
verbatim together with the data, so it must not import anything from the project.
"""

import statistics

import pandas as pd

# Reference categorical palette (light), fixed slot order; a model keeps its color everywhere.
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COLORS = {
    "ResNet-18": "#2a78d6",
    "Qwen3.5-0.8B + LoRA": "#eb6834",
    "BRISQUE/NIQE": "#1baf7a",
    "Qwen3.5-0.8B zero-shot": "#eda100",
    "Qwen2.5-VL-3B zero-shot": "#e87ba4",
    "Qwen3.5-4B + LoRA": "#008300",
}


def _stat(values):
    v = [0.0 if x is None else x for x in values]
    if not v:
        return "–"
    if len(v) == 1:
        return f"{v[0]:.3f}"
    return f"{statistics.mean(v):.3f} ± {statistics.stdev(v):.3f}"


def headline(data):
    """Val metrics per model; seed groups show mean ± sd, single runs a game-bootstrap CI."""
    rows = []
    for model in data["models"]:
        ms = [r["metrics"] for r in model["runs"]]
        if len(ms) == 1 and ms[0]["ap_ci"]:
            lo, hi = ms[0]["ap_ci"]
            ap = f"{ms[0]['ap']:.3f} [{lo:.2f}–{hi:.2f}]"
        else:
            ap = _stat([m["ap"] for m in ms])
        rows.append({
            "Model": model["label"],
            "Runs": len(ms),
            "AP (95% CI or ± sd)": ap,
            "ROC-AUC": _stat([m["roc_auc"] for m in ms]),
            "Recall @ P≥0.90": _stat([m["r_p90"] for m in ms]),
            "Recall @ P≥0.95": _stat([m["r_p95"] for m in ms]),
            "Accuracy @ own decision": _stat([m["accuracy"] for m in ms]),
            "Human-labelled AP": _stat([m["user_ap"] for m in ms]),
            "Parse failures": _stat([m["parse_fail"] for m in ms]),
            "Selection": model["note"],
        })  # fmt: skip
    return pd.DataFrame(rows).set_index("Model")


def split_table(data):
    return pd.DataFrame(data["audit"]["splits"]).T.rename_axis("Split")


def class_support(data):
    df = pd.DataFrame(data["audit"]["class_support"]).fillna(0).astype(int)  # class x split
    df["total"] = df.sum(axis=1)
    return df.sort_values("total", ascending=False)


def per_class(data, labels=("ResNet-18", "Qwen3.5-0.8B + LoRA", "Qwen3.5-4B + LoRA")):
    """Crew-class F1 at each model's own decision (first run of a group); AP when scored."""
    cols = {}
    support = {}
    for model in data["models"]:
        if model["label"] not in labels:
            continue
        crew = model["runs"][0]["metrics"]["crew"]
        if not crew:
            continue
        cols[(model["label"], "F1")] = {c: v["f1"] for c, v in crew.items()}
        if any(v["ap"] is not None for v in crew.values()):
            cols[(model["label"], "AP")] = {c: v["ap"] for c, v in crew.items()}
        support = {c: v["support"] for c, v in crew.items()}
    df = pd.DataFrame(cols).round(3).astype(object)
    df = df.where(df.notna(), "–")
    df.insert(0, ("val", "support"), pd.Series(support))
    return df.sort_values(("val", "support"), ascending=False)


def severity(data):
    rows = {}
    for model in data["models"]:
        s = model["runs"][0]["metrics"]["severity"]
        if s:
            rows[model["label"]] = s
    return pd.DataFrame(rows).T.astype({"n": int}).round(3)


def grid(data):
    df = pd.DataFrame(data["grid"])
    if df.empty:
        return df
    df = df.sort_values(["dec_w", "seed", "r_p90", "ap"], ascending=[True, True, False, False])
    df = df.rename(columns={"ap": "val AP", "r_p90": "R@P≥0.90", "r_p95": "R@P≥0.95"})
    return df.reset_index(drop=True).round(3)


def seed_summary(data):
    rows = []
    for (r, lr), g in pd.DataFrame(data["grid"]).groupby(["r", "lr"]):
        g = g[g["seed"].isin(data["followup_seeds"])]
        if len(g) < 2:
            continue
        rows.append({"r": r, "lr": lr, "seeds": sorted(g["seed"]),
                     "val AP": _stat(list(g["ap"])), "R@P≥0.90": _stat(list(g["r_p90"])),
                     "R@P≥0.95": _stat(list(g["r_p95"]))})  # fmt: skip
    return pd.DataFrame(rows)


def reproducibility(data):
    rows = []
    for model in data["models"]:
        for run in model["runs"]:
            rows.append({"Model": model["label"], "Run": run["run"], "Seed": run["seed"],
                         "Manifest hash": run["manifest"], "Locked test hash": run["lock"],
                         "GPU": run["gpu"]})  # fmt: skip
    return pd.DataFrame(rows).set_index(["Model", "Run"])


def style(ax, title, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.set_xlabel(xlabel, color=INK_2)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.tick_params(colors=INK_2, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def representative(model):
    """The run whose AP is closest to its group's mean (not the best seed)."""
    runs = model["runs"]
    mean = statistics.mean(r["metrics"]["ap"] or 0.0 for r in runs)
    return min(runs, key=lambda r: abs((r["metrics"]["ap"] or 0.0) - mean))


def plot_pr(data, ax):
    """Val precision–recall curve per model; for seed groups, the most typical run."""
    for model in data["models"]:
        pr = representative(model)["metrics"]["pr_curve"]
        if pr:
            ax.plot(pr["recall"], pr["precision"], color=COLORS[model["label"]], linewidth=2,
                    label=model["label"], drawstyle="steps-post")  # fmt: skip
    ax.axhline(0.9, color=INK_2, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(0.99, 0.905, "precision 0.90", ha="right", va="bottom", color=INK_2, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0.4, 1.01)
    style(ax, "Precision–recall on validation", "Recall", "Precision")
    ax.legend(frameon=False, fontsize=8, loc="lower left")


def plot_recall_at_precision(data, ax):
    """Recall at the val-fit P≥0.90 threshold: bootstrap CI for single runs, dots per seed."""
    models = data["models"][::-1]
    for y, model in enumerate(models):
        color = COLORS[model["label"]]
        values = [r["metrics"]["r_p90"] or 0.0 for r in model["runs"]]
        ci = model["runs"][0]["metrics"]["op_recall_ci"]
        if len(values) == 1 and ci:
            ax.plot(ci, [y, y], color=color, linewidth=2, alpha=0.5)
        ax.plot(values, [y] * len(values), "o", color=color, markersize=8, alpha=0.9,
                markeredgecolor=SURFACE, markeredgewidth=2)  # fmt: skip
        label = f"{statistics.mean(values):.2f}" + (" (mean)" if len(values) > 1 else "")
        ax.text(max(values) + 0.02, y, label, va="center", color=INK, fontsize=9)
    ax.set_yticks(range(len(models)), [m["label"] for m in models])
    ax.set_xlim(0, 1)
    style(ax, "Recall at precision ≥ 0.90 (val)", "Recall", "")
    ax.grid(axis="y", visible=False)


def plot_support(data, ax):
    total = class_support(data)["total"][::-1]
    ax.barh(total.index, total.values, color=COLORS["ResNet-18"], height=0.6)
    for y, v in enumerate(total.values):
        ax.text(v + 3, y, str(v), va="center", color=INK, fontsize=9)
    style(ax, "Images per crew class (usable set, all splits)", "Images", "")
    ax.grid(axis="y", visible=False)


def plot_training_curve(data, ax):
    """Val AP during LoRA training for the selected config, one line per seed."""
    lora = next((m for m in data["models"] if m["label"] == "Qwen3.5-4B + LoRA"), None) or next(
        (m for m in data["models"] if m["label"] == "Qwen3.5-0.8B + LoRA"), None
    )
    if lora is None:
        return
    for run in lora["runs"]:
        curve = run["curve"]
        if not curve:
            continue
        ax.plot(curve["step"], curve["val_ap"], color=COLORS[lora["label"]], linewidth=2,
                alpha=0.85)  # fmt: skip
        ax.text(curve["step"][-1] + 4, curve["val_ap"][-1], f"seed {run['seed']}",
                color=INK_2, fontsize=8, va="center")  # fmt: skip
    style(ax, f"{lora['label']}: validation AP during training", "Optimizer step (batch 8)",
          "Val AP")  # fmt: skip
