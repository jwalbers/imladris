<#
.SYNOPSIS
  Export the running Qure.ai App stack (images + named volumes) so it can be
  cloned into another Windows user's Docker Desktop.

.DESCRIPTION
  Run this as the 'qure' Windows user. The Qure installer runs Docker as root
  inside that user's default WSL distro, so every docker call goes through
  `wsl -u root -e docker`.

  Images are exported while the stack is still running. The containers are then
  briefly stopped so the Postgres volumes are archived in a consistent state,
  and restarted afterwards, even if the export fails.

  Output layout:
    <Out>\manifest.json      images, volumes, source project
    <Out>\images.tar         docker save of every image the project uses
    <Out>\volumes\<vol>.tgz  one tarball per named volume

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Export-QureStack.ps1
#>
[CmdletBinding()]
param (
    [string]$Out = "C:\QureTransfer",
    [string]$Project = "platform",
    # Image used to run tar against the volumes; already present in the Qure stack.
    [string]$HelperImage = "postgres:14.4"
)

$ErrorActionPreference = "Stop"

function Invoke-Docker {
    $output = & wsl -u root -e docker @args
    if ($LASTEXITCODE -ne 0) { throw "docker $($args -join ' ') failed (exit $LASTEXITCODE)" }
    $output
}

function ConvertTo-WslPath([string]$WinPath) {
    $full = [System.IO.Path]::GetFullPath($WinPath)
    "/mnt/" + $full.Substring(0, 1).ToLower() + ($full.Substring(2) -replace '\\', '/')
}

New-Item -ItemType Directory -Force (Join-Path $Out "volumes") | Out-Null
$outWsl = ConvertTo-WslPath $Out

$containers = @(Invoke-Docker ps -a -q --filter "label=com.docker.compose.project=$Project")
if ($containers.Count -eq 0) { throw "No containers found for compose project '$Project'. Is the Qure stack installed for this user?" }
$running = @(Invoke-Docker ps -q --filter "label=com.docker.compose.project=$Project")

$images = @(Invoke-Docker inspect --format '{{.Config.Image}}' @containers | Sort-Object -Unique)
# Named volumes only; anonymous (64-hex) volumes are recreated automatically.
# The template avoids embedded double quotes: Windows PowerShell 5.1 strips them
# when passing arguments to native commands, so filter on .Type here instead.
$volumes = @(Invoke-Docker inspect --format '{{range .Mounts}}{{println .Type .Name}}{{end}}' @containers |
    Where-Object { $_ -match '^volume (\S+)$' } | ForEach-Object { $Matches[1] } |
    Where-Object { $_ -notmatch '^[0-9a-f]{64}$' } | Sort-Object -Unique)

[ordered]@{
    project     = $Project
    exported_at = (Get-Date).ToString("o")
    helperImage = $HelperImage
    images      = $images
    volumes     = $volumes
} | ConvertTo-Json | Out-File -Encoding utf8 (Join-Path $Out "manifest.json")

Write-Host "Images ($($images.Count)):"; $images | ForEach-Object { Write-Host "  $_" }
Write-Host "Volumes ($($volumes.Count)):"; $volumes | ForEach-Object { Write-Host "  $_" }

Write-Host "Saving images to $Out\images.tar (this can take a while) ..."
Invoke-Docker save -o "$outWsl/images.tar" @images | Out-Null

try {
    if ($running.Count -gt 0) {
        Write-Host "Stopping $($running.Count) running containers for a consistent volume snapshot ..."
        Invoke-Docker stop @running | Out-Null
    }
    foreach ($v in $volumes) {
        Write-Host "Archiving volume $v ..."
        Invoke-Docker run --rm -v "${v}:/v:ro" -v "${outWsl}/volumes:/out" --entrypoint tar $HelperImage -czf "/out/$v.tgz" -C /v . | Out-Null
    }
}
finally {
    if ($running.Count -gt 0) {
        Write-Host "Restarting containers ..."
        Invoke-Docker start @running | Out-Null
    }
}

Write-Host "Export complete: $Out"
