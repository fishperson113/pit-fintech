<#
.SYNOPSIS
  PowerShell companion for Windows hosts where GNU Make is not installed.

.DESCRIPTION
  Keeps the same public task names as the Makefile and calls the same Python CLI.
  The Makefile remains the canonical command contract.
#>
param(
    [Parameter(Position = 0)]
    [string]$Target = "help",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$JupyterPort = 8888,
    [string]$Dataset = "sample",
    [int]$ModelNonfraudSample = 5000,
    [int]$TrainNonfraudSamplePerType = 100000,
    [int]$ModelSeed = 20260727,
    [double]$ModelFixedFpr = 0.01,
    [ValidateSet("E1", "E4")]
    [string]$T4Experiment = "E4",
    [ValidateSet("static", "pit")]
    [string]$T4FeatureSet = "pit",
    [int]$Start = 1,
    [int]$End = 1,
    [string]$RunId = "",
    [ValidateSet("full", "range", "incremental")]
    [string]$BackfillMode = "range",
    [int]$Watermark = 743,
    [string]$LocustHost = "http://127.0.0.1:8000",
    [string]$GoldRoot = "data/lakehouse/paysim1/16910f90577b0d98",
    [int]$GoldPreVersion = 8,
    [int]$GoldPostVersion = 7,
    [int]$GoldLabelsVersion = 7
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    Write-Host (">> {0} {1}" -f $Program, ($Arguments -join " ")) -ForegroundColor Cyan
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Program"
    }
}

