# Linus Torvalds 式审查：harness-mem v13/v14

## 整体印象

这东西不算烂。说实话，我见过更恶心的 AI 工具代码。有清晰的架构分层，有接口定义，有 FTS5 支持——这已经比我上周审查的那个
"write everything to a single JSON file" 的项目强了十倍。

但它也有几个让我血压升高的地方。

---

## 好的部分

**`sqlite_index.py` — 标准件。** 这个文件写得不错。FTS5 集成、触发器自动同步、WAL 模式、列迁移，全部到位。没有任何多余的东西。`_tokenize_query` 的 stop word 过滤和通配符追加是合理的默认值。`_ensure_columns` 的渐进式迁移设计值得称赞——不需要炸掉用户的数据库就能加字段。这大概就是这个项目里唯一我不用重写就能合并的文件。

**`CLAUDE.md` 的设计原则。** "可测试性 > 可读性 > 一致性 > 简洁性 > 可逆性"——这个优先级队列是对的。虽然我不知道实际代码执行得怎么样，但至少纸上写的是对的。

**错误处理的哲学。** `local_structured_store.py` 里有个注释说 "Blob is already persisted; index will be re-synced on next save." 这是正确的做法。blob 是真理之源，SQLite 只是缓存。很多人搞反这个顺序。

---

## 烂的部分

### 1. CLI dispatch 是屎山

`cli.py` 有 1242 行。不，1242 行本身不是问题——但如果有 1242 行全都是 `if command == "xxx": return asyncio.run(cmd_xxx())` 的 if-else 链，那就是问题。

你有一个 parser，然后你在 `command_name` 上做了一个巨大的 switch 语句。这不是 dispatch，这是 1995 年的 C 代码风格。Python 有 `dict`。你可以这样写：

```python
COMMANDS = {
    "init": lambda _: _ensure_data_dir(),
    "ingest": cmd_ingest,
    "wake-up": cmd_wake_up,
    ...
}
```

那 50 行 if-else 就是纯粹的噪音。更糟糕的是，每个 `cmd_xxx` 函数都在内部重新创建 `LocalMemoryBackend` 和 `init()`——这是**重复的模式**，不是**抽象**。

### 2. Interface protocols 的形式主义

你有四个协议类：`VerbatimStore`、`StructuredStore`、`MemoryBackend`、`ProjectProfileStore`。然后每个协议只有一个实现（`LocalVerbatimStore`、`LocalStructuredStore`、`LocalMemoryBackend`、`LocalProjectProfileStore`）。

**这他妈不是一个抽象，这是 Java 脑残综合征。** 如果你只有一个实现，接口就是浪费时间。你不需要定义一个 `Protocol` 来证明你会写 Python。特别是 `MemoryBackend` 接口——它基本上只是把两个 store 塞在一起加上 `init/close`。`LocalMemoryBackend` 甚至没有继承 `MemoryBackend`，它只是一个普通的类。那这协议是给谁看的？

如果未来计划里有"远程 S3 后端"或"Redis 后端"，我保留意见。现在？删除这些协议类，或者至少标记为 `@deprecated` 直到第二个实现出现。

### 3. cli.py 中公共代码的大量复制

看 `_wake_budget`（第 230 行）、`_status_project_async`（第 577 行）、`cmd_profile`（第 1072 行）、`cmd_wake_up`（第 806 行）。

它们在做完全一样的事：读取 profile/entries/rules/handoffs，计算 token 预算，格式化输出。每一个都是手写的，有细微的偏移——`_wake_budget` 用 `_disclosure_level`，但 `_status_project_async` 把同样的逻辑又手写了一遍。`cmd_profile` 也手写了一遍，但只少了一点点。

**你怎么能从同一个 bug 复制到三个不同地方的？** 把 token 预算计算拉到一个函数里。`_wake_budget` 已经在做了，但 `_status_project_async` 和 `cmd_profile` 不知道它的存在。

### 4. 命名让我头疼

- `_prompt_list_labeled` — 签名的四个参数不告诉任何人它在做什么。字段标签？项目描述？已有列表？第三个参数叫 `existing`，第四个完全没有。这是一个函数，不是沙拉。

- `_claude_session_count` 和 `_codex_session_count` — 它们只是 `len(_recent_*_sessions(...))` 的包装器。对，我算得出来一个函数里调用 `len()` 需要多少脑力。这些包装器每个都是一行——你不需要一个函数来解释 `len(list)`。

- `_project_roots()` — 返回四个 `Path`，但 `[2]` 和 `[3]` 猜测用户在 fixtures 里。一个列表字面量作为搜索策略？真的吗？

### 5. 错误处理很脆弱

```python
except Exception:
    pass  # adapter.py line 106
```

**去你的。** 没有日志。没有指标。没有 "something went wrong, move on" 的信息。就静默吞掉整个会话解析。当用户问 "为什么我的 500 行会话没有被接入？"时——你无法回答，因为你的代码已经删除了证据。

`list_project_sessions` 用 `read_text()` 加载整个文件来计算行数（第 51 行）。对于一个 50MB 的日志文件，这会炸掉你的内存。用 `readline()` 来计数行——你已经有了文件句柄。

### 6. 过度工程和欠工程并存

- **过度工程：** `core/interfaces/__init__.py` 用命名空间包重新导出所有四个协议。当每个协议只有一个实现时，这不是抽象层，这是官僚主义。

- **欠工程：** `_extract_entries` 有 30 个硬编码的正则表达式，从 assistant 文本中手动抓取句子。它假设 `re.I` 就足够了。它把上下文砍到 `match_start-100` 到 `match_start+200` 而没有句子边界检测。"workaround" 匹配到了一个 Git 提交消息里的 "workaround"？很高兴它是一个假的 bug 条目。这才是真正的内存应该是 LLM 驱动的提取而不是正则表达式的地方——正则表达式很好，但加上 LLM 作为回退，否则你就是在收集垃圾。

### 7. CLI 设计看似友好但冗长

`quickstart` 做五件事：初始化、设置项目、检测 profile、列出会话、建议下一步。这没问题。

但 `cmd_doctor` 做同样的事情——初始化检查、项目解析、列出会话、状态显示、建议下一步——大约有 70 行与 `quickstart` 重复的代码。

`cmd_profile_edit` 有 80 行纯输入处理，散布在 cli.py 中。这应该是它自己的文件，或者是一个专用的输入处理模块。除非 "1242 行的 CLI 文件" 是你作为一个写纯 C 内核模块的人的身份——等等，我就是。

---

## 总结

| 方面 | 评级 |
|------|------|
| 存储层 (sqlite_index) | **好。保持这个。** |
| 接口抽象 | **在这个阶段是浪费的。** 去掉或合并。 |
| CLI dispatch | **可以改进。** 用 dict 替换 if-else 链。 |
| 代码重复 | **严重。** 三个地方手写 token 预算。 |
| 错误处理 | **脆弱。** 静默异常是坏的。 |
| 启发式提取 | **可以接受但天真的。** 纯正则没有 LLM 回退。 |
| 命名 | **有些太冗长，有些太隐晦。** |

**底线：** 这对一个 v1 来说是一个不错的项目。架构是合理的，SQLite 集成很扎实，CLI UX 虽然冗长但思路正确。最大的罪过是接口形式主义和代码重复——下次写好点。
