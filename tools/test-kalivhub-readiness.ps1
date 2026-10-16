# Read-only acceptance preflight for Windows. Never starts ModelRig,
# changes firewall settings, reads an HMAC secret or launches a Cast app.
[CmdletBinding()]
param(
    [string]$CastHost = '192.168.1.13',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$CheckCast,
    [switch]$StaticOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) {
    throw 'This readiness preflight requires Windows.'
}

foreach ($name in @('kalivhub_mirror_server.py',
                     'start-kalivhub-mirror.ps1',
                     'set-kalivhub-firewall.ps1')) {
    $file = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Missing KalivHub test-branch file: $file"
    }
}
Write-Host 'PASS: KalivHub receiver and Windows launcher files found.'

# Windows CI can run this mode without Cast devices or PyChromecast installed.
if ($StaticOnly) {
    Write-Host 'STATIC ONLY: runtime dependencies and network deliberately not checked.'
    return
}

if (-not (Get-Command 'py' -ErrorAction SilentlyContinue)) {
    throw 'Python launcher (py) is missing. Install Python 3.11+ and ensure py.exe is available.'
}
& py -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"; print("PASS: Python", sys.version.split()[0])'
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }

# Import only: no device discovery, connection or receiver launch.
& py -c 'import pychromecast; from pychromecast.controllers import BaseController; from pychromecast.socket_client import SocketClient; assert callable(pychromecast.get_chromecast_from_host); assert callable(SocketClient.register_handler); assert callable(BaseController.send_message); print("PASS: PyChromecast controller API available")'
if ($LASTEXITCODE -ne 0) {
    throw 'PyChromecast is missing/incompatible. Try: py -m pip install "pychromecast>=13,<15"'
}

if ($env:LOCALAPPDATA) {
    $secretFile = Join-Path $env:LOCALAPPDATA 'KalivHub/mirror-secret.dpapi'
    if (Test-Path -LiteralPath $secretFile -PathType Leaf) {
        Write-Host 'INFO: DPAPI-encrypted pairing key exists for this Windows user (not decrypted).'
    } else {
        Write-Host 'INFO: First launch will generate an encrypted pairing key.'
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "INFO: TCP $Port already has a listener. Inspect it before starting another mirror."
} else {
    Write-Host "INFO: TCP $Port has no listening process."
}

if ($CheckCast) {
    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($CastHost, [ref]$parsed) -or
        $parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        $parsed.ToString() -cne $CastHost) {
        throw 'CastHost must be one canonical private IPv4 address.'
    }
    $octets = $parsed.GetAddressBytes()
    $allowed = ($octets[0] -eq 10) -or
        ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
        ($octets[0] -eq 192 -and $octets[1] -eq 168) -or
        ($octets[0] -eq 100 -and $octets[1] -ge 64 -and $octets[1] -le 127)
    if (-not $allowed) { throw 'CastHost must be a private LAN/Tailscale IPv4 address.' }
    $reachable = Test-NetConnection -ComputerName $CastHost -Port 8009 -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $reachable) { throw "No TCP connection to Nest Hub on port 8009: $CastHost" }
    Write-Host "PASS: Nest Hub $CastHost accepts TCP 8009 (Cast app not yet verified)."
} else {
    Write-Host 'INFO: No Cast network traffic sent. Use -CheckCast for an optional TCP 8009 check.'
}
Write-Host 'Readiness checked. Actual display and Android mirroring still require physical testing.'
