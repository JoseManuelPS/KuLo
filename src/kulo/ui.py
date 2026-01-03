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
    ColorAssigner,
    extract_log_level,
    extract_message,
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
        no_color_logs: bool = False,
    ) -> None:
        """Initialize the UI.

        Args:
            console: Optional Rich Console instance.
            show_namespace: Whether to include namespace in output.
            show_container: Whether to include container name in output.
            no_color_logs: Whether to disable log message colorization.
        """
        self.console = console or Console()
        self.show_namespace = show_namespace
        self.show_container = show_container
        self.pod_containers: dict[str, int] = {}
        self._color_assigner = ColorAssigner()
        self._max_prefix_width: int = 0
        self._no_color_logs = no_color_logs

    def configure_output(
        self,
        namespaces: list[str],
        pods: list[PodInfo],
        containers: list[ContainerInfo] | None = None,
    ) -> None:
        """Configure output based on discovered resources.

        Automatically hides namespace if single, and container if pods
        have only one container each. Initializes color assignments for
        deterministic coloring.

        Args:
            namespaces: List of namespaces being observed.
            pods: List of pods being observed.
            containers: Optional list of containers to stream. If provided,
                prefix width is calculated based on these containers only
                (useful when max_containers limits the displayed containers).
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

        # Initialize color assignments with sorted pod names for deterministic coloring
        pod_names = [pod.name for pod in pods]
        self._color_assigner.initialize(pod_names)

        # Calculate maximum prefix width for aligned output
        # Use containers list if provided (respects max_containers limit)
        if containers is not None:
            self._calculate_max_prefix_width_from_containers(containers)
        else:
            self._calculate_max_prefix_width(pods)

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
        max_streams_display = "unlimited" if max_containers == 0 else str(max_containers)
        self.console.print(
            Panel.fit(
                f"[bold cyan]KuLo[/] - Kubernetes Log Aggregator\n"
                f"[dim]Namespace(s): {ns_display} | Mode: {mode} | "
                f"Max streams: {max_streams_display}[/]",
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

        # Warning if over limit (skip if unlimited)
        if max_containers > 0 and total_containers > max_containers:
            self.console.print()
            self.console.print(
                f"[bold yellow]⚠  Warning:[/] Found {total_containers} containers, "
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

        Also updates the max prefix width if this container has a longer prefix.

        Args:
            container: The new container.
        """
        # Update prefix width for alignment
        self.update_prefix_width_for_container(container)

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

        # Build prefix parts: [namespace] pod_name (container)
        prefix_parts: list[str] = []

        if self.show_namespace:
            prefix_parts.append(f"[{entry.namespace}] ")

        prefix_parts.append(entry.pod_name)

        if self.show_container:
            prefix_parts.append(f" ({entry.container_name})")

        # Add prefix with pod color, padded to align with other entries
        prefix = "".join(prefix_parts)
        if self._max_prefix_width > 0:
            prefix = prefix.ljust(self._max_prefix_width)
        text.append(prefix, style=pod_color)
        text.append(" > ", style="dim")

        # Format message based on JSON or plain text
        if entry.is_json and entry.json_data:
            self._append_json_message(text, entry)
        else:
            # Plain text - use pod color for message
            message_style = "default" if self._no_color_logs else pod_color
            text.append(entry.message, style=message_style)

        return text

    def _append_json_message(self, text: Text, entry: LogEntry) -> None:
        """Append a JSON log message with intelligent formatting.

        Args:
            text: The Text object to append to.
            entry: The log entry with JSON data.
        """
        assert entry.json_data is not None

        # Get log level color and pod color
        level_color = get_log_level_color(entry.log_level)
        pod_color = self._get_pod_color(entry.pod_name)

        # Extract main message
        main_message = extract_message(entry.json_data)

        if entry.log_level:
            # Format: [LEVEL] message
            # [LEVEL] tag keeps log level color (unless no_color_logs)
            level_display = entry.log_level.upper()
            level_style = "default" if self._no_color_logs else f"bold {level_color}"
            text.append(f"[{level_display}] ", style=level_style)

        if main_message:
            # Message uses pod color (unless no_color_logs)
            message_style = "default" if self._no_color_logs else pod_color
            text.append(main_message, style=message_style)
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

        Uses the ColorAssigner for deterministic, non-repeating colors.

        Args:
            pod_name: The pod name.

        Returns:
            A Rich color string.
        """
        return self._color_assigner.get_color(pod_name)

    def _calculate_prefix_width(
        self,
        namespace: str,
        pod_name: str,
        container_name: str,
    ) -> int:
        """Calculate the width of a log prefix for a specific container.

        Uses the format: [namespace] pod_name (container_name)

        Args:
            namespace: The namespace name.
            pod_name: The pod name.
            container_name: The container name.

        Returns:
            The width of the prefix string (excluding padding).
        """
        width = 0

        if self.show_namespace:
            # Format: "[namespace] " (with trailing space)
            width += len(f"[{namespace}] ")

        # Pod name without brackets
        width += len(pod_name)

        if self.show_container:
            # Format: " (container_name)"
            width += len(f" ({container_name})")

        return width

    def _calculate_max_prefix_width(
        self,
        pods: list[PodInfo],
    ) -> None:
        """Calculate the maximum prefix width across all containers.

        Args:
            pods: List of pods being observed.
        """
        max_width = 0

        for pod in pods:
            # Get all container names for this pod
            all_containers = (
                pod.containers + pod.init_containers + pod.ephemeral_containers
            )

            for container_name in all_containers:
                width = self._calculate_prefix_width(
                    pod.namespace, pod.name, container_name
                )
                max_width = max(max_width, width)

        self._max_prefix_width = max_width

    def _calculate_max_prefix_width_from_containers(
        self,
        containers: list[ContainerInfo],
    ) -> None:
        """Calculate the maximum prefix width from a list of containers.

        This is used when max_containers limits which containers are displayed,
        ensuring prefix width is based only on the actually displayed containers.

        Args:
            containers: List of containers to be displayed.
        """
        max_width = 0

        for container in containers:
            width = self._calculate_prefix_width(
                container.namespace, container.pod_name, container.container_name
            )
            max_width = max(max_width, width)

        self._max_prefix_width = max_width

    def update_prefix_width_for_container(self, container: ContainerInfo) -> None:
        """Update the max prefix width if a new container has a longer prefix.

        Called when a new container is discovered dynamically.

        Args:
            container: The newly discovered container.
        """
        width = self._calculate_prefix_width(
            container.namespace, container.pod_name, container.container_name
        )
        if width > self._max_prefix_width:
            self._max_prefix_width = width

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

