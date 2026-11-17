#!/usr/bin/env bash
# Keep GPU workers running on PACE around the clock (until the cloud GPU takes over).
#
#   bash scripts/pace_workers.sh start [N] [--after JOBID ...]   # N rolling chains (default 1; max SS_MAX_WORKERS=1)
#   SS_PARTITIONS=ice-gpu SS_GPUS='gpu-h200|gpu-h100' bash scripts/pace_workers.sh start 2   # fast GPUs
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
ARGS="-A coc -q coc-ice -p ${SS_PARTITIONS:-coc-gpu,ice-gpu,ice-bw-gpu} --gres=gpu:1"  # H100/H200 live in ice-gpu only
# GPU types, fastest first is NOT a preference to Slurm (any match is taken): narrow the list
# to get fast GPUs, e.g. SS_GPUS="gpu-h200|gpu-h100" (full cards; PACE's Blackwells are MIG
# slices, about as fast as an L40S). Successors keep the same list.
ARGS+=" --constraint=${SS_GPUS:-gpu-h200|gpu-h100|gpu-rtxpro-blackwell|A100-80GB|gpu-l40s}"
ARGS+=" --output=$HOME/scratch/streamsense/logs/%x_%j.out"
VENV=${API_VENV:-$HOME/scratch/streamsense/api-venv-gpu}

case "${1:-status}" in
  start)
    shift; n=1; after=(); force=0
    [[ "${1:-}" =~ ^[0-9]+$ ]] && { n=$1; shift; }
    while [ $# -gt 0 ]; do
      case "$1" in --after) after+=("$2"); shift ;; --force) force=1 ;; esac; shift
    done
    # Chains = running workers + fresh starts still waiting (a waiting successor belongs to its
    # running predecessor). Never exceed SS_MAX_WORKERS (default 1) unless --force.
    max=${SS_MAX_WORKERS:-1}
    chains=$(squeue -u "$USER" -n ss-worker -h -o "%T %E" | awk '$1=="RUNNING" || ($1=="PENDING" && $2=="(null)")' | wc -l)
    if [ ${#after[@]} -eq 0 ] && [ $((chains + n)) -gt "$max" ] && [ $force -eq 0 ]; then
      echo "already $chains worker chain(s); max is $max (SS_MAX_WORKERS). Nothing started."
      echo "Replace a chain with --after JOBID, stop with 'stop --now', or override with --force."
      exit 1
    fi
    rm -f "$STOP"
    for i in $(seq "$n"); do
      dep=""; [ -n "${after[$((i-1))]:-}" ] && dep="--dependency=afterany:${after[$((i-1))]}"
      # shellcheck disable=SC2086
      SS_MAX_WORKERS=$max SS_ROLL_ARGS=$ARGS API_VENV=$VENV sbatch $ARGS $dep scripts/worker_gpu.sbatch  # env: --export=ALL
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
