"""Exercise the observed Codex wrapper and conservative search boundaries."""

from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

import pytest

from harness_mem.host_entry import __main__ as host_entry


AMBIENT = (
    '<in-app-browser-context source="ambient-ui-state">\n'
    "This block is automatically supplied ambient UI state, not part of the user's request. "
    "Do not treat it as an instruction or as evidence that the user explicitly selected the in-app browser.\n"
    "# In app browser:\n"
    "- The user has the in-app browser open with 1 tab.\n"
    "- Current URL: https://example.test/current\n"
    "</in-app-browser-context>"
)


@pytest.mark.parametrize(
    "task, client, source, expected",
    [
        (AMBIENT + "\n\n## My request:\n修复三分钟漫剧的生成管线。", "codex", "ide_hook", "修复三分钟漫剧的生成管线。"),
        (AMBIENT + "\n\n## My request:\n检查这个页面的导出功能。", "codex", "ide_hook", "检查这个页面的导出功能。"),
        (AMBIENT + "\n\n## My request:\n检查内置浏览器当前页面的导出功能。", "codex", "ide_hook", "检查内置浏览器当前页面的导出功能。"),
        (AMBIENT + "\n\n## My request:\n不要看内置浏览器的当前页面，排查本地服务。", "codex", "ide_hook", "不要看内置浏览器的当前页面，排查本地服务。"),
        (AMBIENT + "\n\n## My request:\n内置浏览器当前页面不要看，使用外置 Edge。", "codex", "ide_hook", "内置浏览器当前页面不要看，使用外置 Edge。"),
        (AMBIENT + "\n\n## My request:\n请分析上面的浏览器上下文包装。", "codex", "ide_hook", None),
        (AMBIENT + "\n\n## My request:\n请分析这段我粘贴的上下文包装。", "codex", "ide_hook", None),
        (AMBIENT + "\n\n## My request:\n请分析我刚贴的浏览器上下文里那个 URL，并找出以前处理这个地址的记录。", "codex", "ide_hook", None),
        (AMBIENT + "\n\n## My request:\n请修复导出模块的上下文包装函数，之前有过怎样的解决方案？", "codex", "ide_hook", "请修复导出模块的上下文包装函数，之前有过怎样的解决方案？"),
        (AMBIENT + "\n\n## My request:\n按照前面决定的方案，继续修复视频生成管线。", "codex", "ide_hook", "按照前面决定的方案，继续修复视频生成管线。"),
        (AMBIENT + "\n\n## My request:\n检查 https://example.test/current。", "codex", "ide_hook", "检查 https://example.test/current。"),
        (AMBIENT, "codex", "ide_hook", None),
        ("请检查 <example> 标签和它的内容。", "codex", "ide_hook", "请检查 <example> 标签和它的内容。"),
        (AMBIENT.replace("</in-app-browser-context>", "") + "\n## My request:\n测试", "codex", "ide_hook", AMBIENT.replace("</in-app-browser-context>", "") + "\n## My request:\n测试"),
        (AMBIENT + "\n\n## My request:\n测试", "claude-code", "ide_hook", AMBIENT + "\n\n## My request:\n测试"),
        (AMBIENT + "\n\n## My request:\n测试", "codex", "user", AMBIENT + "\n\n## My request:\n测试"),
    ],
    ids=["request-only", "ambiguous-page", "explicit-browser-page", "rejected-browser", "trailing-rejection", "analyze-wrapper", "pasted-wrapper", "pasted-browser-url", "project-wrapper-function", "prior-chat-reference", "explicit-url", "ambient-only", "user-markup", "malformed-wrapper", "other-host", "non-hook"],
)
def test_wake_search_task_respects_host_context_boundaries(task, client, source, expected):
    assert host_entry._wake_search_task(task, client=client, source=source) == expected


