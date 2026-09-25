"""Model diagnostics: shows the REAL error behind any failed ping, lists the
models your keys can actually reach, and prints the exact ids to paste into
the prereg configs.

Usage: python scripts/diagnose_models.py
"""
from __future__ import annotations
import os
import sys
import traceback

sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()

RESULTS = {}


def section(name):
    print("\n" + "=" * 60)
    print(name)
    print("=" * 60)


def try_ping(label, fn):
    try:
        out = fn()
        print(f"  PING OK -> {out}")
        RESULTS[label] = out
        return True
    except Exception as e:
        print(f"  PING FAILED: {type(e).__name__}: {e}")
        RESULTS[label] = None
        return False


def openai_diag():
    section("OpenAI  (OPENAI_API_KEY)")
    if not os.environ.get("OPENAI_API_KEY"):
        print("  key not set"); RESULTS["openai"] = None; return
    try:
        from openai import OpenAI
        client = OpenAI()
        ids = sorted(m.id for m in client.models.list())
        chat = [i for i in ids if i.startswith(("gpt-", "o"))][:25]
        print("  available (first 25 chat-ish):", ", ".join(chat))
        for cand in ["gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini"]:
            if cand in ids:
                if try_ping("openai", lambda c=cand: _openai_ping(client, c)):
                    return
    except Exception:
        traceback.print_exc()
        RESULTS["openai"] = None


def _openai_ping(client, model):
    r = client.chat.completions.create(model=model, max_tokens=16,
                                       messages=[{"role": "user", "content": "Say ok"}])
    return f"{model} (server reports: {r.model})"


def anthropic_diag():
    section("Anthropic  (ANTHROPIC_API_KEY)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  key not set"); RESULTS["anthropic"] = None; return
    try:
        import anthropic
        print("  SDK version:", anthropic.__version__)
        client = anthropic.Anthropic()
        try:
            ids = [m.id for m in client.models.list(limit=30)]
            print("  available:", ", ".join(ids))
        except Exception as e:
            ids = []
            print("  models.list failed:", type(e).__name__, e)
        candidates = [i for i in ids if "haiku" in i] + \
                     ["claude-haiku-4-5", "claude-haiku-4-5-20251001",
                      "claude-3-5-haiku-latest"] + ids[:3]
        seen = set()
        for cand in [c for c in candidates if not (c in seen or seen.add(c))]:
            def ping(c=cand):
                r = client.messages.create(model=c, max_tokens=16,
                                           messages=[{"role": "user", "content": "Say ok"}])
                return f"{c} (server reports: {r.model})"
            if try_ping("anthropic", ping):
                return
    except Exception:
        traceback.print_exc()
        RESULTS["anthropic"] = None


def google_diag():
    section("Google  (GOOGLE_API_KEY)")
    if not os.environ.get("GOOGLE_API_KEY"):
        print("  key not set"); RESULTS["google"] = None; return
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        avail = []
        try:
            for m in genai.list_models():
                if "generateContent" in getattr(m, "supported_generation_methods", []):
                    avail.append(m.name.replace("models/", ""))
            print("  available:", ", ".join(avail[:25]))
        except Exception as e:
            print("  list_models failed:", type(e).__name__, e)
        flash = [a for a in avail if "flash" in a and "image" not in a and "tts" not in a]
        for cand in flash[:3] + ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]:
            def ping(c=cand):
                model = genai.GenerativeModel(c)
                r = model.generate_content("Say ok",
                                           generation_config={"max_output_tokens": 256})
                return f"{c}"
            if try_ping("google", ping):
                return
    except Exception:
        traceback.print_exc()
        RESULTS["google"] = None


def compat_diag(name, key_env, base_url, candidates):
    section(f"{name}  ({key_env})")
    if not os.environ.get(key_env):
        print("  key not set (optional for the core studies)")
        RESULTS[name.lower()] = None
        return
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=os.environ[key_env])
        ids = []
        try:
            ids = sorted(m.id for m in client.models.list())
            print("  available:", ", ".join(ids[:25]))
        except Exception as e:
            print("  models.list failed:", type(e).__name__, e)
        for cand in [c for c in ids if any(k in c for k in ("mini", "fast", "chat"))][:3] \
                    + candidates + ids[:3]:
            def ping(c=cand):
                r = client.chat.completions.create(model=c, max_tokens=16,
                                                   messages=[{"role": "user", "content": "Say ok"}])
                return f"{c} (server reports: {r.model})"
            if try_ping(name.lower(), ping):
                return
    except Exception:
        traceback.print_exc()
        RESULTS[name.lower()] = None


def main():
    openai_diag()
    anthropic_diag()
    google_diag()
    compat_diag("xAI", "XAI_API_KEY", "https://api.x.ai/v1",
                ["grok-4-fast", "grok-3-mini", "grok-2-latest"])
    compat_diag("DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com",
                ["deepseek-chat"])

    section("SUMMARY - working model ids (paste style: provider:model)")
    fails = 0
    for k, v in RESULTS.items():
        if v:
            print(f"  [ok] {k}: {v.split(' ')[0]}")
        else:
            fails += 1
            print(f"  [!!] {k}: not working")
    print()
    if fails:
        print(f"{fails} provider(s) not working - the real error is printed in its section above.")
    else:
        print("All providers reachable. Use the FULL-SIZE models (not these cheap ping "
              "models) in the prereg configs; run this script's listing to pick them.")


if __name__ == "__main__":
    main()
