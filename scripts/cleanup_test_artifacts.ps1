$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$artifactNames = @(
    "collection_e2e_20260716.db",
    "data_outlook_v2.test.db",
    "demo_run.db",
    "e2e_run.db",
    "e2e_latest_20260716.db",
    "e2e_server.stdout.log",
    "e2e_server.stderr.log"
)

foreach ($name in $artifactNames) {
    $target = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $name))
    if ([System.IO.Path]::GetDirectoryName($target) -ne $projectRoot) {
        throw "Refusing to remove an artifact outside the project root."
    }
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
        Write-Host "Removed $name"
    }
}
