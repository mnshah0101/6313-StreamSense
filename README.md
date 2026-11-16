# StreamSense

Team 6313, Parallax: Moksh Shah, Thomas Li and Rui Chang Lyu (Chang). Client: PlayOn.
Course: CX 3803.

StreamSense finds image-quality problems in sports video (blur, lens smear, over- and
under-exposure, miscalibration, stitching, weather). A reviewer uploads a match recording,
the GPU model samples one frame every 5 seconds, and the timeline fills in as results arrive:
which frames have an issue, what kind, how severe, where in the frame (heat map), plus alerts to
confirm or dismiss and feedback that can improve the next model.

## What is in this repository

| Folder | What it is |
| --- | --- |
| [`ml/`](ml/README.md) | Model research and training: data audit and locked game-level split, baselines, vision-language model (VLM) fine-tuning with LoRA, evaluation, experiment log |
| [`backend/`](backend/README.md) | The service: FastAPI app, GPU worker, database, S3 media, accounts and roles |
| [`frontend/`](frontend/README.md) | The review web app (React + TypeScript) |
| [`docs/`](docs/README.md) | The October planning and readiness documents (the design this work started from) |

```
Browser ── web app ── /api ──▶ FastAPI ──▶ database (jobs, results, reviews, users)
   │                              ▲
   └── video upload (direct) ──▶ S3 ◀── GPU worker: decode → score every frame → describe
                                       flagged frames → heat maps → alerts
```

## Results (measured)

**Model:** Qwen3-VL-4B with LoRA adapters on the lower half of the language layers, trained on
849 frames from 106 games; validation 184 frames / 22 games; a **locked test set** of 186 frames /
24 games kept untouched until the final model was chosen (split by game, so no game appears in
two sets).

| | Validation (4 training seeds) | Locked test (selected model, run once) |
| --- | --- | --- |
| Average precision (issue vs. no issue) | 0.894 ± 0.008 (best 0.900) | **0.887** [0.794, 0.952] |
| At the 90%-precision threshold chosen on validation | recall 0.651 | **precision 0.965, recall 0.585** |
| At the default 0.5 threshold | P 0.80 / R 0.80 | P 0.80 / R 0.69 |

The client asked for precision first (a false alarm can take down a healthy stream), so alerts use
a high-precision operating point. Naming the specific defect is harder (class F1 ≈ 0.37 on test;
stitching and miscalibration are rare in the data), and severity is reported as unvalidated
because the labels rate severity per image, not per defect. The full history of ~80 runs (model
families, LoRA styles, resolutions, losses, batch × learning-rate grid, seeds) is in
[`ml/docs/EXPERIMENT_LOG.md`](ml/docs/EXPERIMENT_LOG.md).

**Speed** (NVIDIA L40S capped at 24 GB as a stand-in for the target L4; p95 per frame):

| Work per frame | L40S | L4 (estimated) |
| --- | --- | --- |
| Score only (enough to flag frames and raise alerts) | 0.10 s | ~0.3 s |
| Score + generated defects and explanation, batch 16 | 0.45 s | ~1.3 s |

The app scores every frame and generates descriptions only for flagged ones, so it stays well
inside the client's 5 s/frame budget. A real 22-minute match (269 frames) took about 4.5 minutes
end to end on one GPU. The **Status** page in the app tracks speed, latency, queue time and
per-GPU throughput over time.

**Live demo:** https://streamsense-nine.vercel.app (sign-in required; accounts are created by
an admin). The web app runs on Vercel, the API on AWS, data in Neon Postgres and S3, and GPU
workers on Georgia Tech PACE (H100/H200/Blackwell) share the same job queue.

## What the app does

- **New Analysis:** upload an MP4/MOV (up to 20 GB / 10 h) or an image with the game details. Large
  files go straight from the browser to S3 in parallel parts.
- **Match Analysis:** a severity-colored timeline that fills in while the job runs ("Analyzing ·
  32 / 269 · ~3 min left"), each frame with defects, the model's explanation and a heat map.
- **Alerts:** one per run of bad frames above the alert threshold; confirm or dismiss (final, and
  two reviewers cannot overwrite each other).
- **Feedback:** mark detections correct/incorrect or flag missed issues; export as CSV for a
  curated future training set (never added to training or test data automatically).
- **Model Performance:** real validation and test metrics, calibration, published thresholds.
- **Status:** live GPUs and queue; speed vs. real time, throughput, latency and queue wait over time.
- **Accounts:** viewer / reviewer / admin roles; admins manage users.

Engineering choices worth noting: jobs are claimed by GPU workers with a lease, so a crashed
worker's job resumes where it stopped; results are written batch by batch; every result records
the exact model version and alert-threshold version that produced it; heat maps and versions are
first-class tables; media is private (presigned links, no public bucket); passwords are
scrypt-hashed and sessions live in HttpOnly cookies with CSRF protection.

## Run it

Requirements: Python 3.11, [uv](https://docs.astral.sh/uv/) 0.13+, Node 24.

```sh
make setup      # backend + frontend
make verify     # backend tests and lint, ml lint, frontend type check and build
```

**Local demo without a GPU** (a stand-in "dummy" model flags dark, blown-out or blurry frames):

```sh
cd backend
uv run python -m app.users create --email you@example.com --name You --role admin
uv run uvicorn app.main:app --port 8000          # API + worker, media under backend/var/
cd ../frontend && cp .env.example .env.local      # set STREAMSENSE_API_TARGET=http://127.0.0.1:8000
npm run dev                                       # open http://localhost:5173
```

**Real model on Georgia Tech PACE:** `bash backend/scripts/pace_up.sh` starts a GPU job (API +
worker with the trained checkpoint, S3 media) and serves the web app; see
[backend/README.md](backend/README.md). Training and evaluation commands are in
[ml/README.md](ml/README.md).

## Data and privacy

Client footage, labels, predictions and trained checkpoints are **not** in this repository: they
stay on private storage (PACE scratch, a private S3 bucket). Everything here is code,
configuration, tests on synthetic data, and aggregate evaluation results.

## Status and next steps

Built and running on PACE with the trained model. Not done yet: hosted deployment (Vercel for the
web app; an EC2 L4 GPU worker; managed Postgres), database migrations (Alembic), single sign-on,
benchmarks on a real L4, and validated localization (heat maps are not yet checked against
labeled regions). See [AGENTS.md](AGENTS.md) for how work in this repository is done.
