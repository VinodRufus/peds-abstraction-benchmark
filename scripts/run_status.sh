#!/bin/bash
# Progress of the overnight benchmark. Run from the repo root any time.
echo "expected: 4 models x 3 runs x 160 records, then 4 x 1 x 40 ablation"
for f in runs/peds_abstraction/*/run*.jsonl; do
  [ -f "$f" ] || continue
  n=$(wc -l < "$f" | tr -d " ")
  e=$(grep -c '"error": "' "$f" 2>/dev/null || true)
  echo "$n done, $e errors   $f"
done
echo "--- last log lines ---"
tail -n 3 runs/benchmark.log 2>/dev/null
