# Manual Smoke Test Guide — harness-mem

> 每一次 CLI 改动后，跑这条最短路径验证核心链路仍然通顺。

## 前置条件

```bash
cd F:\memory-lab\harness-mem
python -m harness_mem.cli --version   # 确认版本
```

## 测试项目

直接使用 `F--memory-lab` 自身的 Claude Code sessions：
- 路径：`C:\Users\<USER>\.claude\projects\F--memory-lab\`
- 不需要准备额外数据

## 手动跑（7 步）

**前置清理**（可选）：
```bash
Remove-Item $env:USERPROFILE\.harness-mem -Recurse -Force -ErrorAction SilentlyContinue
```

### Step 1 — quickstart

```bash
python -m harness_mem.cli quickstart F--memory-lab --client skip
```

**验证点**：`exit code = 0`，有 `Active project` 或 `Suggested next step`。

---

### Step 2 — doctor

```bash
python -m harness_mem.cli doctor
```

**验证点**：`Observations:` 字样存在，exit code = 0。

---

### Step 3 — ingest

```bash
python -m harness_mem.cli ingest claude-code -p F--memory-lab -n 3
```

**验证点**：`Ingested: N sessions`（N >= 1），exit code = 0。

---

### Step 4 — distill (ds)

```bash
python -m harness_mem.cli ds -p F--memory-lab
```

**验证点**：含 `Extracted N memory entries`，exit code = 0。

---

### Step 5 — wake

```bash
python -m harness_mem.cli wake -p F--memory-lab
```

**验证点**：含 `Project Profile:` 或 `Recent Tasks`，exit code = 0。

---

### Step 6 — correct

```bash
# 找最新 session ID
Get-ChildItem "$env:USERPROFILE\.claude\projects\F--memory-lab" -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 | Select-Object Name

python -m harness_mem.cli correct <SESSION_ID> -p F--memory-lab -r "smoke-test-pattern" -t "smoke-test-trigger"
```

**验证点**：`Created rule candidate:`，exit code = 0。

---

### Step 7 — handoff

```bash
python -m harness_mem.cli handoff -p F--memory-lab -t smoke-manual-test -s "manual smoke test run" --status in_progress
```

**验证点**：`Created handoff:`，exit code = 0。

---

## Debug 检查点

### 症状：所有命令报 "Project name required"

```bash
Get-Content "$env:USERPROFILE\.harness-mem\data\active_project.txt"
pwd
```

### 症状：ingest 报 "No sessions found"

```bash
Test-Path "$env:USERPROFILE\.claude\projects\F--memory-lab"
Get-ChildItem "$env:USERPROFILE\.claude\projects\F--memory-lab" -Directory
```

### 症状：correct 报 "No observations found"

```bash
python -m harness_mem.cli timeline -p F--memory-lab -n 5
```

### 症状：wake 输出空

```bash
python -m harness_mem.cli status -p F--memory-lab
```

---

## 回归频率

| 场景 | 建议频率 |
|------|---------|
| CLI 代码改动后 | 每次改动前跑一次 |
| 发布前 | 必须通过 |
| 每周维护 | 跑一次确保没有退化 |