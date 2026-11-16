# StreamSense API

CRUD + GPU inference service behind the StreamSense review UI (`../frontend`).
Model training lives in `../ml`; this service loads a trained run and serves it.

```
Browser ──▶ UI ──/api──▶ API (FastAPI) ──▶ SQLite/Postgres ◀── GPU worker ──▶ model backend
   │                         │                                   │
   └──── direct uploads ────▶ S3 media ◀──────────────────────────┘
```

- **API**: accounts and roles, games, alerts, reviewer feedback, thresholds, model runs, job
  submission. It never runs the model in a request: creating an analysis returns `202`.
- **Worker**: claims queued jobs with a lease, decode-checks the upload, samples one frame
  every 5 s, scores every frame and generates defects/explanations for flagged ones, writes
  results batch by batch (media writes in parallel), raises alerts, and makes heat maps.
  A crashed worker's lease expires and the next claim resumes from the last committed batch.
- **Backends**: `dummy` (no GPU; pixel statistics, for pipeline tests) and `streamsense`
  (a playonsports run directory: VLM + LoRA adapter).

## Run

```sh
uv sync --extra dev
uv run python -m app.users create --email you@example.com --name You --role admin
uv run uvicorn app.main:app --reload --port 8000     # API + embedded worker, dummy backend
uv run pytest && uv run ruff check . && uv run ruff format --check .
```

The database starts empty. Data lives in `var/` (`STREAMSENSE_API_DATA_DIR`); see
`.env.example`. Interactive docs at `/docs`.

**On PACE:** `bash scripts/pace_up.sh` submits the GPU job (API + worker with the real model,
S3 media), serves the UI on the login node, and prints the `ssh -L` tunnel command;
`bash scripts/pace_up.sh down` stops both.

### Real model on a GPU

```sh
uv sync --extra gpu
export STREAMSENSE_API_BACKEND=streamsense
export STREAMSENSE_API_RUN_DIR=/path/to/6313-StreamSense/ml/outputs/E-07c/<run>
export STREAMSENSE_API_STREAMSENSE_REPO=/path/to/6313-StreamSense/ml
export STREAMSENSE_API_EMBEDDED_WORKER=false
uv run uvicorn app.main:app --port 8000      # API
uv run python -m app.worker                  # worker (GPU host, same DB + media store)
```

The run's own `run_record.json` rebuilds the exact model, prompt and taxonomy it was trained
with, and loading refuses an adapter trained on a different base-model revision.
`scripts/gpu_smoke.sbatch` checks the service reproduces the run's saved val scores
(max |diff| 0.004). On ICE, build the GPU env on scratch, hard-linked from the uv cache:
`UV_PROJECT_ENVIRONMENT=~/scratch/streamsense/api-venv-gpu UV_LINK_MODE=hardlink uv sync --extra gpu`.

## Deployment (shared database: PACE + cloud)

PACE and the online demo share **one Postgres (Neon) and one S3 bucket**, so they see the same
games, results, users and job queue. Any worker that is up claims queued jobs: the PACE GPU job
(H100/H200/Blackwell) processes long videos fast; a small cloud GPU covers the demo.

| Piece | Where | How |
| --- | --- | --- |
| Database | Neon (Postgres 18, us-east-2) | `STREAMSENSE_API_DB_URL` in `.env` (provider URLs are mapped to psycopg). `scripts/sqlite_to_postgres.py` copied the earlier SQLite data. |
| API (no GPU) | EC2 t3.small, HTTPS via Caddy on `<elastic-ip>.sslip.io` | `python scripts/aws_api.py up` (idempotent; IAM role scoped to the bucket prefix), `... update` to pull + restart |
| Web app | Vercel | `frontend/` with `vercel.json` rewriting `/api/:path*` to the API URL, built with `VITE_API_URL=/api` (same origin, so session cookies work) |
| GPU workers | PACE (`scripts/pace_up.sh`) and, when the account has G-instance quota, an on-demand EC2 L4 | set `GPU_INSTANCE_ID` on the API to start it when work is queued and no worker is online; `IDLE_SHUTDOWN_SEC` on that worker stops it when idle |

The S3 bucket's CORS rule must allow `PUT` from each UI origin (`localhost:5173`, the Vercel
domains) and expose `ETag`.

## Accounts and roles

Sign-in with email + password; a session token lives in an HttpOnly, SameSite=Lax cookie
(only its SHA-256 is stored). Passwords are scrypt-hashed. Changes made with a session cookie
must send `X-Requested-With` (CSRF). Failed sign-ins are throttled per email and client.

| Role | Can |
| --- | --- |
| viewer | see everything |
| reviewer | + start analyses and re-runs, confirm/dismiss alerts, add/delete feedback, export CSV, create/edit games |
| admin | + manage users, publish thresholds, import/delete model runs, delete games, request fine-tunes |

Role or active changes, password resets and password changes revoke the user's sessions
immediately. Admins cannot demote or deactivate themselves, and one active admin is always kept.
`python -m app.users {create,list,set-role,activate,deactivate,reset-password}` manages accounts
from the shell (passwords are prompted). `AUTH_MODE=off` makes every request a built-in admin:
tests and local scripts only. For production, an OIDC provider can replace the password step
and keep the same users and roles.

## Uploads and analyses

- **Direct to S3** (default with the S3 backend): `POST /uploads` returns presigned part URLs
  (64 MB parts); the browser PUTs them in parallel, then `POST /uploads/{id}/complete` with the
  ETags and game metadata creates the game and queues the job. The bucket needs a CORS rule
  allowing `PUT` from the UI origin and exposing `ETag`.
