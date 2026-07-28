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
| 1 | D2 | Correctly states no future reads, parity intent, reproducible backfill and rejects a higher-metric model with one future-read violation. Correctly recalls the PaySim decision, Bronze/Silver, the baseline and major Sprint 2 services. Missing evidence mapping; describes parity as stores sharing a contract rather than equal versioned vectors at the same cutoff; omits atomic/idempotent/exact-manifest requirements; overstates MLflow tracking as completed registry/promotion. | Re-answer after question 10 with one evidence item and one Sprint 2 gap per invariant. Explicitly include vector parity, atomicity, idempotency and exact lineage. |
| 2 | D2 | Correctly selects transactions 10 and 11 as eligible history, computes count 2, amount sum 50 and the history flag, and explains the late-created and wrong-entity exclusions. Confuses canonicalization with target-specific eligibility, treats both copies of transaction 11 as removed instead of retaining one canonical row, and does not compute recency or post-score state. | Retest with a second fixture. Separate: canonical rows → eligible source rows → pre-score vector → post-score state. |
| 3 | D1 | Correctly rejects late event L from Q because it was not knowable at Q's decision cutoff and has an intuitive left-of-cutoff model. Event time is incorrectly defined as request arrival; created/knowledge time is confused with queue waiting; processing time is treated as completion; watermark and same-cutoff rebuild behavior are unknown. | Learn the three clocks: business occurrence, record knowability, actual computation. Retest late-event reconstruction and explain why watermark is an aggregate progress signal, not a row-level visibility predicate. |
| 4 | D2 | Correctly rejects origin history because roughly 99% of origin entities are singletons, selects destination as the more viable history view, interprets AMBER as engineering-correctness viability with limited model lift, and limits the claim to PIT feasibility. Only one quantitative result is recalled and the forbidden model claim is stated vaguely as “not always accurate” rather than no consistent recipient-history lift or production-fraud generalization. | Add cross-role/history-coverage or CASH_OUT/TRANSFER evidence; state separately what correctness proves and what model utility/generalization it cannot prove. |
| 5 | D2 | Correctly explains that feature computation and dataset splitting are independent operations, so a full-history value already contaminated by future rows survives any split boundary, and correctly names this a violation of the no-future-read invariant. Initially inverted the positive control by stating that a low E2 score would indicate leakage, then self-corrected after being shown the M016 numbers. Does not separate within-row leakage caused by an aggregation window crossing the row cutoff from across-split leakage that a temporal split does bound, omits the training/serving parity consequence, and drifts into Q4 material on nameOrig singletons. On the changed-assumption case where E2 drops to 0.30 while E3 and E4 hold, diagnoses label sparsity although the assumption already holds data, split and labels constant, and does not apply the control logic that a dead positive control invalidates the leakage-detection claim for that run. Labels leakage as overfitting, which directs remediation toward regularization instead of cutoff auditing. | Re-answer Q5 stating both leakage classes and which one a temporal split can bound; include the training/serving skew consequence rather than only inflated metrics; redo the E2-drop case using control logic; and design one concrete test that fails when E2 is accidentally built with a PIT cutoff applied. |
| 6 | D2 | Explains the semantics of the mutation correctly, showing that changing `<` to `<=` pulls the transaction being scored into its own history window so `count_24h` includes itself, and names this a violation of read-history-before-updating-state. Misidentifies the oracle as an online store and frames oracle-versus-optimized divergence as offline/online parity rather than as two implementations of one specification. Lists only clock-skew causes and omits tie-breaking, RANGE versus ROWS, window boundary conventions, deduplication of conflicting duplicates, null history and float accumulation order. Does not design a test, and misreads why a random fixture is blind to the mutation, attributing it to someone editing the fixture rather than to the absence of any record sitting exactly on the boundary. | Restate the oracle role in one sentence without the word store. List at least four non-clock divergence causes. Build a boundary fixture with one record exactly at t, one strictly before t, one out of window and one same-timestamp different-entity row, assert exact values rather than greater-than-zero, run it differentially against both implementations, and add a mutation test asserting the suite turns red when `<` becomes `<=`. |
| 7 | D2 | Describes the transformation flow across raw, Bronze, Silver and Gold accurately and correctly separates the three tools by capability: DuckDB provides a compute engine without built-in versioning, Delta provides versioning and time travel without its own engine, and Parquet is a columnar storage format. Answers transformation rather than grain, so the single grain change in the pipeline is missed: raw through Silver keep one row per transaction while Gold shifts to one row per entity and cutoff, which is where the cutoff enters the key. Places all three tools in one category, describes Parquet as JSON-like and greppable instead of binary columnar with row groups, column statistics and predicate pushdown, and does not state that Delta is Parquet plus a transaction log rather than an alternative to it. Does not answer what breaks without Delta: atomic commits and pinnable versions, on which the reproducibility of M019 depends. | Restate all four grains in the form one row equals X with the key for each, and mark Gold as the only grain change. Correct the Parquet model to binary columnar with row groups, column statistics and predicate pushdown. State the Delta equals Parquet plus transaction log relationship and name atomicity and version pinning as what is lost without it. |
| 8 | D2 | Identifies four of the five correctly at the functional level: Git commit for code state, Delta version for lakehouse table state and time travel, snapshot ID for the raw version and checksum for the contract. Misdescribes the component fingerprint as a version lock that prevents mismatched components from building or running, rather than as stale-artifact lineage detection, and does not explain why ADR-004 replaced commit equality: a commit changes on any file edit while a clean commit can still carry a Silver table built from older code. Answers the isolation question by restating each definition instead of analysing what a single identifier can reproduce alone, and does not separate the two groups: Git commit plus Delta version as the minimum coordinates for a rerun, and checksum, fingerprint and snapshot ID as drift detectors. | Restate the fingerprint as lineage and stale detection with the ADR-004 rationale. Re-answer the isolation question in the form keeping only X reproduces Y but not Z, and close with the coordinates versus detectors split. |
| 9 | D2 | Correctly reads the higher ROC-AUC of E4 as better overall separation and keeps the main claim inside PIT feasibility rather than declaring PIT incorrect. Does not give the mechanism behind the divergence, namely that FPR divides by the full negative population while precision divides only by predicted positives, so a model can rank well globally yet fill its top-k with negatives. Contradicts the recorded numbers by stating E4 blocks more legitimate transactions when its observed FPR is 0.0039 against 0.0080 for E1. Explains the gap as the model being conservative, which is a threshold property and cannot account for a threshold-free metric such as PR-AUC. Inverts the experiment design by treating E1 static as knowing more than E4, when E1 is a subset of E4, and does not identify the PaySim-specific static signal where fraud drains the origin balance so amount approximately equals oldbalanceOrg. | Explain the divergence through the FPR versus precision denominators. Correct the E1 subset of E4 relation. Give one threshold-free mechanism for the low PR-AUC without the word conservative. State the permitted and forbidden claims as two explicit lists. |
| 10 | D1 | States honestly that the evidence surface is not yet known and offers only that metrics would drift from the E4 baseline, which is the slowest and weakest detector available, without naming the direction of the drift. Does not predict that the first visible breakage is the zero-history case, where the first transaction of a previously unseen entity reports `count_24h` of 1 and `has_history` true so no entity retains an empty history. Does not compute the exact plus-one offset for `count_24h` and plus-amount for the sum, and does not distinguish this single-row contamination from the n-row contamination of the `<` to `<=` mutation. Does not note that the leak inflates metrics rather than degrading them, which is why it survives review. Proposes no regression test; the minimal test is a single record for an unseen entity asserting count 0, sum 0 and `has_history` false before scoring, plus the post-score state containing that record. | Redo Q10 end to end: name the zero-history case as the first failing evidence, compute the plus-one offset, explain why the metric moves upward, and write the single-record regression test with pre-score and post-score assertions separated. |

