# Leakage prototype — synthetic positive control

Status: verified by `notebooks/03_leakage_prototype.ipynb` and the temporal test suite.

At transaction 103, the PIT-correct seven-day amount sum is `60.0`: only transactions 100,
101, and 102 were earlier and knowable. Late transaction 104 had not arrived, transaction 103
itself is excluded, and extreme future transaction 105 is excluded.

The deliberately leaky full-entity aggregate is `1,000,105.0`. It consumes the current event,
the late-arrival record, and the future event. This is a positive control demonstrating that a
plausible aggregate can read unavailable information. It is never a deployable feature path and
no model-quality claim is made from this fixture.

The test `test_future_event_cannot_change_past_vectors` separately proves that adding the
extreme future transaction leaves every prior PIT vector unchanged.
