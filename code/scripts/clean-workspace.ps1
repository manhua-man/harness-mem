param(
    [Parameter(Position = 0)]
    [ValidateSet("clean", "clean-all")]
    [string]$Mode = "clean"
)

$root = Split-Path -Parent $PSScriptRoot
$root = (Resolve-Path $root).Path
$skipSegmentRegex = '(?i)(\\\.git\\|\\\.venv\\|\\\.harness-mem\\|\\\.codex\\|\\\.claude\\|\\\.cursor\\|\\\.grok\\|\\\.opencode\\|\\\.gstack\\|\\\.agents\\|\\\.local-archive\\|\\\.hypothesis\\)'

function Remove-PathSafe {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force
        Write-Host "removed: $Path"
    }
    catch {
        Write-Warning "failed: $Path -> $($_.Exception.Message)"
    }
}

function Test-SkipPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ($Path -replace '/', '\') -match $script:skipSegmentRegex
}

function Remove-TopLevel {
    param([string[]]$Names)
    foreach ($name in $Names) {
        Remove-PathSafe (Join-Path $root $name)
    }
}

function Remove-Caches {
    $cacheDirNames = @(
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".cache"
    )

    Get-ChildItem -Path $root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object {
            (-not (Test-SkipPath -Path $_.FullName)) -and
            ($_.Name -in $cacheDirNames)
        } |
        ForEach-Object {
            Remove-PathSafe $_.FullName
        }

    Get-ChildItem -Path $root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            (-not (Test-SkipPath -Path $_.FullName)) -and
            ($_.Extension -in @(".pyc", ".pyo"))
        } |
        ForEach-Object {
            Remove-PathSafe $_.FullName
        }

    Remove-TopLevel @(
        ".coverage",
        "coverage",
        "htmlcov"
    )
}

function Remove-BuildArtifacts {
    $buildDirNames = @(
        "dist",
        "build",
        "target",
        ".eggs",
        "site",
        ".next",
        ".tox",
        "node_modules"
    )

    foreach ($name in $buildDirNames) {
        Get-ChildItem -Path $root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object {
                (-not (Test-SkipPath -Path $_.FullName)) -and
                ($_.Name -eq $name)
            } |
            ForEach-Object {
                Remove-PathSafe $_.FullName
            }
    }
}

Write-Host "=== harness-mem workspace clean: $Mode ==="

if ($Mode -eq "clean") {
    Remove-TopLevel @(
        ".tmp",
        ".temp",
        "terminals",
        ".hypothesis"
    )
    Remove-Caches
}
else {
    Remove-TopLevel @(
        ".tmp",
        ".temp",
        "terminals",
        ".hypothesis"
    )
    Remove-Caches
    Remove-BuildArtifacts
}

Write-Host "=== done ==="
Write-Host "可重复执行（幂等）。`nclean：只删临时缓存。`nclean-all：再删构建产物（build/dist/target/node_modules/etc）。"
