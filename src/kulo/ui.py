"""Rich console UI for KuLo.

This module handles all terminal output using the Rich library:
- Summary tables showing observed pods
- Log line formatting with colors
- JSON log detection and intelligent rendering
- Smart field omission (namespace/container when single)
"""

import json
import logging
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from kulo.models import ContainerInfo, LogEntry, PodInfo
from kulo.utils import (
    extract_log_level,
    extract_message,
    get_color_for_pod,
    get_log_level_color,
)


logger = logging.getLogger(__name__)


class KuloUI:
    """Rich-based terminal UI for log visualization.

    Provides methods for rendering log entries with colors, JSON detection,
    and smart field omission for cleaner output.

    Attributes:
        console: The Rich Console instance.
        show_namespace: Whether to show namespace in output.
        show_container: Whether to show container in output.
        pod_containers: Map of pod names to container counts.

    Example:
        ui = KuloUI()
        ui.print_summary(pods)
        ui.print_log_entry(entry)
    """

    def __init__(
        self,
        console: Console | None = None,
        show_namespace: bool = True,
        show_container: bool = True,
    ) -> None:
        """Initialize the UI.

        Args:
            console: Optional Rich Console instance.
            show_namespace: Whether to include namespace in output.
            show_container: Whether to include container name in output.
        """
        self.console = console or Console()
        self.show_namespace = show_namespace
        self.show_container = show_container
        self.pod_containers: dict[str, int] = {}
        self._pod_colors: dict[str, str] = {}

    def configure_output(
        self,
        namespaces: list[str],
        pods: list[PodInfo],
    ) -> None:
        """Configure output based on discovered resources.

        Automatically hides namespace if single, and container if pods
        have only one container each.

        Args:
            namespaces: List of namespaces being observed.
            pods: List of pods being observed.
        """
        # Hide namespace if only one
        if len(namespaces) == 1:
            self.show_namespace = False
        else:
            self.show_namespace = True

        # Track container count per pod
        for pod in pods:
            total_containers = (
                len(pod.containers)
                + len(pod.init_containers)
                + len(pod.ephemeral_containers)
            )
            self.pod_containers[pod.name] = total_containers

        # Show container only if any pod has multiple containers
        self.show_container = any(count > 1 for count in self.pod_containers.values())

    def print_summary(
        self,
        pods: list[PodInfo],
        namespaces: list[str],
        follow: bool = False,
        max_containers: int = 10,
    ) -> None:
        """Print a summary table of pods being observed.

        Args:
            pods: List of pods to display.
            namespaces: List of namespaces.
            follow: Whether in follow mode.
            max_containers: Maximum concurrent containers.
        """
        # Header panel
        mode = "Follow Mode" if follow else "Snapshot Mode"
        ns_display = ", ".join(namespaces) if namespaces else "current context"

        self.console.print()
        self.console.print(
            Panel.fit(
                f"[bold cyan]KuLo[/] - Kubernetes Log Aggregator\n"
                f"[dim]Namespace(s): {ns_display} | Mode: {mode} | "
                f"Max streams: {max_containers}[/]",
                border_style="cyan",
            )
        )
        self.console.print()

        if not pods:
            self.console.print("[yellow]No pods found matching criteria[/]")
            return

        # Create pods table
        table = Table(
            title="Observed Pods",
            title_style="bold",
            border_style="dim",
            header_style="bold cyan",
        )

        table.add_column("Namespace", style="dim")
        table.add_column("Pod", style="bold")
        table.add_column("Phase", justify="center")
        table.add_column("Containers", justify="right")
        table.add_column("Color")

        total_containers = 0

        for pod in pods:
            color = self._get_pod_color(pod.name)

            # Phase styling
            phase_style = self._get_phase_style(pod.phase)
            phase_display = f"[{phase_style}]{pod.phase}[/]"

            # Container count
            container_count = (
                len(pod.containers)
                + len(pod.init_containers)
                + len(pod.ephemeral_containers)
            )
            total_containers += container_count

            # Container breakdown
            parts = []
            if pod.containers:
                parts.append(f"{len(pod.containers)} main")
            if pod.init_containers:
                parts.append(f"{len(pod.init_containers)} init")
            if pod.ephemeral_containers:
                parts.append(f"{len(pod.ephemeral_containers)} eph")
            container_info = ", ".join(parts) if parts else "0"

            # Color swatch
            color_swatch = f"[{color}]████[/]"

            table.add_row(
                pod.namespace,
                pod.name,
                phase_display,
                container_info,
                color_swatch,
            )

        self.console.print(table)

        # Warning if over limit
        if total_containers > max_containers:
            self.console.print()
            self.console.print(
                f"[bold yellow]⚠ Warning:[/] Found {total_containers} containers, "
                f"but max-containers is {max_containers}. "
                f"Only the first {max_containers} will be streamed."
            )

        self.console.print()
        self.console.print("[dim]─" * 60 + "[/]")
        self.console.print()

    def print_log_entry(self, entry: LogEntry) -> None:
        """Print a formatted log entry.

        Args:
            entry: The log entry to print.
        """
        # Detect JSON and parse if possible
        json_data = self._try_parse_json(entry.message)

        if json_data:
            entry.is_json = True
            entry.json_data = json_data
            entry.log_level = extract_log_level(json_data)

        # Format and print
        formatted = self._format_log_line(entry)
        self.console.print(formatted)

    def print_new_container(self, container: ContainerInfo) -> None:
        """Print a notification about a newly discovered container.

        Args:
            container: The new container.
        """
        color = self._get_pod_color(container.pod_name)
        self.console.print(
            f"[dim][{color}]➜[/] New container: "
            f"{container.namespace}/{container.pod_name}/{container.container_name}[/]"
        )

    def print_error(self, message: str) -> None:
        """Print an error message.

        Args:
            message: The error message.
        """
        self.console.print(f"[bold red]Error:[/] {message}")

    def print_warning(self, message: str) -> None:
        """Print a warning message.

        Args:
            message: The warning message.
        """
        self.console.print(f"[bold yellow]Warning:[/] {message}")

    def print_info(self, message: str) -> None:
        """Print an info message.

        Args:
            message: The info message.
        """
        self.console.print(f"[cyan]Info:[/] {message}")

    def _format_log_line(self, entry: LogEntry) -> Text:
        """Format a log entry for display.

        Args:
            entry: The log entry to format.

        Returns:
            A Rich Text object with formatting.
        """
        text = Text()
        pod_color = self._get_pod_color(entry.pod_name)

        # Build prefix parts
        prefix_parts: list[str] = []

        if self.show_namespace:
            prefix_parts.append(f"[{entry.namespace}]")

        prefix_parts.append(f"[{entry.pod_name}]")

        if self.show_container:
            prefix_parts.append(f"[{entry.container_name}]")

        # Add prefix with pod color
        prefix = "".join(prefix_parts)
        text.append(prefix, style=pod_color)
        text.append(" | ", style="dim")

        # Format message based on JSON or plain text
        if entry.is_json and entry.json_data:
            self._append_json_message(text, entry)
        else:
            # Plain text - apply log level color if detected
            message_style = self._detect_log_level_from_text(entry.message)
            text.append(entry.message, style=message_style)

        return text

    def _append_json_message(self, text: Text, entry: LogEntry) -> None:
        """Append a JSON log message with intelligent formatting.

        Args:
            text: The Text object to append to.
            entry: The log entry with JSON data.
        """
        assert entry.json_data is not None

        # Get log level color
        level_color = get_log_level_color(entry.log_level)

        # Extract main message
        main_message = extract_message(entry.json_data)

        if entry.log_level:
            # Format: [LEVEL] message
            level_display = entry.log_level.upper()
            text.append(f"[{level_display}] ", style=f"bold {level_color}")

        if main_message:
            text.append(main_message, style=level_color)
        else:
            # No message field - show full JSON
            text.append(entry.message, style="dim")
            return

        # Show remaining fields as metadata
        metadata = self._get_metadata_fields(entry.json_data)
        if metadata:
            text.append(" ", style="default")
            text.append(self._format_metadata(metadata), style="dim")

    def _get_metadata_fields(self, json_data: dict) -> dict[str, Any]:
        """Get metadata fields (excluding level and message).

        Args:
            json_data: The parsed JSON data.

        Returns:
            Dictionary of metadata fields.
        """
        from kulo.utils import LOG_LEVEL_FIELDS, MESSAGE_FIELDS

        excluded = set(LOG_LEVEL_FIELDS + MESSAGE_FIELDS)
        excluded.update(["time", "timestamp", "ts", "@timestamp", "t"])

        return {k: v for k, v in json_data.items() if k not in excluded}

    def _format_metadata(self, metadata: dict[str, Any]) -> str:
        """Format metadata fields as a compact string.

        Args:
            metadata: The metadata dictionary.

        Returns:
            Formatted string representation.
        """
        if not metadata:
            return ""

        parts = []
        for key, value in metadata.items():
            if isinstance(value, str):
                parts.append(f"{key}={value}")
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}={value}")
            else:
                # Complex value - use compact JSON
                parts.append(f"{key}={json.dumps(value, separators=(',', ':'))}")

        return " ".join(parts)

    def _try_parse_json(self, message: str) -> dict | None:
        """Try to parse a message as JSON.

        Args:
            message: The log message.

        Returns:
            Parsed JSON dict if valid, None otherwise.
        """
        message = message.strip()
        if not message.startswith("{"):
            return None

        try:
            data = json.loads(message)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    def _detect_log_level_from_text(self, message: str) -> str:
        """Detect log level from plain text message.

        Args:
            message: The log message.

        Returns:
            A Rich style string for the detected level.
        """
        message_upper = message.upper()

        # Check for common patterns
        if any(x in message_upper for x in ["ERROR", "FATAL", "PANIC", "CRITICAL"]):
            return "red"
        if any(x in message_upper for x in ["WARN", "WARNING"]):
            return "yellow"
        if "DEBUG" in message_upper:
            return "dim"

        return "default"

    def _get_pod_color(self, pod_name: str) -> str:
        """Get or assign a color for a pod.

        Args:
            pod_name: The pod name.

        Returns:
            A Rich color string.
        """
        if pod_name not in self._pod_colors:
            self._pod_colors[pod_name] = get_color_for_pod(pod_name)
        return self._pod_colors[pod_name]

    def _get_phase_style(self, phase: str) -> str:
        """Get the style for a pod phase.

        Args:
            phase: The pod phase string.

        Returns:
            A Rich style string.
        """
        phase_styles = {
            "Running": "green",
            "Succeeded": "green",
            "Pending": "yellow",
            "Failed": "red",
            "Unknown": "dim red",
            "CrashLoopBackOff": "bold red",
            "Error": "red",
            "Terminating": "yellow",
        }
        return phase_styles.get(phase, "dim")

