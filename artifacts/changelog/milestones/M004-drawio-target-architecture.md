# M004 — Editable Draw.io target architecture

- Date: 2026-07-21
- Updated: 2026-07-22 09:51:39 +07:00
- Status: verified

## Scope and acceptance

Create a clear, editable target architecture in Draw.io without generated raster imagery, keep
the existing pitch deck unchanged, and correct the project policy so that model selection is
driven by PaySim EDA rather than pre-locking LightGBM.

## Decisions

- Installed `drawio@drawio` from the `jgraph/drawio-mcp` Codex marketplace. The installed
  integration is a Draw.io plugin/skill and does not require a separate MCP server.
- Authored native draw.io XML because Draw.io Desktop is not installed; the browser editor can
  open and edit the file directly.
- Used a connected high-level spine from event data through PIT feature build, Delta, Feast,
  Redis and FastAPI. EDA, training/MLflow and replay attach only through essential relations.
- Labeled every edge with a concrete action and assigned stable line semantics: blue offline,
  green online, purple model/contract and orange replay/evidence.
- Marked Delta Lakehouse as the offline store, Redis as the online store and Feast as the
  feature-contract/materialization bridge rather than a storage layer.
- Represented technology artwork with replaceable `LOGO` objects. Each placeholder is separate
  from its label and records the intended technology in Draw.io metadata; the model placeholder
  remains undecided until the post-EDA gate.
- PaySim is the EDA-first path. IEEE-CIS and Home Credit remain alternatives behind a dataset
  and temporal-viability ADR gate.
- LightGBM is a candidate baseline only. The model family is frozen after PaySim EDA and then
  held constant across E1–E5.
- The PVLDB paper supplies PIT/reuse/evaluation ideas; it does not prescribe the project dataset
  or model and its reported 3x result is not a reproduction target.

## Files changed

- `docs/architecture/pit-feature-platform-target.drawio`
- `docs/architecture/pit-feature-platform-target.md`
- `docs/architecture/pit-feature-platform-high-level.md`
- `docs/architecture-v1.md`
- `docs/data-access.md`
- `AGENTS.md`
- Project status, cumulative changelog, and this milestone log.

The pitch-deck HTML under `docs/reports/` was not modified.

## Verification evidence

```text
Draw.io Codex plugin: installed at version 1.1.0
Draw.io Desktop: not installed; XML/browser path used
XML parse: pass
Diagram elements: 42
Edges: 13
Duplicate IDs: 0
Edges without mxGeometry: 0
Broken source/target references: 0
XML comments: 0
Browser editor: app.diagrams.net loaded the Target Architecture page
Visual inspection: full architecture renders at 50% zoom; the storage roles and end-to-end flow
  are visible, Redis/FastAPI read and update edges are separated, and model/replay routes do not
  cross after the final routing pass
```

Commands run for the final v3 verification:

```text
PowerShell XML/reference validator: pass; 42 elements, 13 edges, 0 duplicate IDs,
  0 missing geometries, 0 broken references, 0 XML comments
uv run pytest -q: 23 passed in 3.40s
uv run ruff check src tests feature_repo notebooks scripts: pass
uv run ruff format --check src tests feature_repo notebooks scripts: 31 files formatted
git diff --check: pass; only existing LF-to-CRLF working-copy warnings
```

## Refinement — modular pipeline reference

The architecture was redrawn after review against the supplied `pipeline.png` reference. The
revision reduces the connector count, removes cross-region fan-out, and preserves clear empty
space between modules. Official logos are intentionally not embedded so they can be supplied
later without changing the architecture structure.

## Refinement — connected high-level relationship graph

Architecture review found that the modular version was over-separated, too detailed and did not
make cross-section behavior explicit. The final v3 deliberately reintroduces only essential
cross-region relationships and labels each one with its action. It removes internal workflow
nodes, reduces the graph from 87 elements/25 edges to 42 elements/13 edges, and makes the
Delta-to-Feast-to-Redis materialization path the visual backbone.

Deviation from the earlier layout: avoiding every cross-module line made the system boundaries
look unrelated. The final layout prioritizes traceable end-to-end relations while routing model
promotion and serving evidence separately to avoid connector intersections.

## Refinement — copy-ready Mermaid high-level source

- Date/time: 2026-07-22 09:08:56 +07:00
- Status: verified
- Scope: provide one Markdown file containing a concise Mermaid diagram; do not perform further
  Draw.io authoring.
- Acceptance: show the offline-training and online-inference branches, keep storage roles clear,
  use short action labels, retain logo placeholders and remove non-component validation nodes.

Technical decisions:

- Feast is the shared contract node. `historical` leads to offline training and MLflow;
  `materialize` leads to Redis and FastAPI.
- The twelve nodes are grouped into seven explicit boundaries: Dev Env, Data Pipeline, Feature
  Platform, Training Pipeline, Model Registry, Serving Pipeline and Observability.
- JupyterLab pulls features from the Delta offline store and logs experiment runs to MLflow.
- Training and FastAPI emit telemetry to OpenTelemetry; Grafana is the high-level dashboard
  destination. These observability services are target design only and remain unimplemented.
- Event History uses Mermaid `shape: das`, the direct-access-storage/horizontal-cylinder equivalent
  of Draw.io `mxgraph.flowchart.direct_data`; the supplied encoded XML is not embedded in Mermaid.
- The Serving Pipeline begins with a logical Transaction Producer. For the local acceptance path,
  this role is implemented by the deterministic replay driver; the diagram does not imply a
  deployed Kafka producer or real payment gateway.
- Transaction routing follows the prediction cutoff rather than the offline/online classification
  of DuckDB: transaction `t` reaches FastAPI first, reads Redis state strictly before `t`, and is
  appended to Event History and applied to Redis only after its score has been produced.
- Delta and Redis use cylinder shapes for offline and online storage. DuckDB remains a process
  box because its project role is offline compute.
- Replay/Quality Gates is absent because it is a test workflow rather than a high-level runtime
  component.
- JupyterLab remains an experiment node that pulls offline features and logs runs to MLflow.
- Ten `LOGO` strings are intentionally retained as copy-time image placeholders.

Verification command/result:

```text
Mermaid fenced-block structural check: pass
flowchart LR header: pass
Subgraphs: 7
Subgraph/end balance: pass
Nodes: 12
Edges: 16
Duplicate node IDs: 0
Broken edge references: 0
Logo placeholders: 10
Replay/Quality Gates nodes: 0
Cutoff flow: Producer -> FastAPI -> post-score Redis/Event History pass
```

Deviation and known gap: the native Draw.io source remains as a prior editable artifact but is
not modified for this refinement. A local Mermaid renderer CLI is not installed, so verification
covers the copy-ready source structure and syntax rules rather than a generated image. Next step
is to replace `LOGO` text only when official artwork is available.

## Known gaps and next step

- No PNG/SVG/PDF export is generated because Draw.io Desktop is not installed. The `.drawio`
  source remains fully editable and can be exported later from the browser or Desktop app.
- PaySim EDA, the dataset ADR and the model-family decision remain planned. The architecture
  must not be relabeled as architecture-as-built until the corresponding gates pass.
