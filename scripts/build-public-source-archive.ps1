# Build a public source tarball from HEAD using git archive, then strip maintainer-only paths.
# See release/public-source-excludes.txt and docs/releasing.md.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path (Join-Path $Root ".git"))) {
    throw "Run from a git checkout of harness-mem (missing .git)."
}

$Version = (python -c "from harness_mem import __version__; print(__version__)").Trim()
$Dist = Join-Path $Root "dist"
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$Prefix = "harness-mem-$Version/"
$Out = Join-Path $Dist "harness-mem-$Version-public-source.tar.gz"

git archive --format=tar.gz -o $Out --prefix=$Prefix HEAD
python (Join-Path $Root "scripts\filter_public_archive.py") $Out

$Listing = tar -tzf $Out 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Could not list archive (is tar available?)."
}
if ($Listing -match "v2-user-test-packet\.md") {
    throw "Public archive still contains docs/v2-user-test-packet.md"
}
if ($Listing -match "integration/artifacts/") {
    throw "Public archive still contains harness_mem/integration/artifacts/"
}
Write-Host "Wrote $Out (maintainer-only paths removed per release/public-source-excludes.txt)"
