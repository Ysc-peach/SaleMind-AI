<#
.SYNOPSIS
Copy the newest verified backup pair to a second host.

.DESCRIPTION
Uses the system scp client with the operator's existing SSH key authentication.
No credentials are read, stored or printed here. The dump is re-checked with
pg_restore -l inside the backup container before anything is transferred, so a
truncated archive never becomes the offsite copy.

.EXAMPLE
$env:OFFSITE_TARGET = 'backup@nas.internal:/srv/salesmind-backups'
powershell -File scripts/offsite-sync.ps1
#>

param(
    [string] $Target = $env:OFFSITE_TARGET,
    [string] $BackupDir = ''
)

$ErrorActionPreference = 'Stop'

if (-not $Target) {
    throw 'Set OFFSITE_TARGET=user@host:/path before running offsite-sync.ps1'
}
# A Windows drive path (D:/...) contains a colon too, so require user@host:
if ($Target -notmatch '^[^@\s]+@[^:\s]+:.+') {
    throw 'OFFSITE_TARGET must be a remote scp target (user@host:/path)'
}

$root = Split-Path -Parent $PSScriptRoot
if (-not $BackupDir) { $BackupDir = Join-Path $root 'backups' }

$db = Get-ChildItem -LiteralPath $BackupDir -Filter 'db-*.dump' -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$media = Get-ChildItem -LiteralPath $BackupDir -Filter 'media-*.tar.gz' -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $db -or -not $media) {
    throw "No complete backup pair found under $BackupDir"
}

Push-Location $root
try {
    $envFile = Join-Path $root '.env.production.local'
    $composeArgs = @('compose')
    if (Test-Path -LiteralPath $envFile) {
        $composeArgs += @('--env-file', '.env.production.local')
    }
    $composeArgs += @(
        'exec', '-T', 'backup',
        'pg_restore', '-l', "/backups/$($db.Name)"
    )
    & docker @composeArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Latest dump $($db.Name) failed its integrity check"
    }

    & scp $db.FullName $media.FullName $Target
    if ($LASTEXITCODE -ne 0) { throw 'scp failed; no offsite copy was made' }

    Write-Output "offsite sync complete: $($db.Name) + $($media.Name)"
}
finally {
    Pop-Location
}
