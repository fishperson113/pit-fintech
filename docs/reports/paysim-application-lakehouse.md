# PaySim application Bronze/Silver path

Status: **verified**.

## Outcome

M018 implements the first application-data path behind the frozen FeatureSpec:

```text
PaySim CSV snapshot
  -> bronze.paysim_transactions
  -> silver.paysim_transactions
  -> silver.paysim_labels
```

This is an offline CLI/Make pipeline. It is not part of the synchronous FastAPI serving path and
does not require Docker, Redis, MLflow, Feast, Spark or JupyterLab.

## Physical layout

For snapshot `<sha16>`:

```text
data/lakehouse/paysim1/<sha16>/bronze/paysim_transactions/
data/lakehouse/paysim1/<sha16>/silver/paysim_transactions/
data/lakehouse/paysim1/<sha16>/silver/paysim_labels/

artifacts/datasets/paysim1/<sha16>/lakehouse/lakehouse-manifest.json
artifacts/datasets/paysim1/<sha16>/lakehouse/manifests/<delta-versions>.json
```

Every Delta table is partitioned by `event_day`, derived from PaySim's hourly `step`. It is only
a synthetic layout key and is not interpreted as a real calendar date.

## Layer contract

Bronze keeps all 11 PaySim source fields and adds:

- `source_row_number`;
- `dataset_snapshot_id`;
- `source_file_sha256`;
- `source_record_id`;
- `event_day`.

Silver transactions contain:

```text
source_row_number
step
transaction_type
amount
origin_entity_id
origin_entity_kind
destination_entity_id
destination_entity_kind
dataset_snapshot_id
source_file_sha256
source_record_id
event_day
```

`isFraud`, `isFlaggedFraud` and all four balance fields are absent. Silver labels contain
`source_row_number`, `step`, `isFraud` and the same snapshot/record lineage needed for a
controlled training join.

All transaction types remain in Silver. The later Gold/model path applies the ADR-003 scoring
scope: `CASH_OUT` and `TRANSFER` whose destination kind is `CUSTOMER`.

## Publish gates

The builder blocks publication unless all eight gates pass:

1. source rows equal the raw snapshot manifest;
2. duplicate source-row numbers equal zero;
3. invalid steps equal zero;
4. unknown transaction types equal zero;
5. null, non-finite or negative amounts equal zero;
6. invalid origin/destination identifiers equal zero;
7. invalid fraud labels equal zero;
8. invalid policy outputs equal zero.

After all Delta writes, the builder hashes the raw file again and refuses to publish the
application manifest if its size or SHA-256 changed during execution.

PaySim has no transaction ID, so M018 does not deduplicate equal business values. Each simulator
row is identified by the deterministic CSV `source_row_number`.

## Manifest evidence

The application manifest records:

- dataset snapshot and raw SHA-256;
- pipeline, entity and feature versions;
- canonical FeatureSpec checksum;
- exact Bronze/Silver Delta versions, row counts, schema checksums and ordered-stream checksums;
- all quality-gate observations;
- wall time, throughput, raw/Delta bytes, process RSS before/after, partition count, Arrow batch
  size and target file size;
- code commit, including a `-dirty` suffix when applicable.

RSS before/after is lightweight feasibility evidence, not sampled peak RSS. Successful table
writes are individually ACID; the cross-table manifest is published only after all three pass.
Atomic multi-table backfill and recovery remain Sprint 2 work.

## User verification

Verified on the full frozen PaySim snapshot:

```text
dataset: paysim1:16910f90577b0d98
rows: 6,362,620 per table
Delta versions: bronze v0, silver transactions v0, silver labels v0
quality gates: 8/8 pass
wall time: 56.29s
throughput: 113,030 rows/s
active Delta bytes: 649,248,646
partitions: 31
unit: 30/30 pass
integration fixture: 3/3 pass, no warnings
temporal prerequisite: 23/23 pass
```

The run recorded code commit `115e98d...-dirty`. It verifies application-path feasibility but
must not be relabeled as the final clean model baseline.

Run the small committed fixture lane first:

```powershell
.\make.ps1 test-lakehouse
$LASTEXITCODE
```

Then build the frozen full PaySim snapshot:

```powershell
.\make.ps1 build-lakehouse -Dataset paysim
$LASTEXITCODE
```

Inspect exact Delta commit history without rebuilding:

```powershell
.\make.ps1 lakehouse-history -Dataset paysim
$LASTEXITCODE
```

The agent does not execute these commands under the project working agreement.
