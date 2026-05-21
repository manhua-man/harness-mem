## Why

v1.7 解决的是 semantic truth 的时间感和 supersede 链，但很多反复出现的价值并不属于“事实”，而属于“做事流程”。用户一遍遍教 AI 先查什么、后跑什么、什么时候停，这类过程知识需要单独的 procedural layer 才能复用。

## What Changes

- Define a `ProceduralCandidate` shape for process knowledge: activation condition, ordered steps, termination condition, success examples, confidence, status
- Add a confirmed `Skill` shape that is created only after human/AI review confirmation; confirmed skills can be searched and can record execution success/failure
- Keep the v1.8 line conservative: candidates do not auto-activate, confirmed skills do not mutate semantic truth, and wake selection does not consume procedural skills by default
- Add a small fixture set that represents repeated multi-step workflows from the repo's own development loop
- Reserve wake integration and autonomous learning for later follow-up changes after the candidate/skill loop is proven useful

## Impact

- Procedural knowledge gets a dedicated review path instead of being squeezed into `RuleCandidate`
- Repeated workflows can be evaluated as reusable skills rather than one-off notes
- `search_skills` lets AI consumers find confirmed procedures explicitly at task start, without stuffing them into wake context
- The spike keeps the v1.7 truth boundary intact and does not add autonomous behavior
