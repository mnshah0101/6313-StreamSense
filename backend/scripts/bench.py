"""Inference throughput/latency benchmark for the real model backend.

Measures, per batch size: per-frame latency (p50/p95/mean), frames/sec and peak GPU memory for
  score    - P(issue) only (one forward pass; enough to flag frames and raise alerts)
  predict  - score + generated defects/explanation (what the worker runs)
  localize - occlusion heat map for one flagged frame (25 score-only passes)
and checks the client target: < 5 s per sampled frame (one frame every 5 s).

L4 profile: there is no L4 on ICE. --mem-cap-gb 24 caps this process at the L4's memory so
batch sizes that would not fit an L4 fail here too, and an L4 estimate is derived by scaling
the measurement by the L4's memory bandwidth and bf16 compute (a range, labelled estimate).

usage:
  python scripts/bench.py run RUN_DIR PLAYONSPORTS_REPO --out results.json [--mem-cap-gb 24]
  python scripts/bench.py import results.json   # into the service DB (run where the DB lives)
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

# Datasheet numbers: memory bandwidth (GB/s), dense bf16 tensor TFLOPS.
GPU_SPECS = {
    "L4": (300, 121),
    "L40S": (864, 362),
    "A40": (696, 150),
    "A100": (2039, 312),
    "H100": (3350, 989),
    "H200": (4800, 989),
}
TARGET_MS = 5000


def spec_for(name: str) -> tuple[str, tuple[int, int]] | None:
    for key in sorted(GPU_SPECS, key=len, reverse=True):
        if key in name.upper().replace(" ", ""):
            return key, GPU_SPECS[key]
    return None


def l4_estimate(gpu: str, per_frame_ms: float) -> dict | None:
    """Scale a measurement to an L4. Memory-bound work scales with bandwidth, compute-bound
    with bf16 TFLOPS; the true L4 number should fall in between."""
    s = spec_for(gpu)
    if s is None or s[0] == "L4" or "MIG" in gpu:
        return None
    _, (bw, tf) = s
    l4_bw, l4_tf = GPU_SPECS["L4"]
    lo, hi = sorted((per_frame_ms * bw / l4_bw, per_frame_ms * tf / l4_tf))
    return {"l4_ms_low": round(lo, 1), "l4_ms_high": round(hi, 1), "basis": s[0],
            "meets_target_worst_case": hi < TARGET_MS}  # fmt: skip


def run(args: argparse.Namespace) -> None:
    import torch
    from PIL import Image

    from app.inference.streamsense_vlm import StreamSenseBackend

    gpu = torch.cuda.get_device_name(0)
    total_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
    if args.mem_cap_gb and args.mem_cap_gb < total_gb:
        torch.cuda.set_per_process_memory_fraction(args.mem_cap_gb / total_gb)
    images_dir = Path(args.repo) / "data" / "extracted" / "partition_1"
    keys = [
        json.loads(x)["key"]
        for x in (Path(args.run_dir) / "scores" / "val.jsonl").read_text().splitlines()
    ]
    keys = keys[: args.frames]
    images = [Image.open(images_dir / k).convert("RGB") for k in keys]

    b = StreamSenseBackend(Path(args.run_dir), Path(args.repo), None, 1, 0.5)
    t0 = time.perf_counter()
    b.load()
    load_s = time.perf_counter() - t0
    print(
        f"{gpu} ({total_gb:.0f} GB, cap {args.mem_cap_gb} GB) model load {load_s:.1f}s", flush=True
    )
    results = []

    import tempfile

    def fresh_cache() -> None:
        b.adapter.cfg.data.cache_dir = tempfile.mkdtemp(prefix="ss-bench-cache-")
        if hasattr(b.adapter, "_disk"):
            del b.adapter._disk

    def measure(mode: str, bs: int) -> None:
        b.adapter.cfg.model.batch_size = bs
        fn = {"score": lambda ims: b._score_only(ims), "predict": b.predict}[mode]
        # Production frames are always new: start every measurement with an empty frame
        # cache, warm up on frames that are not measured, and include decode + resize.
        fresh_cache()
        measured = images[: len(images) - 16]
        try:
            fn(images[-bs:])  # warm-up (kernels, allocator) on unmeasured frames
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            per = []
            for i in range(0, len(measured) - bs + 1, bs):
                t = time.perf_counter()
                fn(measured[i : i + bs])
                torch.cuda.synchronize()
                per += [1000 * (time.perf_counter() - t) / bs] * bs
        except torch.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"{mode:8s} bs={bs:3d}  OOM under the {args.mem_cap_gb} GB cap", flush=True)
            results.append({"mode": mode, "batch_size": bs, "oom": True})
            return
        add(mode, bs, per, torch.cuda.max_memory_allocated() / 2**20)

    def add(mode: str, bs: int, per: list[float], peak: float) -> None:
        a = np.array(per)
        row = {
            "mode": mode, "batch_size": bs, "n_frames": len(per),
            "p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)),
            "mean_ms": float(a.mean()), "frames_per_sec": float(1000 / a.mean()),
            "peak_gpu_mem_mb": peak, "meets_target": bool(np.percentile(a, 95) < TARGET_MS),
            "estimate": l4_estimate(gpu, float(np.percentile(a, 95))),
        }  # fmt: skip
        results.append(row)
        est = row["estimate"]
        print(f"{mode:8s} bs={bs:3d}  p50 {row['p50_ms']:7.1f}  p95 {row['p95_ms']:7.1f} ms/frame  "
              f"{row['frames_per_sec']:6.2f} fps  peak {peak / 1024:5.1f} GB"
              + (f"  L4~{est['l4_ms_low']:.0f}-{est['l4_ms_high']:.0f} ms" if est else ""), flush=True)  # fmt: skip

    for mode in args.modes.split(","):
        if mode == "localize":
            b.adapter.cfg.model.batch_size = 25
            torch.cuda.reset_peak_memory_stats()
            b.localize(images[0])
            torch.cuda.synchronize()
            per = []
            fresh_cache()
            for im in images[: args.localize_frames]:
                t = time.perf_counter()
                b.localize(im)
                torch.cuda.synchronize()
                per.append(1000 * (time.perf_counter() - t))
            add("localize", 25, per, torch.cuda.max_memory_allocated() / 2**20)
            continue
        for bs in [int(x) for x in args.batch_sizes.split(",")]:
            measure(mode, bs)

    out = {
        "model_id": b.model_version, "hardware": gpu, "total_gb": total_gb,
        "mem_cap_gb": args.mem_cap_gb, "target_profile": args.profile, "load_s": load_s,
        "image_max_side": int(b.cfg.model.image_max_side), "results": results,
        "versions": {"torch": torch.__version__},
    }  # fmt: skip
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}")


def import_results(args: argparse.Namespace) -> None:
    from app import db as dbm
    from app.config import get_settings
    from app.models import BenchRun

    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    dbm.init_engine(args.db_url or s.database_url)
    n = 0
    with dbm.session() as db:
        for path in args.files:
            d = json.loads(Path(path).read_text())
            for r in d["results"]:
                if r.get("oom"):
                    continue
                db.add(BenchRun(
                    model_id=d["model_id"], hardware=d["hardware"], target_profile=d["target_profile"],
                    mem_cap_gb=d["mem_cap_gb"], mode=r["mode"], batch_size=r["batch_size"],
                    n_frames=r["n_frames"], p50_ms=r["p50_ms"], p95_ms=r["p95_ms"], mean_ms=r["mean_ms"],
                    frames_per_sec=r["frames_per_sec"], peak_gpu_mem_mb=r["peak_gpu_mem_mb"],
                    meets_target=r["meets_target"], estimate=r["estimate"],
                    details={"load_s": d["load_s"], "image_max_side": d["image_max_side"], **d["versions"]},
                ))  # fmt: skip
                n += 1
        db.commit()
    print(f"imported {n} benchmark rows")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("run_dir")
    r.add_argument("repo")
    r.add_argument("--out", required=True)
    r.add_argument("--frames", type=int, default=80)  # last 16 are warm-up only
    r.add_argument("--batch-sizes", default="1,4,8,16")
    r.add_argument("--modes", default="score,predict,localize")
    r.add_argument("--localize-frames", type=int, default=5)
    r.add_argument("--mem-cap-gb", type=float, default=24.0)
    r.add_argument("--profile", default="L4 (24 GB cap)")
    i = sub.add_parser("import")
    i.add_argument("files", nargs="+")
    i.add_argument("--db-url")
    a = p.parse_args()
    run(a) if a.cmd == "run" else import_results(a)


if __name__ == "__main__":
    main()
