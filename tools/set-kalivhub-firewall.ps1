# Optional firewall permission for one trusted phone ONLY.
# This script is never called by the KalivHub mirror launcher.
# Use an elevated Windows PowerShell session to apply/remove the exact rule.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$PhoneIp,
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) {
    throw 'KalivHub Firewall helper requires Windows.'
}

$ruleName = "KalivHubMirrorPhone-TCP-$Port"

if (-not $Remove) {
    if ([string]::IsNullOrWhiteSpace($PhoneIp)) {
        throw 'Specify -PhoneIp with the exact trusted phone IPv4 address.'
    }
    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($PhoneIp, [ref]$parsed) -or
        $parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        $parsed.ToString() -cne $PhoneIp) {
        throw 'PhoneIp must be a canonical IPv4 address (no hostname, CIDR range or wildcard).'
    }

    $b = $parsed.GetAddressBytes()
    $private = ($b[0] -eq 10) -or
        ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or
        ($b[0] -eq 192 -and $b[1] -eq 168) -or
        ($b[0] -eq 100 -and $b[1] -ge 64 -and $b[1] -le 127)

    if (-not $private) {
        throw 'PhoneIp must be a private LAN or Tailscale IPv4 address.'
    }

    # Do not permit an entire subnet even by accident. A concrete /32 phone
    # address is the only allowed inbound sender.
    $remoteAddress = "$PhoneIp/32"
}

$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($Remove) {
    if ($existing -and $PSCmdlet.ShouldProcess($ruleName, 'Remove scoped phone firewall rule')) {
        $existing | Remove-NetFirewallRule -ErrorAction Stop
        Write-Host "Removed KalivHub phone-only firewall rule (TCP $Port)."
    } elseif (-not $existing) {
        Write-Host 'No KalivHub firewall rule exists for this port.'
    }
    return
}

if ($PSCmdlet.ShouldProcess($ruleName,
    "Allow TCP $Port from ONLY $remoteAddress on Private network profiles")) {
    # Enforce the entire known-safe rule every time, including on address
    # changes. Never widen an existing rule or touch unrelated firewall rules.
    if ($existing) {
        $existing | Remove-NetFirewallRule -ErrorAction Stop
    }
    New-NetFirewallRule -Name $ruleName `
        -DisplayName "KalivHub mirror - trusted phone only (TCP $Port)" `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -RemoteAddress $remoteAddress -Profile Private -Enabled True `
        -ErrorAction Stop | Out-Null
    Write-Host "Allowed ONLY $remoteAddress to connect to KalivHub TCP $Port on Private networks."
    Write-Host 'If the phone changes IP, rerun this command with the new address.'
}
