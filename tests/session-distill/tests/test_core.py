import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(r"C:\Users\EDY\.claude\skills\manhua\session-distill\bin\session-distill.py")


def load_module():
    spec = importlib.util.spec_from_file_location("session_distill_core", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SessionDistillCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()

        self.module.DISTILL_DIR = self.home / ".claude" / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.PROJECTS_DIR = self.home / ".claude" / "projects"
        self.project_path = self.module.PROJECTS_DIR / "sample-project"
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.module.ensure_dirs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_jsonl(self, session_name, records):
        session_path = self.project_path / f"{session_name}.jsonl"
        with session_path.open("w", encoding="utf-8") as handle:
            for record in records:
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
        session_path = self.project_path / "sample-session.jsonl"
        with session_path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "hello"}}, ensure_ascii=False) + "\n")
            handle.write("{invalid json\n")
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {"type": "tool_result", "tool_use_id": "missing-call", "content": "stdout"},
                            ]
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
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
        alias = "C--Users-EDY--claude-mem-observer-sessions"
        alias_path = self.module.PROJECTS_DIR / alias
        alias_path.mkdir(parents=True, exist_ok=True)

        resolved = self.module.find_project_path(alias)
        self.assertEqual(alias_path, resolved)


if __name__ == "__main__":
    unittest.main()
