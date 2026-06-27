"""Shell completion support for the harness-mem maintenance CLI."""

from __future__ import annotations

import argparse
import sys


SUPPORTED_SHELLS = ["bash", "zsh", "fish"]
CLI_COMMANDS = [
    "init",
    "quickstart",
    "doctor",
    "maintenance",
    "config",
    "integration",
]
CLI_ALIASES = {"qs": "quickstart"}
MAINTENANCE_ACTIONS = [
    "rebuild-vector-index",
    "rebuild-verbatim-index",
    "migrate-store-v2",
    "export-json-snapshot",
    "state-audit",
    "import",
    "purge",
]
CONFIG_ACTIONS = ["get", "set", "list", "validate"]
INTEGRATION_ACTIONS = ["install-cursor-hook", "install-claude-hook", "commands"]
INTEGRATION_COMMAND_ACTIONS = ["list", "sync", "enable"]
COMMAND_PROFILES = ["daily", "maintenance", "full"]
OPTIONAL_COMMAND_GROUPS = ["maintenance"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-mem", add_help=False)
    parser.add_argument("--completion", choices=SUPPORTED_SHELLS, help="Generate completion script for shell")
    return parser


def completion_bash() -> str:
    """Generate bash completion script."""
    commands = " ".join(CLI_COMMANDS)
    aliases = " ".join(CLI_ALIASES.keys())
    maintenance_actions = " ".join(MAINTENANCE_ACTIONS)
    config_actions = " ".join(CONFIG_ACTIONS)
    integration_actions = " ".join(INTEGRATION_ACTIONS)
    integration_command_actions = " ".join(INTEGRATION_COMMAND_ACTIONS)
    command_profiles = " ".join(COMMAND_PROFILES)
    optional_command_groups = " ".join(OPTIONAL_COMMAND_GROUPS)
    return f"""# harness-mem bash completion
_harness_mem_completion() {{
    local cur prev words cword
    _init_completion || return

    if [[ "${{cword}}" -eq 1 ]]; then
        COMPREPLY=($(compgen -W "{commands} {aliases}" -- "${{cur}}"))
        return
    fi

    if [[ "${{cur}}" == -* ]]; then
        case "${{prev}}" in
            -p|--project|--before|--source)
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
            --kind)
                COMPREPLY=($(compgen -W "reflection dream preview metabolism" -- "${{cur}}"))
                return
                ;;
            --profile)
                COMPREPLY=($(compgen -W "{command_profiles}" -- "${{cur}}"))
                return
                ;;
            --include)
                COMPREPLY=($(compgen -W "{optional_command_groups}" -- "${{cur}}"))
                return
                ;;
            *)
                ;;
        esac
    else
        case "${{words[1]}}" in
            maintenance)
                COMPREPLY=($(compgen -W "{maintenance_actions}" -- "${{cur}}"))
                return
                ;;
            config)
                COMPREPLY=($(compgen -W "{config_actions}" -- "${{cur}}"))
                return
                ;;
            integration)
                if [[ "${{words[2]}}" == "commands" ]]; then
                    COMPREPLY=($(compgen -W "{integration_command_actions}" -- "${{cur}}"))
                else
                    COMPREPLY=($(compgen -W "{integration_actions}" -- "${{cur}}"))
                fi
                return
                ;;
            *)
                ;;
        esac
    fi

    if [[ "${{words[1]}}" == "config" && "${{cur}}" == -* ]]; then
        COMPREPLY=($(compgen -W "--project-root --scope" -- "${{cur}}"))
        return
    fi

    if [[ "${{words[1]}}" == "maintenance" && "${{cur}}" == -* ]]; then
        COMPREPLY=($(compgen -W "-p --project --source --before --category --stale-only --dry-run --apply --export-rollback --export-dir" -- "${{cur}}"))
        return
    fi

    if [[ "${{words[1]}}" == "integration" && "${{cur}}" == -* ]]; then
        COMPREPLY=($(compgen -W "--project-root --force --profile --include --source-dir --target-dir --dry-run" -- "${{cur}}"))
        return
    fi
}}

complete -F _harness_mem_completion harness-mem
"""


def completion_zsh() -> str:
    """Generate zsh completion script."""
    commands = " ".join(CLI_COMMANDS + list(CLI_ALIASES.keys()))
    maintenance_actions = " ".join(MAINTENANCE_ACTIONS)
    config_actions = " ".join(CONFIG_ACTIONS)
    integration_actions = " ".join(INTEGRATION_ACTIONS)
    integration_command_actions = " ".join(INTEGRATION_COMMAND_ACTIONS)
    command_profiles = " ".join(COMMAND_PROFILES)
    optional_command_groups = " ".join(OPTIONAL_COMMAND_GROUPS)
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
        '--source[JSON draft path]:source:' \\
        '--dry-run[preview only]' \\
        '--stale-only[only stale entries]' \\
        '--apply[write maintenance changes]' \\
        '--export-rollback[export Storage v2 canonical rows as v3 JSON]:export_dir:' \\
        '--project-root[project directory]:project_root:' \\
        '--scope[config scope]:(user project)' \\
        '--force[overwrite existing hook]' \\
        '--profile[command profile]:profile:({command_profiles})' \\
        '--include[optional command group]:include:({optional_command_groups})' \\
        '--source-dir[slash command source directory]:source_dir:' \\
        '--target-dir[Claude Code hm command directory]:target_dir:' \\
        '1: :->command' \\
        '2: :->arg'

    case $state in
        command)
            _describe 'command' commands
            ;;
        arg)
            case $words[2] in
                maintenance)
                    _values 'action' {maintenance_actions}
                    ;;
                config)
                    _values 'action' {config_actions}
                    ;;
                integration)
                    _values 'action' {integration_actions}
                    ;;
                commands)
                    _values 'action' {integration_command_actions}
                    ;;
            esac
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

