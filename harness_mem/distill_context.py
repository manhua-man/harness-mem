"""Distill 路径的只读边界 (v1.6.1)。

`harness-mem` 的护城河是 ``auditable memory runtime`` ——所有 truth 变更必须保留
历史并经过审核。distill 是 LLM 主导、最容易"顺手清理"的路径，所以本模块把
distill 能拿到的写边界静态收紧为"只能落候选层"：

- 读：``read_observations / search / list_confirmed_rules / list_relation_facts /
  compare``
- 写：``suggest_memory_entry / suggest_relation_fact / suggest_rule``，强制
  ``status="pending"``
- 任何对 ``ConfirmedRule / RelationFact / Observation / MemoryEntry`` 的
  ``delete / update / purge`` 类访问 → ``DistillReadOnlyError``

这条边界在 v1.6.2 持久化向量落地之前先做掉，避免 distill 在拿到"读全库 + 跑
聚类"能力后绕过候选层。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_mem.core.schemas import MemoryEntry, RelationFact

if TYPE_CHECKING:
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class DistillReadOnlyError(RuntimeError):
    """raised 当 distill 路径试图访问 mutator 类方法。

    携带 ``method`` 与 ``hint`` 字段，帮助调用方迁移到候选层入口。
    """

    def __init__(self, method: str, hint: str) -> None:
        super().__init__(
            f"{method} is not allowed from distill context. {hint}"
        )
        self.method = method
        self.hint = hint


_FORBIDDEN_KEYWORDS: tuple[str, ...] = (
    "delete",
    "update",
    "purge",
    "mutate",
    "remove",
    "drop",
)


class DistillContext:
    """distill adapter 的唯一入口，封装只读 + 候选写两类操作。

    Adapter 方法签名 MUST 接受 ``DistillContext`` 而不是 ``LocalMemoryBackend``：
    这样静态层就保证 adapter 拿不到 ``backend.structured_store.delete_*``。
    """

    def __init__(self, backend: "LocalMemoryBackend") -> None:
        self._backend = backend

    @property
    def backend(self) -> "LocalMemoryBackend":
        """读路径需要直接访问 backend 时的受控入口。

        故意命名为 ``backend`` 而不是 ``_backend``——adapter 旧代码若直接 ``ctx.backend.structured_store.delete_*``
        仍会被边界单测抓到。这条 property 不是 mutator 防线，只是迁移期的便利
        访问；真正的防线是 ``__getattr__`` 拒绝 mutator-shaped names。
        """
        return self._backend

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    async def read_observations(
        self,
        *,
        session_id: str | None = None,
        project_name: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        observations = await self._backend.verbatim_store.list(
            session_id=session_id,
            limit=limit,
        )
        if project_name is None:
            return list(observations)
        return [
            obs
            for obs in observations
            if obs.metadata.get("project_name") == project_name
        ]

    async def list_memory_entries(
        self, project_name: str, *, limit: int = 1000
    ) -> list[MemoryEntry]:
        return await self._backend.structured_store.list_memory_entries(
            project_name, limit=limit
        )

    async def list_relation_facts(
        self, project_name: str, *, limit: int = 1000
    ) -> list[RelationFact]:
        return await self._backend.structured_store.list_relation_facts(
            project_name, limit=limit
        )

    async def list_confirmed_rules(self, project_name: str) -> list[Any]:
        return await self._backend.structured_store.list_confirmed_rules(project_name)

    async def search(
        self,
        query: str,
        *,
        project_name: str | None,
        scope: str = "project",
        mode: str = "auto",
        memory_entry_limit: int = 20,
        observation_limit: int = 20,
    ) -> tuple[list[MemoryEntry], list[Any]]:
        from harness_mem.read_api import search_memory  # local import to avoid cycle

        return await search_memory(
            self._backend,
            project_name=project_name,
            query=query,
            scope=scope,
            mode=mode,
            memory_entry_limit=memory_entry_limit,
            observation_limit=observation_limit,
        )

    def compare(
        self, left: Any, right: Any
    ) -> tuple[Any, Any, dict[str, Any]]:
        """v1.6.1 的最小 compare：返回两个对象与简单 diff 摘要。

        v1.7 引入 bi-temporal 字段后，本方法会扩展为生成 supersede 候选的输入。
        """
        diff: dict[str, Any] = {}
        if hasattr(left, "content") and hasattr(right, "content"):
            diff["content_changed"] = left.content != right.content
        if hasattr(left, "category") and hasattr(right, "category"):
            diff["category_changed"] = left.category != right.category
        return left, right, diff

    # ------------------------------------------------------------------
    # Write paths -- candidate layer only
    # ------------------------------------------------------------------

    async def suggest_memory_entry(self, entry: MemoryEntry) -> MemoryEntry:
        """以 ``status="pending"`` 落盘 MemoryEntry 候选。

        v1.6.1 起 distill 默认走这条路径；旧的 "立即 accepted" 行为只能由 CLI
        ``--auto-confirm`` flag 在外层显式转换。
        """
        entry.status = "pending"
        await self._backend.structured_store.save_memory_entry(entry)
        return entry

    async def suggest_relation_fact(self, fact: RelationFact) -> RelationFact:
        fact.status = "pending"
        await self._backend.structured_store.save_relation_fact(fact)
        return fact

    async def suggest_rule(self, candidate: Any) -> Any:
        """RuleCandidate 已经走候选层；本方法保持调用形态对称。"""
        await self._backend.structured_store.save_rule_candidate(candidate)
        return candidate

    # ------------------------------------------------------------------
    # Boundary enforcement
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """阻断 mutator-shaped attribute 名。

        这是"约定 + 类型注解 + 边界单测"中的第三层：即使 adapter 错误地拿到
        ``ctx.delete_memory_entry`` 这种属性，也会立即 raise，而不是因为属性不
        存在拿到 ``AttributeError``。
        """
        # __getattr__ 只在常规查找失败时触发，因此走到这里说明 name 确实不是
        # 显式定义的成员。检查 mutator 关键字命中即拒绝。
        lowered = name.lower()
        for keyword in _FORBIDDEN_KEYWORDS:
            if keyword in lowered:
                raise DistillReadOnlyError(
                    name,
                    "Use DistillContext.suggest_memory_entry / "
                    "suggest_relation_fact / suggest_rule to propose changes "
                    "via the candidate layer.",
                )
        raise AttributeError(name)
