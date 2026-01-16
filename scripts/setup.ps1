param(
  [Parameter(Mandatory = $false)]
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

& $Python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -U pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Setup complete."
Write-Host "Run tests: .\\.venv\\Scripts\\python.exe -m pytest"

