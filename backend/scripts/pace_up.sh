#!/usr/bin/env bash
# Bring StreamSense up on PACE: GPU job (API + worker, real model, S3 media) + the site on the
# login node. Then, from your laptop:
#   ssh -N -L 5173:127.0.0.1:5173 <user>@<this login node>   and open http://localhost:5173
#
#   bash scripts/pace_up.sh          # start (reuses a running GPU job)
#   bash scripts/pace_up.sh down     # stop the site and the GPU job
#   bash scripts/pace_up.sh admin    # create an admin account (only while stopped)
set -euo pipefail
API_REPO=$(cd "$(dirname "$0")/.." && pwd)
UI_REPO=${UI_REPO:-$(cd "$API_REPO/../frontend" && pwd)}
S=${STREAMSENSE_SCRATCH:-$HOME/scratch/streamsense}
DATA=$S/api-data-gpu
TOKEN_FILE=$S/tmp/api_token
NODE=$S/node/bin
LOG=$S/logs

job_up() { squeue -h -u "$USER" -n ss-api-gpu | grep -q .; }
users_cli() {  # account admin against the GPU job's database (only while that job is stopped)
  (cd "$API_REPO" && STREAMSENSE_API_DATA_DIR=$DATA STREAMSENSE_API_MEDIA_BACKEND=local \
    STREAMSENSE_API_ALLOW_EPHEMERAL_MEDIA=true .venv/bin/python -m app.users "$@")
}

if [ "${1:-up}" = admin ]; then
  # SQLite must never be written from two machines at once (login node + GPU node over NFS).
  if job_up; then echo "stop the GPU job first: bash scripts/pace_up.sh down"; exit 1; fi
  shift; read -rp "admin email: " email; read -rp "name: " name
  users_cli create --email "$email" --name "$name" --role admin; exit 0
fi

if [ "${1:-up}" = down ]; then
  pkill -u "$USER" -f "vite preview --host 127.0.0.1 --port 5173" || true
  scancel -u "$USER" -n ss-api-gpu || true
  echo "stopped"; exit 0
fi

mkdir -p "$S/tmp" "$LOG" "$DATA"
[ -s "$TOKEN_FILE" ] || { openssl rand -hex 24 > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"; }

# 1. GPU job (API + embedded worker). Reuse it if it is already queued or running.
if ! job_up; then
  if ! users_cli list | grep -q .; then
    echo "No accounts yet. Create the first admin (while nothing is running):"
    echo "  bash scripts/pace_up.sh admin"
    exit 1
  fi
  rm -f "$DATA/endpoint"
  (cd "$API_REPO" && STREAMSENSE_API_TOKEN=$(cat "$TOKEN_FILE") STREAMSENSE_API_DATA_DIR=$DATA \
    sbatch -A coc -q coc-ice -p coc-gpu,ice-gpu,ice-bw-gpu --gres=gpu:1 \
      --constraint="gpu-l40s|A100-80GB|gpu-h100|gpu-h200|gpu-a40|gpu-rtxpro-blackwell" \
      --output="$LOG/%x_%j.out" --export=ALL,API_VENV="$S/api-venv-gpu" scripts/serve_gpu.sbatch)
fi
echo -n "waiting for the GPU job and model"
until [ -s "$DATA/endpoint" ] && curl -s "http://$(cat "$DATA/endpoint")/health" | grep -q '"loaded":true'; do
  echo -n "."; sleep 10
done
echo " up at $(cat "$DATA/endpoint")"

# 2. Site: production build served with the /api proxy (token added server-side).
printf 'VITE_API_URL=/api\nSTREAMSENSE_API_ENDPOINT_FILE=%s\nSTREAMSENSE_API_TOKEN=%s\n' \
  "$DATA/endpoint" "$(cat "$TOKEN_FILE")" > "$UI_REPO/.env.local"
chmod 600 "$UI_REPO/.env.local"
pkill -u "$USER" -f "vite preview --host 127.0.0.1 --port 5173" || true
cd "$UI_REPO"
export PATH=$NODE:$PATH TMPDIR=$S/tmp npm_config_cache=$S/npm-cache
npm run build >/dev/null
nohup npx vite preview --host 127.0.0.1 --port 5173 --strictPort > "$LOG/ui-preview.log" 2>&1 &
until curl -sf 127.0.0.1:5173/ >/dev/null; do sleep 1; done
echo "site up. From your laptop:"
echo "  ssh -N -L 5173:127.0.0.1:5173 $USER@$(hostname -f)    then open http://localhost:5173"
