# ADR-001: Temporal and entity contract

- Status: accepted for the synthetic oracle; provisional for the application dataset
- Date: 2026-07-21

## Decision

The reference cutoff order is `(event_timestamp, transaction_id)` with strict `<` semantics.
Feature windows use an inclusive lower bound. A source must also have
`created_timestamp <= cutoff_created_timestamp`, so a late record is not available before it
arrives. Primary IEEE-CIS rows will set created time to ordered event time; late arrivals are
explicit synthetic fault injections.

Exact duplicate transaction rows are deduplicated. A duplicate ID with conflicting content is
rejected. Online replay and future serving must query/score first, then update post-event state.

The synthetic epoch for IEEE-CIS is provisionally `2017-01-01T00:00:00Z`; it preserves only
relative offsets and has no business-calendar meaning. Ties add deterministic microsecond rank
after sorting by `TransactionID`.

The initial application entity candidate is canonical SHA-256 of
`card1|card2|card3|card5`. Numeric-like categories share one representation, missing values
use `<NULL:v1>`, and the hash payload includes an entity-definition version.

## Deferred decisions

The final entity candidate, maximum application window, split cutoffs, and embargo remain
provisional until IEEE-CIS entity/time EDA. Changing a locked contract requires a new ADR and
version bump; it must never be edited silently after artifacts depend on it.

## Consequences

The oracle is bitemporal enough to test event time and knowledge time, while the primary
dataset remains honest about its synthetic created time. Same-second events are deterministic,
window boundaries are testable, and adding a future event cannot alter a past vector.
