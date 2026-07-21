# Synthetic temporal fixture profile

Status: verified by `pit data sample`, temporal tests, and Delta snapshot test.

- Source rows: 8.
- Canonical transactions: 7.
- Entities: 2.
- Exact duplicate rows: 1.
- Same-timestamp tie group: transaction 100/101.
- Late-arrival injection: transaction 104.
- Extreme future event: transaction 105.
- Cold-start/missing-field proxy entity: transaction 200.
- Window boundaries: transaction 102 at exactly one hour and transaction 103 at exactly
  twenty-four hours from the relevant prior transaction.

The expected vectors are hand-calculated in `data/fixtures/expected_features.json`; they are
not generated from the implementation under test.
