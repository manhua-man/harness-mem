import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "tools" / "session-distill" / "bin" / "session-distill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("session_distill_core", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SessionDistillCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()

        self.module.DISTILL_DIR = self.home / ".codex" / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.MEMORY_DRAFTS_DIR = self.module.DISTILL_DIR / "memory-drafts"
        self.module.KB_BACKUPS_DIR = self.module.DISTILL_DIR / "backups" / "knowledge-base"
        self.module.KB_REVIEW_STATE_FILE = self.module.DISTILL_DIR / "kb-review-state.json"
        self.module.PRUNED_SOURCES_FILE = self.module.DISTILL_DIR / "pruned-sources.jsonl"
        self.module.PROJECTS_DIR = self.home / ".claude" / "projects"
        self.module.CODEX_RAW_ROOTS = (
            self.home / ".codex" / "archived_sessions",
            self.home / ".codex" / "sessions",
        )
        self.project_path = self.module.PROJECTS_DIR / "sample-project"
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.module.ensure_dirs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_jsonl(self, session_name, records, directory=None):
        target_dir = directory or self.project_path
        target_dir.mkdir(parents=True, exist_ok=True)
        session_path = target_dir / f"{session_name}.jsonl"
        with session_path.open("w", encoding="utf-8") as handle:
            for record in records:
                if isinstance(record, str):
                    handle.write(record + "\n")
                else:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return session_path

    def bundle_session(self, session_name, force=False):
        self.module.cmd_index(self.project_path)
        self.module.cmd_bundle(self.project_path, next_count=1, force=force)
        return (self.module.PACKETS_DIR / f"{session_name}.md").read_text(encoding="utf-8")

    def make_turn_records(self, turn_number, final_text=None):
        final_text = final_text or f"Final answer {turn_number}"
        return [
            {
                "type": "user",
                "timestamp": f"2026-04-24T10:{turn_number:02d}:00Z",
                "message": {"content": f"User request {turn_number}"},
            },
            {
                "type": "assistant",
                "timestamp": f"2026-04-24T10:{turn_number:02d}:10Z",
                "message": {
                    "content": [{"type": "text", "text": f"Assistant update {turn_number}"}],
                    "stop_reason": "end_turn",
                },
                "uuid": f"assistant-{turn_number}",
            },
            {
                "type": "assistant",
                "timestamp": f"2026-04-24T10:{turn_number:02d}:20Z",
                "message": {
                    "content": [{"type": "text", "text": final_text}],
                    "stop_reason": "end_turn",
                },
                "uuid": f"assistant-final-{turn_number}",
            },
        ]

    def write_good_note(
        self,
        session_name,
        raw_review="Raw transcript reviewed: yes",
        summary="Reviewed the packet and source.",
    ):
        note_path = self.module.DISTILLED_DIR / f"{session_name}.md"
        note_path.write_text(
            "\n".join(
                [
                    f"# Session Note: {session_name}",
                    "",
                    "## Source",
                    f"- Session: `{session_name}`",
                    "",
                    "## Raw Review",
                    f"- {raw_review}",
                    "",
                    "## Summary",
                    f"- {summary}",
                    "",
                    "## Verification From Session",
                    "- Evidence supports the archival decision.",
                    "",
                    "## Promotion Decision",
                    "- No Promotion: session-only archival note.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return note_path

    def manifest_session(self, session_name):
        manifest = self.module.load_manifest()
        return next(s for s in manifest["sessions"] if s["session_id"] == session_name)

    def test_long_session_tail_is_preserved(self):
        records = []
        for index in range(1, 16):
            tail_text = f"Tail evidence turn {index}" if index == 15 else f"Final answer {index}"
            records.extend(self.make_turn_records(index, final_text=tail_text))
        self.write_jsonl("sample-session", records)

        packet = self.bundle_session("sample-session", force=True)

        self.assertIn("## Turn 15", packet)
        self.assertIn("Tail evidence turn 15", packet)

    def test_compaction_marks_packet_partial(self):
        records = self.make_turn_records(1)
        records.append(
            {
                "type": "system",
                "subtype": "compact_boundary",
                "timestamp": "2026-04-24T10:01:30Z",
                "content": "conversation compacted",
                "compactMetadata": {"preTokens": 12000, "postTokens": 4000},
            }
        )
        self.write_jsonl("sample-session", records)

        packet = self.bundle_session("sample-session", force=True)

        self.assertIn("Coverage: `partial`", packet)
        self.assertIn("Compaction events: 1", packet)

    def test_invalid_json_and_orphan_tool_results_are_exposed(self):
        self.write_jsonl(
            "sample-session",
            [
                {"type": "user", "message": {"content": "hello"}},
                "{invalid json",
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": "missing-call", "content": "stdout"},
                        ]
                    },
                },
            ],
        )

        packet = self.bundle_session("sample-session", force=True)

        self.assertIn("Invalid JSON lines skipped: 1", packet)
        self.assertIn("Orphan tool results: 1", packet)
        self.assertIn("Coverage: `partial`", packet)

    def test_bundle_refreshes_when_source_grows(self):
        records = self.make_turn_records(1, final_text="Original final answer")
        session_path = self.write_jsonl("sample-session", records)

        first_packet = self.bundle_session("sample-session", force=True)
        self.assertIn("Original final answer", first_packet)

        with session_path.open("a", encoding="utf-8") as handle:
            for record in self.make_turn_records(2, final_text="Appended final answer"):
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        self.module.cmd_index(self.project_path)
        self.module.cmd_bundle(self.project_path, next_count=1, force=False)
        second_packet = (self.module.PACKETS_DIR / "sample-session.md").read_text(encoding="utf-8")

        self.assertIn("Appended final answer", second_packet)

    def test_nonstandard_project_name_can_be_resolved(self):
        alias = "C--Users-TestUser--observer-sessions"
        alias_path = self.module.PROJECTS_DIR / alias
        alias_path.mkdir(parents=True, exist_ok=True)

        resolved = self.module.find_project_path(alias)
        self.assertEqual(alias_path, resolved)

    def test_mark_distilled_requires_session_note(self):
        self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)

        result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(1, result)
        self.assertEqual("bundled", self.manifest_session("sample-session")["status"])

    def test_mark_distilled_requires_raw_review_for_partial_packet(self):
        records = self.make_turn_records(1)
        records.append({"type": "system", "subtype": "compact_boundary"})
        self.write_jsonl("sample-session", records)
        self.bundle_session("sample-session", force=True)
        self.write_good_note("sample-session", raw_review="Raw transcript reviewed: no")

        result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(1, result)
        self.assertEqual("bundled", self.manifest_session("sample-session")["status"])

    def test_mark_distilled_blocks_pending_memory_draft(self):
        self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)
        self.write_good_note("sample-session")
        draft_path = self.module.MEMORY_DRAFTS_DIR / "sample-session.json"
        draft_path.write_text(
            json.dumps({"entries": [{"id": "entry-1", "review_status": "pending"}]}),
            encoding="utf-8",
        )

        result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(1, result)
        self.assertEqual("bundled", self.manifest_session("sample-session")["status"])

    def test_mark_distilled_blocks_unstable_same_source_knowledge_entry(self):
        self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)
        self.write_good_note("sample-session")
        self.module.KNOWLEDGE_FILE.write_text(
            "\n".join(
                [
                    "# Session Distill Knowledge Base",
                    "",
                    "## Review queue",
                    "- TODO: maybe temporary workaround. [source: sample-session]",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(1, result)
        self.assertEqual("bundled", self.manifest_session("sample-session")["status"])

    def test_mark_distilled_deletes_codex_raw_source_and_keeps_manifest_state(self):
        raw_dir = self.home / ".codex" / "archived_sessions"
        source = self.write_jsonl("sample-session", self.make_turn_records(1), directory=raw_dir)
        manifest = {
            "version": 1,
            "updated_at": "",
            "sessions": [
                {
                    "session_id": "sample-session",
                    "file_name": source.name,
                    "file_path": str(source),
                    "file_size_bytes": source.stat().st_size,
                    "source_mtime": source.stat().st_mtime,
                    "size": "1.0KB",
                    "status": "bundled",
                    "bundle_path": str(self.module.PACKETS_DIR / "sample-session.md"),
                    "distilled_path": None,
                }
            ],
        }
        self.module.save_manifest(manifest)
        self.module.generate_packet(manifest["sessions"][0], self.module.PACKETS_DIR / "sample-session.md")
        self.write_good_note("sample-session")

        result = self.module.cmd_mark("sample-session", "distilled")

        session = self.manifest_session("sample-session")
        self.assertEqual(0, result)
        self.assertFalse(source.exists())
        self.assertEqual("distilled", session["status"])
        self.assertTrue(session["source_missing"])
        self.assertIn("raw_deleted_at", session)

    def test_mark_distilled_keeps_non_codex_raw_source(self):
        source = self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)
        self.write_good_note("sample-session")

        result = self.module.cmd_mark("sample-session", "distilled")

        session = self.manifest_session("sample-session")
        self.assertEqual(0, result)
        self.assertTrue(source.exists())
        self.assertEqual("outside_codex_raw_roots", session["raw_retained_reason"])

    def test_prune_removes_source_missing_manifest_placeholders_only_when_applied(self):
        manifest = {
            "version": 1,
            "updated_at": "",
            "sessions": [
                {"session_id": "gone", "status": "distilled", "source_missing": True},
                {"session_id": "kept", "status": "distilled", "source_missing": False},
            ],
        }
        self.module.save_manifest(manifest)

        dry_run = self.module.cmd_prune("distilled,skipped", source_missing=True, apply=False)
        self.assertEqual(0, dry_run)
        self.assertIsNotNone(self.module.find_manifest_session(self.module.load_manifest(), "gone"))

        applied = self.module.cmd_prune("distilled,skipped", source_missing=True, apply=True)
        self.assertEqual(0, applied)
        new_manifest = self.module.load_manifest()
        self.assertIsNone(self.module.find_manifest_session(new_manifest, "gone"))
        self.assertIsNotNone(self.module.find_manifest_session(new_manifest, "kept"))

    def test_prune_refuses_non_handled_statuses(self):
        manifest = {
            "version": 1,
            "updated_at": "",
            "sessions": [
                {"session_id": "new-one", "status": "new", "source_missing": True},
                {"session_id": "bundled-one", "status": "bundled", "source_missing": True},
            ],
        }
        self.module.save_manifest(manifest)

        result = self.module.cmd_prune("bundled,new", source_missing=True, apply=True)

        self.assertEqual(1, result)
        new_manifest = self.module.load_manifest()
        self.assertIsNotNone(self.module.find_manifest_session(new_manifest, "new-one"))
        self.assertIsNotNone(self.module.find_manifest_session(new_manifest, "bundled-one"))

    def test_prune_requires_source_missing_boundary(self):
        manifest = {
            "version": 1,
            "updated_at": "",
            "sessions": [
                {"session_id": "gone", "status": "distilled", "source_missing": True},
                {"session_id": "kept", "status": "distilled", "source_missing": False},
            ],
        }
        self.module.save_manifest(manifest)

        result = self.module.cmd_prune("distilled,skipped", source_missing=False, apply=True)

        self.assertEqual(1, result)
        new_manifest = self.module.load_manifest()
        self.assertIsNotNone(self.module.find_manifest_session(new_manifest, "gone"))
        self.assertIsNotNone(self.module.find_manifest_session(new_manifest, "kept"))

    def test_review_kb_classifies_entries_and_records_state(self):
        self.module.KNOWLEDGE_FILE.write_text(
            "\n".join(
                [
                    "# Session Distill Knowledge Base",
                    "",
                    "## Stable workflows",
                    "- Use packet first before raw review. [source: sample-session]",
                    "- TODO: maybe temporary workaround.",
                    "- This old rule is obsolete. [source: stale-session]",
                    "- Superseded by the new distill workflow. [source: old-session]",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.module.cmd_review_kb(20)

        state = json.loads(self.module.KB_REVIEW_STATE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(0, result)
        self.assertEqual(4, state["total_entries"])
        self.assertEqual(1, state["summary"]["stable"])
        self.assertEqual(1, state["summary"]["needs-review"])
        self.assertEqual(1, state["summary"]["stale"])
        self.assertEqual(1, state["summary"]["superseded"])

    def test_prune_kb_backs_up_and_removes_stale_entries(self):
        self.module.KNOWLEDGE_FILE.write_text(
            "\n".join(
                [
                    "# Session Distill Knowledge Base",
                    "",
                    "## Stable workflows",
                    "- Keep this stable workflow. [source: sample-session]",
                    "- This old rule is obsolete. [source: stale-session]",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.module.cmd_prune_kb("stale", dry_run=False)

        content = self.module.KNOWLEDGE_FILE.read_text(encoding="utf-8")
        backups = list(self.module.KB_BACKUPS_DIR.glob("knowledge-base-*.md"))
        self.assertEqual(0, result)
        self.assertIn("Keep this stable workflow", content)
        self.assertNotIn("obsolete", content)
        self.assertEqual(1, len(backups))

    def test_prune_kb_refuses_non_prunable_statuses(self):
        original = "\n".join(
            [
                "# Session Distill Knowledge Base",
                "",
                "## Stable workflows",
                "- Keep this stable workflow. [source: sample-session]",
                "- TODO: maybe temporary workaround.",
                "",
            ]
        )
        self.module.KNOWLEDGE_FILE.write_text(original, encoding="utf-8")

        result = self.module.cmd_prune_kb("stable,needs-review", dry_run=False)

        content = self.module.KNOWLEDGE_FILE.read_text(encoding="utf-8")
        backups = list(self.module.KB_BACKUPS_DIR.glob("knowledge-base-*.md"))
        self.assertEqual(1, result)
        self.assertEqual(original, content)
        self.assertEqual([], backups)

    def test_prune_kb_dry_run_does_not_write_backup_or_mutate(self):
        original = "\n".join(
            [
                "# Session Distill Knowledge Base",
                "",
                "## Stable workflows",
                "- Keep this stable workflow. [source: sample-session]",
                "- This old rule is obsolete. [source: stale-session]",
                "",
            ]
        )
        self.module.KNOWLEDGE_FILE.write_text(original, encoding="utf-8")

        result = self.module.cmd_prune_kb("stale", dry_run=True)

        content = self.module.KNOWLEDGE_FILE.read_text(encoding="utf-8")
        backups = list(self.module.KB_BACKUPS_DIR.glob("knowledge-base-*.md"))
        self.assertEqual(0, result)
        self.assertEqual(original, content)
        self.assertEqual([], backups)

    def test_verify_entry_outputs_recheck_questions(self):
        self.module.KNOWLEDGE_FILE.write_text(
            "- Use packet first before raw review. [source: sample-session]\n",
            encoding="utf-8",
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.module.cmd_verify_entry("sample-session")

        self.assertEqual(0, result)
        self.assertIn("Recheck questions", output.getvalue())
        self.assertIn("current code/config/docs", output.getvalue())

    def test_verify_entry_matches_keyword_in_knowledge_text(self):
        self.module.KNOWLEDGE_FILE.write_text(
            "- Cache invalidation policy should be verified before promotion. [source: old-session]\n",
            encoding="utf-8",
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.module.cmd_verify_entry("cache")

        self.assertEqual(0, result)
        self.assertIn("Cache invalidation policy", output.getvalue())
        self.assertIn("Recheck questions", output.getvalue())

    def test_mark_distilled_reminds_when_kb_review_is_due(self):
        self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)
        self.write_good_note("sample-session")
        entries = [
            f"- Stable workflow {index} for packet review. [source: old-session-{index}]"
            for index in range(1, 6)
        ]
        self.module.KNOWLEDGE_FILE.write_text("\n".join(entries) + "\n", encoding="utf-8")
        self.module.KB_REVIEW_STATE_FILE.write_text(
            json.dumps({"reviewed_at": "2026-05-01T00:00:00Z", "total_entries": 0}),
            encoding="utf-8",
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(0, result)
        self.assertIn("/hm:review-kb --next 20", output.getvalue())

    def test_mark_distilled_does_not_remind_review_before_threshold(self):
        self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)
        self.write_good_note("sample-session")
        entries = [
            f"- Stable workflow {index} for packet review. [source: old-session-{index}]"
            for index in range(1, 5)
        ]
        self.module.KNOWLEDGE_FILE.write_text("\n".join(entries) + "\n", encoding="utf-8")
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(0, result)
        self.assertNotIn("/hm:review-kb --next 20", output.getvalue())

    def test_bundle_reminds_verify_entry_when_packet_hits_old_knowledge(self):
        self.module.KNOWLEDGE_FILE.write_text(
            "- Authentication token refresh workflow stays in project memory. [source: old-session]\n",
            encoding="utf-8",
        )
        self.write_jsonl(
            "sample-session",
            self.make_turn_records(1, final_text="Authentication token refresh failed again."),
        )
        output = io.StringIO()

        with redirect_stdout(output):
            self.module.cmd_index(self.project_path)
            result = self.module.cmd_bundle(self.project_path, next_count=1, force=True)

        self.assertEqual(0, result)
        self.assertIn("/hm:verify-entry", output.getvalue())
        self.assertIn("authentication", output.getvalue())

    def test_mark_distilled_reminds_verify_entry_when_note_hits_old_knowledge(self):
        self.write_jsonl("sample-session", self.make_turn_records(1))
        self.bundle_session("sample-session", force=True)
        self.write_good_note(
            "sample-session",
            summary="Cache invalidation policy changed during review.",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            "- Cache invalidation policy should be verified before promotion. [source: old-session]\n",
            encoding="utf-8",
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.module.cmd_mark("sample-session", "distilled")

        self.assertEqual(0, result)
        self.assertIn("/hm:verify-entry", output.getvalue())
        self.assertIn("cache", output.getvalue())


if __name__ == "__main__":
    unittest.main()
