"""Pod legend widget for KuLo TUI.

This module provides an interactive pod list with color indicators
and toggle functionality.
"""

from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from kulo.models import PodInfo
    from kulo.state import AppState


class PodToggled(Message):
    """Message sent when a pod is toggled."""

    def __init__(self, pod_name: str, enabled: bool) -> None:
        """Initialize the message.

        Args:
            pod_name: The name of the toggled pod.
            enabled: The new enabled state.
        """
        super().__init__()
        self.pod_name = pod_name
        self.enabled = enabled


class PodLegend(OptionList):
    """Interactive pod legend panel.

    Shows all pods with their assigned colors and allows toggling
    individual pods on/off to filter the log display.
    Use SPACE to toggle pods (preserves cursor position).

    Display format: [namespace] pod (container)
    - Namespace only shown if multiple namespaces are selected
    - Container only shown if the pod has multiple containers

    The width auto-adjusts to fit the longest entry.

    Attributes:
        state: Reference to the application state.
    """

    BINDINGS = [
        Binding("space", "toggle_selected", "Toggle pod", show=False),
    ]

    DEFAULT_CSS = """
    PodLegend {
        border: solid $success;
        background: $surface;
        min-width: 20;
        max-width: 60;
    }

    PodLegend > .option-list--option {
        padding: 0 1;
    }
    """

    def __init__(
        self,
        state: "AppState | None" = None,
        **kwargs,
    ) -> None:
        """Initialize the pod legend.

        Args:
            state: Application state for pod info and colors.
            **kwargs: Additional arguments passed to OptionList.
        """
        super().__init__(**kwargs)
        self._state = state
        self._show_namespace = False
        self._multi_container_pods: set[str] = set()
        self._max_entry_width = 0

    def set_state(self, state: "AppState") -> None:
        """Set the application state reference.

        Args:
            state: The application state.
        """
        self._state = state
        self._update_display_settings()
        self.refresh_pods()

    def _update_display_settings(self) -> None:
        """Update display settings based on current state."""
        if not self._state:
            return

        # Show namespace only if multiple namespaces
        namespaces = set(pod.namespace for pod in self._state.pods_info)
        self._show_namespace = len(namespaces) > 1

        # Track which pods have multiple containers
        self._multi_container_pods = set()
        for pod in self._state.pods_info:
            total_containers = (
                len(pod.containers)
                + len(pod.init_containers)
                + len(pod.ephemeral_containers)
            )
            if total_containers > 1:
                self._multi_container_pods.add(pod.name)

    def refresh_pods(self, preserve_position: bool = False) -> None:
        """Refresh the pod list from state.

        Args:
            preserve_position: If True, restore the highlighted position after refresh.
        """
        if not self._state:
            return

        # Save current position if needed
        saved_index = self.highlighted if preserve_position else None

        self._update_display_settings()
        self._calculate_max_width()
        self.clear_options()

        for pod in self._state.pods_info:
            color = self._state.get_pod_color(pod.name)
            enabled = self._state.is_pod_active(pod.name)

            # Create visual representation
            option_text = self._format_pod_option(pod, color, enabled)
            self.add_option(Option(option_text, id=pod.name))

        # Update the widget width to fit content
        self._update_width()

        # Restore position if requested
        if saved_index is not None and self.option_count > 0:
            # Clamp to valid range
            self.highlighted = min(saved_index, self.option_count - 1)

    def _calculate_max_width(self) -> None:
        """Calculate the maximum width needed for all pod entries.

        Calculates based on the actual rendered text format:
        "● [namespace] pod-name (Nc)"
        """
        if not self._state:
            return

        max_width = 0

        for pod in self._state.pods_info:
            # Build the exact string that will be displayed
            parts = ["● "]  # Status indicator (2 chars)

            # Namespace prefix (only if multiple namespaces)
            if self._show_namespace:
                parts.append(f"[{pod.namespace}] ")

            # Pod name
            parts.append(pod.name)

            # Container suffix (only if pod has multiple containers)
            if pod.name in self._multi_container_pods:
                container_count = (
                    len(pod.containers)
                    + len(pod.init_containers)
                    + len(pod.ephemeral_containers)
                )
                parts.append(f" ({container_count}c)")

            width = sum(len(p) for p in parts)
            max_width = max(max_width, width)

        self._max_entry_width = max_width

    def _update_width(self) -> None:
        """Update the widget width based on content."""
        if self._max_entry_width > 0:
            # Add padding: 2 for borders + 2 for option padding (padding: 0 1) + 2 scrollbar
            new_width = self._max_entry_width + 6
            # Clamp between min and max
            new_width = max(20, min(60, new_width))
            self.styles.width = new_width

    def _format_pod_option(
        self, pod: "PodInfo", color: str, enabled: bool
    ) -> Text:
        """Format a pod option with color and status indicator.

        Format: [namespace] pod (container)
        - Namespace only if multiple namespaces selected
        - Container only if pod has multiple containers

        Args:
            pod: The pod info.
            color: The Rich color for this pod.
            enabled: Whether the pod is enabled.

        Returns:
            A Rich Text object for display.
        """
        text = Text()

        # Status indicator
        if enabled:
            text.append("● ", style=color)
        else:
            text.append("○ ", style="dim")

        # Build display string
        style = color if enabled else "dim strike"

        # Namespace prefix (only if multiple namespaces)
        if self._show_namespace:
            text.append(f"[{pod.namespace}] ", style=style)

        # Pod name
        text.append(pod.name, style=style)

        # Container suffix (only if pod has multiple containers)
        if pod.name in self._multi_container_pods:
            # Show container count
            container_count = (
                len(pod.containers)
                + len(pod.init_containers)
                + len(pod.ephemeral_containers)
            )
            suffix_style = "dim" if not enabled else f"dim {color}"
            text.append(f" ({container_count}c)", style=suffix_style)

        return text

    def action_toggle_selected(self) -> None:
        """Toggle the currently highlighted pod (triggered by SPACE key)."""
        if not self._state or self.highlighted is None:
            return

        # Get the pod at the highlighted index
        if self.highlighted >= len(self._state.pods_info):
            return

        pod = self._state.pods_info[self.highlighted]
        new_state = self._state.toggle_pod(pod.name)

        # Update the visual representation, preserving position
        self.refresh_pods(preserve_position=True)

        # Notify parent
        self.post_message(PodToggled(pod.name, new_state))

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle pod selection with ENTER to toggle its state.

        Args:
            event: The selection event.
        """
        if not self._state or event.option_id is None:
            return

        pod_name = str(event.option_id)
        new_state = self._state.toggle_pod(pod_name)

        # Update the visual representation, preserving position
        self.refresh_pods(preserve_position=True)

        # Notify parent
        self.post_message(PodToggled(pod_name, new_state))

    def toggle_all(self, enabled: bool) -> None:
        """Toggle all pods to a specific state.

        Args:
            enabled: Whether to enable or disable all pods.
        """
        if not self._state:
            return

        self._state.set_all_pods_active(enabled)
        self.refresh_pods()

    def highlight_pod(self, pod_name: str) -> None:
        """Highlight a specific pod in the list.

        Args:
            pod_name: The name of the pod to highlight.
        """
        if not self._state:
            return

        for index, pod in enumerate(self._state.pods_info):
            if pod.name == pod_name:
                self.highlighted = index
                break

