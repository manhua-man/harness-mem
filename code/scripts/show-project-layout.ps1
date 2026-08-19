param()

$root = (Get-Location).Path

$groups = @(
    @{
        Name = "源码与运行时（代码）"
        Paths = @(
            "harness_mem",
            "crates",
            "plugins",
            "tools",
            "mcps",
            "scripts",
            "tests"
        )
    },
    @{
        Name = "文档与契约"
        Paths = @(
            "docs",
            "README.md",
            "README.zh-CN.md",
            "CHANGELOG.md",
            "DESIGN.md",
            "AGENTS.md",
            "CLAUDE.md",
            ".github",
            "canvases"
        )
    },
    @{
        Name = "运行时与工作区数据（本地）"
        Paths = @(
            ".codex",
            ".claude",
            ".cursor",
            ".grok",
            ".opencode",
            ".gstack",
            ".harness-mem",
            ".hypothesis",
            ".local-archive",
            ".venv",
            ".agents"
        )
    }
)

$known = @()
foreach ($group in $groups) {
    foreach ($path in $group.Paths) {
        $known += $path
    }
}
$hidden = Get-ChildItem -Force $root | Select-Object -ExpandProperty Name

Write-Host "## harness-mem 项目结构（按组）"
foreach ($group in $groups) {
    Write-Host ""
    Write-Host ("- " + $group.Name)
    foreach ($path in $group.Paths) {
        if (Test-Path (Join-Path $root $path)) {
            Write-Host ("  - " + $path)
        } else {
            Write-Host ("  - " + $path + " (缺失)")
        }
    }
}

$other = $hidden | Where-Object { $known -notcontains $_ }
if ($other) {
    Write-Host ""
    Write-Host "- 其他"
    $other | ForEach-Object { Write-Host ("  - " + $_) }
}
