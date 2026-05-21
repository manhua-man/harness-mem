## Why

v1.7 解决的是 semantic truth 的时间感和 supersede 链，但很多反复出现的价值并不属于“事实”，而属于“做事流程”。用户一遍遍教 AI 先查什么、后跑什么、什么时候停，这类过程知识需要单独的 procedural layer 才能复用。

## What Changes

- Define a `Skill` candidate shape for process knowledge: activation condition, ordered steps, termination condition, success examples, confidence, status
- Keep the v1.8 spike read-only at first: extract and review skill candidates, but do not auto-activate them or let them mutate truth
- Add a small fixture set that represents repeated multi-step workflows from the repo's own development loop
- Reserve retrieval and wake integration for later follow-up changes after the candidate loop is proven useful

## Impact

- Procedural knowledge gets a dedicated review path instead of being squeezed into `RuleCandidate`
- Repeated workflows can be evaluated as reusable skills rather than one-off notes
- The spike keeps the v1.7 truth boundary intact and does not add autonomous behavior