Pass criteria:

- at least 8/10 answers are substantively correct;
- no hard-invariant answer is below D3;
- temporal calculation is correct on two different fixtures;
- the author can present Sprint 1 in five minutes without listing technologies as the story.

## Interview status

```text
Review date: 2026-07-28
Reviewer: Fisch
Closed-note score: 10/10 assessed, total 18/40 — Q1 D2, Q2 D2, Q3 D1, Q4 D2, Q5 D2, Q6 D2, Q7 D2, Q8 D2, Q9 D2, Q10 D1
Hard-invariant failures: Q1, Q2, Q3, Q5, Q6 and Q10 all below D3; Sprint 1 knowledge gate does not pass
Core concepts below D3: temporal clocks and watermark; canonicalization versus eligibility versus state; positive-control reasoning and leakage taxonomy; oracle role and boundary test design; unseen-mutation prediction and minimal regression test
Strongest concept: consistent D2 across eight questions with no answer below D1; concept-level explanation and design intent are solid
Largest mental-model gap: layers 2 and 3 of the four-layer test — computing an unseen case by hand and designing a test that traps the bug. Q5, Q6 and Q10 fail with the same shape: the rule is understood but cannot be simulated on concrete data. Two model errors need direct correction: the oracle is not a store layer, and E1 is a subset of E4 rather than a superset.
Next remediation: rebuild layers 2 and 3 first — boundary fixture for Q6, zero-history fixture for Q10, control logic for Q5 — then re-test Q1, Q2 and Q3 with evidence and a second temporal fixture
```
