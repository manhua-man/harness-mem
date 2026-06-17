# Releasing（维护者）

> **Maintainer-only.** 说明对外发布物与完整 git clone 的差异。

## 两种「拿到源码」的方式

| 方式 | 含 `docs/v2-user-test-packet.md`？ | 用途 |
|---|---|---|
| `git clone` 完整仓库 | 是 | 开发、发版审计、跨客户端测试包 |
| **公开源码归档**（`git archive` / 下方脚本） | **否** | GitHub Release 附件、对外分发 tarball |

公开归档通过两层机制排除维护者材料，只保留产品 README、可安装代码、插件入口和必要的产品错误码文档：

1. **Git `export-ignore`**（`.gitattributes`，对已提交的树生效；GitHub「Source code」归档会尊重）。
2. **打包后过滤**（`scripts/filter_public_archive.py`，按清单删除成员；发布脚本始终执行）。

清单真值：[`release/public-source-excludes.txt`](../release/public-source-excludes.txt)。

当前排除类别：

- `benchmark-suite/**` — benchmark 设计、运行脚本、结果和内部评估资产
- `docs/roadmap*.md`、`docs/roadmap/**` — roadmap、历史切片设计和未来规划
- `docs/reference-projects.md`、`openspec/**` — 维护者参考边界和内部 spec 过程材料
- `docs/v2-user-test-packet.md`、`harness_mem/integration/artifacts/**` — 跨客户端测试包、transcript 和 repro 附件
- `tests/**` — 维护者回归测试，不作为产品分发面
- `release/**`、`AGENTS.md`、维护者 release / testing / CLI design 文档 — 本地维护材料

## 发版前检查

发版、打 tag、或发布 broad status / benchmark claim 前先跑 full gate：

```powershell
.\scripts\test-full.ps1
```

或（Linux / macOS / Git Bash）：

```bash
bash scripts/test-full.sh
```

full gate 会额外运行：

```bash
python benchmark-suite/tools/check_release_artifacts.py
```

这一步校验完整维护者 clone 里的 benchmark / release gate，包括 `claim_readiness` gates。
clean checkout 没有 raw artifacts 时仍可走 `snapshot-only` 路径做维护者侧一致性检查。
它不是公开产品包的一部分；公开源码包不携带 benchmark-suite。

## 生成公开源码包

在仓库根目录：

```powershell
.\scripts\build-public-source-archive.ps1
```

或（Linux / macOS / Git Bash）：

```bash
bash scripts/build-public-source-archive.sh
```

输出：`dist/harness-mem-<version>-public-source.tar.gz`

脚本会在打包后检查归档内**不包含**清单中的维护者路径。

## Python 分发（wheel / sdist）

`pip install` 使用的 wheel 只包含 `harness_mem` 包；sdist 在 `pyproject.toml` 里仅额外带上
`README.md`、`CHANGELOG.md`、`docs/error-codes.md` 等产品材料，**不包含**完整 `docs/`、
`benchmark-suite/`、`openspec/` 或 `tests/` 树。

## GitHub Release 建议

1. 用 `build-public-source-archive` 生成 tarball 并上传为 Release asset。
2. 或使用 `git archive` / GitHub 的 Source code (zip/tar) — 在推送 `.gitattributes` 的 `export-ignore` 之后，自动归档同样会省略维护者资料。

完整 clone 的维护者仍可在本地阅读与更新 roadmap、benchmark、测试包和参考项目材料；只是**不要**把它们打进对外源码包。
