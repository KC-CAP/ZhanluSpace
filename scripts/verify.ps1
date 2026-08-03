[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$PnpmPath,
    [string]$NodePath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot

if (-not $PythonPath) {
    $venvPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    $PythonPath = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}
if (-not $PnpmPath) {
    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) {
        throw "pnpm not found. Pass -PnpmPath with the full path to pnpm.cmd."
    }
    $PnpmPath = $pnpmCommand.Source
}
if ($NodePath) {
    $nodeDirectory = Split-Path -Parent ([System.IO.Path]::GetFullPath($NodePath))
    $previousPath = $env:PATH
    $env:PATH = "$nodeDirectory;$previousPath"
} elseif (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "node not found. Pass -NodePath with the full path to node.exe."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE"
    }
}

Push-Location $repositoryRoot
try {
    Invoke-Checked $PythonPath @("-m", "pytest", "--cov=zhanlu_worker", "--cov-report=term-missing")
    Invoke-Checked $PnpmPath @("--dir", "apps/obsidian-plugin", "test")
    Invoke-Checked $PnpmPath @("--dir", "apps/obsidian-plugin", "typecheck")
    Invoke-Checked $PnpmPath @("--dir", "apps/obsidian-plugin", "build")
    Invoke-Checked "git" @("diff", "--check")
    Write-Host "Zhanlu verification passed."
}
finally {
    Pop-Location
    if ($NodePath) { $env:PATH = $previousPath }
}