# maintenance
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -a "rebuild-vector-index rebuild-verbatim-index migrate-store-v2 export-json-snapshot state-audit import purge" -d "Action"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l project -r -d "Project name"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l source -r -d "JSON draft path"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l before -r -d "Date (YYYY-MM-DD)"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l category -x -a "observations structured all" -d "Category"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l limit -x -d "Maximum records"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l stale-only -d "Only stale entries"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l dry-run -d "Preview only"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l apply -d "Write changes"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l export-rollback -r -d "Export Storage v2 canonical rows as v3 JSON"
complete -c harness-mem -n '__fish_seen_subcommand_from maintenance' -l export-dir -r -d "Export directory"

# config
complete -c harness-mem -n '__fish_seen_subcommand_from config' -a "get set list validate" -d "Action"
complete -c harness-mem -n '__fish_seen_subcommand_from config' -l project-root -r -d "Project directory"
complete -c harness-mem -n '__fish_seen_subcommand_from config; and __fish_seen_subcommand_from set' -l scope -x -a "user project" -d "Config scope"

# integration
complete -c harness-mem -n '__fish_seen_subcommand_from integration' -a "install-cursor-hook install-claude-hook commands" -d "Installer"
complete -c harness-mem -n '__fish_seen_subcommand_from integration' -l project-root -r -d "Project directory"
complete -c harness-mem -n '__fish_seen_subcommand_from integration' -l force -d "Overwrite existing hook"
complete -c harness-mem -n '__fish_seen_subcommand_from commands' -a "list sync enable" -d "Command profile action"
complete -c harness-mem -n '__fish_seen_subcommand_from commands' -l profile -x -a "daily maintenance full" -d "Command profile"
complete -c harness-mem -n '__fish_seen_subcommand_from commands' -l include -x -a "maintenance" -d "Optional command group"
complete -c harness-mem -n '__fish_seen_subcommand_from commands' -l source-dir -r -d "Slash command source directory"
complete -c harness-mem -n '__fish_seen_subcommand_from commands' -l target-dir -r -d "Claude Code hm command directory"
complete -c harness-mem -n '__fish_seen_subcommand_from commands' -l dry-run -d "Preview only"
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
