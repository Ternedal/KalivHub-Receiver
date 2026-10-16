# Safe native-Windows contract tests for the optional explicit BindIp.
# Never launches a Cast app, opens a socket or exposes pairing secrets.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$launcher = Join-Path $PSScriptRoot '../tools/start-kalivhub-mirror.ps1'
$originalLocalAppdata = $env:LOCALAPPDATA
$fixture = Join-Path $env:RUNNER_TEMP ("kalivhub-bind-$([Guid]::NewGuid().ToString('N'))")
$env:LOCALAPPDATA = $fixture
$keyFile = Join-Path $fixture 'KalivHub/mirror-secret.dpapi'

try {
    # Every invalid bind address must fail BEFORE generating any DPAPI secret.
    foreach ($bad in @(
        '0.0.0.0', '127.0.0.1', '8.8.8.8', '169.254.4.5',
        '100.63.255.255', '100.128.0.1', '192.0.2.1',
        '192.168.1.0/24', '192.168.001.22', 'example.org',
        '::1', '255.255.255.255'
    )) {
        $refused = $false
        try { & $launcher -BindIp $bad -VerifyKeyOnly | Out-Null }
        catch { $refused = $true }
        if (-not $refused) { throw "Unsafe explicit bind address accepted: $bad" }
        if (Test-Path -LiteralPath $keyFile) {
            throw "Invalid BindIp created a DPAPI pairing secret: $bad"
        }
    }

    foreach ($good in @('192.168.1.100', '10.1.2.3', '172.21.5.10', '100.101.50.10')) {
        & $launcher -BindIp $good -VerifyKeyOnly | Out-Null
    }
    if (-not (Test-Path -LiteralPath $keyFile -PathType Leaf)) {
        throw 'Valid BindIp did not preserve DPAPI initialization.'
    }

    # Replace py.exe by a test-scoped function. Capture the exact command-line
    # arguments but NEVER spawn a receiver or talk to Nest Hub.
    function global:py {
        $global:KalivHubCapturedPyArgs = @($args)
        $global:LASTEXITCODE = 0
    }
    $global:LASTEXITCODE = 0

    & $launcher -BindIp '100.101.50.10' -Port 8765 | Out-Null
    $explicit = @($global:KalivHubCapturedPyArgs)
    if ('--bind' -notin $explicit -or '--auto-bind' -in $explicit -or
        '--allow-lan' -notin $explicit) {
        throw 'Explicit Tailscale interface was not forwarded safely to Python.'
    }
    $index = [array]::IndexOf($explicit, '--bind')
    if ($explicit[$index + 1] -ne '100.101.50.10') {
        throw 'The exact requested Tailscale IP was not passed to the receiver.'
    }

    & $launcher -Port 8765 | Out-Null
    $default = @($global:KalivHubCapturedPyArgs)
    if ('--auto-bind' -notin $default -or '--bind' -in $default -or
        '--allow-lan' -notin $default) {
        throw 'No-BindIp launch must preserve the legacy private-LAN automatic binding.'
    }

    Write-Host 'PASS: BindIp rejects unsafe addresses before key creation, forwards only exact IPs, and preserves default auto-bind.'
} finally {
    Remove-Item Function:\py -ErrorAction SilentlyContinue
    Remove-Variable -Name KalivHubCapturedPyArgs -Scope Global -ErrorAction SilentlyContinue
    $env:LOCALAPPDATA = $originalLocalAppdata
    if (Test-Path -LiteralPath $fixture) {
        Remove-Item -LiteralPath $fixture -Recurse -Force
    }
}
