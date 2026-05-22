"""Shell completion support for harness-mem CLI.

Generates completion scripts for bash, zsh, and fish shells.
Run with: source <(harness-mem --completion bash)
"""

from __future__ import annotations
import argparse
import sys


SUPPORTED_SHELLS = ["bash", "zsh", "fish"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-mem", add_help=False)
    parser.add_argument("--completion", choices=SUPPORTED_SHELLS, help="Generate completion script for shell")
    return parser


def completion_bash() -> str:
    """Generate bash completion script."""
    commands = [
        "init", "use", "quickstart", "doctor", "ingest", "wake-up", "search",
        "timeline", "show", "status", "profile", "correct",
        "confirm-rule", "reject-rule", "purge", "list-candidates", "confirmed-rules",
        "handoff",
    ]
    aliases = {
        "qs": "quickstart", "wake": "wake-up",
        "confirm": "confirm-rule", "reject": "reject-rule",
        "tl": "timeline", "st": "status", "rules": "confirmed-rules",
        "candidates": "list-candidates",
    }

    script = f'''# harness-mem bash completion
_harness_mem_completion() {{
    local cur prev words cword
    _init_completion || return

    # Command names
    if [[ "${{cur}}" == -* ]]; then
        # Options for the current command
        case "${{prev}}" in
            -p|--project)
                _filedir -d
                return
                ;;
            -c|--client)
                COMPREPLY=($(compgen -W "auto claude-code codex skip" -- "${{cur}}"))
                return
                ;;
            --scope)
                COMPREPLY=($(compgen -W "project all" -- "${{cur}}"))
                return
                ;;
            --category)
                COMPREPLY=($(compgen -W "observations structured all architecture convention api bug decision" -- "${{cur}}"))
                return
                ;;
            --before)
                return
                ;;
            -n|--limit|--observation-id|-i|-o|-r|--rule-id|-s|--session-id|-t|--task-id|--status|--pattern|--trigger|--project-root)
                return
                ;;
            --full-rescan|--dry-run|--edit)
                return
                ;;
            *)
                ;;
        esac
    else
        # Command or subcommand
        local IFS=$'\\n'
        COMPREPLY=($(compgen -W "{' '.join(commands)}" -- "${{cur}}"))
        # Add aliases
        COMPREPLY+=($(compgen -W "{' '.join(aliases.keys())}" -- "${{cur}}"))
        return
    fi
}}

complete -F _harness_mem_completion harness-mem
'''
    return script


def completion_zsh() -> str:
    """Generate zsh completion script."""
    commands = " ".join([
        "init", "use", "quickstart", "doctor", "ingest", "wake-up", "search",
        "timeline", "show", "status", "profile", "correct",
        "confirm-rule", "reject-rule", "purge", "list-candidates", "confirmed-rules",
        "handoff",
    ])
    clients = "(auto claude-code codex skip)"
    ingest_clients = "(auto claude-code codex codex-archive)"
    categories = "(observations structured all architecture convention api bug decision)"

    script = f'''# harness-mem zsh completion
_harness_mem() {{
    local -a commands
    commands=({commands})

    _arguments -C \\
        '-p[project name]:project:_files -/' \\
        '--project[project name]:project:_files -/' \\
        '-c[client]:client:{clients}' \\
        '--client[client]:client:{clients}' \\
        '--scope[session scope]:(project all)' \\
        '--project-root[project root]:project:_files -/' \\
        '-n[limit]:limit:' \\
        '--limit[limit]:limit:' \\
        '--category[category]:category:{categories}' \\
        '--before[date (YYYY-MM-DD)]:date:' \\
        '--full-rescan[ignore last ingest cursor]' \\
        '--dry-run[preview only]' \\
        '--edit[edit profile interactively]' \\
        '-o[observation id]:' \\
        '--observation-id[observation id]:' \\
        '-i[observation id (legacy)]:' \\
        '--id[observation id (legacy)]:' \\
        '-r[rule id]:' \\
        '--rule-id[rule id]:' \\
        '-s[session id]:' \\
        '--session-id[session id]:' \\
        '-t[trigger]:' \\
        '--trigger[trigger]:' \\
        '-b[blocker]:' \\
        '--blocker[blocker]:' \\
        '--status[status]:' \\
        '--pattern[pattern]:' \\
        '1: :->command' \\
        '2:client:{ingest_clients}' \\
        '2: :->arg'

    case $state in
        command)
            _describe 'command' commands
            ;;
    esac
}}

compdef _harness_mem harness-mem
'''
    return script


def completion_fish() -> str:
    """Generate fish completion script."""
    commands = " ".join([
        "init", "use", "quickstart", "doctor", "ingest", "wake-up", "search",
        "timeline", "show", "status", "profile", "correct",
        "confirm-rule", "reject-rule", "purge", "list-candidates", "confirmed-rules",
        "handoff",
    ])

    script = f'''# harness-mem fish completion
complete -c harness-mem -f

# Global options
complete -c harness-mem -l version -d "Show version"
complete -c harness-mem -l completion -x -a "bash zsh fish" -d "Generate completion script"

# Subcommands
complete -c harness-mem -n '__fish_use_subcommand' -a '{commands}' -d "Command"

# init
complete -c harness-mem -n '__fish_seen_subcommand_from init' -l project -r -d "Project name"

# use
complete -c harness-mem -n '__fish_seen_subcommand_from use' -l project -r -d "Project name"

# quickstart
complete -c harness-mem -n '__fish_seen_subcommand_from quickstart' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from quickstart' -l client -x -a "auto claude-code codex skip" -d "Client"
complete -c harness-mem -n '__fish_seen_subcommand_from quickstart' -l limit -x -d "Max sessions"

# doctor
complete -c harness-mem -n '__fish_seen_subcommand_from doctor' -l project -r -d "Project name"

# ingest
complete -c harness-mem -n '__fish_seen_subcommand_from ingest' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from ingest' -l limit -x -d "Max sessions"
complete -c harness-mem -n '__fish_seen_subcommand_from ingest' -l full-rescan -d "Ignore last cursor"
complete -c harness-mem -n '__fish_seen_subcommand_from ingest' -l project-root -r -d "Project root for session matching"
complete -c harness-mem -n '__fish_seen_subcommand_from ingest' -l scope -x -a "project all" -d "Session scope"

# wake-up
complete -c harness-mem -n '__fish_seen_subcommand_from wake-up; or __fish_seen_subcommand_from wake' -l project -r -d "Project name"

# search
complete -c harness-mem -n '__fish_seen_subcommand_from search' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from search' -l query -r -d "Search query"

# timeline
complete -c harness-mem -n '__fish_seen_subcommand_from timeline; or __fish_seen_subcommand_from tl' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from timeline; or __fish_seen_subcommand_from tl' -l limit -x -d "Max results"

# show
complete -c harness-mem -n '__fish_seen_subcommand_from show' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from show' -l observation-id -r -d "Observation ID"
complete -c harness-mem -n '__fish_seen_subcommand_from show' -l id -r -d "Observation ID (legacy)"

# status
complete -c harness-mem -n '__fish_seen_subcommand_from status; or __fish_seen_subcommand_from st' -l project -r -d "Project name"

# profile
complete -c harness-mem -n '__fish_seen_subcommand_from profile' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from profile' -l edit -d "Edit interactively"

# correct
complete -c harness-mem -n '__fish_seen_subcommand_from correct' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from correct' -l session-id -r -d "Session ID"
complete -c harness-mem -n '__fish_seen_subcommand_from correct' -l pattern -r -d "Rule pattern"
complete -c harness-mem -n '__fish_seen_subcommand_from correct' -l trigger -r -d "Trigger scenario"

# confirm-rule / reject-rule
complete -c harness-mem -n '__fish_seen_subcommand_from confirm-rule; or __fish_seen_subcommand_from confirm' -l rule-id -r -d "Rule ID"
complete -c harness-mem -n '__fish_seen_subcommand_from reject-rule; or __fish_seen_subcommand_from reject' -l rule-id -r -d "Rule ID"

# purge
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l before -r -d "Date (YYYY-MM-DD)"
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l category -x -a "observations structured all" -d "Category"
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l dry-run -d "Preview only"

# list-candidates
complete -c harness-mem -n '__fish_seen_subcommand_from list-candidates; or __fish_seen_subcommand_from candidates' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from list-candidates; or __fish_seen_subcommand_from candidates' -l status -x -a "pending accepted rejected" -d "Status"

# confirmed-rules
complete -c harness-mem -n '__fish_seen_subcommand_from confirmed-rules; or __fish_seen_subcommand_from rules' -l project -r -d "Project name"

# handoff
complete -c harness-mem -n '__fish_seen_subcommand_from handoff' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from handoff' -l task-id -r -d "Task ID"
complete -c harness-mem -n '__fish_seen_subcommand_from handoff' -l summary -r -d "Task summary"
complete -c harness-mem -n '__fish_seen_subcommand_from handoff' -l next-step -r -d "Next step"
complete -c harness-mem -n '__fish_seen_subcommand_from handoff' -l blocker -r -d "Blocker"
complete -c harness-mem -n '__fish_seen_subcommand_from handoff' -l status -x -a "in_progress pending blocked done" -d "Status"
'''
    return script


COMPLETION_GENERATORS = {
    "bash": completion_bash,
    "zsh": completion_zsh,
    "fish": completion_fish,
}


def print_completion(shell: str) -> None:
    """Print completion script for the specified shell."""
    generator = COMPLETION_GENERATORS.get(shell)
    if not generator:
        print(f"Unsupported shell: {shell}", file=sys.stderr)
        print(f"Supported: {', '.join(SUPPORTED_SHELLS)}", file=sys.stderr)
        sys.exit(1)
    print(generator())


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.completion:
        print_completion(args.completion)
        return

    # If called directly without --completion, show help
    parser.print_help()


if __name__ == "__main__":
    main()
