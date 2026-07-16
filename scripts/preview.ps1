param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18081,
    [switch]$NoBrowser,
    [switch]$SmokeOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$environmentPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".preview-venv"))
$expectedEnvironmentPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".preview-venv"))

if ($environmentPath -ne $expectedEnvironmentPath -or
    [System.IO.Path]::GetDirectoryName($environmentPath) -ne $projectRoot) {
    throw "Preview environment path must stay inside the project root."
}

$basePythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $basePythonCommand) {
    throw "Python was not found. Install Python 3.10 or newer, then run preview.cmd again."
}
$basePython = $basePythonCommand.Source
$previewPython = Join-Path $environmentPath "Scripts\python.exe"
$requirementsStamp = Join-Path $environmentPath ".requirements.sha256"
$requirementsHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash

function New-PreviewEnvironment {
    param([switch]$Clear)

    Write-Host "Preparing the isolated preview environment..."
    if ($Clear) {
        & $basePython -m venv --clear $environmentPath
    }
    else {
        & $basePython -m venv $environmentPath
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $previewPython -PathType Leaf)) {
        throw "Failed to create the preview environment."
    }
}

function Test-PreviewEnvironment {
    if (-not (Test-Path -LiteralPath $previewPython -PathType Leaf)) {
        return $false
    }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $previewPython -c "import fastapi, uvicorn, sqlalchemy, pydantic, pydantic_settings, cryptography, httpx" *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

if (-not (Test-Path -LiteralPath $previewPython -PathType Leaf)) {
    New-PreviewEnvironment
}

$environmentReady = Test-PreviewEnvironment
if (-not $environmentReady) {
    New-PreviewEnvironment -Clear
}

$installedHash = ""
if (Test-Path -LiteralPath $requirementsStamp -PathType Leaf) {
    $installedHash = (Get-Content -LiteralPath $requirementsStamp -Raw).Trim()
}

if (-not $environmentReady -or $installedHash -ne $requirementsHash) {
    Write-Host "Installing preview dependencies (only needed on the first run or after dependency changes)..."
    & $previewPython -m pip install --disable-pip-version-check --upgrade -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install preview dependencies."
    }
    & $previewPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Preview dependencies are inconsistent."
    }
    if (-not (Test-PreviewEnvironment)) {
        throw "Preview dependencies were installed but cannot be imported."
    }
    Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding Ascii
}

Write-Host "Starting local preview..."
& (Join-Path $PSScriptRoot "demo.ps1") `
    -Port $Port `
    -NoBrowser:$NoBrowser `
    -SmokeOnly:$SmokeOnly `
    -PythonPath $previewPython
exit $LASTEXITCODE
