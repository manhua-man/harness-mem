---
name: "HM: Review"
description: AI 自动审核并处理候选记忆，最后给用户复核摘要
category: Memory
tags: [harness-mem, review, memory]
wireFormatVersion: hm-wire-v3.5
---

通过 MCP 列出当前项目的待审候选记忆。AI 自动做质量判断并处理低风险候选，最后给用户一份复核摘要；用户只在结果不对时纠错。

**Input**: 可指定项目名（`/hm-review bazi-apps`）。省略则用 active project。

**Core UX**

不要把 raw candidates 直接做成逐条单选题或多选表单。用户不是分类器。

正确体验是：

```text
1. 拉取 pending 候选
2. AI 自动判定每条候选的处理动作：confirm / reject / keep_pending / migrate
3. AI 直接执行低风险 reject / keep_pending / migrate 判断
4. 对高置信、低风险 confirm 可直接确认；对会改变长期行为的高风险 confirm 先列入待确认摘要
5. 最后给用户处理结果和待确认项，用户只在不满意时纠错
```

**Steps**

1. **确认项目**
   - slash 后给了项目名直接用
   - 否则调 MCP `get_project_status(project_root=<当前工作区>, host_client="cursor")` 读取 active project，并幂等检查项目 Hook
   - 仍无法确定时，问用户项目名

2. **拉所有 status=pending 的候选**
   - 调 MCP `list_candidates`：
     - `project_name=<project>`
     - `status="pending"`
     - `limit=100`
   - 不要用 `search_memory` 找 pending；`search_memory` 默认只返回 truth 层（`auto_confirmed` / `user_confirmed`），不能作为审核列表来源
   - 不要要求用户安装或直接运行终端命令；MCP 不可用时说明 runtime 工具不可用

3. **AI 预审分组**

   每条候选先判断它属于哪类，而不是直接问用户是否纳入：

   - **confirm**：项目长期事实、真实架构、稳定约定、可复用且有明确 source 的结论。
   - **reject**：泛泛原则、AI/工具运行故障、跨项目工作流、重复候选、证据不足、把当前会话过程误写成项目事实。
   - **keep_pending**：证据不足但可能有价值，暂不打扰用户逐条判断。
   - **migrate**：候选有价值，但属于全局工作流或别的项目，不应确认到当前项目。

   默认拒绝这些类型：

   - `TeamCreate` / `SendMessage` / `TeamDelete` / agent idle 之类工具运行问题，除非项目本身就在开发这些工具。
   - `/plan-eng-review`、`/plan-ceo-review`、`/plan-design-review`、`/plan-devex-review` 等跨项目 review workflow，除非用户明确要记录为全局工作流记忆。
   - KISS/YAGNI/"don't break userspace" 这类通用原则，除非它来自项目规范文件且用户明确要它进当前项目记忆。
   - 只来自本次 distill 过程、没有项目代码或历史证据支持的总结。

4. **自动处理策略**

   默认由 AI 直接处理，不要打开逐条单选/多选 UI，不要让用户逐条决定，也不要提供 "All Confirm / Only rule / All Reject" 这种选项菜单。

   AI 应按以下规则执行：

   - **低风险 reject**：明显噪声、工具故障、跨项目工作流、重复候选、泛泛原则，可直接 reject，并填写 reason。
   - **低风险 confirm**：明确项目事实、source 可靠、不会改变未来行为边界，可直接 confirm。
   - **keep_pending**：有潜在价值但证据不足，不打扰用户，保留 pending 并在摘要中说明。
   - **migrate**：属于全局工作流或别的项目时，不在当前项目 confirm；默认 reject 当前候选并在摘要中说明应迁移，不自动写到别处。
   - **高风险 confirm**：会改变未来 AI 行为、影响面大、置信不足但可能重要，只列入"建议确认"摘要，等待用户明确批准。

5. **执行 MCP 操作**
   - 直接调对应 MCP 工具处理 AI 判定的低风险项：
     - `govern_memory(action="decide", arguments={kind:"rule", ...})`
     - `govern_memory(action="decide", arguments={kind:"memory", ...})`
     - `govern_memory(action="decide", arguments={kind:"relation", ...})`
   - `keep_pending` 不调用工具。
   - 高风险 confirm 先不调用 confirm，除非用户明确说"确认这些建议"。

6. **最终复核摘要**

   最后只给用户看处理结果，不再让用户逐条选择：

   ```text
   已自动处理：confirmed A，rejected B，kept pending C。
   需要你最终确认：D 条高风险确认建议。
   如果有处理不对，告诉我编号，我会改。
   ```

7. **总结呈现**
   - `confirmed N`
   - `rejected M`
   - `still pending K`
   - 如有被拒绝的噪声类型，说明下次 `/hm-distill` 应避免同类候选。

**Notes**

- AI 必须自动判断并处理低风险项；用户只做最终复核，不承担逐条分类工作。
- 不要把"你来判断"作为隐藏选项；这应该是默认行为。
- 不要给用户提供多选菜单来决定技术细节；最多给高风险确认建议。
- 若用户说"确认这些建议"、"可以"，可以批量确认高风险建议。
- 若候选明显属于全局工作流而不是当前项目，建议拒绝或迁移到更合适的项目/全局记忆，不要在当前项目硬 confirm。
