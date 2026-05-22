"""CLI entry point for harness-mem."""

from __future__ import annotations

import argparse
import asyncio
import sys

from harness_mem import __version__
from harness_mem.commands import (
    cmd_assign_memory_types,
    cmd_distill,
    cmd_doctor,
    cmd_ingest,
    cmd_import,
    cmd_profile,
    cmd_profile_edit,
    cmd_purge,
    cmd_quickstart,
    cmd_search,
    cmd_search_raw,
    cmd_show,
    cmd_status,
    cmd_timeline,
    cmd_trace_relations,
    cmd_use,
    cmd_wake_up,
    cmd_correct,
    cmd_confirm_rule,
    cmd_confirmed_rules,
    cmd_handoff,
    cmd_list_candidates,
    cmd_reject_rule,
    cmd_confirm_supersede,
    cmd_reject_supersede,
    cmd_suggest_supersede,
    cmd_suggest_procedural,
    cmd_confirm_procedural,
    cmd_reject_procedural,
    cmd_search_skills,
    cmd_record_skill_result,
)
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    can_prompt,
    get_active_project,
    log_cli_event,
    log_command_invoked,
    prompt_list,
    prompt_text,
    resolve_project_name,
    clean_cli_list,
    clean_cli_text,
    normalize_handoff_status,
)
from harness_mem.event_log import EventType
from harness_mem.commands.handoff import HANDOFF_STATUSES

# Test compatibility: tests monkeypatch these via cli module
from harness_mem.adapters.codex.adapter import CodexAdapter  # noqa: F401

_can_prompt = can_prompt


