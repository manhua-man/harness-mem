# Releasing（维护者）

> **Maintainer-only.** 说明对外发布物与完整 git clone 的差异。

## 两种「拿到源码」的方式

| 方式 | 含 `docs/v2-user-test-packet.md`？ | 用途 |
|---|---|---|
| `git clone` 完整仓库 | 是 | 开发、发版审计、跨客户端测试包 |
| **公开源码归档**（`git archive` / 下方脚本） | **否** | GitHub Release 附件、对外分发 tarball |

公开归档通过两层机制排除维护者材料：

1. **Git `export-ignore`**（`.gitattributes`，对已提交的树生效；GitHub「Source code」归档会尊重）。
2. **打包后过滤**（`scripts/filter_public_archive.py`，按清单删除成员；发布脚本始终执行）。

清单真值：[`release/public-source-excludes.txt`](../release/public-source-excludes.txt)。

当前排除项：

- `docs/v2-user-test-packet.md` — v2 跨客户端 release 测试包（含 scenario / transcript）
- `harness_mem/integration/artifacts/**` — 集成联调 transcript 与 repro 附件
- `benchmark-suite/artifacts/**` — raw BENCH artifact bundles（可能含 transcript / notes）；
  对外只保留 `benchmark-suite/release-snapshot.json` 这类 privacy-preserving summary

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

这一步校验 accepted BENCH artifact bundle、tracked `release-snapshot.json` 和
`claim_readiness` gates。完整 clone 有 raw artifacts 时会检查 artifacts 与 snapshot
一致；公开/CI clean checkout 没有 raw artifacts 时会走 `snapshot-only`，至少保证
tracked snapshot 仍是 v2 且 public-claim gate 没丢。

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

脚本会在打包后检查归档内**不包含**上述路径。

## Python 分发（wheel / sdist）

`pip install` 使用的 wheel 只包含 `harness_mem` 包；sdist 在 `pyproject.toml` 里仅额外带上 `README.md`、`CHANGELOG.md`、`docs/error-codes.md` 等，**不包含**完整 `docs/` 树，因此不会带上测试包。

## GitHub Release 建议

1. 用 `build-public-source-archive` 生成 tarball 并上传为 Release asset。
2. 或使用 `git archive` / GitHub 的 Source code (zip/tar) — 在推送 `.gitattributes` 的 `export-ignore` 之后，自动归档同样会省略测试包。

完整 clone 的维护者仍可在本地阅读与更新 `docs/v2-user-test-packet.md`；只是**不要**把它打进对外源码包。
