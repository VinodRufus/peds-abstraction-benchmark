#!/bin/bash
# Self-driving Gemini completion. Loops until every Gemini call is done:
#   strip failed lines -> count missing -> if quota open, run (resume-safe)
#   -> else sleep 30 min -> repeat. Log: runs/gemini_autoretry.log
cd "$(dirname "$0")/.." || exit 1
LOG=runs/gemini_autoretry.log
echo "$(date '+%F %T') autoretry started" >> "$LOG"
while true; do
  python scripts/retry_errors.py >/dev/null 2>&1
  missing=$(python scripts/gemini_missing.py 2>/dev/null | tail -1)
  echo "$(date '+%F %T') gemini calls missing: $missing" >> "$LOG"
  if [ "$missing" = "0" ]; then
    echo "$(date '+%F %T') ================ GEMINI COMPLETE ================" >> "$LOG"
    break
  fi
  if python scripts/gemini_probe.py >> "$LOG" 2>&1; then
    echo "$(date '+%F %T') quota open - running" >> "$LOG"
    python src/peds_abstraction/run_models.py >> "$LOG" 2>&1
    python src/peds_abstraction/run_models.py --ablation >> "$LOG" 2>&1
    sleep 60
  else
    echo "$(date '+%F %T') quota closed - sleeping 30 min" >> "$LOG"
    sleep 1800
  fi
done
