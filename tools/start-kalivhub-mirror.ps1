# Start the opt-in Nest Hub display mirror without exposing the AI backend.
# Windows only. Stores an independent HMAC key encrypted with CurrentUser DPAPI.
# Re-run as the SAME Windows user to keep Android pairing valid.
[CmdletBinding()]
param(
    [string]$CastHost = '192.168.1.13',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$ShowSecret,
    [switch]$SelfTest,
    [switch]$StrictAcks,
    [ValidateRange(0, 3600)][int]$ClearAfterSeconds = 0,
    [switch]$VerifyKeyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) {
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
    # A unique staging name avoids two simultaneous startups overwriting
    # each other's DPAPI ciphertext before the atomic move.
    $temporary = "$keyFile.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllBytes($temporary, $protected)
        try {
            [IO.File]::Move($temporary, $keyFile)
        } catch [IO.IOException] {
            if ([IO.File]::Exists($keyFile)) {
                throw 'Another KalivHub process created the mirror key. Restart this launcher; never use an unpersisted pairing secret.'
            }
            throw
        }
    } finally {
        if ([IO.File]::Exists($temporary)) {
            [IO.File]::Delete($temporary)
        }
    }
}

if ($secret -cnotmatch '^[0-9a-f]{64}$') {
    throw 'Stored mirror secret has invalid format. Refusing to start.'
}

if ($VerifyKeyOnly) {
    # Offline Windows/DPAPI test: no Cast connection, no cleartext output.
    Write-Host 'PASS: KalivHub mirror key initialized, decrypted and validated (DPAPI CurrentUser).'
    return
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
if ($ClearAfterSeconds -gt 0) {
    Write-Host "  Skærmbeskeder nulstilles efter $ClearAfterSeconds sekunder uden nye svar."
}
if ($SelfTest) {
    Write-Host '  Én signeret testbesked sendes gennem riggens HTTP-server til Nest Hub.'
}
if ($StrictAcks) {
    Write-Host '  STRICT ACKS: kræver opdateret receiver med request_id-ekko.'
}
$env:KALIVHUB_MIRROR_SECRET = $secret
try {
    $serverArgs = @($serverPath, '--cast-host', $CastHost, '--auto-bind', '--allow-lan', '--port', $Port)
    if ($SelfTest) { $serverArgs += '--startup-test' }
    if ($StrictAcks) { $serverArgs += '--strict-acks' }
    if ($ClearAfterSeconds -gt 0) {
        $serverArgs += @('--clear-after', "$ClearAfterSeconds")
    }
    & py @serverArgs
    if ($LASTEXITCODE -ne 0) {
        throw "KalivHub mirror server failed with exit code $LASTEXITCODE"
    }
} finally {
    Remove-Item Env:\KALIVHUB_MIRROR_SECRET -ErrorAction SilentlyContinue
}
