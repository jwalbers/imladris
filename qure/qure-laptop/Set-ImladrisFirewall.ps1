<#
.SYNOPSIS
  Windows Firewall policy for the Qure.ai laptop as an IMLADRIS lab resource.

.DESCRIPTION
  Docker Desktop adds an inbound ALLOW rule for its backend program, which
  covers every port the Qure stack publishes. In Windows Firewall a BLOCK rule
  beats any ALLOW rule, so "only from these hosts" is done by blocking every
  remote address EXCEPT an allowlist, per port group. Loopback is never
  filtered, so the laptop's own browser and tools keep working, and
  container-to-container traffic never reaches the host firewall.

  Idempotent: removes and recreates every rule in the "IMLADRIS" group.
  Applies to all profiles (Domain/Private/Public): Windows can flip the LAN to
  Public after a router or pfSense change.

.PARAMETER LabVm       Lab Docker host (Guacamole RDP; future lab MinXray modality). Default 192.168.3.66.
.PARAMETER AdminHosts  Admin workstations allowed RDP. Default 192.168.3.5 (EILEEN).
.PARAMETER FieldLan    Field mode: subnet whose tablets may use the Qure.ai App (3000 + its API).
.PARAMETER Remove      Remove all IMLADRIS rules and exit.

.EXAMPLE
  # Lab (Wisconsin), from an elevated PowerShell:
  powershell -ExecutionPolicy Bypass -File .\Set-ImladrisFirewall.ps1
.EXAMPLE
  # Field: also let tablets on the clinic Wi-Fi reach the app
  .\Set-ImladrisFirewall.ps1 -FieldLan 192.168.8.0/24
#>
param(
    [string]   $LabVm      = '192.168.3.66',
    [string[]] $AdminHosts = @('192.168.3.5'),
    [string]   $FieldLan   = '',
    [switch]   $Remove
)
$ErrorActionPreference = 'Stop'
$Group = 'IMLADRIS'

# Never blocked: loopback, plus the Docker Desktop / WSL2 internal ranges
# (containers reaching the host via host.docker.internal).
$Internal = @('127.0.0.0/8', '172.16.0.0/12')

function ConvertTo-UInt64([string]$ip) {
    $b = ([System.Net.IPAddress]::Parse($ip)).GetAddressBytes(); [Array]::Reverse($b)
    [uint64][BitConverter]::ToUInt32($b, 0)
}
function ConvertTo-Ip([uint64]$n) {
    $b = [BitConverter]::GetBytes([uint32]$n); [Array]::Reverse($b)
    ([System.Net.IPAddress]::new($b)).ToString()
}
# Every IPv4 range NOT covered by $Allowed (CIDRs or single addresses).
function Get-Complement([string[]]$Allowed) {
    $ranges = foreach ($a in $Allowed) {
        if ($a -match '/') {
            $ip, $len = $a.Split('/'); $n = ConvertTo-UInt64 $ip
            $size = [uint64][math]::Pow(2, 32 - [int]$len); $s = $n - ($n % $size)
            [pscustomobject]@{ S = $s; E = $s + $size - 1 }
        } else {
            $n = ConvertTo-UInt64 $a; [pscustomobject]@{ S = $n; E = $n }
        }
    }
    $out = @(); $cur = [uint64]0
    foreach ($r in ($ranges | Sort-Object S)) {
        if ($r.S -gt $cur) { $out += "$(ConvertTo-Ip $cur)-$(ConvertTo-Ip ($r.S - 1))" }
        if ($r.E + 1 -gt $cur) { $cur = $r.E + 1 }
    }
    if ($cur -le 4294967295) { $out += "$(ConvertTo-Ip $cur)-255.255.255.255" }
    $out
}
function Add-OnlyFrom([string]$Name, [string[]]$Ports, [string[]]$Allowed) {
    New-NetFirewallRule -Group $Group -DisplayName "IMLADRIS: $Name (block all but allowlist)" `
        -Direction Inbound -Action Block -Protocol TCP -LocalPort $Ports `
        -RemoteAddress (Get-Complement @($Internal + $Allowed | Where-Object { $_ })) -Profile Any | Out-Null
    Write-Host ("  {0,-34} ports {1,-32} from {2}" -f $Name, ($Ports -join ','), (($Allowed + 'localhost') -join ', '))
}

Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) { Write-Host "IMLADRIS firewall rules removed."; return }

Write-Host "IMLADRIS firewall rules:"
# Remote desktop: Guacamole on the lab VM, plus admin workstations.
Add-OnlyFrom 'RDP'                    @('3389')                 (@($LabVm) + $AdminHosts)
# Detector-facing DICOM (MWL C-FIND, DCMIO C-STORE): the on-laptop simulator uses
# the Docker network; the lab VM is allowed for a future lab MinXray modality.
Add-OnlyFrom 'DICOM MWL / DCMIO'      @('9003', '5252')          @($LabVm)
# Qure.ai App UI and the APIs its browser code calls: local only in the lab
# (remote users see it through RDP); field tablets via -FieldLan.
$app = @(); if ($FieldLan) { $app = @($FieldLan) }
Add-OnlyFrom 'Qure.ai App + API'      @('3000', '8080', '8081', '2001') $app
# Everything else the stack publishes: never from the network.
Add-OnlyFrom 'Qure admin and internal' @(
    '7000', '7888',            # DCMIO config UI (no auth) + Jupyter
    '9002',                    # MWL HTTP API (registers patients, no auth)
    '5888',                    # platform Jupyter shell_plus
    '8180',                    # cathode (qXR inference) API
    '3099', '5520',            # metabase, countly
    '5432', '5433', '5435',    # Postgres: platform, cathode, MWL
    '6379',                    # Redis
    '11112', '8085'            # laptop AdvaPACS gateway (used only by containers)
) @()

# Ping from the lab subnet, for monitoring (e.g. a Home Assistant ping sensor).
New-NetFirewallRule -Group $Group -DisplayName 'IMLADRIS: ping from lab LAN' -Direction Inbound `
    -Action Allow -Protocol ICMPv4 -IcmpType 8 -RemoteAddress '192.168.3.0/24' -Profile Any | Out-Null
Write-Host "  ping                               allowed from 192.168.3.0/24"
Write-Host "Done. Review: Get-NetFirewallRule -Group $Group | Format-Table DisplayName, Action, Enabled"
