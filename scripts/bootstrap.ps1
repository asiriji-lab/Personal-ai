param(
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"
$tempPath = Join-Path $repoRoot ".tmp-bootstrap"
$uvCachePath = Join-Path $repoRoot ".uv-cache"

function Resolve-PythonExe {
    param([string]$Requested)

    if ($Requested) {
        return $Requested
    }

    $candidates = @(
        "C:\Users\acer.nitrov15\AppData\Local\Programs\Python\Python312\python.exe",
        "python"
    )

    foreach ($candidate in $candidates) {
        try {
            & $candidate --version *> $null
            return $candidate
        } catch {
        }
    }

    throw "No usable Python interpreter found. Pass -PythonExe explicitly."
}

$resolvedPython = Resolve-PythonExe -Requested $PythonExe
$bundledPipWheel = & $resolvedPython -c "from pathlib import Path; import ensurepip; wheels = sorted((Path(ensurepip.__file__).parent / '_bundled').glob('pip-*.whl')); print(wheels[-1] if wheels else '')"

New-Item -ItemType Directory -Force $tempPath | Out-Null
$env:TEMP = $tempPath
$env:TMP = $tempPath
$env:UV_CACHE_DIR = $uvCachePath

Write-Host "Creating project environment at $venvPath"
if (Test-Path $venvPath) {
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

& $resolvedPython -m venv --without-pip $venvPath

$venvPython = Join-Path $venvPath "Scripts\python.exe"

if ($bundledPipWheel -and (Test-Path $bundledPipWheel)) {
    Write-Host "Seeding pip from bundled Python wheel"
    & $resolvedPython -m pip --python $venvPython install --no-index $bundledPipWheel
} else {
    throw "Bundled pip wheel not found at $bundledPipWheel"
}

Write-Host "Installing Roojai in editable mode"
try {
    & $venvPython -m pip install -e .
} catch {
    Write-Host ""
    Write-Host "Editable install failed. The local environment exists, but dependency installation did not complete."
    Write-Host "This usually means package download is blocked or the host Python package index is unavailable."
    Write-Host "Retry when network/package access is available:"
    Write-Host "  $venvPython -m pip install -e ."
    throw
}

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Interpreter: $venvPython"
Write-Host "Select this interpreter in VS Code if it is not picked automatically."
