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
    $slashSrc = Join-Path $pluginRoot "commands\hm"
    $slashDst = Join-Path $env:USERPROFILE ".claude\commands\hm"
    if (Test-Path $slashSrc) {
        if (-not (Test-Path $slashDst)) {
            New-Item -ItemType Directory -Path $slashDst -Force | Out-Null
        }

        $dailyCommands = @("status", "wake", "search", "search-all", "distill", "review")
        $maintenanceCommands = @("mark", "prune", "review-kb", "prune-kb", "verify-entry")
        $productDocCommands = @("prd-sync")
        $labsCommands = @("dream")

        $selectedCommands = @($dailyCommands)
        if ($WithMaintenanceCommands) {
            $selectedCommands += $maintenanceCommands
            $selectedCommands += $productDocCommands
        } elseif ($WithProductDocCommands) {
            $selectedCommands += $productDocCommands
        }
        if ($WithLabsCommands) {
            $selectedCommands += $labsCommands
        }

        $knownCommands = @($dailyCommands + $maintenanceCommands + $productDocCommands + $labsCommands)
        foreach ($command in $knownCommands) {
            $destination = Join-Path $slashDst "$command.md"
            if ($selectedCommands -notcontains $command -and (Test-Path $destination)) {
                Remove-Item -LiteralPath $destination -Force
            }
        }

        foreach ($command in $selectedCommands) {
            $source = Join-Path $slashSrc "$command.md"
            if (-not (Test-Path $source)) {
                throw "Slash command source not found at $source"
            }
            Copy-Item -LiteralPath $source -Destination $slashDst -Force
        }

        $availableCommands = ($selectedCommands | ForEach-Object { "/hm:$($_)" }) -join " "
        Write-Host "Installed $($selectedCommands.Count) Claude Code slash commands to $slashDst"
        Write-Host "  Available: $availableCommands"
        Write-Host "  Optional profiles: -WithMaintenanceCommands -WithProductDocCommands -WithLabsCommands"
    } else {
        Write-Warning "Slash command source not found at $slashSrc; skipping."
    }

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
