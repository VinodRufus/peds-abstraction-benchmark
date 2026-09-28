# AI plausibility screen and AI assessment - findings record

## Round 1 (2026-09-28): AI plausibility screen of the original 160 records
Researcher triage BEFORE any clinical review and BEFORE any model run. Rule-based
text checks plus literature-informed questions; NOT clinical validation. Priorities:
28 urgent, 115 review, 17 routine; 0 literal age/sex/weight mismatches (T1 = 0).
Codes and resolutions:
- C1 (15) early-onset sepsis beyond 72h -> sepsis age restricted (final: days 1-2)
- C2 (15) neonatal "RSV last winter" impossible -> band-aware distractor pools
- C3 (12) jaundice lacked gestation/feeding context -> fixed history line, age 3-6 d
- C4 (16) bronchiolitis routine albuterol (AAP) -> medication removed, supportive care
- C5 (12) AOM amoxicillin 45 mg/kg/day -> 90 mg/kg/day divided q12h (AAP)
- C6 (12) historical MDD + new sertraline ambiguity -> active MDD + fluoxetine 10 mg
- C7 (4) outpatient DKA -> DKA excluded from outpatient
- C8 (9) ICU AOM/concussion/MDD without severity -> excluded from ICU
- C9 (4) ICU asthma without severity -> status asthmaticus + continuous albuterol
- C10 (3) ICU pneumonia on oral amoxicillin -> CAP excluded from ICU
- C11 (3) outpatient appendicitis + IV morphine -> excluded from outpatient
- C12 (4) outpatient neonatal sepsis workup -> excluded from outpatient
- K1 (87) negation lines absent from key -> keyed as ruled_out entries; prompt updated
- K2 (61) dose-basis line absent from key -> keyed as historical temporal event
- Reviewer-2 subset covered only alternating positions -> seeded stratified draw
  (2 per band-setting cell + 3rd in 8 cells, seed 20260923)

## Round 2 (2026-09-28): AI clinical assessment of the corrected corpus
A second AI pass filled assessment columns on the corrected corpus (160 + 40 files;
the 40-record file is verbatim identical to the 160 on shared records - same AI,
NO independence, never usable for inter-reviewer agreement). Verdicts: 18 approve,
142 approve-with-corrections, 0 reject; 0 literal mismatches. Resolutions:
- Key taxonomy objection (dominant, ~100 records): denied allergy/fever typed as
  "diagnoses" -> schema and prompt now define the diagnoses list explicitly as
  clinical concept assertions (conditions, symptoms, allergies) with assertion
  status, i2b2-style. No data change needed.
- Concussion "head CT planned" not indicated (CDC mild TBI) -> replaced with a
  completed concussion symptom assessment.
- Bronchiolitis WBC not routinely indicated (AAP) -> lab removed.
- Sepsis "3-day-old can exceed 72h" -> age restricted to days 1-2.
- Preschool peak flow unreliable (NHLBI) -> asthma age range 6-11 years.
- Dextrose "IV prn" order ambiguity -> single bolus frequency "once".
- AOM admitted from ED without rationale -> ED otitis media discharges home.
- Remaining comments request richer documentation (ICU severity/monitoring detail,
  hour-specific bilirubin rationale, post-op antibiotics). These are DOCUMENTATION
  DEPTH requests on deliberately terse notes, not identified errors (the
  assessment's own method-limit note says missing mention is not evidence care was
  absent). Recorded as the stated scope limitation: this benchmark tests
  abstraction from brief notes, not documentation completeness.

Primary sources cited across both rounds: AAP bronchiolitis 2014; AAP neonatal
sepsis terminology 2023; AAP hyperbilirubinemia 2022; AAP acute otitis media 2013;
FDA fluoxetine labeling; ISPAD DKA guidance; CDC pediatric mild TBI; NHLBI asthma
testing guidance; UCSF neonatal antimicrobial dosing; DailyMed sertraline label.

Screen/assessment workbooks stored in this folder when present.
