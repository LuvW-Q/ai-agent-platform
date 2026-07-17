param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18081,
    [switch]$SmokeOnly,
    [switch]$NoBrowser,
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ($PythonPath) {
    $python = [System.IO.Path]::GetFullPath($PythonPath)
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python executable does not exist: $python"
    }
}
else {
    $python = Join-Path $projectRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $python = Join-Path $projectRoot ".preview-venv\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $python = (Get-Command python -ErrorAction Stop).Source
    }
}

$demoArguments = @((Join-Path $PSScriptRoot "demo.py"), "--port", "$Port")
if ($SmokeOnly) {
    $demoArguments += "--smoke-only"
}
if ($NoBrowser) {
    $demoArguments += "--no-browser"
}

& $python @demoArguments
exit $LASTEXITCODE
