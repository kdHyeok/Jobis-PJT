$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Stop-ExpectedPortService {
    param(
        [int]$Port,
        [string]$CommandPattern,
        [string]$ServiceName
    )

    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        Write-Host "[stopped] $ServiceName was not running."
        return
    }

    foreach ($ownerId in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction SilentlyContinue
        if (-not $owner -or $owner.CommandLine -notmatch $CommandPattern) {
            throw "Refusing to stop PID $ownerId because port $Port is not owned by the expected JOBIS $ServiceName process."
        }

        & taskkill.exe /PID $ownerId /T /F *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not stop $ServiceName (PID $ownerId)."
        }
    }

    Write-Host "[stopped] $ServiceName"
}

Stop-ExpectedPortService `
    -Port 8380 `
    -CommandPattern "com\.jobiss\.JobissBackendApplication|JobissBackendApplication" `
    -ServiceName "backend"
Stop-ExpectedPortService `
    -Port 8600 `
    -CommandPattern "jobis_capability_graph\.api:app" `
    -ServiceName "Capability Graph"
Stop-ExpectedPortService `
    -Port 8400 `
    -CommandPattern "jobis_ai\.v2bridge\.app:app" `
    -ServiceName "JOBIS AI"
Stop-ExpectedPortService `
    -Port 5473 `
    -CommandPattern "node(?:\.exe)?.*vite|vite(?:\.js)?" `
    -ServiceName "frontend"

& (Join-Path $PSScriptRoot "stop-local-postgres.ps1")
Write-Host "All JOBIS local services are stopped."
