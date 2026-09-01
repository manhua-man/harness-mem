# Hook 发版验收 Checklist（0.9.26+）

> 发 GitHub Release 前在**目标项目**跑一遍。隔离脚本 (`validate_autonomous_host_cli_chain.py`) 不能替代本清单。

## 1. 配置（项目 `.harness-mem.toml`）

```toml
[distill.autonomous]
enabled = true
cli = "hermes"   # 或 claude-code / codex / opencode；Cursor 宿主常用 hermes 或 claude-code
```

确认：

- [ ] `enabled=true`，关后台只用 `false`（不用 legacy `semantic.execution.profile`）
- [ ] `cli=` 与你要验收的后台 CLI 一致
- [ ] 所选 CLI 在 PATH 上（`hermes` / `claude` / `codex` / `opencode`）
- [ ] Cursor hooks 已安装：`.cursor/hooks/after-agent.sh` 指向当前 `harness-mem-hook`

## 2. 安装当前待发版代码

Hook 后台 worker 用 `python -m harness_mem.host_entry`，**必须**装待发版 wheel/sdist 或 editable：

```powershell
pip install --force-reinstall dist/wheel/harness_mem-0.9.26-*.whl
# 或发版前：pip install -e .
harness-mem --version   # 应为 0.9.26
```

## 3. 跑真实 Hook（二选一）

### A. 自动化（推荐）

```powershell
$env:PYTHONPATH="F:\AIInfra\harness-mem"   # 若未 pip 安装
python code/scripts/run_release_hook_acceptance.py --cli hermes --hook-client cursor
```

### B. 手动（Cursor Stop 后）

1. 在本项目开短会话，做一点可见改动后结束 turn（触发 after-agent hook）
2. 或手动：

```powershell
harness-mem-hook --action post-turn-maintenance `
  --project-root F:\AIInfra\harness-mem `
  --source ide_hook --client cursor `
  --trigger-id <session-id> --wait --wait-timeout 900
```

## 4. Receipt 必查字段（`~/.harness-mem/data/autonomous/receipts/*.json`）

| 字段 | 期望 |
|------|------|
| `state` | `succeeded` |
| `execution_source` | `autonomous_worker` |
| `provider.name` | `{cli}_cli`（如 `hermes_cli`） |
| `provider.execution_mode` | `agent` |
| `provider.host_client` | 与 `cli=` 一致 |
| `runtime_fingerprint` | 与当前安装一致（否则 outcome `runtime_current=false`） |
| `config_fingerprint` | 与当前 `.harness-mem.toml` 一致 |
| `hook_guard_check.all_blocked` | `true` |
| `hook_guard_check.downstream_jobs_created` | `0` |
| `last_verified_completion.job_id` | 对应 completed distill job |
| `last_semantic_success_at` | 非空，且为**本次** Stop 之后 |

## 5. Outcome 合同（14/14）

```powershell
python code/tools/outcome-verifier/scripts/verify_outcomes.py `
  --config .codex/outcomes.json `
  --output .tmp/outcome-verifier/harness-mem-release.json
```

必须 **Status: passed**；若仅 `autonomous_distill_completion` 失败且 `runtime_current=false`，说明 receipt 是旧 runtime，重做第 3 步。

## 6. 发版门禁（仓库）

- [ ] `python -m pytest -q` 全绿
- [ ] `maturin build --release --features python-extension -o dist/wheel`
- [ ] 干净 venv `pip install` wheel + `harness-mem --help`
- [ ] `CHANGELOG.md` / `release-notes.md` 已写 0.9.26
- [ ] `git tag v0.9.26 && git push origin v0.9.26`（触发 CI 打 Release）

## 7. 发版后

- [ ] GitHub Release 附件含六平台 wheel + sdist
- [ ] `README` 安装示例指向 `v0.9.26`