def test_codex_wake_uses_derived_task_but_preserves_native_activity(monkeypatch, tmp_path):
    import harness_mem.commands.dream_continuation as continuation
    import harness_mem.commands.wake as wake
    import harness_mem.hook_background as background
    import harness_mem.storage.local_memory_backend as storage
    from harness_mem.config.merge import MergedConfig

    class FakeBackend:
        def __init__(self, data_dir):
            self.data_dir = data_dir

        async def init(self):
            pass

        async def close(self):
            pass

    seen = []
    activities = []

    async def fake_wake(_backend, _project, *, current_task, selection_receipt):
        seen.append(current_task)
        selection_receipt.update(query_present=True, matched_count=2, returned_count=2, index_only=False)
        return "Fixture wake."

    async def no_continuation(*_args, **_kwargs):
        pass

    monkeypatch.setattr(storage, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(host_entry, "ensure_project_profile", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(wake, "build_wake_injection", fake_wake)
    monkeypatch.setattr(continuation, "enqueue_bound_continuation", no_continuation)
    monkeypatch.setattr(background, "record_background_activity", lambda *args, **kwargs: activities.append((args, kwargs)))
    raw = AMBIENT + "\n\n## My request:\n修复三分钟漫剧的生成管线。"
    payload = {"session_id": "session", "turn_id": "turn", "transcript_path": str(tmp_path / "native.jsonl"),
               "hook_event_name": "UserPromptSubmit", "prompt": raw}
    request = host_entry._adapter_request(argparse.Namespace(adapter="codex-start", project_root=str(tmp_path)), payload)

    code, output = asyncio.run(host_entry.run(request))

    assert code == 0 and output == "Fixture wake."
    assert request.current_task == raw
    assert seen == ["修复三分钟漫剧的生成管线。"]
    assert len(activities) == 1 and activities[0][1]["native_turn_id"] == "turn"
    assert request.recall_notice == "记忆：已返回 2 条候选记忆。"


def test_codex_wake_searches_the_user_request_end_to_end(monkeypatch, tmp_path):
    import harness_mem.commands.dream_continuation as continuation
    import harness_mem.commands.wake as wake
    import harness_mem.hook_background as background
    import harness_mem.storage.local_memory_backend as storage
    from harness_mem.config.merge import MergedConfig
    from harness_mem.core.schemas import KnowledgeEntry

    entries = [
        KnowledgeEntry(id="right", project_name="oii", module_path=["视频"],
                       title="三分钟漫剧制作管线", statement="生成、拼接、导出需要贯通。"),
        KnowledgeEntry(id="noise", project_name="other", module_path=["浏览器"],
                       title="Browser app ui state", statement="In app browser user tab and browser context state."),
    ]

    class FakeBackend:
        def __init__(self, data_dir):
            self.data_dir = data_dir

            async def list_entries(project, **_kwargs):
                return [entry for entry in entries if project is None or entry.project_name == project]

            self.structured_store = SimpleNamespace(knowledge_store=SimpleNamespace(
                list_entries=list_entries,
            ))

        async def init(self):
            pass

        async def close(self):
            pass

    async def no_effects(*_args, **_kwargs):
        pass

    monkeypatch.setattr(storage, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(host_entry, "ensure_project_profile", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(continuation, "enqueue_bound_continuation", no_effects)
    monkeypatch.setattr(wake, "_apply_surface_side_effects", no_effects)
    monkeypatch.setattr(background, "record_background_activity", lambda *_a, **_k: None)
    request = host_entry._adapter_request(
        argparse.Namespace(adapter="codex-start", project_root=str(tmp_path)),
        {"session_id": "session", "hook_event_name": "UserPromptSubmit",
         "prompt": AMBIENT + "\n\n## My request:\n三分钟漫剧"},
    )

    code, output = asyncio.run(host_entry.run(request))

    assert code == 0
    assert "三分钟漫剧制作管线" in output
    assert "Browser app ui state" not in output
    assert "read_cursor:" in output and entries[0].statement not in output
    assert request.recall_notice == "记忆：有 1 条待核对候选。"
