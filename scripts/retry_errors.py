"""Strip API-error records from run files so a rerun retries ONLY them.

Completed calls and parse failures are kept (parse failures are results).
Use after a quota/billing outage: top up, run this, rerun run_models.py.
"""
import glob, json

total = 0
for path in glob.glob("runs/peds_abstraction/*/run*.jsonl"):
    keep, dropped = [], 0
    for line in open(path):
        r = json.loads(line)
        if r.get("error"):
            dropped += 1
        else:
            keep.append(line)
    if dropped:
        with open(path, "w") as f:
            f.writelines(keep)
        print(f"{path}: removed {dropped} errored calls (will be retried)")
        total += dropped
print(f"{total} errored calls cleared. Rerun run_models.py to retry them.")
