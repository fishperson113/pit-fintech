"""T6 -- one-producer ordered replay and the offline/online parity harness (guide s8; gate G6)."""

from pit_fintech.replay.driver import (
    ReplayDriver,
    ReplayEvent,
    ReplayHandler,
    ReplayRunResult,
    ReplayStepResult,
    load_replay_events,
)
from pit_fintech.replay.parity import (
    CheckpointPlan,
    CheckpointResult,
    MismatchKind,
    ParityFieldResult,
    ParityRunReport,
    RequiredCheckpoint,
    canonicalize_vector,
    classify_mismatch,
    compare_at_checkpoint,
    plan_checkpoints,
    run_parity_harness,
    write_parity_report,
)

__all__ = [
    "CheckpointPlan",
    "CheckpointResult",
    "MismatchKind",
    "ParityFieldResult",
    "ParityRunReport",
    "ReplayDriver",
    "ReplayEvent",
    "ReplayHandler",
    "ReplayRunResult",
    "ReplayStepResult",
    "RequiredCheckpoint",
    "canonicalize_vector",
    "classify_mismatch",
    "compare_at_checkpoint",
    "load_replay_events",
    "plan_checkpoints",
    "run_parity_harness",
    "write_parity_report",
]
