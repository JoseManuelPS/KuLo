"""KuLo - Kubernetes Log Aggregator.

Entry point and CLI argument parsing for the KuLo application.
Orchestrates client, manager, and UI components.

Supports two modes:
- TUI Mode (default with -f): Interactive Textual-based interface
- CLI Mode (--no-tui or snapshot): Classic Rich-based output
"""

import argparse
import asyncio
import logging
import sys
from typing import NoReturn

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from kulo import __version__
from kulo.client import (
    KuloClient,
    KuloClientError,
    NamespaceNotFoundError,
    PermissionDeniedError,
)
from kulo.manager import LogManager
from kulo.models import ContainerInfo, PodInfo
from kulo.ui import KuloUI
from kulo.utils import (
    DurationParseError,
    compile_patterns,
    is_regex_pattern,
    matches_any,
    parse_duration,
    parse_namespaces,
    validate_label_selector,
)

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


LOGO = r"""
[bold cyan]  _  __      _          [/]
[bold cyan] | |/ /     | |         [/]
[bold cyan] | ' / _   _| |     ___  [/]
[bold cyan] |  < | | | | |    / _ \ [/]
[bold cyan] | . \| |_| | |___| (_) |[/]
[bold cyan] |_|\_\\__,_|______\___/ [/]
"""


def print_help() -> None:
    """Print a beautifully formatted help message using Rich."""
    console = Console()

    # Logo and title
    console.print(LOGO)
    console.print(
        f"  [bold]KuLo[/] [dim]v{__version__}[/] · Kubernetes Log Aggregator\n",
        highlight=False,
    )
    console.print(
        "  [italic]Visualize K8s logs in an aggregated, filterable, "
        "and aesthetically superior manner.[/]\n"
    )

    # Usage
    console.print("[bold yellow]Usage:[/]")
    console.print("  kulo [OPTIONS]\n")

    # Filtering options
    console.print("[bold yellow]Filtering:[/]")
    filter_table = Table(show_header=False, box=None, padding=(0, 2), collapse_padding=True)
    filter_table.add_column("Option", style="cyan", no_wrap=True)
    filter_table.add_column("Description")
    filter_table.add_row("-n, --namespace NS", "Namespaces (comma-separated or regex)")
    filter_table.add_row("-l, --label-selector SEL", "Kubernetes label selector [dim](e.g., app=web)[/]")
    filter_table.add_row("-f, --filter PATTERN", "Regex patterns to filter/include pods")
    filter_table.add_row("-e, --exclude PATTERN", "Regex patterns to exclude pods")
    filter_table.add_row("--exclude-init", "Exclude init containers")
    filter_table.add_row("--exclude-ephemeral", "Exclude ephemeral containers")
    console.print(filter_table)
    console.print()

    # Mode options
    console.print("[bold yellow]Mode:[/]")
    mode_table = Table(show_header=False, box=None, padding=(0, 2), collapse_padding=True)
    mode_table.add_column("Option", style="cyan", no_wrap=True)
    mode_table.add_column("Description")
    mode_table.add_row("--snap", "Snapshot mode (fetch logs once, no streaming)")
    console.print(mode_table)
    console.print()

    # General options
    console.print("[bold yellow]Options:[/]")
    options_table = Table(show_header=False, box=None, padding=(0, 2), collapse_padding=True)
    options_table.add_column("Option", style="cyan", no_wrap=True)
    options_table.add_column("Description")
    options_table.add_row("-s, --since DURATION", "Show logs since duration [dim](default: 10m)[/]")
    options_table.add_row("-t, --tail N", "Initial lines to show [dim](default: 25)[/]")
    options_table.add_row("--max-containers N", "Max concurrent streams [dim](default: 10, 0=unlimited)[/]")
    options_table.add_row("-v, --verbose", "Increase verbosity [dim](-v info, -vv debug)[/]")
    console.print(options_table)
    console.print()

    # Examples panel
    examples = Text()
    examples.append("kulo", style="cyan")
    examples.append("                           # Stream logs (TUI mode)\n")
    examples.append("kulo ", style="white")
    examples.append("-n", style="cyan")
    examples.append(" frontend,backend       # Multiple namespaces\n")
    examples.append("kulo ", style="white")
    examples.append("-n", style="cyan")
    examples.append(" 'dev-.*'               # Namespaces matching regex\n")
    examples.append("kulo ", style="white")
    examples.append("-l", style="cyan")
    examples.append(" app=web                # Filter pods by label\n")
    examples.append("kulo ", style="white")
    examples.append("-f", style="cyan")
    examples.append(" 'api-.*' ")
    examples.append("-e", style="cyan")
    examples.append(" 'test-.*'  # Filter/exclude by regex\n")
    examples.append("kulo ", style="white")
    examples.append("--snap", style="cyan")
    examples.append(" -s", style="cyan")
    examples.append(" 1h ")
    examples.append("-t", style="cyan")
    examples.append(" 100       # Snapshot: last hour, 100 lines")

    console.print(Panel(examples, title="[bold]Examples[/]", border_style="dim", padding=(0, 1)))


