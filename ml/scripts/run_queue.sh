#!/usr/bin/env bash
# Run each line of a queue file as `python scripts/train.py <line>`, one after another.
# Blank lines and lines starting with # are skipped. A failed run is logged and skipped.
#   bash scripts/run_queue.sh queues/explore.txt
set -uo pipefail
queue=${1:?usage: run_queue.sh QUEUE_FILE}
log=logs/queue.log
mkdir -p logs
n=0
while IFS= read -r line || [ -n "$line" ]; do
  [[ -z "${line//[[:space:]]/}" || "$line" == \#* ]] && continue
  n=$((n + 1))
  runlog="logs/$(basename "$queue" .txt)_$(printf %02d $n).log"
  echo "$(date +%T) START $runlog | $line" >> "$log"
  # shellcheck disable=SC2086
  python scripts/train.py $line > "$runlog" 2>&1 < /dev/null
  rc=$?  # capture before any command substitution resets $?
  echo "$(date +%T) END exit=$rc $runlog" >> "$log"
done < "$queue"
echo "$(date +%T) QUEUE DONE $queue" >> "$log"
