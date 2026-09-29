"""Count Gemini benchmark calls still missing (good lines vs expected)."""
import glob, json, os, sys
gold = sorted(os.path.basename(p)[:-5] for p in glob.glob("data/peds_abstraction/gold/*.json"))
by_band = {}
for r in gold:
    b = r.split("-")[1]
    by_band.setdefault(b, [])
    if len(by_band[b]) < 10:
        by_band[b].append(r)
abl = {r for v in by_band.values() for r in v}
d = glob.glob("runs/peds_abstraction/google_*/")
if not d:
    print(999); sys.exit()
d = d[0]
def good(path):
    if not os.path.exists(path):
        return set()
    s = set()
    for line in open(path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("error"):
            s.add(r["record_id"])
    return s
missing = 0
for k in (1, 2, 3):
    missing += len(set(gold) - good(f"{d}run{k}.jsonl"))
missing += len(abl - good(f"{d}run1_ablation.jsonl"))
print(missing)
