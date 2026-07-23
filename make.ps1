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
    [string]$Dataset = "sample"
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
    "doctor" { Invoke-Checked "uv" @("run", "pit", "doctor") }
    "lab" {
        Invoke-Checked "uv" @(
            "run", "--group", "dev", "jupyter", "lab",
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
        Invoke-Checked "uv" @("run", "pit", "data", "build-lakehouse", "--dataset", "sample")
    }
    "lakehouse-history" {
        Invoke-Checked "uv" @("run", "pit", "data", "lakehouse-history")
    }
    "test-temporal" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q", "-m", "temporal", "tests/temporal")
    }
    "test-unit" { Invoke-Checked "uv" @("run", "pytest", "-q", "tests/unit") }
    "test-lakehouse" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "pytest", "-q", "tests/integration/test_sample_lakehouse.py")
    }
    "test-notebooks" {
        Invoke-Checked "uv" @("run", "pit", "data", "sample")
        Invoke-Checked "uv" @("run", "--group", "dev", "pit", "notebooks", "verify")
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
    "up-core" { Invoke-Checked "docker" @("compose", "up", "-d", "redis", "mlflow") }
    "status" { Invoke-Checked "docker" @("compose", "ps") }
    "logs" { Invoke-Checked "docker" @("compose", "logs", "--tail=200", "-f", "redis", "mlflow") }
    "down" { Invoke-Checked "docker" @("compose", "down") }
    default {
        Write-Host "PIT Fintech task runner" -ForegroundColor Green
        Write-Host ""
        @(
            @("bootstrap", "install locked dev environment"),
            @("doctor", "inspect local prerequisites without printing secrets"),
            @("lab", "start local JupyterLab"),
            @("lab-container", "start isolated JupyterLab with Compose"),
            @("data-sample", "build and validate temporal fixture"),
            @("data-snapshot", "freeze PaySim identity and write the snapshot manifest"),
            @("profile", "generate the decision-oriented profile for -Dataset"),
            @("build-lakehouse", "build sample Bronze/Silver Delta tables after tests"),
            @("lakehouse-history", "inspect local Delta commit history"),
            @("test-temporal", "run PIT correctness suite"),
            @("test-unit", "run fast unit tests"),
            @("test-lakehouse", "run Delta snapshot and time-travel tests"),
            @("test-notebooks", "execute Sprint 1 notebooks in memory"),
            @("test", "run all tests"),
            @("lint", "check source and notebooks"),
            @("format", "apply source formatting"),
            @("check", "run lint plus tests"),
            @("changelog-check", "require milestone logs for staged implementation changes"),
            @("lock", "refresh uv.lock"),
            @("up-core", "start Redis and MLflow"),
            @("status", "show local service state"),
            @("logs", "follow local service logs"),
            @("down", "stop services without deleting volumes")
        ) | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_[0], $_[1]) }
        Write-Host ""
        Write-Host "Usage: .\make.ps1 <target>" -ForegroundColor DarkGray
    }
}
