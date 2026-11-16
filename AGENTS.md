# Instructions for agents working on StreamSense

Read the root `README.md` first, then the README of the part you are changing:
`ml/` (research and training), `backend/` (API, worker, storage, auth), `frontend/` (web app).
`docs/` holds the October planning documents; they explain intent, but the code and the READMEs
describe what is actually built.

## Ground rules

- **Never commit client material.** No footage, frames, label rows, predictions, trained
  checkpoints, private links, credentials or personal contact details. This repository is public.
  `.gitignore` is not enough: review what you stage. Tests use synthetic data only.
- **Keep the test set locked.** Choose models, prompts and thresholds on validation data. The
  locked test set (`ml/splits/LOCKED_TEST.json`, kept out of Git) is evaluated once, on a final
  model, and that run is recorded in `ml/docs/EXPERIMENT_LOG.md`.
- **Never invent results.** Report numbers you measured, with the data split and hardware. A check
  that was not run is not a pass. Severity stays "not validated per defect" until per-defect labels
  exist; a missing heat map never means a frame is clean.
- **Keep model output and human review separate.** Reviews never change what the model said; every
  result keeps its model version and alert-threshold version.
- **Ask before changing scope**: label meanings, data splits, retention, access rules, hosting.

## How the parts fit

- `ml/` trains and evaluates; a training run directory (config + LoRA adapter) is what the backend
  loads (`STREAMSENSE_API_RUN_DIR`). Experiments are Hydra configs; results go to
  `ml/docs/EXPERIMENT_LOG.md`.
- `backend/` is one FastAPI app plus a GPU worker that shares the database and media store. The
  API never runs the model in a request; it queues jobs. Workers claim jobs with a lease and write
  results batch by batch. Roles: viewer < reviewer < admin; every route declares its role.
- `frontend/` talks only to the API through `/api` (session cookie, `X-Requested-With` on changes).
  Keep the design minimal: show what a reviewer acts on; details go in tooltips.

## Checks before proposing a change

```sh
make verify              # backend tests (every API test runs against local and mocked-S3
                         # storage), ruff for backend and ml, frontend type check + build
cd ml && uv run pytest   # ml tests (needs the models extra: torch)
```

Test behaviour that matters: access checks per role, bad inputs, conflicting reviews, worker
crashes and retries, and that results trace back to their model and threshold versions. Avoid
tests that only restate the code.

## Working on PACE

GPU jobs use `-A coc -q coc-ice -p coc-gpu,ice-gpu,ice-bw-gpu` with a GPU-type constraint;
large files (data, outputs, virtual environments, caches) go on scratch, never home (30 GB quota);
never write one SQLite file from two machines at once. `backend/scripts/pace_up.sh` starts and
stops the whole stack.
