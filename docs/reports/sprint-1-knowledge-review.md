# Sprint 1 knowledge review

Status: **unassessed — closed-note interview required**

This review evaluates whether the project author's mental model has caught up with the verified
Sprint 1 implementation. Green tests alone do not pass this review.

## Review protocol

- Answer without opening code, notebooks or reports.
- State assumptions when the question is underspecified.
- The reviewer asks one question at a time and may change one assumption.
- After the closed-note answer, repository evidence may be opened to correct the model.
- Each answer is scored D0–D4 using the
  [Knowledge Defense Checklist](knowledge-defense-checklist.md).

Depth target:

| Level | Observable behavior |
|---|---|
| D0–D1 | terminology or memorized tool role only |
| D2 | explains with a relevant example and distinction |
| D3 | computes an unseen case, predicts failure and designs a test |
| D4 | defends trade-off with code/evidence and adapts when assumptions change |

Sprint 1 passes only when temporal core, leakage, grain/entity/order, oracle and test reasoning
reach at least D3.

## Ten-question interview

| # | Domain | Question | Hard invariant |
|---:|---|---|:---:|
| 1 | Framing | State the three project invariants, then separate what Sprint 1 verified from what remains planned. | yes |
| 2 | Temporal calculation | Given an unseen six-event timeline, calculate canonical order, eligible history, feature vector before score and state after update. | yes |
| 3 | Time semantics | Distinguish event time, created/knowledge time, processing time, cutoff and watermark using one late-arrival example. | yes |
| 4 | Entity/EDA | Defend destination customer as PaySim's entity and explain `AMBER_CORRECTNESS_ONLY` with numbers. | no |
| 5 | Leakage/evaluation | Explain why temporal split cannot repair a full-history leaky feature and why E2 is a positive control. | yes |
| 6 | Oracle/testing | Explain how an oracle can disagree with optimized code, and design tests for `<` changed to `<=`. | yes |
| 7 | Storage | Separate raw, Bronze, Silver and future Gold grains; distinguish DuckDB, Parquet and Delta responsibilities. | no |
| 8 | Reproducibility | Distinguish snapshot ID, Delta version, schema/logical checksum, Git commit and component fingerprint. | no |
| 9 | Model evidence | Interpret why E4 has higher ROC-AUC but lower PR-AUC/recall@FPR without calling PIT incorrect. | no |
| 10 | Unseen mutation | Predict the first failing evidence if score updates state before reading history; propose the minimal regression test. | yes |

## Scoring

| Question | Score D0–D4 | Evidence/feedback | Remediation |
|---:|---:|---|---|
| 1 |  |  |  |
| 2 |  |  |  |
| 3 |  |  |  |
| 4 |  |  |  |
| 5 |  |  |  |
| 6 |  |  |  |
| 7 |  |  |  |
| 8 |  |  |  |
| 9 |  |  |  |
| 10 |  |  |  |

Pass criteria:

- at least 8/10 answers are substantively correct;
- no hard-invariant answer is below D3;
- temporal calculation is correct on two different fixtures;
- the author can present Sprint 1 in five minutes without listing technologies as the story.

## Interview status

```text
Review date:
Reviewer: Codex
Closed-note score: pending
Hard-invariant failures: pending
Core concepts below D3: pending
Strongest concept: pending
Largest mental-model gap: pending
Next remediation: pending
```
