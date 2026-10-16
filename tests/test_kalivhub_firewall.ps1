# Offline native-Windows preflight. -WhatIf guarantees no firewall mutation.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$helper = Join-Path $PSScriptRoot '../tools/set-kalivhub-firewall.ps1'

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $helper), [ref]$tokens, [ref]$parseErrors
) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw "KalivHub firewall helper contains PowerShell syntax errors."
}

foreach ($bad in @(
    '', '0.0.0.0', '127.0.0.1', '169.254.0.1',
    '8.8.8.8', '192.168.1.0/24', '192.168.1.22,192.168.1.23',
    '192.168.1.001', '0xC0A80113', '255.255.255.255',
    'example.com', '::1'
)) {
    $accepted = $false
    try {
        & $helper -PhoneIp $bad -WhatIf | Out-Null
        $accepted = $true
    } catch {
        # Correct: fail closed without running New-NetFirewallRule.
    }
    if ($accepted) { throw "Unsafe firewall PhoneIp was accepted: $bad" }
}

foreach ($valid in @('192.168.1.22', '10.1.2.3', '172.20.1.5', '100.101.50.10')) {
    & $helper -PhoneIp $valid -WhatIf | Out-Null
}
& $helper -Remove -WhatIf | Out-Null
Write-Host 'PASS: firewall helper parses, accepts only canonical private IPs and supports non-mutating -WhatIf.'
