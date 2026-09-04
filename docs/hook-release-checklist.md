# Hook 发版验收 Checklist

> 发 GitHub Release 前在目标项目跑一遍。自动脚本使用隔离的数据与 Note 目录，不改真实记忆。

执行顺序固定为：定向测试 → 一次小模型检查 → 一次完整 Hook → 完整测试与
发版门禁。小检查失败或超时就停止，不自动重试、不创建 job、不继续跑 Hook。
完整 Hook 失败也停止。代码或相关配置变化后，旧结果作废，不能拼接多次运行。

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
pip install --force-reinstall dist/wheel/harness_mem-<version>-*.whl
# 或发版前：pip install -e .
harness-mem --version   # 应与待发布版本一致
```

## 3. 跑实际结果检查

发版时只运行下面这一条；它已经包含隔离的完整 Hook，不要先单独运行同一
Hook 脚本再重复验收：

```powershell
python code/tools/outcome-verifier/scripts/verify_outcomes.py `
  --config .codex/outcomes.json `
  --output .tmp/outcome-verifier/harness-mem-release.json
```

其中 `background_memory_hook_flow` 会调用：

```powershell
python code/scripts/run_release_hook_acceptance.py --hook-client cursor
```

该脚本先让所选 CLI 处理一个固定的小样本，只调用一次。通过后才创建隔离的
合成会话并运行一次完整 Hook。job、Note、SQLite 和 receipt 都保存在
`.tmp/release-hook-acceptance-runs/`；脚本还会通过正常 MCP 搜索读回本次知识，
并确认真实数据目录没有出现本次 job 或 Note。单独运行该脚本只用于定位 Hook
问题，不是发版前的额外必跑步骤。

## 4. 报告必查字段

自动脚本的报告默认写入 `.tmp/release-hook-acceptance.json`；手动路径的
receipt 才写入 `~/.harness-mem/data/autonomous/receipts/`。

| 字段 | 期望 |
|------|------|
| `model_check.status` | `passed`；否则完整 Hook 不启动 |
| `full_hook_started` | `true` |
| `receipt_state` | `succeeded` |
| `autonomous.execution_source` | `autonomous_worker` |
| `provider_name` | `{cli}_cli`（如 `hermes_cli`） |
| `selected_cli` | 与 `cli=` 一致 |
| `runtime_fingerprint` | 与当前安装一致（否则 outcome `runtime_current=false`） |
| `config_fingerprint` | 与当前 `.harness-mem.toml` 一致 |
| `autonomous.hook_guard_check.all_blocked` | `true` |
| `autonomous.hook_guard_check.downstream_jobs_created` | `0` |
| `autonomous.last_verified_completion.job_id` | 对应 completed distill job |
| `autonomous.last_semantic_success_at` | 非空，且为**本次** Stop 之后 |
| `persistence.bound_truth_count` | 至少 `1` |
| `persistence.sqlite_truth_count` | 至少 `1` |
| `persistence.normal_search_hit` | `true` |
| `isolation.real_ledger_run_absent` | `true` |
| `isolation.real_note_absent` | `true` |

## 5. 发版门禁（仓库）

- [ ] 第 3 步为 **Status: passed**；失败后不继续
- [ ] `python -m pytest -q` 全绿
- [ ] `maturin build --release --features python-extension -o dist/wheel`
- [ ] 干净 venv `pip install` wheel + `harness-mem --help`
- [ ] `CHANGELOG.md` / `release-notes.md` 已写当前版本
- [ ] `git tag v<version> && git push origin v<version>`（触发 CI 打 Release）

## 6. 发版后

- [ ] GitHub Release 附件含六平台 wheel + sdist
- [ ] `README` 安装示例指向当前 Release
