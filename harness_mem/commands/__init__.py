"""Commands module — CLI implementation entry points."""

from harness_mem.commands.doctor import cmd_doctor
from harness_mem.commands.ingest import cmd_ingest
from harness_mem.commands.import_bridge import cmd_import
from harness_mem.commands.maintenance import (
    cmd_export_json_snapshot,
    cmd_migrate_store_v2,
    cmd_state_audit,
)
from harness_mem.commands.profile import cmd_profile, cmd_profile_edit, cmd_use
from harness_mem.commands.purge import cmd_purge
from harness_mem.commands.search import (
    cmd_search,
    cmd_search_raw,
    cmd_show,
    cmd_timeline,
    cmd_trace_relations,
)
from harness_mem.commands.status import cmd_status
from harness_mem.commands.dream import cmd_dream
from harness_mem.commands.wake import cmd_wake_up
from harness_mem.commands.candidates import (
    cmd_correct,
    cmd_confirm_rule,
    cmd_reject_rule,
    cmd_list_candidates,
    cmd_confirmed_rules,
    cmd_suggest_supersede,
    cmd_confirm_supersede,
    cmd_reject_supersede,
)
from harness_mem.commands.handoff import cmd_handoff
from harness_mem.commands.onboarding import cmd_quickstart
from harness_mem.commands.config_cmds import (
    cmd_config_get,
    cmd_config_set,
    cmd_config_list,
    cmd_config_validate,
)
from harness_mem.commands.integration_cmds import (
    cmd_install_claude_hook,
    cmd_install_claude_wake_hook,
    cmd_install_hook_suite,
    cmd_install_claude_suite,
    cmd_install_cursor_hook,
    cmd_install_cursor_wake_hook,
    cmd_install_cursor_suite,
    cmd_list_command_profiles,
    cmd_sync_commands,
    cmd_transcript_evidence,
)

__all__ = [
    "cmd_export_json_snapshot",
    "cmd_migrate_store_v2",
    "cmd_config_get",
    "cmd_config_set",
    "cmd_config_list",
    "cmd_config_validate",
    "cmd_install_cursor_hook",
    "cmd_install_claude_hook",
    "cmd_install_cursor_wake_hook",
    "cmd_install_claude_wake_hook",
    "cmd_install_cursor_suite",
    "cmd_install_claude_suite",
    "cmd_install_hook_suite",
    "cmd_list_command_profiles",
    "cmd_sync_commands",
    "cmd_transcript_evidence",
    "cmd_doctor",
    "cmd_ingest",
    "cmd_import",
    "cmd_profile",
    "cmd_profile_edit",
    "cmd_state_audit",
    "cmd_purge",
    "cmd_search",
    "cmd_search_raw",
    "cmd_status",
    "cmd_dream",
    "cmd_wake_up",
    "cmd_correct",
    "cmd_confirm_rule",
    "cmd_reject_rule",
    "cmd_list_candidates",
    "cmd_confirmed_rules",
    "cmd_suggest_supersede",
    "cmd_confirm_supersede",
    "cmd_reject_supersede",
    "cmd_handoff",
    "cmd_use",
    "cmd_show",
    "cmd_quickstart",
    "cmd_timeline",
    "cmd_trace_relations",
]
