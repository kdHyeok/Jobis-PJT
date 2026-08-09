[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$NoBrowser,
    [int]$ReadyTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $projectRoot ".local\logs"
$startedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

function Get-ExpectedListener {
    param(
        [int]$Port,
        [string]$CommandPattern,
        [string]$ServiceName
    )

    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        return $null
    }

    foreach ($ownerId in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction SilentlyContinue
        if ($owner -and $owner.CommandLine -match $CommandPattern) {
            return $owner
        }
    }

    $ownerSummary = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "$ServiceName cannot start because port $Port is owned by another process (PID: $ownerSummary)."
}

function Start-BackgroundPowerShell {
    param(
        [string]$ScriptPath,
        [string[]]$ScriptArguments,
        [string]$LogName
    )

    $argumentList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $ScriptPath + '"')
    ) + $ScriptArguments

    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $argumentList `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "$LogName.out.log") `
        -RedirectStandardError (Join-Path $logRoot "$LogName.error.log") `
        -PassThru
    $startedProcesses.Add($process)
    return $process
}

function Wait-ForExpectedListener {
    param(
        [int]$Port,
        [string]$CommandPattern,
        [string]$ServiceName
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $listener = Get-ExpectedListener -Port $Port -CommandPattern $CommandPattern -ServiceName $ServiceName
        if ($listener) {
            Write-Host "[ready] $ServiceName (port $Port)"
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw "$ServiceName did not become ready within $ReadyTimeoutSeconds seconds. Check $logRoot."
}

try {
    Write-Host "Preparing JOBIS local PostgreSQL..."
    & (Join-Path $PSScriptRoot "start-local-postgres.ps1")

    $jobisAiPattern = "jobis_ai\.v2bridge\.app:app"
    $backendPattern = "com\.jobiss\.JobissBackendApplication|JobissBackendApplication"
    $frontendPattern = "node(?:\.exe)?.*vite|vite(?:\.js)?"

    if (-not (Get-ExpectedListener -Port 8400 -CommandPattern $jobisAiPattern -ServiceName "JOBIS AI")) {
        $jobisAiArguments = @()
        if ($Install -or -not (Test-Path -LiteralPath (Join-Path $projectRoot "AI\.venv\Scripts\python.exe"))) {
            $jobisAiArguments += "-Install"
        }
        Start-BackgroundPowerShell `
            -ScriptPath (Join-Path $PSScriptRoot "start-ai-agent.ps1") `
            -ScriptArguments $jobisAiArguments `
            -LogName "ai" | Out-Null
    }
    else {
        Write-Host "[ready] JOBIS AI is already running (port 8400)"
    }

    if (-not (Get-ExpectedListener -Port 8380 -CommandPattern $backendPattern -ServiceName "backend")) {
        Start-BackgroundPowerShell `
            -ScriptPath (Join-Path $PSScriptRoot "start-backend.ps1") `
            -ScriptArguments @() `
            -LogName "backend" | Out-Null
    }
    else {
        Write-Host "[ready] backend is already running (port 8380)"
    }

    if (-not (Get-ExpectedListener -Port 5473 -CommandPattern $frontendPattern -ServiceName "frontend")) {
        $frontendArguments = @()
        if ($Install -or -not (Test-Path -LiteralPath (Join-Path $projectRoot "frontend\node_modules"))) {
            $frontendArguments += "-Install"
        }
        Start-BackgroundPowerShell `
            -ScriptPath (Join-Path $PSScriptRoot "start-frontend.ps1") `
            -ScriptArguments $frontendArguments `
            -LogName "frontend" | Out-Null
    }
    else {
        Write-Host "[ready] frontend is already running (port 5473)"
    }

    Wait-ForExpectedListener -Port 8400 -CommandPattern $jobisAiPattern -ServiceName "JOBIS AI"
    Wait-ForExpectedListener -Port 8380 -CommandPattern $backendPattern -ServiceName "backend"
    Wait-ForExpectedListener -Port 5473 -CommandPattern $frontendPattern -ServiceName "frontend"

    Write-Host ""
    Write-Host "JOBIS single-AI lab is ready: http://localhost:5473"
    Write-Host "Logs: $logRoot"

    if (-not $NoBrowser) {
        Start-Process "http://localhost:5473"
    }
}
catch {
    foreach ($startedProcess in $startedProcesses) {
        if (-not $startedProcess.HasExited) {
            & taskkill.exe /PID $startedProcess.Id /T /F *> $null
        }
    }
    throw
}
