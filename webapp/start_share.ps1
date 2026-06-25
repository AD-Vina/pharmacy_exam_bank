$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function New-RandomText([int]$Length = 16) {
  $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789".ToCharArray()
  $bytes = New-Object byte[] $Length
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $AppDir

$Python = Join-Path $AppDir ".venv\Scripts\python.exe"
if (!(Test-Path $Python)) {
  py -m venv .venv
  & $Python -m pip install -r requirements.txt
}

if (!$env:PORT) { $env:PORT = "5000" }
if (!$env:SECRET_KEY) { $env:SECRET_KEY = New-RandomText 48 }

$env:SECURITY_ENABLED = "1"
$env:ALLOW_GUEST_LOGIN = "1"
$env:LOCAL_AUTO_LOGIN = "1"
$env:SHARE_ACCESS_CODE = ""
$env:BIND_HOST = "127.0.0.1"

Write-Host ""
Write-Host "Pharmacy Exam Bank local server is starting."
Write-Host "Open on this PC: http://127.0.0.1:$env:PORT"
Write-Host ""
Write-Host "No account or password is required."
Write-Host "Local only: this server is not exposed to phones or other computers."
Write-Host "Security: local bind, guest isolation, rate limits, noindex, bot UA block, security headers."
Write-Host "Press Ctrl+C to stop."
Write-Host ""

& $Python app.py