class RichHelpAction(argparse.Action):
    """Custom help action that prints Rich-formatted help."""

    def __init__(
        self,
        option_strings,
        dest=argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        help="Show this help message and exit",  # noqa: A002
    ):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, _namespace, _values, _option_string=None):
        print_help()
        parser.exit()


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for KuLo.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="kulo",
        add_help=False,
    )

    # Custom help
    parser.add_argument(
        "-h", "--help",
        action=RichHelpAction,
    )

    # Version
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Namespace selection
    parser.add_argument(
        "-n", "--namespace",
        type=str,
        default=None,
        metavar="NS",
        help="Comma-separated list of namespaces or regex patterns (default: current context)",
    )

    # Label selector
    parser.add_argument(
        "-l", "--label-selector",
        type=str,
        default=None,
        metavar="SELECTOR",
        help="Kubernetes label selector for server-side filtering (e.g., 'app=web')",
    )

    # Filter/exclude regex
    parser.add_argument(
        "-f", "--filter",
        type=str,
        default=None,
        metavar="PATTERN",
        help="Comma-separated regex patterns to filter/include pods",
    )

    parser.add_argument(
        "-e", "--exclude",
        type=str,
        default=None,
        metavar="PATTERN",
        help="Comma-separated regex patterns to exclude pods",
    )

    # Container type exclusions
    parser.add_argument(
        "--exclude-init",
        action="store_true",
        help="Exclude init containers from output",
    )

    parser.add_argument(
        "--exclude-ephemeral",
        action="store_true",
        help="Exclude ephemeral containers from output",
    )

    # Mode selection
    parser.add_argument(
        "--snap",
        action="store_true",
        help="Snapshot mode: fetch logs once without streaming (CLI output)",
    )

    parser.add_argument(
        "-s", "--since",
        type=str,
        default="10m",
        metavar="DURATION",
        help="Show logs since duration (e.g., 10s, 5m, 1h). Default: 10m",
    )

    parser.add_argument(
        "-t", "--tail",
        type=int,
        default=25,
        metavar="N",
        help="Number of lines to show initially. Default: 25",
    )

    # Throttling
    parser.add_argument(
        "--max-containers",
        type=int,
        default=10,
        metavar="N",
        help="Maximum concurrent container streams (0 = unlimited). Default: 10",
    )

    # Verbosity
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug)",
    )

    # Log colorization
    parser.add_argument(
        "--no-color-logs",
        action="store_true",
        help="Disable log message colorization (plain output)",
    )

    return parser


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level.

    Args:
        verbosity: Number of -v flags (0=warning, 1=info, 2=debug).
    """
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.getLogger().setLevel(level)
    logging.getLogger("kulo").setLevel(level)

    # Suppress noisy libraries unless very verbose
    if verbosity < 2:
        logging.getLogger("kubernetes_asyncio").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)


async def run_kulo(args: argparse.Namespace) -> int:
    """Main async entry point for KuLo.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    ui = KuloUI(no_color_logs=args.no_color_logs)

    # Parse and validate arguments
    try:
        since_seconds = parse_duration(args.since)
    except DurationParseError as e:
        ui.print_error(str(e))
        return 1

    try:
        label_selector = validate_label_selector(args.label_selector)
    except ValueError as e:
        ui.print_error(str(e))
        return 1

    try:
        filter_patterns = compile_patterns(args.filter)
    except ValueError as e:
        ui.print_error(f"Invalid filter pattern: {e}")
        return 1

    try:
        exclude_patterns = compile_patterns(args.exclude)
    except ValueError as e:
        ui.print_error(f"Invalid exclude pattern: {e}")
        return 1

    # Connect to Kubernetes
    try:
        async with KuloClient.create() as client:
            # Resolve namespaces (supports both exact names and regex patterns)
            namespace_args = parse_namespaces(args.namespace)
            if not namespace_args:
                # Use current context namespace
                current_ns = await client.get_current_namespace()
                namespaces = [current_ns]
            else:
                # Check if any namespace arg contains regex patterns
                has_regex = any(is_regex_pattern(ns) for ns in namespace_args)

                if has_regex:
                    # Resolve regex patterns against all cluster namespaces
                    namespaces = await resolve_namespace_patterns(
                        client, namespace_args, ui
                    )
                    if not namespaces:
                        return 1  # Error already printed
                else:
                    # Exact namespace names - validate they exist
                    namespaces = []
                    for ns in namespace_args:
                        if not await client.check_namespace_exists(ns):
                            ui.print_error(f"Namespace '{ns}' does not exist")
                            return 1
                        namespaces.append(ns)

            # Discover pods
            all_pods: list[PodInfo] = []
            for ns in namespaces:
                try:
                    pods = await client.list_pods(ns, label_selector)
                    all_pods.extend(pods)
                except NamespaceNotFoundError as e:
                    ui.print_error(str(e))
                    return 1
                except PermissionDeniedError as e:
                    ui.print_error(str(e))
                    return 1

            # Apply regex filters (client-side)
            filtered_pods = filter_pods(
                pods=all_pods,
                filter_patterns=filter_patterns,
                exclude_patterns=exclude_patterns,
            )

            if not filtered_pods:
                ui.print_warning("No pods found matching the specified criteria")
                return 0

            # Get all containers
            all_containers = get_containers(
                pods=filtered_pods,
                exclude_init=args.exclude_init,
                exclude_ephemeral=args.exclude_ephemeral,
            )

            if not all_containers:
                ui.print_warning("No containers found in matching pods")
                return 0

            # Apply throttling (0 = unlimited)
            containers_to_stream = all_containers
            if args.max_containers > 0 and len(all_containers) > args.max_containers:
                containers_to_stream = all_containers[:args.max_containers]

            # Configure UI output (pass containers to calculate prefix width correctly)
            ui.configure_output(namespaces, filtered_pods, containers_to_stream)

            # Print summary (snapshot mode - no follow)
            ui.print_summary(
                pods=filtered_pods,
                namespaces=namespaces,
                follow=False,
                max_containers=args.max_containers,
            )

            # Create and run manager (snapshot mode - no streaming)
            manager = LogManager(client)

            # When max_containers is 0 (unlimited), use actual container count
            max_concurrent = (
                len(containers_to_stream)
                if args.max_containers == 0
                else args.max_containers
            )

            await manager.run(
                containers=containers_to_stream,
                ui=ui,
                follow=False,
                since_seconds=since_seconds,
                tail_lines=args.tail,
                max_concurrent=max_concurrent,
                label_selector=label_selector,
                namespaces=namespaces,
                on_new_container=ui.print_new_container,
            )

            return 0

    except KuloClientError as e:
        ui.print_error(str(e))
        return 1
    except KeyboardInterrupt:
        ui.console.print("\n[dim]Interrupted[/]")
        return 130  # Standard exit code for SIGINT


