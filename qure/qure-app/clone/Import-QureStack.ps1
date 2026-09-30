<#
.SYNOPSIS
  Import a Qure.ai App stack exported by Export-QureStack.ps1 into the current
  user's Docker Desktop, and set up a local copy of the qureapp config.

.DESCRIPTION
  Run this as the 'dev' Windows user, with Docker Desktop running.

  1. docker load the exported images
  2. restore each named volume from its tarball
  3. copy the 'qure' user's qureapp\ directory, which includes the .env files and
     credentials, to a local working directory OUTSIDE any git repo
  4. drop in docker-compose.dev-override.yml, which disables the services that
     talk to Qure's cloud

  Existing volumes and an existing destination directory are left alone unless
  -Force is given.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Import-QureStack.ps1
#>
[CmdletBinding()]
param (
    [string]$In = "C:\QureTransfer",
    [string]$Source = "C:\Users\qure\AppData\Local\Qure.ai\qureapp",
    [string]$Dest = (Join-Path $env:USERPROFILE "qure-dev\qureapp"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Invoke-Docker {
    $output = & docker @args
    if ($LASTEXITCODE -ne 0) { throw "docker $($args -join ' ') failed (exit $LASTEXITCODE)" }
    $output
}

$manifest = Get-Content -Raw (Join-Path $In "manifest.json") | ConvertFrom-Json
$volDir = Join-Path $In "volumes"

Write-Host "Loading images from $In\images.tar ..."
Invoke-Docker load -i (Join-Path $In "images.tar")

$existing = @(Invoke-Docker volume ls -q)
foreach ($v in $manifest.volumes) {
    if ($existing -contains $v) {
        if (-not $Force) { Write-Host "Volume $v exists, skipping (use -Force to overwrite)"; continue }
        Invoke-Docker volume rm $v | Out-Null
    }
    Write-Host "Restoring volume $v ..."
    Invoke-Docker volume create $v | Out-Null
    Invoke-Docker run --rm -v "${v}:/v" -v "${volDir}:/in:ro" --entrypoint tar $manifest.helperImage -xzf "/in/$v.tgz" -C /v | Out-Null
}

if ((Test-Path $Dest) -and -not $Force) {
    Write-Host "$Dest exists, not copying config (use -Force to overwrite)"
} else {
    Write-Host "Copying $Source -> $Dest ..."
    New-Item -ItemType Directory -Force (Split-Path $Dest) | Out-Null
    Copy-Item -Recurse -Force $Source $Dest
}
Copy-Item -Force (Join-Path $PSScriptRoot "docker-compose.dev-override.yml") $Dest

Write-Host ""
Write-Host "Import complete. Make sure the 'qure' user is logged OUT, then start the clone with:"
Write-Host "  cd `"$Dest`""
Write-Host "  docker compose -p $($manifest.project) -f docker-compose.yml -f docker-compose.dev-override.yml up -d"
