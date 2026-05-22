"""Shared fixture data for loop_harness scenarios.

Each fixture pairs a Claude Code session transcript with a hand-labeled
expected extraction set. The transcripts are written in a real-session
style (multi-paragraph, mixed signal/noise) rather than synthetic one-liners.

Adding a new fixture:

1. Add an entry to ``LOOP_FIXTURES``. ``user_text`` and ``assistant_texts``
   feed straight into ``tests.helpers.write_claude_session``.
2. Fill ``expected_signals`` with the rule fragments a competent reviewer
   would extract; the harness checks substring match against the distilled
   ``MemoryEntry.content``.
3. Fill ``expected_noise`` with text fragments that *should not* surface
   as memory (banter, status updates, generic encouragement, etc).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LoopFixture:
    """One loop_harness session sample plus hand-labeled ground truth."""

    fixture_id: str
    project_name: str
    session_id: str
    user_text: str
    assistant_texts: list[str]
    # Substring fragments that *should* be extracted as long-term memory.
    expected_signals: list[str] = field(default_factory=list)
    # Substring fragments that *should not* be extracted (noise / banter).
    expected_noise: list[str] = field(default_factory=list)


LOOP_FIXTURES: list[LoopFixture] = [
    LoopFixture(
        fixture_id="tauri-ipc-windows",
        project_name="inkpad",
        session_id="sess-tauri-ipc-001",
        user_text=(
            "Yesterday I burned two hours on Tauri IPC randomly hanging on "
            "Windows when I send the document tree across. Can you take a "
            "look and figure out what's going on?"
        ),
        assistant_texts=[
            # Signal: a real, project-specific bug fix worth remembering.
            "I traced the hang to the emit channel — on Windows, large "
            "payloads over Tauri's emit deadlock the webview when the buffer "
            "exceeds ~1MB. The fix was to switch from emit to invoke for "
            "any payload larger than the document tree threshold. Confirmed "
            "with a 4MB test payload after the change.",
            # Noise: chatty status update with no reusable knowledge.
            "Glad we got that one nailed down — that was a tricky one.",
            # Signal: a real architectural decision.
            "We decided to use invoke as the default for all data-shaped "
            "IPC and reserve emit only for fire-and-forget UI events.",
        ],
        # NOTE on "Windows": Windows lives in a different sentence than the
        # "the fix was" pattern match, so the v1.8 sentence-bounded extractor
        # will not include it in the captured content. We keep "Windows" in
        # the labeled signals on purpose — it surfaces a real and ongoing
        # tradeoff: sentence-bounded extraction trades cross-sentence context
        # for cleaner content. The harness should report that honestly via
        # recall, not hide it with a permissive label.
        expected_signals=[
            "emit",
            "invoke",
            "Windows",
        ],
        expected_noise=[
            "Glad we got that one nailed down",
        ],
    ),
    LoopFixture(
        fixture_id="pnpm-monorepo-convention",
        project_name="inkpad",
        session_id="sess-pnpm-monorepo-002",
        user_text=(
            "Help me wire up the new editor package in the monorepo."
        ),
        assistant_texts=[
            # Signal: a project convention.
            "I always use pnpm workspaces for cross-package linking in "
            "this monorepo, so I'll add the new package under "
            "packages/editor and reference it from apps/desktop via "
            "workspace:* in package.json.",
            # Noise: tooling status update.
            "Installed the dependencies, lockfile updated.",
        ],
        expected_signals=[
            "pnpm",
        ],
        expected_noise=[
            "Installed the dependencies",
        ],
    ),
    LoopFixture(
        fixture_id="auth-jwt-expiry",
        project_name="inkpad",
        session_id="sess-auth-jwt-003",
        user_text=(
            "Users keep getting silently logged out. Can you find why?"
        ),
        assistant_texts=[
            # Signal: a real bug root cause + resolution.
            "The root cause was that we never validated JWT expiry on the "
            "client before issuing API requests, so expired tokens silently "
            "404'd from the gateway. The fix was to check exp claim against "
            "Date.now() in the auth interceptor and refresh proactively.",
            # Noise: hypothetical exploration that user prompts contain;
            # heuristic distill should not turn user-side hypotheticals
            # into memory.
            "If we wanted, we could also explore rotating refresh tokens.",
        ],
        expected_signals=[
            "JWT",
            "fix",
        ],
        expected_noise=[
            "we could also explore",
        ],
    ),
]


def get_fixture(fixture_id: str) -> LoopFixture:
    for fixture in LOOP_FIXTURES:
        if fixture.fixture_id == fixture_id:
            return fixture
    raise KeyError(f"Unknown loop fixture: {fixture_id}")
