"""Generate shell completion scripts for the ls-compressor CLI."""

from __future__ import annotations

import argparse

_SHELLS = ("bash", "zsh", "fish")


def available_shells() -> tuple[str, ...]:
    """Return the shells with completion script templates."""
    return _SHELLS


def _subcommand_map(
    parser: argparse.ArgumentParser,
) -> dict[str, argparse.ArgumentParser]:
    """Map subcommand names to their parsers."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _option_strings(parser: argparse.ArgumentParser) -> list[str]:
    """Collect every long/short option string on a parser."""
    options: list[str] = []
    for action in parser._actions:
        if not action.option_strings:
            continue
        for option in action.option_strings:
            if option not in options:
                options.append(option)
    return options


def _option_choices(
    parser: argparse.ArgumentParser,
) -> dict[str, tuple[str, ...]]:
    """Map long option strings to their allowed choice values."""
    choices: dict[str, tuple[str, ...]] = {}
    for action in parser._actions:
        if action.choices is None:
            continue
        name = next(
            (option for option in action.option_strings if option.startswith("--")),
            None,
        )
        if name is not None:
            choices[name] = tuple(str(choice) for choice in action.choices)
    return choices


def completion_script(
    shell: str, parser: argparse.ArgumentParser, program: str = "ls-compressor"
) -> str:
    """Render a completion script for the given shell."""
    generators = {
        "bash": _bash_script,
        "zsh": _zsh_script,
        "fish": _fish_script,
    }
    if shell not in generators:
        raise ValueError(f"Unsupported shell: {shell}")
    return generators[shell](parser, program)


def _bash_script(parser: argparse.ArgumentParser, program: str) -> str:
    """Build a bash completion script."""
    commands = sorted(_subcommand_map(parser))
    cases = []
    for name, sub in sorted(_subcommand_map(parser).items()):
        words = " ".join(
            sorted(set(_option_strings(sub)) | set(_option_strings(parser)))
        )
        cases.append(f'        {name}) opts="{words}" ;;')
    case_block = "\n".join(cases)
    sub_words = " ".join(commands + _option_strings(parser))
    return f"""# bash completion for {program}
_{program.replace("-", "_")}() {{
    local cur sub opts
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    sub=""
    local i
    for ((i = 1; i < COMP_CWORD; i++)); do
        case "${{COMP_WORDS[i]}}" in
            {"|".join(commands)}) sub="${{COMP_WORDS[i]}}" ;;
        esac
    done
    if [ -z "$sub" ]; then
        COMPREPLY=($(compgen -W "{sub_words}" -- "$cur"))
        return 0
    fi
    case "$sub" in
{case_block}
        *) opts="" ;;
    esac
    if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "$opts" -- "$cur"))
    else
        COMPREPLY=($(compgen -f -- "$cur"))
    fi
    return 0
}}
complete -F _{program.replace("-", "_")} {program}
"""


def _zsh_script(parser: argparse.ArgumentParser, program: str) -> str:
    """Build a zsh completion script."""
    commands = sorted(_subcommand_map(parser))
    cases = []
    for name, sub in sorted(_subcommand_map(parser).items()):
        words = " ".join(
            sorted(set(_option_strings(sub)) | set(_option_strings(parser)))
        )
        cases.append(f"        {name}) opts=({words}) ;;")
    case_block = "\n".join(cases)
    return f"""#compdef {program}
# zsh completion for {program}
_{program.replace("-", "_")}() {{
    local -a subs opts
    subs=({" ".join(commands)})
    if (( CURRENT == 2 )); then
        compadd -- $subs
        return
    fi
    case "$words[2]" in
{case_block}
        *) opts=() ;;
    esac
    if [[ "$words[CURRENT]" == -* ]]; then
        compadd -- $opts
    else
        _files
    fi
}}
compdef _{program.replace("-", "_")} {program}
"""


def _fish_script(parser: argparse.ArgumentParser, program: str) -> str:
    """Build a fish completion script."""
    lines = [f"# fish completion for {program}"]
    lines.append(
        f"complete -c {program} -n '__fish_use_subcommand' "
        f"-a '{' '.join(sorted(_subcommand_map(parser)))}'"
    )
    for name, sub in sorted(_subcommand_map(parser).items()):
        condition = f"__fish_seen_subcommand_from {name}"
        choices = _option_choices(sub)
        for option in _option_strings(sub):
            parts = [
                f"complete -c {program} -n '{condition}'",
            ]
            if option.startswith("--"):
                parts.append(f"-l {option[2:]}")
            else:
                parts.append(f"-s {option.lstrip('-')}")
            if option in choices:
                parts.append(f"-a '{' '.join(choices[option])}'")
            lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"
