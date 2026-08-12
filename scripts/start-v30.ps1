<#
V30 one-click Windows launcher.

This is the only normal local startup path:
- keeps the named Docker volumes and never requests volume deletion;
- uses a free local web port starting at 3100;
- runs Docker build/start, schema migration, database-backed admin bootstrap, and
  the verified 1,000-row fictional demo seed in one controlled flow;
- prints the exact URL and live database counts.

Use `RECOVER_ADMIN_V30.bat` only when a database administrator password must be
reset. Normal startup never changes an existing administrator password.
#>
[CmdletBinding()]
param(
    [switch]$ResetAdmin,
    [string]$AdminUsername = "ADMIN",
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExample = Join-Path $ProjectRoot ".env.example"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-EnvValue([string]$Key) {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return $null }
    $escaped = [regex]::Escape($Key)
    $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match "^\s*$escaped=" } | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -replace "^\s*$escaped=", "").Trim()
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $escapedKey = [regex]::Escape($Key)
    $lines = @(Get-Content -LiteralPath $EnvFile -ErrorAction Stop)
    $updated = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$escapedKey=") {
            $updated = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $updated) { $out += "$Key=$Value" }
    [System.IO.File]::WriteAllLines($EnvFile, [string[]]$out, [System.Text.UTF8Encoding]::new($false))
}

function Set-EnvDefault([string]$Key, [string]$Value) {
    if ([string]::IsNullOrWhiteSpace((Get-EnvValue $Key))) {
        Set-EnvValue $Key $Value
    }
}

function Test-PortInUse([int]$Port) {
    try {
        return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
    } catch {
        return $false
    }
}

function Find-FreeLocalPort([int]$PreferredPort) {
    $candidate = $PreferredPort
    while (Test-PortInUse $candidate) { $candidate++ }
    return $candidate
}

function Wait-ForHealthyService([string]$Service, [int]$TimeoutSeconds = 360) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $containerId = (docker compose ps -q $Service 2>$null | Select-Object -First 1)
        if ($containerId) {
            $status = (docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId 2>$null).Trim()
            if ($status -eq "healthy") { return }
            if ($status -in @("exited", "dead")) {
                docker compose logs --tail 80 $Service | Out-Host
                throw "$Service stopped during startup. The last log lines are shown above."
            }
        }
        Start-Sleep -Seconds 2
    }
    docker compose logs --tail 80 $Service | Out-Host
    throw "$Service did not become healthy within $TimeoutSeconds seconds. The last log lines are shown above."
}

Write-Step "Checking Docker Desktop"
docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start Docker Desktop, wait for Engine running, then launch V30 again."
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    # Preserve credentials, API keys, and named volumes from a prior V29 project.
    # Account passwords stay in PostgreSQL and are never read from the copied .env
    # after a database account exists.
    $parentFolder = Split-Path -Parent $ProjectRoot
    $priorEnv = Get-ChildItem -LiteralPath $parentFolder -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^mcp_agent_ai_university_V29(_|\.)' -and $_.FullName -ne $ProjectRoot } |
        ForEach-Object { Join-Path $_.FullName '.env' } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Sort-Object { (Get-Item -LiteralPath $_).LastWriteTime } -Descending |
        Select-Object -First 1
    if ($priorEnv) {
        Copy-Item -LiteralPath $priorEnv -Destination $EnvFile
        Write-Host "Copied compatible local connection settings from your prior V29 folder." -ForegroundColor Green
    } else {
        Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
        Write-Host "Created a local V30 .env from the demo template." -ForegroundColor Green
    }
}

# Safe development defaults. Existing values are preserved, so production users
# must opt in deliberately and will never have demo data injected.
Set-EnvDefault "APP_ENV" "development"
Set-EnvDefault "DEMO_DATA_MODE" "true"
Set-EnvDefault "AUTO_SEED_SYNTHETIC_DATA" "true"
Set-EnvDefault "ADMIN_BOOTSTRAP_USERNAME" "ADMIN"
Set-EnvDefault "ADMIN_BOOTSTRAP_PASSWORD" "admin123"
Set-EnvDefault "ADMIN_BOOTSTRAP_DISPLAY_NAME" "Administrator"

$desiredPort = 3100
$actualPort = Find-FreeLocalPort $desiredPort
Set-EnvValue "FRONTEND_PORT" "$actualPort"
Set-EnvValue "PUBLIC_APP_URL" "http://localhost:$actualPort"
Set-EnvValue "CORS_ALLOWED_ORIGINS" "http://localhost:$actualPort,http://127.0.0.1:$actualPort"

Write-Step "Stopping only previous University AI containers (named database volumes are preserved)"
docker compose down --remove-orphans | Out-Host

Write-Step "Building V30 and starting verified services"
docker compose up -d --build | Out-Host
Wait-ForHealthyService "backend"
Wait-ForHealthyService "frontend"

Write-Step "Verifying real V30 dataset counts"
$status = docker compose exec -T backend python -m app.system_bootstrap --status
$status | Out-Host
if ($LASTEXITCODE -ne 0) { throw "V30 database verification failed." }

Write-Step "Checking PostgreSQL-backed Administrator account"
docker compose exec -T backend python -m app.admin_recovery --username $AdminUsername --status | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Administrator account status could not be verified." }

if ($ResetAdmin) {
    Write-Step "Recovering Administrator password in PostgreSQL"
    Write-Host "Enter a new password twice. It is saved only as a PBKDF2 hash in PostgreSQL." -ForegroundColor Yellow
    docker compose exec -it backend python -m app.admin_recovery --username $AdminUsername --reset-password --confirm-local-recovery
    if ($LASTEXITCODE -ne 0) { throw "Administrator recovery did not complete." }
    docker compose restart backend | Out-Host
    Wait-ForHealthyService "backend"
}

$url = "http://localhost:$actualPort"
Write-Host "`nV30 is ready: $url" -ForegroundColor Green
Write-Host "Demo data: 1,000 fictional students synchronized in MongoDB and PostgreSQL." -ForegroundColor Green
Write-Host "Administrator ID: $AdminUsername (password is database-backed)." -ForegroundColor Green
Write-Host "No Docker volume was deleted." -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $url }
