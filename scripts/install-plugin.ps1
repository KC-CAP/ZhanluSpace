[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$VaultPath,
    [string]$PythonPath = "python",
    [string]$HermesPath = "hermes",
    [string]$HermesProfile = "default",
    [string]$PnpmPath = "pnpm",
    [string]$NodePath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
if ($NodePath) {
    $nodeDirectory = Split-Path -Parent ([System.IO.Path]::GetFullPath($NodePath))
    $env:PATH = "$nodeDirectory;$env:PATH"
}
$vaultCandidate = [System.IO.Path]::GetFullPath($VaultPath)
if (-not (Test-Path -LiteralPath $vaultCandidate -PathType Container)) {
    throw "Vault directory does not exist: $vaultCandidate"
}
$vaultRoot = (Resolve-Path -LiteralPath $vaultCandidate).Path
$resolvedRepositoryRoot = (Resolve-Path -LiteralPath $repositoryRoot).Path
$userProfile = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath("UserProfile")).TrimEnd('\')
$driveRoot = [System.IO.Path]::GetPathRoot($vaultRoot).TrimEnd('\')
if ($vaultRoot.TrimEnd('\') -in @($resolvedRepositoryRoot.TrimEnd('\'), $userProfile, $driveRoot)) {
    throw "Refusing an unsafe Vault target: $vaultRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $vaultRoot ".git") -PathType Container)) {
    throw "The Vault root must be a Git repository with a local main branch."
}
if (-not (Test-Path -LiteralPath (Join-Path $vaultRoot ".obsidian") -PathType Container)) {
    throw "Open the Vault in Obsidian once before installing the plugin."
}

$excludePath = Join-Path $vaultRoot ".git\info\exclude"
$excludeEntries = @("/.knowledge-runtime/", "/.obsidian/plugins/zhanlu-knowledge/")
$excludeText = if (Test-Path -LiteralPath $excludePath) {
    [System.IO.File]::ReadAllText($excludePath)
} else {
    ""
}
foreach ($entry in $excludeEntries) {
    if ($excludeText -notmatch "(?m)^$([regex]::Escape($entry))$") {
        if ($excludeText -and -not $excludeText.EndsWith("`n")) { $excludeText += "`n" }
        $excludeText += "$entry`n"
    }
}
[System.IO.File]::WriteAllText($excludePath, $excludeText, $utf8NoBom)

$pluginSource = Join-Path $repositoryRoot "apps\obsidian-plugin"
& $PnpmPath --dir $pluginSource build
if ($LASTEXITCODE -ne 0) { throw "Obsidian plugin build failed." }

$obsidianRoot = Join-Path $vaultRoot ".obsidian"
$pluginRoot = Join-Path $obsidianRoot "plugins\zhanlu-knowledge"
$resolvedPluginRoot = [System.IO.Path]::GetFullPath($pluginRoot)
$vaultPrefix = $vaultRoot.TrimEnd('\') + '\'
if (-not $resolvedPluginRoot.StartsWith($vaultPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved plugin target escaped the selected Vault."
}
New-Item -ItemType Directory -Force -Path $pluginRoot | Out-Null
foreach ($name in @("manifest.json", "main.js", "styles.css")) {
    Copy-Item -LiteralPath (Join-Path $pluginSource $name) -Destination (Join-Path $pluginRoot $name) -Force
}

$runtimeRoot = Join-Path $pluginRoot "worker-venv"
$workerPython = Join-Path $runtimeRoot "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $workerPython)) {
    & $PythonPath -m venv $runtimeRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Worker virtual environment." }
}
& $workerPython -m pip install --disable-pip-version-check $repositoryRoot
if ($LASTEXITCODE -ne 0) { throw "Could not install zhanlu-worker." }

$settings = [ordered]@{
    pythonExecutable = $workerPython
    workerModule = "zhanlu_worker"
    hermesExecutable = $HermesPath
    hermesProfile = $HermesProfile
    jobTimeoutSeconds = 300
}
$settingsJson = ConvertTo-Json -InputObject $settings
[System.IO.File]::WriteAllText((Join-Path $pluginRoot "data.json"), $settingsJson, $utf8NoBom)

Write-Host "Installed Zhanlu Knowledge into $pluginRoot"
Write-Host "Restart Obsidian, enable Zhanlu Knowledge, then open its import ribbon action."