switch ($Target) {
    "bootstrap" {
        Invoke-Checked "uv" @("sync", "--frozen", "--group", "dev")
        Invoke-Checked "uv" @("run", "pre-commit", "install")
    }
    "setup" {
        Invoke-Checked "uv" @("sync", "--frozen", "--all-groups")
        Invoke-Checked "uv" @("run", "pre-commit", "install")
    }
    "doctor" { Invoke-Checked "uv" @("run", "pit", "doctor") }
    "lab" {
        Invoke-Checked "uv" @(
            "run", "--group", "dev", "jupyter", "lab",
            "--ip=$HostAddress", "--port=$JupyterPort", "--no-browser"
        )
    }
    "lab-training" {
        Invoke-Checked "uv" @(
            "run", "--group", "dev", "--group", "training", "jupyter", "lab",
            "--ip=$HostAddress", "--port=$JupyterPort", "--no-browser"
        )
    }
    "lab-container" {
        Invoke-Checked "docker" @("compose", "--profile", "lab", "up", "--build", "jupyter")
    }
    "data-sample" { Invoke-Checked "uv" @("run", "pit", "data", "sample") }
    "data-snapshot" {
        Invoke-Checked "uv" @("run", "pit", "data", "snapshot", "--dataset", "paysim")
    }
    "profile" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pit", "data", "profile", "--dataset", $Dataset)
    }
    "build-lakehouse" {
        & $PSCommandPath "test-temporal"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Invoke-Checked "uv" @(
            "run", "pit", "data", "build-lakehouse", "--dataset", $Dataset
        )
    }
    "lakehouse-history" {
        Invoke-Checked "uv" @(
            "run", "pit", "data", "lakehouse-history", "--dataset", $Dataset
        )
    }
    "build-fixture" {
        Invoke-Checked "uv" @("run", "pit", "data", "build-fixture", "--dataset", "paysim")
    }
    "features" {
        Invoke-Checked "uv" @("run", "pit", "features", "show", "--dataset", "paysim")
    }
    "gold" {
        Invoke-Checked "uv" @(
            "run", "pit", "features", "build-gold",
            "--start", "$Start", "--end", "$End"
        )
    }
    "promote-gold" {
        if ([string]::IsNullOrWhiteSpace($RunId)) {
            throw "-RunId is required for promote-gold"
        }
        Invoke-Checked "uv" @(
            "run", "pit", "features", "promote-gold", "--run-id", $RunId
        )
    }
    "test-temporal" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q", "-m", "temporal", "tests/temporal")
    }
    "test-unit" { Invoke-Checked "uv" @("run", "pytest", "-q", "tests/unit") }
    "test-lakehouse" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q", "tests/integration")
    }
    "test-t3-smoke" {
        $env:UV_PROJECT_ENVIRONMENT = ".venv"
        Invoke-Checked "uv" @(
            "run", "--frozen", "--all-groups", "python", "-m", "pytest",
            "tests/integration/test_gold_offline_features.py::test_t3_smoke_backfill_rerun_and_late_arrival_guard",
            "-q"
        )
    }
    "test-t4-dataset" {
        & $PSCommandPath "test-t3-smoke"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $env:UV_PROJECT_ENVIRONMENT = ".venv"
        Invoke-Checked "uv" @(
            "run", "--frozen", "--all-groups", "python", "-m", "pytest",
            "tests/integration/test_gold_offline_features.py::test_t4_gold_to_training_dataset_fixture",
            "-q"
        )
    }
    "train-gold-candidate" {
        $env:UV_PROJECT_ENVIRONMENT = ".venv"
        Invoke-Checked "uv" @(
            "run", "--frozen", "--all-groups", "python", "scripts/run_t4_training.py",
            "--experiment", $T4Experiment, "--feature-set", $T4FeatureSet
        )
    }
    "gold-evaluate" {
        Invoke-Checked "uv" @(
            "run", "--frozen", "--all-groups", "pit", "model", "gold-evaluate",
            "--pre-path", "$GoldRoot/gold/pre_decision_features",
            "--pre-version", "$GoldPreVersion",
            "--post-path", "$GoldRoot/gold/post_event_state_updates",
            "--post-version", "$GoldPostVersion",
            "--labels-path", "$GoldRoot/silver/paysim_labels",
            "--labels-version", "$GoldLabelsVersion"
        )
    }
    "ingest-event-history" {
        Invoke-Checked "uv" @("run", "--frozen", "--all-groups", "pit", "ingest", "event-history")
    }
    "ingest" {
        Invoke-Checked "uv" @("run", "--frozen", "--all-groups", "pit", "ingest", "event-history")
    }
    "test-notebooks" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "--group", "dev", "pit", "notebooks", "verify")
    }
    "model-spike" {
        Invoke-Checked "uv" @(
            "run", "--group", "training", "pit", "model", "spike",
            "--dataset", "paysim",
            "--nonfraud-sample-per-group", "$ModelNonfraudSample",
            "--seed", "$ModelSeed",
            "--fixed-fpr",
            $ModelFixedFpr.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        )
    }
    "train" {
        Invoke-Checked "uv" @(
            "run", "--group", "training", "pit", "model", "train",
            "--dataset", "paysim",
            "--train-nonfraud-sample-per-type", "$TrainNonfraudSamplePerType",
            "--seed", "$ModelSeed",
            "--fixed-fpr",
            $ModelFixedFpr.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        )
    }
    "test" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q")
    }
    "lint" {
        Invoke-Checked "uv" @(
            "run", "ruff", "check", "src", "tests", "feature_repo", "notebooks", "scripts"
        )
        Invoke-Checked "uv" @(
            "run", "ruff", "format", "--check", "src", "tests", "feature_repo", "notebooks", "scripts"
        )
    }
    "format" {
        Invoke-Checked "uv" @(
            "run", "ruff", "check", "--fix", "src", "tests", "feature_repo", "notebooks", "scripts"
        )
        Invoke-Checked "uv" @(
            "run", "ruff", "format", "src", "tests", "feature_repo", "notebooks", "scripts"
        )
    }
    "check" {
        & $PSCommandPath "lint"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $PSCommandPath "test"
    }
    "changelog-check" {
        Invoke-Checked "uv" @("run", "python", "scripts/verify_milestone_changelog.py")
    }
    "lock" { Invoke-Checked "uv" @("lock") }
    "materialize" {
        Invoke-Checked "uv" @("run", "pit", "materialize", "run", "--watermark", "$Watermark")
    }
    "materialize-recover" {
        Invoke-Checked "uv" @(
            "run", "pit", "materialize", "recover",
            "--watermark", "$Watermark",
            "--gold-post-event-version", "$GoldPostVersion",
            "--run-id", $(if ($RunId) { $RunId } else { "" })
        )
    }
    "backfill" {
        Invoke-Checked "uv" @(
            "run", "pit", "backfill", "run",
            "--mode", "$BackfillMode", "--start", "$Start", "--end", "$End",
            "--run-id", $(if ($RunId) { $RunId } else { "" })
        )
    }
    "parity-reconcile" {
        Invoke-Checked "uv" @("run", "pit", "parity", "reconcile")
    }
    "serve" { Invoke-Checked "uv" @("run", "pit", "serving", "up") }
    "serve-otel" { Invoke-Checked "uv" @("run", "pit", "serving", "up", "--otel") }
    "worker" { Invoke-Checked "uv" @("run", "pit", "serving", "worker") }
    "worker-up" { Invoke-Checked "docker" @("compose", "up", "-d", "pit-online-worker") }
    "worker-down" { Invoke-Checked "docker" @("compose", "stop", "pit-online-worker") }
    "tools" {
        Invoke-Checked "uv" @("pip", "install", "locust")
        Invoke-Checked "uv" @(
            "pip", "install",
            "opentelemetry-sdk",
            "opentelemetry-exporter-otlp-proto-http",
            "opentelemetry-instrumentation-fastapi",
            "opentelemetry-instrumentation-logging"
        )
    }
    "locust" {
        Invoke-Checked "uv" @(
            "run", "locust", "-f", "scripts/locust_parity.py", "--host", $LocustHost
        )
    }
    "mlflow-ui" {
        Write-Host "Stopping the container MLflow to free port 5000..."
        Invoke-Checked "docker" @("compose", "stop", "mlflow")
        Invoke-Checked "uv" @(
            "run", "mlflow", "server",
            "--backend-store-uri", "sqlite:///artifacts/mlflow/tracking.db",
            "--host", "127.0.0.1", "--port", "5000"
        )
    }
    "demo" { Invoke-Checked "uv" @("run", "python", "scripts/run_demo_e2e.py") }
    "demo-score" { Invoke-Checked "uv" @("run", "python", "scripts/demo_score.py") }
    "debug-strict-pit" { Invoke-Checked "uv" @("run", "python", "scripts/debug_strict_pit.py") }
    "live-write-matrix" { Invoke-Checked "uv" @("run", "python", "scripts/live_write_path_matrix.py") }
    "locust-write-path" {
        Invoke-Checked "uv" @("run", "locust", "-f", "scripts/locust_write_path.py", "--host", $LocustHost)
    }
    "demo-bad" { Invoke-Checked "uv" @("run", "python", "scripts/demo_bad_request.py") }
    "demo-metrics" { Invoke-Checked "uv" @("run", "python", "scripts/demo_metrics.py") }
    "demo-medallion" { Invoke-Checked "uv" @("run", "python", "scripts/demo_medallion.py") }
    "demo-contract" {
        Invoke-Checked "uv" @("run", "pit", "features", "show", "--dataset", "paysim")
    }
    "demo-history" {
        Invoke-Checked "uv" @("run", "pit", "data", "lakehouse-history", "--dataset", "paysim")
    }
    "demo-watermark" { Invoke-Checked "uv" @("run", "pit", "materialize", "show") }
    "demo-lineage" { Invoke-Checked "uv" @("run", "python", "scripts/demo_lineage.py") }
    "demo-ablation" { Invoke-Checked "uv" @("run", "python", "scripts/demo_ablation.py") }
    "redis-up" { Invoke-Checked "docker" @("compose", "up", "-d", "redis") }
    "redis-down" { Invoke-Checked "docker" @("compose", "stop", "redis") }
    "up-core" { Invoke-Checked "docker" @("compose", "up", "-d", "redis", "mlflow") }
    "status" { Invoke-Checked "docker" @("compose", "ps") }
    "logs" { Invoke-Checked "docker" @("compose", "logs", "--tail=200", "-f", "redis", "mlflow") }
    "down" { Invoke-Checked "docker" @("compose", "down") }
    default {
        Write-Host "PIT Fintech task runner" -ForegroundColor Green
        Write-Host ""
        @(
            @("bootstrap", "install locked dev environment"),
            @("setup", "install every dependency group and hooks in one shot"),
            @("doctor", "inspect local prerequisites without printing secrets"),
            @("lab", "start local JupyterLab"),
            @("lab-training", "start JupyterLab with LightGBM and MLflow"),
            @("lab-container", "start isolated JupyterLab with Compose"),
            @("data-sample", "build and validate temporal fixture"),
            @("data-snapshot", "freeze PaySim identity and write the snapshot manifest"),
            @("profile", "generate the decision-oriented profile for -Dataset"),
            @("build-lakehouse", "build Bronze/Silver Delta tables for -Dataset"),
            @("lakehouse-history", "inspect Delta history for -Dataset"),
            @("build-fixture", "extract and score a small real-Silver PaySim temporal fixture"),
            @("features", "inspect the frozen PaySim FeatureSpec v2"),
            @("gold", "build Gold tables into staging for -Start/-End"),
            @("promote-gold", "promote a staged Gold run from -RunId"),
            @("test-temporal", "run PIT correctness suite"),
            @("test-unit", "run fast unit tests"),
            @("test-lakehouse", "run Delta snapshot and time-travel tests"),
            @("test-t3-smoke", "run T3 backfill seam smoke lane on an isolated fixture"),
            @("test-t4-dataset", "run T4 Gold-to-training dataset fixture lane"),
            @("train-gold-candidate", "train one E1/E4 candidate from committed Gold into local MLflow"),
            @("gold-evaluate", "run Gold-backed E1-E4 with precision/recall and log MLflow runs"),
            @("ingest-event-history", "append unseen serving Event History rows into Bronze landing Delta"),
            @("ingest", "short alias for offline Event History ingestion"),
            @("test-notebooks", "execute Sprint 1 notebooks in memory"),
            @("model-spike", "run the PaySim LightGBM E1-E4 candidate matrix"),
            @("train", "train locked E1/E4 models from exact Silver versions"),
            @("test", "run all tests"),
            @("lint", "check source and notebooks"),
            @("format", "apply source formatting"),
            @("check", "run lint plus tests"),
            @("changelog-check", "require milestone logs for staged implementation changes"),
            @("lock", "refresh uv.lock"),
            @("materialize", "materialize Gold post-event state into the online store up to -Watermark"),
            @("parity-reconcile", "reconcile online aggregates against the offline DuckDB reference (async, ADR-009)"),
            @("serve", "start the FastAPI scoring service against the local Redis online store"),
            @("serve-otel", "start FastAPI scoring with OTel traces/metrics (reads PIT_OTEL_ENDPOINT from .env)"),
            @("worker", "run the pit-online-worker (consume score events, maintain the online store, ADR-010)"),
            @("worker-up", "start the pit-online-worker Docker container"),
            @("worker-down", "stop the pit-online-worker container"),
            @("tools", "install hand-installed dev tools (locust + OpenTelemetry) into the current env"),
            @("locust", "run the Locust web UI + offline/online parity harness against a running service"),
            @("mlflow-ui", "run the MLflow server on the Windows HOST (Artifacts tab works); stops the container first"),
            @("demo", "run the end-to-end demo: Redis -> Gold -> materialize -> serve -> score"),
            @("demo-score", "score one normal and one suspicious transaction against a running API"),
            @("debug-strict-pit", "probe duplicate and out-of-order strict-PIT behavior against a running API"),
            @("live-write-matrix", "exercise advancing writes, retries, gaps and late arrivals against a running API"),
            @("locust-write-path", "run the Locust advancing-write and retry sequence against a running API"),
            @("demo-bad", "prove invalid requests are rejected before scoring (metrics before/after)"),
            @("demo-metrics", "show the in-process /metrics counters"),
            @("demo-medallion", "show grain (version/rows/cols) of the five medallion tables from Delta"),
            @("demo-contract", "show the frozen PaySim FeatureSpec v2"),
            @("demo-history", "show Delta version history for Bronze/Silver"),
            @("demo-watermark", "show the online store materialization watermark"),
            @("demo-lineage", "show MLflow run lineage (required tags/metrics/artifacts) from the local sqlite"),
            @("demo-ablation", "show the E1-E4 ablation table from the spike experiment (same cohort)"),
            @("redis-up", "start the local Redis container"),
            @("redis-down", "stop the local Redis container"),
            @("up-core", "start Redis and MLflow"),
            @("status", "show local service state"),
            @("logs", "follow local service logs"),
            @("down", "stop services without deleting volumes")
        ) | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_[0], $_[1]) }
        Write-Host ""
        Write-Host "Usage: .\make.ps1 <target>" -ForegroundColor DarkGray
    }
}
