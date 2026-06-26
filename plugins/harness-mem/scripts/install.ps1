param(
    [switch]$WithHybrid,
    [switch]$RegisterClaude,
    [switch]$NoSlashCommands,
    [switch]$WithMaintenanceCommands,
    [switch]$WithProductDocCommands,
    [switch]$WithLabsCommands
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
$pyproject = Join-Path $repoRoot "pyproject.toml"

if (-not (Test-Path $pyproject)) {
    throw "Could not find pyproject.toml at $pyproject"
}

$python = Get-Command python -ErrorAction Stop
$installTarget = $repoRoot.Path
if ($WithHybrid) {
    $installTarget = "$($repoRoot.Path)[hybrid]"
}

& $python.Source -m pip install -e $installTarget

# Install Claude Code slash commands so users can run the stable /hm:* daily
# workflow from any project without remembering CLI flags. Skip with -NoSlashCommands.
if (-not $NoSlashCommands) {
    $syncCommands = Join-Path $PSScriptRoot "sync-commands.ps1"
    $syncArgs = @("-Profile", "Daily")

    if ($WithMaintenanceCommands) {
        $syncArgs = @("-Profile", "Maintenance")
    } elseif ($WithProductDocCommands) {
        $syncArgs = @("-Profile", "ProductDoc")
    }
    if ($WithLabsCommands) {
        if ($WithMaintenanceCommands -or $WithProductDocCommands) {
            $syncArgs += "-IncludeLabsCommands"
        } else {
            $syncArgs = @("-Profile", "Labs")
        }
    }
    & $syncCommands @syncArgs
    Write-Host "  Change command visibility later without reinstalling:"
    Write-Host "  .\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Maintenance"
    Write-Host "  .\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Labs"

    $skillSrc = Join-Path $pluginRoot "skills"
    $skillDst = Join-Path $env:USERPROFILE ".claude\skills"
    if (Test-Path $skillSrc) {
        if (-not (Test-Path $skillDst)) {
            New-Item -ItemType Directory -Path $skillDst -Force | Out-Null
        }
        Copy-Item -Path (Join-Path $skillSrc "*") -Destination $skillDst -Recurse -Force
        $skillCount = (Get-ChildItem $skillSrc -Directory).Count
        Write-Host "Installed $skillCount Claude Code skills to $skillDst"
        Write-Host "  Available: harness-mem / harness-mem-autopilot"
    } else {
        Write-Warning "Skill source not found at $skillSrc; skipping."
    }
}

if ($RegisterClaude) {
    $claude = Get-Command claude -ErrorAction Stop
    & $claude.Source mcp add -s user harness_mem "python -m harness_mem.mcp.server"
}

& $python.Source -m harness_mem.cli doctor
