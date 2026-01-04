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


class ContainerToggled(Message):
    """Message sent when a container is toggled."""

    def __init__(self, pod_name: str, container_name: str, enabled: bool) -> None:
        """Initialize the message.

        Args:
            pod_name: The name of the pod.
            container_name: The name of the container.
            enabled: The new enabled state.
        """
        super().__init__()
        self.pod_name = pod_name
        self.container_name = container_name
        self.enabled = enabled


class PodLegend(OptionList):
    """Interactive pod legend panel.

    Shows all pods/containers with their assigned colors and allows toggling
    individual containers on/off to filter the log display.
    Use SPACE to toggle (preserves cursor position).

    Display format:
    - Single container pod: [namespace] pod
    - Multi container pod:
        [namespace] pod
          ● container-1
          ○ container-2

    Attributes:
        state: Reference to the application state.
    """

    BINDINGS = [
        Binding("space", "toggle_selected", "Toggle", show=False),
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
            containers = pod.get_all_containers()
            
            # If multiple containers, we might want a header + indented containers?
            # Or just flat list?
            # User request image shows:
            # - multi-container-pod (2c)
            # The request says: "Me gustaría cambiar este comportamiento... de forma separada"
            # So I should list them separately.
            
            # Implementation Strategy:
            # 1. Always list containers.
            # 2. If 1 container, just show "[ns] pod (container)" or "[ns] pod" if container name is redundant?
            #    Usually k8s pods with 1 container are just referred by pod name.
            # 3. If multiple, maybe list pod name as disabled header, then containers?
            #    OptionList doesn't support headers well efficiently without custom rendering.
            #    Simple approach: Just list every container as an option.
            #    Label: "[ns] pod (container)"
            #    This might be repetitive for multi-container pods.
            #    Alternative:
            #    [pod-a]
            #      ● main
            #      ○ sidecar
            
            # I will go with the indentation approach for multi-container pods.
            
            is_multi = len(containers) > 1
            
            if is_multi:
                # Add pod header (non-selectable/info or just text)
                # OptionList options are all selectable. 
                # I'll make the header selectable but effectively it might toggle all? 
                # For now, let's just use it as a label.
                
                # To make it allow "toggle all for this pod", I could support that.
                # But let's stick to individual containers first.
                
                pod_header = self._format_pod_header(pod, len(containers))
                self.add_option(Option(pod_header, id=f"pod:{pod.name}", disabled=True)) 
                
                for container in containers:
                    enabled = self._state.is_container_active(
                        pod.namespace, pod.name, container.container_name
                    )
                    option_text = self._format_container_option(
                        container, color, enabled, indent=True
                    )
                    # ID format: "namespace/pod_name/container_name"
                    unique_id = f"{pod.namespace}/{pod.name}/{container.container_name}"
                    self.add_option(Option(option_text, id=unique_id))
            else:
                # Single container - show as pod line
                if not containers:
                    continue
                container = containers[0]
                enabled = self._state.is_container_active(
                    pod.namespace, pod.name, container.container_name
                )
                option_text = self._format_single_pod_option(
                    pod, container, color, enabled
                )
                unique_id = f"{pod.namespace}/{pod.name}/{container.container_name}"
                self.add_option(Option(option_text, id=unique_id))

        # Update the widget width to fit content
        self._update_width()

        # Restore position if requested
        if saved_index is not None and self.option_count > 0:
            # Clamp to valid range
            self.highlighted = min(saved_index, self.option_count - 1)

    def _calculate_max_width(self) -> None:
        """Calculate max width."""
        # Simplified max width calc
        # This is an approximation.
        if not self._state:
            return
        
        max_len = 0
        for pod in self._state.pods_info:
            base_len = len(pod.name) + (len(pod.namespace) + 3 if self._show_namespace else 0)
            containers = pod.get_all_containers()
            if len(containers) > 1:
                # Header length
                max_len = max(max_len, base_len + 6) # " (Nc)"
                # Container lengths
                for c in containers:
                    # indented: "  ● container_name"
                    max_len = max(max_len, len(c.container_name) + 6)
            else:
                max_len = max(max_len, base_len + 4)
                
        self._max_entry_width = max_len

    def _update_width(self) -> None:
        """Update the widget width based on content."""
        if self._max_entry_width > 0:
            new_width = self._max_entry_width + 8
            new_width = max(20, min(60, new_width))
            self.styles.width = new_width

    def _format_pod_header(self, pod: "PodInfo", count: int) -> Text:
        """Format pod header for multi-container pods."""
        # Get color for the pod (header uses it to indicate association)
        # Assuming header is always 'active' colored
        color = self._state.get_pod_color(pod.name)
        
        text = Text()
        text.append("● ", style=color)
        if self._show_namespace:
            text.append(f"[{pod.namespace}] ", style=color)
        text.append(pod.name, style=f"bold {color}")
        return text

    def _format_container_option(self, container: "ContainerInfo", color: str, enabled: bool, indent: bool) -> Text:
        """Format individual container option."""
        text = Text()
        if indent:
            text.append("  ", style="default")
            
        if enabled:
            text.append("> ", style=color)
            style = color
        else:
            text.append("> ", style="dim")
            style = "dim strike"
            
        text.append(container.container_name, style=style)
        return text

    def _format_single_pod_option(self, pod: "PodInfo", container: "ContainerInfo", color: str, enabled: bool) -> Text:
        """Format single-container pod option."""
        text = Text()
        
        if enabled:
            text.append("● ", style=color)
            style = color
        else:
            text.append("○ ", style="dim")
            style = "dim strike"

        if self._show_namespace:
            text.append(f"[{pod.namespace}] ", style=style)
            
        text.append(pod.name, style=style)
        return text

    def action_toggle_selected(self) -> None:
        """Toggle the currently highlighted container."""
        if not self.highlighted:
            return
        
        # We need to get the option at highlighted index
        # OptionList doesn't expose get_option_at_index easily if not selected?
        # Actually it does `get_option_at_index` in newer textual? 
        # But `self.get_option_at_index(self.highlighted)` is available.
        # Let's rely on `self.get_option_at_index(self.highlighted)` existing or use `self.options`? Not exposed public.
        # But `on_option_selected` is triggered by Enter. 
        # Space binding triggers this action.
        # We can simulate logic similar to `on_option_selected`.
        
        # Workaround: OptionList doesn't easily give accessed to option at index without private access `_options`.
        # But wait, `self.get_option_at_index` exists in Textual? 
        # Checking docs... `get_option_at_index` exists.
        
        try:
            option = self.get_option_at_index(self.highlighted)
            if option and not option.disabled and option.id:
                 self._toggle_option(str(option.id))
        except Exception:
            pass

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle selection."""
        if event.option_id:
            self._toggle_option(str(event.option_id))

    def _toggle_option(self, option_id: str) -> None:
        """Toggle the option ID."""
        if not self._state:
            return
            
        # Parse ID: "namespace/pod_name/container_name"
        try:
            namespace, pod_name, container_name = option_id.split("/")
        except ValueError:
            return  # Invalid ID (maybe header)

        # Toggle in state
        new_state = self._state.toggle_container(namespace, pod_name, container_name)
        
        self.refresh_pods(preserve_position=True)
        self.post_message(ContainerToggled(pod_name, container_name, new_state))

    def toggle_all(self, enabled: bool) -> None:
        """Toggle all containers."""
        if not self._state:
            return

        self._state.set_all_containers_active(enabled)
        self.refresh_pods()

