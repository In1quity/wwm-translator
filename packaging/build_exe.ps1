param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist\\WWMTranslator") { Remove-Item "dist\\WWMTranslator" -Recurse -Force }

& $Python -m PyInstaller --noconfirm --clean "packaging/wwm_translator.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Build completed: dist/WWMTranslator"
