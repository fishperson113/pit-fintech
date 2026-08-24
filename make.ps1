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
    [int]$JupyterPort = 8888,
    [string]$Dataset = "sample",
    [int]$TrainNonfraudSamplePerType = 100000,
    [int]$ModelSeed = 20260727,
    [double]$ModelFixedFpr = 0.01,
    [int]$Start = 1,
    [int]$End = 1,
    [string]$RunId = "",
    [ValidateSet("full", "range", "incremental")]
    [string]$BackfillMode = "range",
    [int]$Watermark = 743
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
    "lock" { Invoke-Checked "uv" @("lock") }
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
    "data-sample" { Invoke-Checked "uv" @("run", "pit", "data", "sample") }
    "build-lakehouse" {
        & $PSCommandPath "test-temporal"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Invoke-Checked "uv" @(
            "run", "pit", "data", "build-lakehouse", "--dataset", $Dataset
        )
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
    "serve" { Invoke-Checked "uv" @("run", "pit", "serving", "up") }
    "worker" { Invoke-Checked "uv" @("run", "pit", "serving", "worker") }
    "materialize" {
        Invoke-Checked "uv" @("run", "pit", "materialize", "run", "--watermark", "$Watermark")
    }
    "backfill" {
        Invoke-Checked "uv" @(
            "run", "pit", "backfill", "run",
            "--mode", "$BackfillMode", "--start", "$Start", "--end", "$End"
        )
    }
    "mlflow-ui" {
        Invoke-Checked "uv" @(
            "run", "mlflow", "server",
            "--backend-store-uri", "sqlite:///artifacts/mlflow/tracking.db",
            "--host", "127.0.0.1", "--port", "5000"
        )
    }
    "demo-score" { Invoke-Checked "uv" @("run", "python", "scripts/demo_score.py") }
    "up-core" { Invoke-Checked "docker" @("compose", "up", "-d", "redis", "pit-online-worker") }
    "status" { Invoke-Checked "docker" @("compose", "ps") }
    "logs" { Invoke-Checked "docker" @("compose", "logs", "--tail=200", "-f", "redis", "pit-online-worker") }
    "down" { Invoke-Checked "docker" @("compose", "down") }
    "test-temporal" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q", "-m", "temporal", "tests/temporal")
    }
    "test-unit" { Invoke-Checked "uv" @("run", "pytest", "-q", "tests/unit") }
    "test" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q")
    }
    "lint" {
        Invoke-Checked "uv" @(
            "run", "ruff", "check", "src", "tests", "notebooks", "scripts"
        )
        Invoke-Checked "uv" @(
            "run", "ruff", "format", "--check", "src", "tests", "notebooks", "scripts"
        )
    }
    "format" {
        Invoke-Checked "uv" @(
            "run", "ruff", "check", "--fix", "src", "tests", "notebooks", "scripts"
        )
        Invoke-Checked "uv" @(
            "run", "ruff", "format", "src", "tests", "notebooks", "scripts"
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
    default {
        Write-Host "PIT Fintech task runner" -ForegroundColor Green
        Write-Host ""
        @(
            @("bootstrap", "install locked dev environment"),
            @("setup", "install every dependency group and hooks in one shot"),
            @("doctor", "inspect local prerequisites without printing secrets"),
            @("lock", "refresh uv.lock"),
            @("lab", "start local JupyterLab"),
            @("lab-training", "start JupyterLab with the dev + training dependency groups"),
            @("data-sample", "build and validate temporal fixture"),
            @("build-lakehouse", "build Bronze/Silver Delta tables for -Dataset"),
            @("gold", "build Gold tables into staging for -Start/-End"),
            @("promote-gold", "promote a staged Gold run from -RunId"),
            @("train", "train locked E1/E4 models from exact Silver versions"),
            @("serve", "start the FastAPI scoring service against the local Redis online store"),
            @("worker", "run the pit-online-worker (consume score events, maintain the online store, ADR-010)"),
            @("materialize", "materialize Gold post-event state into the online store up to -Watermark"),
            @("backfill", "run atomic/idempotent Gold backfill with -BackfillMode/-Start/-End"),
            @("mlflow-ui", "run the MLflow server on the Windows HOST (Artifacts tab works)"),
            @("demo-score", "score one normal and one suspicious transaction against a running API"),
            @("up-core", "start Redis and the pit-online-worker"),
            @("status", "show local service state"),
            @("logs", "follow local service logs"),
            @("down", "stop services without deleting volumes"),
            @("test-temporal", "run PIT correctness suite"),
            @("test-unit", "run fast unit tests"),
            @("test", "run all tests"),
            @("lint", "check source and notebooks"),
            @("format", "apply source formatting"),
            @("check", "run lint plus tests"),
            @("changelog-check", "require milestone logs for staged implementation changes")
        ) | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_[0], $_[1]) }
        Write-Host ""
        Write-Host "Usage: .\make.ps1 <target>" -ForegroundColor DarkGray
    }
}
