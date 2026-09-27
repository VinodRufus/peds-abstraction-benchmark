"""Identifier and institution audit. Runs over data/ and runs/ before any
release. Must return zero findings; wired into tests/ so pytest fails on hits.

Extend BLOCKLIST with every employer, vendor, and internal system name that
must never appear in study data, and keep it frozen with the prereg tag.
"""
from __future__ import annotations
import os
import hashlib
import re as _re
import re
import sys

# Patterns that suggest real-world identifiers
PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN-like"),
    (re.compile(r"\bMRN[:\s#]*\d{5,}\b", re.I), "MRN-like"),
    (re.compile(r"(?<![\d.])\d{10,}\b"), "long numeric id"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "email address"),
    (re.compile(r"\b\(\d{3}\)\s?\d{3}-\d{4}\b"), "phone number"),
]

# Employer / internal-system perimeter. NEVER present in study data.
# Stored as SHA-256 digests of the lower-cased term (one word or two adjacent words)
# so that the perimeter itself is not published. A file is flagged when any word or
# adjacent word pair in it hashes to one of these digests.
BLOCKLIST_SHA256 = {
    "9cd1fd944147dc3706f20de97b122b7abf5d750e72d3fd58efcb3d0256c6825d",
    "49a70bd1e731c8cd1f77a9b75803bad6453ea9c6bc1cbc5e32a1dd19aa5d31db",
    "de5a1adf4fedcce1533915edc60177547f1057b61b7119fd130e1f7428705f73",
    "c4e96ef720ad19a25112b228d0ed40252968bd8b5f7c0fc7158424f4b1a4fe78",
    "79f43c3b9c23fbdf293bdba80dab38ba194fc1da79187091b3d3760dad840bf8",
    "0addcc1de26ee0f660d21b01c1afdff9f59efb989331fed17334cf8a6dcd8d6b",
    "644d1a899dcac61cf331c8e5fbbec1e7597c72200561ab8a6d652ab189f5b61e",
    "5d11926dd637b275a5dfc5c7586fc3566e11e1f46e6c1cd2a12e1526b6b30b47",
    "67b51232d90eef075f44549519a721f50e31cfe58c93c9c30132291aac942601",
    "bea01bbc7831e7e55a66afcf0bdcf31e96896e065a3ddbd3ce0db5f7e8f99f5e",
}


def _blocklist_hits(low: str):
    words = _re.findall(r"[a-z0-9]+", low)
    hits = []
    for i, w in enumerate(words):
        if hashlib.sha256(w.encode()).hexdigest() in BLOCKLIST_SHA256:
            hits.append(w)
        if i + 1 < len(words):
            pair = w + " " + words[i + 1]
            if hashlib.sha256(pair.encode()).hexdigest() in BLOCKLIST_SHA256:
                hits.append(pair)
    return sorted(set(hits))

# The PHI-leakage study corpus (data/phi_leakage, runs/phi_leakage) intentionally contains
# SYNTHETIC identifier patterns; identifier PATTERNS are skipped there by
# design, documented in the PHI paper. The employer/vendor BLOCKLIST is
# enforced everywhere with no exemptions.
# The RQAF study likewise injects fabricated identifier-shaped strings on
# purpose (the pre-registered privacy_leak error type), so its corpus and
# outputs get the same pattern exemption. The employer/vendor blocklist
# still runs over every path with no exemptions.
PATTERN_EXEMPT_PREFIXES = ("data/phi_leakage", "runs/phi_leakage", "results/phi_leakage",
                           "data/rqaf", "runs/rqaf", "results/rqaf")

SKIP_DIRS = {".git", ".venv", "__pycache__"}
TEXT_EXT = {".txt", ".json", ".jsonl", ".yaml", ".yml", ".md", ".csv"}


def _pattern_exempt(path: str) -> bool:
    norm = path.lstrip("./")
    return any(norm.startswith(pref) for pref in PATTERN_EXEMPT_PREFIXES)


def scan_file(path: str):
    findings = []
    try:
        text = open(path, errors="ignore").read()
    except OSError:
        return findings
    low = text.lower()
    if not _pattern_exempt(path):
        for rx, label in PATTERNS:
            for m in rx.finditer(text):
                findings.append((path, label, m.group(0)[:40]))
    for term in _blocklist_hits(low):
        findings.append((path, "blocklist term", term))
    return findings


def scan(*roots):
    findings = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                    findings.extend(scan_file(os.path.join(dirpath, fn)))
    return findings


if __name__ == "__main__":
    roots = sys.argv[1:] or ["data", "runs", "results"]
    found = scan(*[r for r in roots if os.path.isdir(r)])
    for path, label, snippet in found:
        print(f"AUDIT HIT [{label}] {path}: {snippet}")
    print(f"{len(found)} finding(s).")
    sys.exit(1 if found else 0)
