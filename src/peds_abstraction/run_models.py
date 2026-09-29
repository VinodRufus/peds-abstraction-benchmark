"""Execute the benchmark: models x runs x records, one fixed prompt.

Writes runs/peds_abstraction/{model_tag}/run{k}.jsonl with full call metadata. Parse
failures are recorded, never dropped. Rerunning skips records already
present in the output file (safe resume).

Usage:
    python src/peds_abstraction/run_models.py --config config/prereg_peds_abstraction.yaml
    python src/peds_abstraction/run_models.py --config config/prereg_peds_abstraction.yaml --ablation
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import yaml
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.runner import make_runner, parse_json_strict, append_jsonl, completion_record  # noqa: E402


def model_tag(model_id: str) -> str:
    return model_id.replace(":", "_").replace("/", "_").replace(".", "-")


def load_done(path: str) -> set:
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                done.add(json.loads(line)["record_id"])
            except Exception:
                pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/prereg_peds_abstraction.yaml")
    ap.add_argument("--ablation", action="store_true",
                    help="free-text prompt on the pre-registered subset")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))

    schema = open("schema/abstraction_schema.json").read()
    prompt_name = cfg["prompt"]["ablation"] if a.ablation else cfg["prompt"]["primary"]
    template = open(f"prompts/{prompt_name}.txt").read()
    system, user_t = template.split("USER:", 1)
    system = system.replace("SYSTEM:", "").strip()

    records = sorted(glob.glob("data/peds_abstraction/records/*.txt"))
    if a.ablation:
        # deterministic subset: first N per age band by sorted id
        per_band = cfg["prompt"]["ablation_subset"] // 4
        by_band = {}
        subset = []
        for p in records:
            band = os.path.basename(p).split("-")[1]
            by_band.setdefault(band, [])
            if len(by_band[band]) < per_band:
                by_band[band].append(p)
                subset.append(p)
        records = subset
    if not records:
        sys.exit("No records. Run make_scenarios.py and generate_records.py first, "
                 "and DO NOT run models before gold-peds_abstraction-v1 is tagged.")

    dec = cfg["decoding"]
    runs = cfg["runs_per_record"] if not a.ablation else 1
    suffix = "_ablation" if a.ablation else ""
    for m in cfg["models"]:
        runner = make_runner(m["id"])
        quota_stop = False
        for k in range(1, runs + 1):
            out = f"runs/peds_abstraction/{model_tag(m['id'])}/run{k}{suffix}.jsonl"
            done = load_done(out)
            todo = [p for p in records if os.path.basename(p)[:-4] not in done]
            consecutive_quota = 0
            for p in tqdm(todo, desc=f"{m['id']} run{k}{suffix}"):
                rid = os.path.basename(p)[:-4]
                note = open(p).read()
                user = user_t.strip().replace("{schema}", schema).replace("{note}", note)
                c = runner.complete(system, user, temperature=dec["temperature"],
                                    max_tokens=dec["max_tokens"], seed=dec["seed"])
                parsed, perr = (None, "no output") if c.error else parse_json_strict(c.text)
                append_jsonl(out, completion_record(
                    c, record_id=rid, run=k, prompt_name=prompt_name,
                    parsed=parsed, parse_error=perr))
                # Operational guard (2026-09-29): a provider daily-quota wall
                # rejects every further call; stop this model's loop after 5
                # consecutive quota errors instead of issuing hundreds of
                # rejected requests. Errored lines are stripped and retried
                # later; recorded successful outputs are unaffected.
                if c.error and ("ResourceExhausted" in c.error or "quota" in c.error.lower()
                                or "RateLimit" in c.error or "429" in c.error):
                    consecutive_quota += 1
                    if consecutive_quota >= 5:
                        print(f"\n{m['id']}: quota wall ({consecutive_quota} consecutive); "
                              f"stopping this model, will resume on next launch")
                        quota_stop = True
                        break
                else:
                    consecutive_quota = 0
            if quota_stop:
                break
    print("done. Score with: python src/peds_abstraction/score.py")


if __name__ == "__main__":
    main()
