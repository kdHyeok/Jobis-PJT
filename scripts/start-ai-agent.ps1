param(
    [int]$Port = 8400,
    [switch]$Install,
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$aiRoot = Join-Path $projectRoot "AI"
$python = Join-Path $aiRoot ".venv\Scripts\python.exe"

function Import-JobissEnvFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }

    foreach ($line in Get-Content -LiteralPath $Path -Encoding utf8) {
        if ($line -notmatch '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            continue
        }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
    Write-Host "Loaded AI environment settings from $Path"
    return $true
}

if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $envCandidates = @(
        (Join-Path $aiRoot ".env"),
        (Join-Path $projectRoot ".env"),
        (Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\env")
    )
    $EnvFile = $envCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
    [void](Import-JobissEnvFile $EnvFile)
}
else {
    Write-Warning "No AI env file was found. Use -EnvFile <path> or create AI\.env."
}

# 팀 표준 프로바이더는 Anthropic API 직접 호출이다(D140) — .env 의 LLM_PROVIDER 를
# 존중하고, 비어 있을 때만 anthropic 으로 기본값을 깐다. (종전에는 codex_cli 를 강제해
# .env 에 anthropic 을 넣어도 무시됐다 — 실측 2026-08-07: codex 실행 파일이 없는 PC 에서
# 전 LLM 호출이 WinError 2 로 죽었다.)
if ([string]::IsNullOrWhiteSpace($env:LLM_PROVIDER)) {
    $env:LLM_PROVIDER = "anthropic"
}
if ([string]::IsNullOrWhiteSpace($env:CODEX_CLI)) {
    $env:CODEX_CLI = "codex"
}
if ([string]::IsNullOrWhiteSpace($env:CODEX_MODEL)) {
    $env:CODEX_MODEL = "gpt-5.6-luna"
}
if ([string]::IsNullOrWhiteSpace($env:CODEX_MODEL_LIGHT)) {
    $env:CODEX_MODEL_LIGHT = $env:CODEX_MODEL
}
if ([string]::IsNullOrWhiteSpace($env:CODEX_MODEL_ROUTER)) {
    $env:CODEX_MODEL_ROUTER = $env:CODEX_MODEL
}
if ([string]::IsNullOrWhiteSpace($env:CODEX_EFFORT)) {
    $env:CODEX_EFFORT = "low"
}

# The career pipeline always consumes the local, read-only Capability Graph.
# Keep these defaults after .env import: an explicitly configured remote URL or
# secret wins, while a local launch works without duplicating graph settings in
# every developer env file.
if ([string]::IsNullOrWhiteSpace($env:CAPABILITY_GRAPH_URL)) {
    $env:CAPABILITY_GRAPH_URL = "http://127.0.0.1:8600"
}
if ([string]::IsNullOrWhiteSpace($env:CAPABILITY_GRAPH_SHARED_SECRET)) {
    $env:CAPABILITY_GRAPH_SHARED_SECRET = "local-capability-graph-secret"
}
if ([string]::IsNullOrWhiteSpace($env:CAPABILITY_GRAPH_TIMEOUT_SECONDS)) {
    $env:CAPABILITY_GRAPH_TIMEOUT_SECONDS = "10"
}

if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & py -3.12 -m venv (Join-Path $aiRoot ".venv")
    }
    else {
        & python -m venv (Join-Path $aiRoot ".venv")
    }
    $Install = $true
}

if ($Install) {
    Push-Location $aiRoot
    try {
        & $python -m pip --version *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "pip is missing from the AI virtual environment. Restoring it with ensurepip..."
            & $python -m ensurepip --upgrade
            if ($LASTEXITCODE -ne 0) {
                throw "Could not restore pip in the real AI virtual environment."
            }
        }

        & $python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }

        & $python -m pip install -e ".[dev,prototype]"
        if ($LASTEXITCODE -ne 0) { throw "Real AI dependencies failed to install." }
    }
    finally { Pop-Location }
}

Push-Location $aiRoot
try {
    Write-Host "Capability Graph: $($env:CAPABILITY_GRAPH_URL)" -ForegroundColor DarkCyan
    Write-Host "Starting unified JOBIS AI (LLM_PROVIDER=$($env:LLM_PROVIDER))..." -ForegroundColor Cyan
    & $python -m uvicorn jobis_ai.v2bridge.app:app --host 127.0.0.1 --port $Port
}
finally { Pop-Location }
