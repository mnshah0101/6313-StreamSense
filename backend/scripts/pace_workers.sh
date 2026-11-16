#!/usr/bin/env bash
# Keep GPU workers running on PACE around the clock (until the cloud GPU takes over).
#
#   bash scripts/pace_workers.sh start [N] [--after JOBID ...]   # N rolling chains (default 1)
#   bash scripts/pace_workers.sh status
#   bash scripts/pace_workers.sh stop                             # chains end after the current jobs
#   bash scripts/pace_workers.sh stop --now                       # ...and cancel them now
#
# Each chain is one worker-only Slurm job (scripts/worker_gpu.sbatch) that queues its own
# successor when it starts, so the next GPU is already waiting in line when the 8 h limit hits.
# Needs a Postgres STREAMSENSE_API_DB_URL in .env (workers share the job queue).
set -euo pipefail
cd "$(dirname "$0")/.."
STOP=$HOME/.streamsense/stop-pace-workers
ARGS="-A coc -q coc-ice -p coc-gpu,ice-gpu,ice-bw-gpu --gres=gpu:1"
ARGS+=" --constraint=gpu-h200|gpu-h100|gpu-rtxpro-blackwell|A100-80GB|gpu-l40s"
ARGS+=" --output=$HOME/scratch/streamsense/logs/%x_%j.out"
VENV=${API_VENV:-$HOME/scratch/streamsense/api-venv-gpu}

case "${1:-status}" in
  start)
    shift; n=1; after=()
    [[ "${1:-}" =~ ^[0-9]+$ ]] && { n=$1; shift; }
    while [ $# -gt 0 ]; do [ "$1" = --after ] && after+=("$2") && shift; shift; done
    rm -f "$STOP"
    for i in $(seq "$n"); do
      dep=""; [ -n "${after[$((i-1))]:-}" ] && dep="--dependency=afterany:${after[$((i-1))]}"
      # shellcheck disable=SC2086
      SS_ROLL_ARGS=$ARGS API_VENV=$VENV sbatch $ARGS $dep scripts/worker_gpu.sbatch  # env: --export=ALL
    done ;;
  stop)
    mkdir -p "$(dirname "$STOP")"; touch "$STOP"
    echo "rolling stopped: running workers finish their jobs, no successors are queued"
    if [ "${2:-}" = --now ]; then scancel -u "$USER" -n ss-worker; echo "cancelled ss-worker jobs"; fi ;;
  status)
    [ -e "$STOP" ] && echo "rolling: stopped" || echo "rolling: on"
    squeue -u "$USER" -n ss-worker -o "%.10i %.3t %.10M %.10L %.24R %E" ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