def main():
    # Handle --completion before full argument parsing
    if "--completion" in sys.argv:
        from harness_mem.shell_completion import print_completion
        for arg in sys.argv[1:]:
            if arg.startswith("--completion="):
                shell = arg.split("=", 1)[1]
                print_completion(shell)
                return
            elif arg == "--completion":
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    print_completion(sys.argv[idx + 1])
                    return
        print("--completion requires a shell argument: bash, zsh, or fish", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(prog="harness-mem")
    parser.add_argument("--version", action="version", version=f"harness-mem {__version__}")
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Initialize harness-mem data directory").set_defaults(command_name="init")

    # use
    use_cmd = sub.add_parser("use", help="Set or show the active project")
    use_cmd.add_argument("project", nargs="?", help="Project name")
    use_cmd.set_defaults(command_name="use")

    # quickstart
    qs = sub.add_parser("quickstart", aliases=["qs"], help="Initialize, pick a project, and try ingestion")
    qs.add_argument("project", nargs="?", help="Project name")
    qs.add_argument("-c", "--client", choices=["auto", "claude-code", "codex", "skip"], default="auto")
    qs.add_argument("-n", "--limit", type=int, default=5)
    qs.set_defaults(command_name="quickstart")

    # doctor
    doc = sub.add_parser("doctor", help="Inspect local setup and suggest next steps")
    doc.add_argument("-p", "--project")
    doc.set_defaults(command_name="doctor")

    # ingest
    ingest = sub.add_parser("ingest", help="Ingest sessions for the current agent environment")
    ingest.add_argument("client", nargs="?", default="auto", choices=["auto", "claude-code", "codex", "codex-archive"])
    ingest.add_argument("-p", "--project")
    ingest.add_argument("-n", "--limit", type=int, default=10)
    ingest.add_argument("--full-rescan", action="store_true", help="Ingest all sessions (default: incremental)")
    ingest.add_argument("--project-root", help="Project root for cwd-scoped session matching (default: current directory)")
    ingest.add_argument("--scope", choices=["project", "all"], default="project", help="Session scope for global stores (default: project)")
    ingest.set_defaults(command_name="ingest")

    # wake-up
    wake = sub.add_parser("wake-up", aliases=["wake"], help="Generate wake-up context")
    wake.add_argument("-p", "--project")
    wake.add_argument("--no-auto-ingest", action="store_true", help="Skip automatic session ingestion")
    wake.add_argument(
        "--no-bucket-quota",
        action="store_true",
        help=(
            "v1.6.1: disable memory_type bucket quotas; falls back to v1.6.0 "
            "single-pool selection. Same as [wake] bucket_quota_enabled = false."
        ),
    )
    wake.set_defaults(command_name="wake-up")

    # search
    search = sub.add_parser("search", help="Search memory")
    search.add_argument("query_arg", nargs="?")
    search.add_argument("-p", "--project")
    search.add_argument("-q", "--query")
    search.add_argument("--mode", choices=["auto", "fts", "hybrid"], default="auto")
    search.add_argument(
        "--include-history",
        action="store_true",
        help="v1.7.0: include historical structured truth in search results.",
    )
    search.add_argument(
        "--memory-type",
        action="append",
        choices=["episodic", "semantic", "procedural"],
        help=(
            "v1.6.1: filter memory entries by memory_type (repeatable for OR-filter; "
            "default no filter). Observations / relation facts are unaffected."
        ),
    )
    search.set_defaults(command_name="search")

    # search-raw
    search_raw = sub.add_parser("search-raw", help="Regex search raw observation evidence")
    search_raw.add_argument("pattern_arg", nargs="?")
    search_raw.add_argument("-p", "--project")
    search_raw.add_argument("--regex", dest="pattern")
    search_raw.add_argument("-n", "--limit", type=int, default=20)
    search_raw.add_argument("--scope", choices=["project", "all"], default="project")
    search_raw.set_defaults(command_name="search-raw")

    # timeline
    tl = sub.add_parser("timeline", aliases=["tl"], help="Show observation timeline")
    tl.add_argument("limit_arg", nargs="?", type=int)
    tl.add_argument("-p", "--project")
    tl.add_argument("-n", "--limit", type=int, default=50)
    tl.set_defaults(command_name="timeline")

    # trace-relations
    tr = sub.add_parser("trace-relations", help="Trace bounded relation paths")
    tr.add_argument("source_entity_arg", nargs="?")
    tr.add_argument("-p", "--project")
    tr.add_argument("--source-entity", dest="source_entity")
    tr.add_argument("--relation-type")
    tr.add_argument("--max-depth", type=int, default=2)
    tr.add_argument("-n", "--limit", type=int, default=10)
    tr.add_argument("--min-confidence", type=float, default=0.0)
    tr.add_argument(
        "--include-history",
        action="store_true",
        help="v1.7.2: include historical relation facts in relation traces.",
    )
    tr.set_defaults(command_name="trace-relations")

    # show
    show = sub.add_parser("show", help="Show a specific observation")
    show.add_argument("observation_id_arg", nargs="?")
    show.add_argument("-p", "--project")
    show.add_argument("-i", "--id", dest="observation_id", help="Legacy alias for -o")
    show.add_argument("-o", "--observation-id", dest="observation_id")
    show.set_defaults(command_name="show")

    # status
    st = sub.add_parser("status", aliases=["st"], help="Show memory status")
    st.add_argument("-p", "--project")
    st.set_defaults(command_name="status")

    # profile
    prof = sub.add_parser("profile", help="Show project profile")
    prof.add_argument("-p", "--project")
    prof.add_argument("--edit", action="store_true", help="Edit profile fields interactively")
    prof.set_defaults(command_name="profile")

    # distill
    ds = sub.add_parser("distill", aliases=["ds"], help="Extract structured memory from sessions")
    ds.add_argument("session_id_arg", nargs="?")
    ds.add_argument("-p", "--project")
    ds.add_argument("-s", "--session-id", dest="session_id")
    ds.add_argument("-c", "--category", choices=["architecture", "convention", "api", "bug", "decision"])
    ds.add_argument("--project-root", help="Project root for Claude project session matching")
    ds.add_argument(
        "--auto-confirm",
        action="store_true",
        help=(
            "v1.6.1 compat: flip distilled candidates from 'pending' back to 'accepted' "
            "after extraction (legacy ingest -> distill -> wake loop). Default is 'pending'."
        ),
    )
    ds.set_defaults(command_name="distill")

    # import
    imp = sub.add_parser("import", help="Import memory drafts from AI skills into candidate layer")
    imp.add_argument("file", help="Path to JSON draft or sync-list")
    imp.add_argument("-p", "--project")
    imp.set_defaults(command_name="import")

    # correct
    corr = sub.add_parser("correct", help="Create a rule candidate from a correction (interactive)")
    corr.add_argument("session_id_arg", nargs="?")
    corr.add_argument("-s", "--session-id", dest="session_id")
    corr.add_argument("-p", "--project")
    corr.add_argument("-r", "--pattern")
    corr.add_argument("-t", "--trigger")
    corr.add_argument(
        "--supersedes",
        dest="supersedes_rule_id",
        help=(
            "ConfirmedRule id this correction replaces. When set, the old "
            "rule is marked historical and the new rule is confirmed in one "
            "step (supersede chain stays auditable via --include-history). "
            "Use this when reality changed (schema upgrade, policy reversal) "
            "rather than when adding a brand new rule."
        ),
    )
    corr.add_argument(
        "--reason",
        dest="reason",
        help="Optional human-readable reason recorded on the supersede chain.",
    )
    corr.set_defaults(command_name="correct")

    # confirm-rule / reject-rule
    for name, aliases in [("confirm-rule", ["confirm"]), ("reject-rule", ["reject"])]:
        p = sub.add_parser(name, aliases=aliases, help=f"{name} a rule candidate")
        p.add_argument("rule_id_arg", nargs="?")
        p.add_argument("-r", "--rule-id", dest="rule_id")
        p.set_defaults(command_name=name)

    sup = sub.add_parser("supersede", help="Create a supersede candidate")
    sup.add_argument("-p", "--project")
    sup.add_argument("--target-type", required=True, choices=["memory_entry", "relation_fact", "confirmed_rule"])
    sup.add_argument("--target-id", required=True)
    sup.add_argument("--replacement-type", required=True, choices=["memory_entry", "relation_fact", "confirmed_rule"])
    sup.add_argument("--replacement-id", required=True)
    sup.add_argument("--reason", required=True)
    sup.add_argument("--evidence", required=True)
    sup.add_argument("--source", default="")
    sup.add_argument("--confidence", type=float, default=0.7)
    sup.set_defaults(command_name="supersede")

    cs = sub.add_parser("confirm-supersede", aliases=["confirm-sup"], help="Confirm a supersede candidate")
    cs.add_argument("candidate_id")
    cs.set_defaults(command_name="confirm-supersede")

    rs = sub.add_parser("reject-supersede", aliases=["reject-sup"], help="Reject a supersede candidate")
    rs.add_argument("candidate_id")
    rs.set_defaults(command_name="reject-supersede")

    proc = sub.add_parser("suggest-skill", aliases=["skill-candidate"], help="Create a procedural skill candidate")
    proc.add_argument("-p", "--project")
    proc.add_argument("--activation-condition", required=True)
    proc.add_argument("--step", dest="steps", action="append", required=True)
    proc.add_argument("--termination-condition", required=True)
    proc.add_argument("--success-example", dest="success_examples", action="append", default=[])
    proc.add_argument("--source-session-id", default="")
    proc.add_argument("--source", default="")
    proc.add_argument("--confidence", type=float, default=0.7)
    proc.set_defaults(command_name="suggest-skill")

    cp = sub.add_parser("confirm-skill", help="Confirm a procedural skill candidate")
    cp.add_argument("candidate_id")
    cp.set_defaults(command_name="confirm-skill")

    rp = sub.add_parser("reject-skill", help="Reject a procedural skill candidate")
    rp.add_argument("candidate_id")
    rp.set_defaults(command_name="reject-skill")

    ss = sub.add_parser("search-skills", aliases=["skills"], help="Search confirmed procedural skills")
    ss.add_argument("query_arg", nargs="?")
    ss.add_argument("-p", "--project")
    ss.add_argument("-q", "--query")
    ss.add_argument("-n", "--limit", type=int, default=10)
    ss.set_defaults(command_name="search-skills")

    sr = sub.add_parser("record-skill-result", help="Record a confirmed skill execution result")
    sr.add_argument("skill_id")
    outcome = sr.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--success", action="store_true")
    outcome.add_argument("--failure", action="store_true")
    sr.set_defaults(command_name="record-skill-result")

    # purge
    purge = sub.add_parser("purge", help="Soft-delete observations/structured memory")
    purge.add_argument("-p", "--project")
    purge.add_argument("--before", required=True, help="YYYY-MM-DD")
    purge.add_argument("--category", choices=["observations", "structured", "all"], default="all")
    purge.add_argument("--dry-run", action="store_true")
    purge.add_argument("--stale-only", action="store_true", help="Only include never-accessed or stale entries")
    purge.set_defaults(command_name="purge")

    # list-candidates / confirmed-rules
    lc = sub.add_parser("list-candidates", aliases=["candidates"], help="List rule candidates")
    lc.add_argument("-p", "--project")
    lc.add_argument("--status")
    lc.set_defaults(command_name="list-candidates")

    cr = sub.add_parser("confirmed-rules", aliases=["rules"], help="List confirmed rules")
    cr.add_argument("-p", "--project")
    cr.add_argument(
        "--include-history",
        action="store_true",
        help="v1.7.0: include historical confirmed rules.",
    )
    cr.set_defaults(command_name="confirmed-rules")

    # handoff
    ho = sub.add_parser("handoff", help="Create or update a task handoff (interactive)")
    ho.add_argument("-p", "--project")
    ho.add_argument("-t", "--task-id", dest="task_id")
    ho.add_argument("-s", "--summary")
    ho.add_argument("--status", default="in_progress")
    ho.add_argument("-n", "--next-step", dest="next_steps", action="append", default=[])
    ho.add_argument("-b", "--blocker", dest="blockers", action="append", default=[])
    ho.set_defaults(command_name="handoff")

    # api
    api = sub.add_parser("api", help="Start the REST API server")
    api.add_argument("-p", "--port", type=int, default=8000)
    api.add_argument("-H", "--host", default="0.0.0.0")
    api.set_defaults(command_name="api")

    # maintenance
    maint = sub.add_parser("maintenance", help="One-shot maintenance utilities")
    maint.add_argument(
        "action",
        choices=["assign-memory-types", "rebuild-vector-index", "rebuild-verbatim-index"],
        help="Maintenance action to run",
    )
    maint.add_argument("-p", "--project", help="Project name (defaults to active project)")
    apply_group = maint.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Preview changes without writing (default)",
    )
    apply_group.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Commit changes to disk",
    )
    maint.set_defaults(command_name="maintenance")

    args = parser.parse_args()
    command = getattr(args, "command_name", args.command)

    if command is None:
        parser.print_help()
        return 0

    # --- Simple dispatch (no arg massaging needed) ---
    if command == "init":
        DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Initialized at {DEFAULT_DATA_DIR}")
        return 0

    if command == "use":
        return cmd_use(args.project)

    if command == "quickstart":
        return asyncio.run(cmd_quickstart(args.project, args.client, args.limit))

    if command == "doctor":
        return asyncio.run(cmd_doctor(args.project))

    if command == "status":
        if not DEFAULT_DATA_DIR.exists():
            print("Not initialized. Run: harness-mem init")
            return 1
        return asyncio.run(cmd_status(args.project))

    if command == "wake-up":
        return asyncio.run(
            cmd_wake_up(
                args.project,
                no_auto_ingest=getattr(args, "no_auto_ingest", False),
                no_bucket_quota=getattr(args, "no_bucket_quota", False),
            )
        )

    if command == "search":
        query = args.query or args.query_arg
        if not query:
            print('No query provided. Try: harness-mem search "your search terms"')
            return 1
        return asyncio.run(
            cmd_search(
                args.project,
                query,
                args.mode,
                memory_type=getattr(args, "memory_type", None),
                include_history=getattr(args, "include_history", False),
            )
        )

    if command == "search-raw":
        pattern = args.pattern or args.pattern_arg
        if not pattern:
            print('No regex provided. Try: harness-mem search-raw --regex "ERROR-[0-9]+"')
            return 1
        return asyncio.run(
            cmd_search_raw(
                args.project,
                pattern,
                limit=getattr(args, "limit", 20),
                scope=getattr(args, "scope", "project"),
            )
        )

    if command == "timeline":
        limit = args.limit if args.limit is not None else (args.limit_arg or 50)
        return asyncio.run(cmd_timeline(args.project, limit))

    if command == "trace-relations":
        source_entity = args.source_entity or args.source_entity_arg
        if not source_entity:
            parser.error("trace-relations requires --source-entity or a source entity argument.")
        return asyncio.run(
            cmd_trace_relations(
                args.project,
                source_entity,
                relation_type=getattr(args, "relation_type", None),
                max_depth=getattr(args, "max_depth", 2),
                limit=getattr(args, "limit", 10),
                min_confidence=getattr(args, "min_confidence", 0.0),
                include_history=getattr(args, "include_history", False),
            )
        )

    if command == "show":
        obs_id = args.observation_id or args.observation_id_arg
        if not obs_id:
            parser.error("show requires an observation or session id.")
        return asyncio.run(cmd_show(args.project, obs_id))

    if command == "ingest":
        return asyncio.run(
            cmd_ingest(
                args.client,
                args.project,
                args.limit,
                args.full_rescan,
                scope=args.scope,
                project_root=args.project_root,
            )
        )

    if command == "profile":
        if getattr(args, "edit", False):
            return asyncio.run(cmd_profile_edit(args.project))
        return asyncio.run(cmd_profile(args.project))

    if command == "distill":
        sid = args.session_id or args.session_id_arg
        return asyncio.run(
            cmd_distill(
                args.project,
                sid,
                category=getattr(args, "category", None),
                project_root=getattr(args, "project_root", None),
                auto_confirm=getattr(args, "auto_confirm", False),
            )
        )

    if command == "import":
        return asyncio.run(cmd_import(args.file, args.project))

    if command == "purge":
        return asyncio.run(cmd_purge(args.before, args.category, args.dry_run, args.project, stale_only=args.stale_only))

    if command == "api":
        import uvicorn
        from harness_mem.api.server import create_app
        print(f"Starting API server on {args.host}:{args.port}")
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0

    if command == "maintenance":
        if args.action == "assign-memory-types":
            return asyncio.run(
                cmd_assign_memory_types(args.project, apply=not args.dry_run)
            )
        elif args.action == "rebuild-vector-index":
            from harness_mem.commands.maintenance import cmd_rebuild_vector_index
            return asyncio.run(
                cmd_rebuild_vector_index(args.project)
            )
        elif args.action == "rebuild-verbatim-index":
            from harness_mem.commands.maintenance import cmd_rebuild_verbatim_index
            return asyncio.run(
                cmd_rebuild_verbatim_index(args.project)
            )
        parser.error(f"Unknown maintenance action: {args.action}")

    # --- Commands needing interactive arg massaging or logging ---
    if command == "correct":
        if (
            args.session_id
            and args.session_id_arg
            and clean_cli_text(args.session_id) != clean_cli_text(args.session_id_arg)
        ):
            parser.error("correct received conflicting session ids.")
        session_id = clean_cli_text(args.session_id or args.session_id_arg)
        if not session_id and _can_prompt():
            print("Interactive correct mode")
            session_id = prompt_text("Session ID")
        pattern = clean_cli_text(args.pattern)
        if not pattern and _can_prompt():
            pattern = prompt_text("Rule pattern")
        trigger = clean_cli_text(args.trigger)
        if not trigger and _can_prompt():
            trigger = prompt_text("Trigger")
        if not session_id:
            parser.error("correct requires a session id.")
        if not pattern:
            parser.error("correct requires a pattern.")
        if not trigger:
            parser.error("correct requires a trigger.")
        project_name = resolve_project_name(args.project, action_label="correct")
        if not project_name:
            return 1
        result = asyncio.run(
            cmd_correct(
                session_id,
                project_name,
                pattern,
                trigger,
                supersedes_rule_id=clean_cli_text(getattr(args, "supersedes_rule_id", None)),
                reason=clean_cli_text(getattr(args, "reason", None)),
            )
        )
        if result == 0:
            log_command_invoked("correct", project_name=project_name, session_id=session_id)
            stage = (
                "rule_superseded"
                if getattr(args, "supersedes_rule_id", None)
                else "candidate_created"
            )
            log_cli_event(
                EventType.LEARNING_LOOP_COMPLETE,
                project_name=project_name,
                command="correct",
                session_id=session_id,
                extra={"stage": stage},
            )
        return result

    if command == "confirm-rule":
        rule_id = args.rule_id or args.rule_id_arg
        if not rule_id:
            parser.error("confirm-rule requires a rule id.")
        result = asyncio.run(cmd_confirm_rule(rule_id))
        if result == 0:
            ap = get_active_project()
            log_command_invoked("confirm", project_name=ap)
            log_cli_event(EventType.RULE_CONFIRMED, project_name=ap, command="confirm", extra={"rule_id": rule_id})
            log_cli_event(EventType.LEARNING_LOOP_COMPLETE, project_name=ap, command="confirm", extra={"stage": "rule_confirmed", "rule_id": rule_id})
        return result

    if command == "reject-rule":
        rule_id = args.rule_id or args.rule_id_arg
        if not rule_id:
            parser.error("reject-rule requires a rule id.")
        result = asyncio.run(cmd_reject_rule(rule_id))
        if result == 0:
            ap = get_active_project()
            log_command_invoked("reject", project_name=ap)
            log_cli_event(EventType.RULE_REJECTED, project_name=ap, command="reject", extra={"rule_id": rule_id})
        return result

    if command == "supersede":
        pn = resolve_project_name(args.project, action_label="supersede")
        if not pn:
            return 1
        return asyncio.run(
            cmd_suggest_supersede(
                pn,
                args.target_type,
                args.target_id,
                args.replacement_type,
                args.replacement_id,
                args.reason,
                args.evidence,
                source=getattr(args, "source", ""),
                confidence=getattr(args, "confidence", 0.7),
            )
        )

    if command == "confirm-supersede":
        return asyncio.run(cmd_confirm_supersede(args.candidate_id))

    if command == "reject-supersede":
        return asyncio.run(cmd_reject_supersede(args.candidate_id))

    if command == "suggest-skill":
        pn = resolve_project_name(args.project, action_label="suggest-skill")
        if not pn:
            return 1
        return asyncio.run(
            cmd_suggest_procedural(
                pn,
                args.activation_condition,
                args.steps,
                args.termination_condition,
                success_examples=getattr(args, "success_examples", []),
                source_session_id=getattr(args, "source_session_id", ""),
                source=getattr(args, "source", ""),
                confidence=getattr(args, "confidence", 0.7),
            )
        )

    if command == "confirm-skill":
        return asyncio.run(cmd_confirm_procedural(args.candidate_id))

    if command == "reject-skill":
        return asyncio.run(cmd_reject_procedural(args.candidate_id))

    if command == "search-skills":
        query = args.query or args.query_arg
        if not query:
            parser.error("search-skills requires a query.")
        pn = resolve_project_name(args.project, action_label="search-skills")
        if not pn:
            return 1
        return asyncio.run(cmd_search_skills(pn, query, limit=getattr(args, "limit", 10)))

    if command == "record-skill-result":
        return asyncio.run(
            cmd_record_skill_result(
                args.skill_id,
                success=bool(getattr(args, "success", False)),
            )
        )

    if command == "list-candidates":
        pn = resolve_project_name(args.project, action_label="list-candidates")
        if not pn:
            return 1
        return asyncio.run(cmd_list_candidates(pn, args.status))

    if command == "confirmed-rules":
        pn = resolve_project_name(args.project, action_label="confirmed-rules")
        if not pn:
            return 1
        return asyncio.run(
            cmd_confirmed_rules(
                pn,
                include_history=getattr(args, "include_history", False),
            )
        )

    if command == "handoff":
        task_id = clean_cli_text(args.task_id)
        summary = clean_cli_text(args.summary)
        status = normalize_handoff_status(args.status)
        next_steps = clean_cli_list(args.next_steps)
        blockers = clean_cli_list(args.blockers)
        if _can_prompt() and (not task_id or not summary):
            print("Interactive handoff mode")
            task_id = task_id or prompt_text("Task ID")
            summary = summary or prompt_text("Summary")
            status = normalize_handoff_status(prompt_text("Status", default=status) or status)
            if not next_steps:
                next_steps = prompt_list("Next steps")
            if not blockers:
                blockers = prompt_list("Blockers (optional)")
        next_steps = clean_cli_list(next_steps)
        blockers = clean_cli_list(blockers)
        if not task_id:
            parser.error("handoff requires a task id.")
        if not summary:
            parser.error("handoff requires a summary.")
        if status not in HANDOFF_STATUSES:
            parser.error(f"handoff status must be one of: {', '.join(HANDOFF_STATUSES)}.")
        pn = resolve_project_name(args.project, action_label="handoff")
        if not pn:
            return 1
        result = asyncio.run(cmd_handoff(pn, task_id, summary, status=status, next_steps=next_steps, blockers=blockers))
        if result == 0:
            log_command_invoked("handoff", project_name=pn, extra={"task_id": task_id, "status": status})
        return result

    return 0


if __name__ == "__main__":
    sys.exit(main())
