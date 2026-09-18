"""CLI for running production Jev use-case harnesses."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from jev_usecases.client import MissingApiKeyError
from jev_usecases.registry import USE_CASES, run_use_case

console = Console()


@click.group()
def main() -> None:
    """Production TypeSafe Jev use-case runners."""


@main.command("list")
def list_cmd() -> None:
    """List available use cases."""
    table = Table(title="Jev use cases")
    table.add_column("name")
    for name in sorted(USE_CASES):
        table.add_row(name)
    console.print(table)


@main.command("run")
@click.argument("name", type=click.Choice(sorted(USE_CASES), case_sensitive=True))
@click.option("--json-out", "json_out", is_flag=True, help="Print machine-readable JSON only")
def run_cmd(name: str, json_out: bool) -> None:
    """Run one use case against the live TypeSafe API using its fixture."""
    try:
        result = run_use_case(name)
    except MissingApiKeyError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 — surface API/validation errors to CLI users
        console.print(f"[red]{type(exc).__name__}: {exc}[/red]")
        sys.exit(1)

    payload = result.to_cli_dict()
    if json_out:
        click.echo(json.dumps(payload, indent=2))
        return

    console.print(f"[bold]{result.use_case}[/bold] → {result.decision} ({result.action_band})")
    console.print(result.rationale)
    console.print("actions:", result.actions)
    console.print(JSON.from_data(payload))


@main.command("run-all")
@click.option("--fail-fast/--no-fail-fast", default=True)
@click.option("--json-out", "json_out", is_flag=True)
def run_all_cmd(fail_fast: bool, json_out: bool) -> None:
    """Run every use case against the live API."""
    results = []
    failures = []
    for name in sorted(USE_CASES):
        console.print(f"[cyan]Running {name}...[/cyan]")
        try:
            result = run_use_case(name)
            results.append(result.to_cli_dict())
            console.print(f"  [green]OK[/green] {result.decision} ({result.action_band})")
        except Exception as exc:  # noqa: BLE001
            failures.append({"use_case": name, "error": f"{type(exc).__name__}: {exc}"})
            console.print(f"  [red]FAIL[/red] {exc}")
            if fail_fast:
                break
    payload = {"results": results, "failures": failures}
    if json_out:
        click.echo(json.dumps(payload, indent=2))
    if failures:
        sys.exit(1)


@main.command("security")
@click.option("--json-out", "json_out", is_flag=True)
def security_cmd(json_out: bool) -> None:
    """Run the Jev + Claude/OpenAI security pipelines."""
    names = (
        "security_incident_copilot",
        "security_guarded_assistant",
        "security_tool_gate",
    )
    payload = []
    failed = False
    for name in names:
        console.print(f"[cyan]Running {name}...[/cyan]")
        try:
            result = run_use_case(name)
        except Exception as exc:  # noqa: BLE001
            failed = True
            console.print(f"  [red]FAIL[/red] {type(exc).__name__}: {exc}")
            payload.append({"use_case": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        llm = (result.metadata or {}).get("llm") or {}
        provider = llm.get("provider", "not-called")
        model = llm.get("model", "")
        console.print(
            f"  [green]OK[/green] {result.decision} ({result.action_band}) via {provider} {model}".rstrip()
        )
        payload.append(result.to_cli_dict())
    if json_out:
        click.echo(json.dumps(payload, indent=2))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
