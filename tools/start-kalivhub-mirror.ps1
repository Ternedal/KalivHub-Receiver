# Start the opt-in Nest Hub display mirror without exposing the AI backend.
# Windows only. Stores an independent HMAC key encrypted with CurrentUser DPAPI.
# Re-run as the SAME Windows user to keep Android pairing valid.
[CmdletBinding()]
param(
    [string]$CastHost = '192.168.1.13',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$ShowSecret
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') {
    throw 'This launcher needs Windows for DPAPI.'
}

$directory = Join-Path $env:LOCALAPPDATA 'KalivHub'
$keyFile = Join-Path $directory 'mirror-secret.dpapi'
[IO.Directory]::CreateDirectory($directory) | Out-Null

if ([IO.File]::Exists($keyFile)) {
    try {
        $protected = [IO.File]::ReadAllBytes($keyFile)
        $clear = [Security.Cryptography.ProtectedData]::Unprotect(
            $protected, $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        $secret = [Text.Encoding]::UTF8.GetString($clear)
    } catch {
        throw 'Cannot decrypt KalivHub mirror key. Do not silently replace it: phone would need re-pairing.'
    }
} else {
    $random = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($random) } finally { $rng.Dispose() }
    $secret = [BitConverter]::ToString($random).Replace('-', '').ToLowerInvariant()
    $encoded = [Text.Encoding]::UTF8.GetBytes($secret)
    $protected = [Security.Cryptography.ProtectedData]::Protect(
        $encoded, $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    # Never write the secret in plaintext to disk; fail if storage fails.
    $temporary = "$keyFile.tmp"
    try {
        [IO.File]::WriteAllBytes($temporary, $protected)
        [IO.File]::Move($temporary, $keyFile)
    } finally {
        if ([IO.File]::Exists($temporary)) {
            [IO.File]::Delete($temporary)
        }
    }
}

if ($secret -cnotmatch '^[0-9a-f]{64}$') {
    throw 'Stored mirror secret has invalid format. Refusing to start.'
}

if ($ShowSecret) {
    Write-Host 'Spejlingsnøgle (kun til Android Nest Hub-spejling; del den ikke):'
    Write-Host $secret
}

$serverPath = Join-Path $PSScriptRoot 'kalivhub_mirror_server.py'
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw "Cannot find local mirror server: $serverPath"
}

Write-Host 'Starter KalivHub-spejling:'
Write-Host '  Nest Hub:' $CastHost
Write-Host '  Port:' $Port
Write-Host '  Den lokale LAN-adresse vælges automatisk. Stop med Ctrl+C.'
Write-Host '  OBS: Brug kun betroet netværk. HTTP krypterer IKKE indholdet.'
$env:KALIVHUB_MIRROR_SECRET = $secret
try {
    & py $serverPath --cast-host $CastHost --auto-bind --allow-lan --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "KalivHub mirror server failed with exit code $LASTEXITCODE"
    }
} finally {
    Remove-Item Env:\KALIVHUB_MIRROR_SECRET -ErrorAction SilentlyContinue
}