- **Through the API**: `POST /analyses` (multipart file + metadata), used with local storage.
- Limits: 20 GB per upload, 10 hours per video (`MAX_UPLOAD_MB`, `MAX_VIDEO_SEC`). The worker
  decode-checks every upload, makes its poster and fails the job with a clear code if invalid.
- Jobs report what they are doing for the UI: `stage` (queued with `queuePosition`,
  downloading with MB progress, checking, analyzing with `etaSec`, finishing) and a heartbeat.

## Scheduling (shortest remaining work first, with preemption)

GPU workers take the queued job with the **least video left to analyze**, not the oldest
(`app/scheduler.py`; SRPT minimises mean turnaround). Sizes come from the probed length, or the
upload size until a worker probes the file. A busy worker checks between batches: if every GPU is
busy and a waiting job has under half its remaining work, it **pauses** (results so far are
committed; it resumes from the next frame, from a local copy of the video) and runs the short job.

Guards: waiting jobs gain priority over time (aging, so long matches never starve); only the
job with the most work left is paused; never one nearly done; at most 3 pauses per job; never
while another GPU is idle. A pause is not a failed attempt. Settings: `STREAMSENSE_API_SCHED_*`,
`_PREEMPT*`, `_MAX_PREEMPTIONS` (`SCHED_POLICY=fifo` turns it off).

## Media storage (local or S3)

The database keeps only keys; files live in the media store:

```
games/<gameId>/video/<random>.mp4           uploaded video or image
games/<gameId>/poster.jpg                   640x360 poster, ~10% in, skips black
games/<gameId>/runs/<jobId>/000123.jpg      sampled frame (+ _thumb.jpg 320x180, _heat.png overlay)
```

Frames are written before their database rows commit, and persist until the game is deleted
(which deletes its objects). The UI reads media only through `/media/...` after a record lookup;
with S3 that is a `307` to a short-lived presigned URL (`private, no-store`; thumbnails and
posters `private, max-age=300`). The S3 store detects the bucket's region so presigned URLs are
valid. Local media under `/tmp`, `/dev/shm` or `$TMPDIR` is refused unless
`ALLOW_EPHEMERAL_MEDIA=true`. Credentials come from the standard AWS chain (instance role or
env keys); the IAM policy needs Get/Put/DeleteObject on `<bucket>/<prefix>*` and ListBucket.

## Throughput and latency

Jobs record batch size, per-frame latency (mean/p50/p95/max), heat-map time, frames/sec and
peak GPU memory. `scripts/bench.py` benchmarks a checkpoint per batch size and mode (`score`,
`predict`, `localize`) with `--mem-cap-gb 24` (L4 memory); results are labelled with the GPU
they ran on plus an L4 estimate range, imported with `scripts/bench.py import`, read at `/bench`.

## Data model

| Table | Purpose |
| --- | --- |
| `users`, `sessions` | Accounts (role, active) and hashed session tokens with expiry. |
| `games` | One stream = one match; its uploaded media and poster. |
| `uploads` | Direct-to-S3 multipart uploads before they become a game + job. |
| `jobs` | An analysis: lease, attempts, failure code, stage/heartbeat, model and threshold version, throughput stats. |
| `frames` | One sampled frame + its prediction: score, defects (`severity_source`), raw model output, model version. |
| `localizations` | Heat maps per frame: method, version, status (`available` / `unsupported` / `failed`), region, PNG key. |
| `model_versions` | The exact model behind every result. |
| `threshold_versions` | Immutable alert policies; alerts keep the version that raised them. |
| `alerts` | One per defect stretch above the threshold; follows the stretch's worst frame while open; review is final and version-checked (`409`). |
| `feedback` | Reviewer labels; exported as CSV, never auto-added to training or test data. |
| `model_runs`, `bench_runs` | Evaluation summaries and inference benchmarks. |

Severity comes from image-level training labels (`severitySource: "image"`), not validated per
defect. Heat maps (occlusion: 25 extra forward passes) are made for spatial defects only: every
flagged frame on short media, the alerted frames on long matches.

## Endpoints

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password`; admin: `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/password` |
| New analysis | `POST /uploads`, `POST /uploads/{id}/complete`, `POST /uploads/{id}/abort`, `POST /analyses` |
| Games | `GET /games?q&sport&status&camera&defect`, `GET/POST/PATCH/DELETE /games/{id}`, `GET /games/{id}/frames?start&end&flagged`, `GET /games/{id}/frames/{i}` |
| Jobs | `GET /jobs?game_id&status`, `GET /jobs/{id}`, `POST /jobs/match` (re-run), `POST /jobs/{id}/cancel` |
| Review | `GET /alerts?status&game_id`, `POST /alerts/{id}/review {decision, expectedVersion}`, `GET/POST /feedback`, `DELETE /feedback/{id}`, `GET /feedback/summary`, `GET /feedback/export.csv`, `POST /feedback/fine-tune` |
| Model | `GET /model`, `GET /runs`, `GET /runs/{id}`, `POST /runs/import`, `DELETE /runs/{id}`, `GET /thresholds/current`, `GET /thresholds`, `POST /thresholds`, `GET /bench` |
| Media | `GET /media/frames/{id}`, `/media/frames/{id}/thumb`, `/media/overlays/{id}`, `/media/games/{id}/poster` |
| Ops | `GET /health` (public) |

JSON is camelCase. Errors are `{"error": {"code", "message"}, "requestId"}` with stable codes
and no internals.

## Not done yet

- Alembic migrations. Until then `add_missing_columns` adds new nullable/defaulted columns at
  startup and refuses anything that needs a real migration.
- Postgres: SQLAlchemy throughout and conditional updates for leases, but only SQLite is tested.
- Database backups to S3; OIDC sign-in; deployment (Dockerfiles, Terraform).
