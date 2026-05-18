param(
    [switch]$WithHybrid,
    [switch]$RegisterClaude,
    [switch]$NoSlashCommands
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

# Install Claude Code slash commands so users can run /hm:status, /hm:distill, etc.
# from any project without remembering CLI flags. Skip with -NoSlashCommands.
if (-not $NoSlashCommands) {
    $slashSrc = Join-Path $pluginRoot "commands\hm"
    $slashDst = Join-Path $env:USERPROFILE ".claude\commands\hm"
    if (Test-Path $slashSrc) {
        if (-not (Test-Path $slashDst)) {
            New-Item -ItemType Directory -Path $slashDst -Force | Out-Null
        }
        Copy-Item -Path (Join-Path $slashSrc "*.md") -Destination $slashDst -Force
        $count = (Get-ChildItem $slashDst -Filter "*.md").Count
        Write-Host "Installed $count Claude Code slash commands to $slashDst"
        Write-Host "  Available: /hm:status /hm:distill /hm:review /hm:wake /hm:search"
    } else {
        Write-Warning "Slash command source not found at $slashSrc; skipping."
    }
}

if ($RegisterClaude) {
    $claude = Get-Command claude -ErrorAction Stop
    & $claude.Source mcp add -s user harness_mem "python -m harness_mem.mcp.server"
}

& $python.Source -m harness_mem.cli doctor