def filter_pods(
    pods: list[PodInfo],
    filter_patterns: list,
    exclude_patterns: list,
) -> list[PodInfo]:
    """Filter pods based on filter/exclude patterns.

    Args:
        pods: List of pods to filter.
        filter_patterns: Compiled filter regex patterns (include).
        exclude_patterns: Compiled exclude regex patterns.

    Returns:
        Filtered list of pods.
    """
    result = []

    for pod in pods:
        # Filter: if patterns exist, pod must match at least one
        if filter_patterns and not matches_any(pod.name, filter_patterns):
            continue

        # Exclude filter: if pod matches any pattern, skip it
        if exclude_patterns and matches_any(pod.name, exclude_patterns):
            continue

        result.append(pod)

    return result


def get_containers(
    pods: list[PodInfo],
    exclude_init: bool = False,
    exclude_ephemeral: bool = False,
) -> list[ContainerInfo]:
    """Get all containers from a list of pods.

    Args:
        pods: List of pods.
        exclude_init: Whether to exclude init containers.
        exclude_ephemeral: Whether to exclude ephemeral containers.

    Returns:
        List of ContainerInfo objects.
    """
    containers: list[ContainerInfo] = []

    for pod in pods:
        # Skip pods that aren't in a loggable state
        if pod.phase not in ("Running", "Succeeded", "Failed"):
            logger.debug(f"Skipping pod {pod.name} in phase {pod.phase}")
            continue

        pod_containers = pod.get_all_containers(
            exclude_init=exclude_init,
            exclude_ephemeral=exclude_ephemeral,
        )
        containers.extend(pod_containers)

    return containers


