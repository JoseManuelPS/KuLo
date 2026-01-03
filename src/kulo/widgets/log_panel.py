"""Log panel widget for KuLo TUI.

This module provides the main log display area using Textual's RichLog widget.
"""

import json
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import RichLog

from kulo.models import LogEntry
from kulo.utils import (
    LOG_LEVEL_FIELDS,
    MESSAGE_FIELDS,
    extract_log_level,
    extract_message,
    get_log_level_color,
)

if TYPE_CHECKING:
    from kulo.state import AppState


class LogPanel(RichLog):
    """Main log display panel.

    Shows log entries with colored prefixes based on pod assignment.
    Supports virtual scrolling for large log volumes.

    Attributes:
        state: Reference to the application state for colors and filtering.
        show_namespace: Whether to show namespace in log prefix.
        show_container: Whether to show container name in log prefix.
        max_prefix_width: Maximum width of log prefix for alignment.
    """

    DEFAULT_CSS = """
    LogPanel {
        border: solid $primary;
        background: $surface;
        scrollbar-gutter: stable;
    }
    """

    def __init__(
        self,
        state: "AppState | None" = None,
        show_namespace: bool = True,
        show_container: bool = True,
        **kwargs,
    ) -> None:
        """Initialize the log panel.

        Args:
            state: Application state for colors and pod info.
            show_namespace: Whether to show namespace prefix.
            show_container: Whether to show container prefix.
            **kwargs: Additional arguments passed to RichLog.
        """
        super().__init__(
            highlight=False,
            markup=False,
            wrap=True,
            auto_scroll=True,
            **kwargs,
        )
        self._state = state
        self.show_namespace = show_namespace
        self.show_container = show_container
        self._max_prefix_width: int = 0

    def set_state(self, state: "AppState") -> None:
        """Set the application state reference.

        Args:
            state: The application state.
        """
        self._state = state

    def configure_output(
        self,
        namespaces: list[str],
        show_container: bool = True,
    ) -> None:
        """Configure output display options.

        Args:
            namespaces: List of namespaces being observed.
            show_container: Whether to show container names.
        """
        # Hide namespace if only one
        self.show_namespace = len(namespaces) > 1
        self.show_container = show_container

    def update_prefix_width(self, width: int) -> None:
        """Update the maximum prefix width for alignment.

        Args:
            width: The new maximum width.
        """
        if width > self._max_prefix_width:
            self._max_prefix_width = width

    def add_log_entry(self, entry: LogEntry) -> None:
        """Add a log entry to the display.

        Filters entries from inactive pods and formats with colors.

        Args:
            entry: The log entry to display.
        """
        # Filter out inactive pods
        if self._state and not self._state.is_pod_active(entry.pod_name):
            return

        # Format and display
        formatted = self._format_log_line(entry)
        self.write(formatted)

    def _format_log_line(self, entry: LogEntry) -> Text:
        """Format a log entry for display.

        In TUI mode, shows only a colored dot as prefix instead of full pod name.
        The pod legend on the right provides the full reference.

        Args:
            entry: The log entry to format.

        Returns:
            A Rich Text object with formatting.
        """
        text = Text()

        # Get pod color from state or default
        if self._state:
            pod_color = self._state.get_pod_color(entry.pod_name)
        else:
            pod_color = "cyan"

        # In TUI mode: just show colored dot as identifier
        text.append("● ", style=pod_color)

        # Try to parse as JSON
        json_data = self._try_parse_json(entry.message)

        if json_data:
            self._append_json_message(text, json_data, pod_color)
        else:
            # Plain text - use pod color for message
            no_color = self._state.no_color_logs if self._state else False
            message_style = "default" if no_color else pod_color
            text.append(entry.message, style=message_style)

        return text

    def _append_json_message(self, text: Text, json_data: dict, pod_color: str) -> None:
        """Append a JSON log message with intelligent formatting.

        Args:
            text: The Text object to append to.
            json_data: The parsed JSON data.
            pod_color: The color assigned to the pod.
        """
        # Get log level and color
        log_level = extract_log_level(json_data)
        level_color = get_log_level_color(log_level)

        # Check if colorization is disabled
        no_color = self._state.no_color_logs if self._state else False

        # Extract main message
        main_message = extract_message(json_data)

        if log_level:
            # Format: [LEVEL] message
            # [LEVEL] tag keeps log level color (unless no_color_logs)
            level_display = log_level.upper()
            level_style = "default" if no_color else f"bold {level_color}"
            text.append(f"[{level_display}] ", style=level_style)

        if main_message:
            # Message uses pod color (unless no_color_logs)
            message_style = "default" if no_color else pod_color
            text.append(main_message, style=message_style)
        else:
            # No message field - show full JSON
            text.append(json.dumps(json_data, separators=(",", ":")), style="dim")
            return

        # Show remaining fields as metadata
        metadata = self._get_metadata_fields(json_data)
        if metadata:
            text.append(" ", style="default")
            text.append(self._format_metadata(metadata), style="dim")

    def _get_metadata_fields(self, json_data: dict) -> dict:
        """Get metadata fields (excluding level and message).

        Args:
            json_data: The parsed JSON data.

        Returns:
            Dictionary of metadata fields.
        """
        excluded = set(LOG_LEVEL_FIELDS + MESSAGE_FIELDS)
        excluded.update(["time", "timestamp", "ts", "@timestamp", "t"])

        return {k: v for k, v in json_data.items() if k not in excluded}

    def _format_metadata(self, metadata: dict) -> str:
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

        if any(x in message_upper for x in ["ERROR", "FATAL", "PANIC", "CRITICAL"]):
            return "red"
        if any(x in message_upper for x in ["WARN", "WARNING"]):
            return "yellow"
        if "DEBUG" in message_upper:
            return "dim"

        return "default"

