"""Shell completion support for the harness-mem maintenance CLI."""

from __future__ import annotations

import argparse
import sys


SUPPORTED_SHELLS = ["bash", "zsh", "fish"]
CLI_COMMANDS = ["init", "quickstart", "doctor", "import", "purge", "maintenance"]
CLI_ALIASES = {"qs": "quickstart"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-mem", add_help=False)
    parser.add_argument("--completion", choices=SUPPORTED_SHELLS, help="Generate completion script for shell")
    return parser


def completion_bash() -> str:
    """Generate bash completion script."""
    commands = " ".join(CLI_COMMANDS)
    aliases = " ".join(CLI_ALIASES.keys())
    return f"""# harness-mem bash completion
_harness_mem_completion() {{
    local cur prev words cword
    _init_completion || return

    if [[ "${{cur}}" == -* ]]; then
        case "${{prev}}" in
            -p|--project|--before)
                return
                ;;
            -c|--client)
                COMPREPLY=($(compgen -W "auto claude-code codex skip" -- "${{cur}}"))
                return
                ;;
            --category)
                COMPREPLY=($(compgen -W "observations structured all" -- "${{cur}}"))
                return
                ;;
            *)
                ;;
        esac
    else
        COMPREPLY=($(compgen -W "{commands} {aliases}" -- "${{cur}}"))
        return
    fi
}}

complete -F _harness_mem_completion harness-mem
"""


def completion_zsh() -> str:
    """Generate zsh completion script."""
    commands = " ".join(CLI_COMMANDS)
    return f"""# harness-mem zsh completion
_harness_mem() {{
    local -a commands
    commands=({commands})

    _arguments -C \\
        '-p[project name]:project:' \\
        '--project[project name]:project:' \\
        '-c[client]:client:(auto claude-code codex skip)' \\
        '--client[client]:client:(auto claude-code codex skip)' \\
        '-n[limit]:limit:' \\
        '--limit[limit]:limit:' \\
        '--category[category]:(observations structured all)' \\
        '--before[date (YYYY-MM-DD)]:date:' \\
        '--dry-run[preview only]' \\
        '--stale-only[only stale entries]' \\
        '--apply[write maintenance changes]' \\
        '1: :->command' \\
        '2: :->arg'

    case $state in
        command)
            _describe 'command' commands
            ;;
    esac
}}

compdef _harness_mem harness-mem
"""


def completion_fish() -> str:
    """Generate fish completion script."""
    commands = " ".join(CLI_COMMANDS + list(CLI_ALIASES.keys()))
    return f"""# harness-mem fish completion
complete -c harness-mem -f

# Global options
complete -c harness-mem -l version -d "Show version"
complete -c harness-mem -l completion -x -a "bash zsh fish" -d "Generate completion script"

# Maintenance-console subcommands
complete -c harness-mem -n '__fish_use_subcommand' -a '{commands}' -d "Command"

# quickstart
complete -c harness-mem -n '__fish_seen_subcommand_from quickstart; or __fish_seen_subcommand_from qs' -l client -x -a "auto claude-code codex skip" -d "Client"
complete -c harness-mem -n '__fish_seen_subcommand_from quickstart; or __fish_seen_subcommand_from qs' -l limit -x -d "Max sessions"

# doctor
complete -c harness-mem -n '__fish_seen_subcommand_from doctor' -l project -r -d "Project name"

# import
complete -c harness-mem -n '__fish_seen_subcommand_from import' -l project -r -d "Project name"

# purge
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l before -r -d "Date (YYYY-MM-DD)"
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l category -x -a "observations structured all" -d "Category"
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l dry-run -d "Preview only"
complete -c harness-mem -n '__fish_seen_subcommand_from purge' -l stale-only -d "Only stale entries"

# maintenance
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -a "assign-memory-types rebuild-vector-index rebuild-verbatim-index prepare-knowledge-cache rebuild-wiki-bridge cleanup-generated-cache" -d "Action"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l dry-run -d "Preview only"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l apply -d "Write changes"
"""


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

    parser.print_help()


if __name__ == "__main__":
    main()
