param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18081,
    [switch]$SmokeOnly,
    [switch]$Detach,
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
        $python = (Get-Command python -ErrorAction Stop).Source
    }
}

$occupiedPort = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
    Where-Object { $_.Port -eq $Port } |
    Select-Object -First 1
if ($occupiedPort) {
    throw "Port $Port is already in use. Stop the existing service or run preview.cmd -Port <another-port>."
}

$databasePath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "demo_run.db"))
if ([System.IO.Path]::GetDirectoryName($databasePath) -ne $projectRoot) {
    throw "Demo database path must stay inside the project root."
}
if (Test-Path -LiteralPath $databasePath) {
    Remove-Item -LiteralPath $databasePath -Force
}

$adminUsername = "demo_admin"
$adminPassword = "Demo-" + (& $python -c "import secrets; print(secrets.token_urlsafe(18))")
$env:SECRET_KEY = & $python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:APP_SECRET_KEY = & $python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:SQLITE_URL = "sqlite:///" + ($databasePath -replace '\\', '/')
$env:ENABLE_DEMO_SEED = "1"
$env:INITIAL_ADMIN_USERNAME = $adminUsername
$env:INITIAL_ADMIN_PASSWORD = $adminPassword
$env:INITIAL_ADMIN_EMAIL = "demo-admin@example.local"
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "$Port"
$env:CORS_ORIGINS = "http://127.0.0.1:$Port"
$env:WORKFLOW_CODE_EXECUTION_ENABLED = "0"

$stdoutLog = Join-Path $env:TEMP "ai-agent-platform-demo-$PID.stdout.log"
$stderrLog = Join-Path $env:TEMP "ai-agent-platform-demo-$PID.stderr.log"
$process = $null
$process = Start-Process -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
$keepRunning = $false

try {
    & $python (Join-Path $PSScriptRoot "demo_smoke.py") `
        --base-url "http://127.0.0.1:$Port" `
        --username $adminUsername `
        --password $adminPassword
    if ($LASTEXITCODE -ne 0) {
        throw "Core demo smoke test failed."
    }

    Write-Host ""
    if ($SmokeOnly) {
        Write-Host "Demo smoke test passed; stopping the temporary service."
    }
    else {
        Write-Host "Demo is ready: http://127.0.0.1:$Port/login"
        Write-Host "Admin username: $adminUsername"
        Write-Host "Admin password: $adminPassword"
        Write-Host "Service PID: $($process.Id)"
        if (-not $NoBrowser) {
            Start-Process "http://127.0.0.1:$Port/login" | Out-Null
        }
        if ($Detach) {
            $keepRunning = $true
        }
        else {
            Write-Host "Press Ctrl+C to stop the demo service."
            Wait-Process -Id $process.Id
        }
    }
}
finally {
    if ($null -ne $process -and -not $keepRunning -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    if (Test-Path -LiteralPath $stderrLog) {
        $errors = Get-Content -LiteralPath $stderrLog -Raw
        if ($errors) { Write-Host $errors }
    }
}
