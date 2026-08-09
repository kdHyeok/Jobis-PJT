param(
    [string]$BaseUrl = "http://127.0.0.1:8088",
    [string]$Email = "",
    [string]$Password = "",
    [switch]$KeepAccount
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$artifactDir = Join-Path $repoRoot "artifacts/predeploy-ai-smoke/$stamp"
$frontendDir = Join-Path $repoRoot "frontend"
$testLog = Join-Path $artifactDir "playwright.log"
$serviceLog = Join-Path $artifactDir "services.log"
$summaryFile = Join-Path $artifactDir "summary.txt"
$startedAt = (Get-Date).ToUniversalTime().ToString("o")

New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null

$env:E2E_BASE_URL = $BaseUrl
$env:E2E_LIVE_AI = "1"
$env:E2E_LIVE_KEEP_ACCOUNT = if ($KeepAccount) { "1" } else { "0" }
if (($Email -and -not $Password) -or ($Password -and -not $Email)) {
    throw "Email and Password must be supplied together."
}
if ($Email) {
    $env:E2E_LIVE_EMAIL = $Email
    $env:E2E_LIVE_PASSWORD = $Password
} else {
    Remove-Item Env:E2E_LIVE_EMAIL -ErrorAction SilentlyContinue
    Remove-Item Env:E2E_LIVE_PASSWORD -ErrorAction SilentlyContinue
}

$testExit = 0
Push-Location $frontendDir
try {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & npm run test:e2e -- tests/e2e/predeploy-ai-live.spec.ts --reporter=line 2>&1 |
        Tee-Object -FilePath $testLog
    $testExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorPreference
    Pop-Location
}

$logExit = 0
try {
    & docker-compose logs --since $startedAt --no-color ai backend 2>&1 |
        Tee-Object -FilePath $serviceLog | Out-Null
    $logExit = $LASTEXITCODE
} catch {
    $logExit = 1
    $_ | Out-String | Set-Content -Encoding utf8 $serviceLog
}

$fatalLines = @()
$fatalPattern = '(\sERROR\s|Traceback \(most recent call last\)|Unhandled exception|AnalysisPipelineFailure|PostingInterpretationFailure|CONTRACT_VALIDATION_FAILED|request[^\r\n]*status[=: ]5\d\d)'
if (Test-Path $serviceLog) {
    $fatalLines = @(Select-String -Path $serviceLog -Pattern $fatalPattern -CaseSensitive)
}

$summary = @(
    "JOBIS predeploy AI feature smoke",
    "startedAt=$startedAt",
    "baseUrl=$BaseUrl",
    "playwrightExit=$testExit",
    "serviceLogExit=$logExit",
    "fatalLogMatches=$($fatalLines.Count)",
    "artifacts=$artifactDir"
)
$summary | Set-Content -Encoding utf8 $summaryFile
$summary | ForEach-Object { Write-Host $_ }

if ($fatalLines.Count -gt 0) {
    Write-Host "Fatal service log matches:" -ForegroundColor Red
    $fatalLines | Select-Object -First 30 | ForEach-Object { Write-Host $_.Line }
}

if ($testExit -ne 0 -or $logExit -ne 0 -or $fatalLines.Count -gt 0) {
    exit 1
}

Write-Host "Predeploy AI feature smoke passed." -ForegroundColor Green