async def resolve_namespace_patterns(
    client: KuloClient,
    namespace_args: list[str],
    ui: KuloUI,
) -> list[str]:
    """Resolve namespace arguments that may contain regex patterns.

    For exact namespace names, validates they exist.
    For regex patterns, lists all namespaces and filters by matching patterns.

    Args:
        client: The KuloClient instance.
        namespace_args: List of namespace names or regex patterns.
        ui: The UI instance for error reporting.

    Returns:
        List of resolved namespace names, or empty list on error.
    """
    import re

    # Separate exact names from regex patterns
    exact_names: list[str] = []
    regex_patterns: list[re.Pattern[str]] = []

    for ns_arg in namespace_args:
        if is_regex_pattern(ns_arg):
            try:
                regex_patterns.append(re.compile(ns_arg, re.IGNORECASE))
            except re.error as e:
                ui.print_error(f"Invalid namespace regex pattern '{ns_arg}': {e}")
                return []
        else:
            exact_names.append(ns_arg)

    resolved: list[str] = []

    # Validate exact names exist
    for ns in exact_names:
        if not await client.check_namespace_exists(ns):
            ui.print_error(f"Namespace '{ns}' does not exist")
            return []
        resolved.append(ns)

    # Resolve regex patterns by listing all namespaces
    if regex_patterns:
        try:
            all_namespaces = await client.list_all_namespaces()
        except PermissionDeniedError as e:
            ui.print_error(str(e))
            return []

        for ns in all_namespaces:
            # Skip if already in resolved (from exact match)
            if ns in resolved:
                continue

            # Check if matches any pattern
            if any(pattern.search(ns) for pattern in regex_patterns):
                resolved.append(ns)

    if not resolved:
        ui.print_warning("No namespaces found matching the specified patterns")

    return resolved


def is_snapshot_mode(args: argparse.Namespace) -> bool:
    """Determine if snapshot mode should be used.

    Snapshot mode is used when --snap flag is set.
    Otherwise, the default is follow mode (TUI).

    Args:
        args: Parsed command-line arguments.

    Returns:
        True if snapshot mode should be used.
    """
    return args.snap


def run_tui_mode(args: argparse.Namespace) -> int:
    """Run KuLo in interactive TUI mode (follow/streaming mode).

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    from kulo.app import run_tui

    # Parse arguments
    try:
        since_seconds = parse_duration(args.since)
    except DurationParseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        label_selector = validate_label_selector(args.label_selector)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Parse namespaces
    namespaces = parse_namespaces(args.namespace)

    try:
        run_tui(
            namespaces=namespaces or None,
            filter_pattern=args.filter or "",
            exclude_pattern=args.exclude or "",
            label_selector=label_selector or "",
            since_seconds=since_seconds,
            tail_lines=args.tail,
            max_containers=args.max_containers,
            no_color_logs=args.no_color_logs,
        )
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main() -> NoReturn:
    """CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    configure_logging(args.verbose)

    # Choose mode based on arguments
    # Default is follow mode (TUI), --snap triggers snapshot mode (CLI)
    if is_snapshot_mode(args):
        try:
            exit_code = asyncio.run(run_kulo(args))
        except KeyboardInterrupt:
            print("\nInterrupted")
            exit_code = 130
    else:
        exit_code = run_tui_mode(args)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

