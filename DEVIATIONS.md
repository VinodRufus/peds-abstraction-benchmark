# Deviations log

Any change made after the prereg tags (prereg-peds_abstraction-v1, prereg-rqaf-v1) or the gold
tags (gold-peds_abstraction-v1, gold-rqaf-v1) is recorded here with date, reason, and impact,
and is reported in the papers. An empty log after the run is the goal.

## 2026-09-27 Repository-wide study rename (non-substantive)
Letter slugs replaced by descriptive slugs before any model runs:
A->rqaf, B->peds_abstraction, delay->surgical_delay, dosing->peds_dosing,
rag->ehr_rag, phi->phi_leakage, ctx->long_context. Prompt files, config
filenames, data folders and internal paths renamed to match; flagship
record-id prefix changed from B- to REC- and the corpus regenerated from
the same seed (content identical, ids renamed). No design value in any
prereg config changed. Tags prereg-B-v1 and prereg-A-v1 were re-issued as
prereg-peds_abstraction-v1 and prereg-rqaf-v1 on the rename commit.
Zero API runs and zero gold review existed at the time of the rename.

## 2026-09-28 Pre-gold corpus corrections (peds_abstraction) from AI plausibility screen and AI assessment
Two AI-assisted, literature-informed screening passes over the corpus (researcher
triage, not clinical validation; findings in data/peds_abstraction/screen/) flagged
content and design issues before any gold review and before any model run.
Round 1 (original corpus): C1 early-onset sepsis restricted to <= 72 hours.
C2 distractor pools made age-band aware (no neonatal "last winter" history;
caregivers report, neonates do not "deny"). C3 jaundice records given
gestational/feeding context, age 3-6 days. C4 bronchiolitis albuterol removed per
AAP. C5 AOM amoxicillin corrected to 90 mg/kg/day q12h per AAP. C6 adolescent
depression is active MDD with fluoxetine 10 mg. C7-C12 diagnosis templates
restricted to plausible care settings; ICU asthma is status asthmaticus on
continuous weight-based albuterol; ICU appendicitis is perforated,
post-appendectomy. K1 negation distractors keyed in gold as ruled_out entries and
the schema prompt states pertinent negatives must be output; K2 the dose-basis
distractor keyed as a historical temporal event (rationale: a schema-following
model must never be penalized for preserving negation or temporality). Fixed
history lines keyed as temporal events. Matching tables extended pre-freeze
(fluoxetine synonym, pertinent-negative name variants, units/kg/hour equivalences).
Second-reviewer overlap rule replaced by a seeded stratified draw (2 per
band-setting cell plus a third in 8 cells, seed 20260923) spanning all scenario
positions.
Round 2 (corrected corpus): the diagnoses list is now explicitly defined, in the
schema and prompt, as clinical concept assertions (conditions, symptoms,
allergies) with assertion status; concussion imaging replaced with a completed
symptom assessment per CDC mild-TBI guidance; bronchiolitis routine WBC removed
per AAP; sepsis age tightened to days 1-2; asthma ages 6-11 for reliable peak
flow; neonatal dextrose given as a single bolus; ED otitis media discharges home.
Remaining round-2 comments request documentation depth on deliberately terse
notes and are recorded as the benchmark's stated scope limitation, not as errors.
Narrative paraphrase stays OFF; template dependence will be reported as a
limitation. State at time of change: zero model runs, zero clinical review, gold
not tagged. Corpus regenerated from seed 20260923; digest recorded by PASTE 2.

## 2026-09-28 Gold policy amendment (peds_abstraction): construction validity + post-hoc clinical validation
The pre-specified gold policy (two clinicians reviewing before the freeze) could not be
executed on the study timeline. BEFORE any model run, the policy is amended to:
(1) gold derives deterministically from scenario specifications whose clinical content
was aligned with published pediatric guidance during the documented 2026-09-28
screening and correction rounds; (2) the automated repository audit and the screen
findings are committed as corpus-construction evidence; (3) an independent registered
nurse review of all 160 records (25 percent double-reviewed for Cohen's kappa)
proceeds AFTER the freeze as validation, and the paper will report its agreement
statistics and any disputed records, with a sensitivity analysis excluding disputed
records if any arise; (4) the paper states plainly that no clinician approved the
corpus before freezing, as a limitation. Gold is frozen at this commit.

## 2026-09-29 Operational note (peds_abstraction): provider daily quota during the benchmark
Gemini 3.1 Pro (preview) enforces 250 requests per model per day at the study's billing
tier, so its 3 x 160 + 40 calls span more than one calendar day; the run logs record
every call's timestamp (runs_meta.csv reports the span). Errored calls were stripped and
re-issued with identical prompt, schema, and decoding settings until complete. Two
operational changes, none affecting recorded outputs or design values: run_models.py
stops a model's loop after five consecutive quota errors (resume-safe), and a
supervisor script re-launches when the quota reopens. Recorded successful outputs were
never modified.
