# v1.5.1 Baseline & Closeout Snapshot

Date: 2026-05-16T13:39:59.512284+00:00

## 1. Wake-up Latency Baseline (synthetic)

命令：`python benchmarks/scripts/v151_latency_baseline.py`

| Scale (N) | P50 (ms) | P95 (ms) |
|-----------|----------|----------|
| 10 | 16.67 | 24.64 |
| 100 | 19.76 | 25.57 |
| 1000 | 21.47 | 22.69 |

## 2. Search Latency Sample (N=1000, for v1.5.2 reference)

说明：第一条查询通常包含向量检索模型的冷启动开销，因此只作为相对参考，不直接拿来做单点 SLA。

| Query | Latency (ms) |
|-------|--------------|
| scalability test | 23992.91 |
| architecture | 868.7 |
| benchmark data | 1174.0 |
| non-existent query | 737.96 |
| test entry | 1149.14 |

## 3. Storage Coverage Snapshot

命令：`python -m pytest --cov=harness_mem.storage --cov-report=term tests/storage -q`

| Module | Stmts | Miss | Coverage |
|--------|-------|------|----------|
| `storage/__init__.py` | 6 | 0 | 100% |
| `storage/local_memory_backend.py` | 32 | 17 | 47% |
| `storage/local_project_profile_store.py` | 31 | 21 | 32% |
| `storage/local_structured_store.py` | 289 | 69 | 76% |
| `storage/local_verbatim_store.py` | 114 | 12 | 89% |
| `storage/sqlite_index.py` | 192 | 12 | 94% |
| **TOTAL** | **664** | **131** | **80%** |

## 4. Closeout Verification Snapshot

- `python -m pytest -q` -> `194 passed in 401.30s`
- `python -m ruff check harness_mem benchmarks/scripts/v151_latency_baseline.py tests/integration/test_wake_auto_ingest.py` -> pass
- `python -m mypy harness_mem` -> pass
- `python -m pytest tests/integration/test_wake_auto_ingest.py tests/cli/test_learning_loop.py tests/storage/test_local_verbatim_store_deep.py -q` -> `17 passed`

## 5. Mechanism Snapshot

- `wake-up` auto-sync 现在使用 per-project `projects/<slug>/runtime/.ingest-lock`；其 `mtime` 表示最近一次成功 auto-ingest cursor。
- `.ingest-lock` 文件 body 保存 `pid / state / last_session_id / updated_at`，用于锁态判断与 stale reclaim。
- `wake-up` 会先走“时间门 -> 会话门 -> 锁门”，并用 `projects/<slug>/runtime/.ingest-scan-stamp` 做持久化 scan throttle。
- auto-sync 仍然只写 verbatim observations，不跑 LLM distill，也不会阻断主 `wake-up` 输出。

---

**v1.5.1 验收锚点（当前真相）**

- 当前 synthetic baseline 下，wake-up 的 P95 预算可按 `25.57ms * 1.5 = 38.36ms` 估算上限。
- `local_verbatim_store.py` 已从最初 baseline 的 `52%` 提升到本次快照的 `89%`；后续如果要继续追平 `local_structured_store.py`，请继续用本页的覆盖命令做同口径比较。
- 本页是 `v1.5.1` 的 closeout 证据页；`v1.5.2` 的检索优化应在此基础上新增自己的 recall / latency 诊断文档，而不是覆盖本页。
