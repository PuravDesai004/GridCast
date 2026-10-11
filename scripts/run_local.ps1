param(
    [ValidateSet('build','daily')][string]$Mode = 'build',
    [switch]$Fixture,
    [switch]$Offline,
    [string]$Origin
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$env:OMP_NUM_THREADS = '2'
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
$env:MPLCONFIGDIR = Join-Path $projectRoot 'state\matplotlib'
$env:TEMP = Join-Path $projectRoot 'state\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$cliArguments = @('-u','-m','gridcast','run','--mode',$Mode)
if ($Fixture) {
    $cliArguments += @('--fixture','--compact','--root',(Join-Path $projectRoot 'state\clean-fixture'),
                      '--config',(Join-Path $projectRoot 'config\fixture.yaml'),
                      '--splits',(Join-Path $projectRoot 'config\fixture_splits.yaml'))
}
if ($Offline) { $cliArguments += '--offline' }
if ($Origin) { $cliArguments += @('--origin',$Origin) }
& $pythonPath @cliArguments
if ($LASTEXITCODE -ne 0) { throw "GridCast workflow failed with exit $LASTEXITCODE" }
