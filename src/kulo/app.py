"""KuLo TUI Application.

This module provides the main Textual application for KuLo,
with Vim-style keybindings and reactive state management.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Footer, Header

from kulo.client import KuloClient, KuloClientError, PermissionDeniedError
from kulo.manager import LogManager
from kulo.models import ContainerInfo, LogEntry, PodInfo
from kulo.modals import ConfirmModal, FilterModal, NamespaceModal
from kulo.state import AppState
from kulo.utils import compile_patterns, is_regex_pattern, matches_any
from kulo.widgets import HelpBar, LogPanel, PodLegend
from kulo.widgets.help_bar import ExpandedHelp
from kulo.widgets.pod_legend import PodToggled

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class NewLogEntry(Message):
    """Message sent when a new log entry is received."""

    def __init__(self, entry: LogEntry) -> None:
        """Initialize the message.

        Args:
            entry: The log entry.
        """
        super().__init__()
        self.entry = entry


class StreamingStarted(Message):
    """Message sent when log streaming starts."""

    pass


class StreamingStopped(Message):
    """Message sent when log streaming stops."""

    pass


class KuloApp(App):
    """Main KuLo TUI Application.

    Provides an interactive interface for viewing Kubernetes logs
    with filtering, pod selection, and real-time updates.
    """

    TITLE = "KuLo - Kubernetes Log Aggregator"
    SUB_TITLE = "Interactive Log Viewer"

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr auto;
        grid-rows: 1fr auto;
    }

    #log-panel {
        column-span: 1;
        row-span: 1;
    }

    #pod-legend {
        column-span: 1;
        row-span: 1;
    }

    #help-bar {
        column-span: 2;
        row-span: 1;
    }

    .hidden {
        display: none;
    }

    #expanded-help {
        layer: overlay;
    }
    """

    BINDINGS = [
        Binding("n", "namespace", "Namespace", show=True),
        Binding("i", "include", "Include", show=True),
        Binding("e", "exclude", "Exclude", show=True),
        Binding("l", "labels", "Labels", show=True),
        Binding("p", "toggle_pods", "Toggle Pods", show=True),
        Binding("a", "all_on", "All On", show=False),
        Binding("z", "all_off", "All Off", show=False),
        Binding("c", "clear_logs", "Clear", show=False),
        Binding("s", "toggle_scroll", "Auto-scroll", show=False),
        Binding("question_mark", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "close_overlay", "Close", show=False),
    ]

    def __init__(
        self,
        initial_namespaces: list[str] | None = None,
        include_pattern: str = "",
        exclude_pattern: str = "",
        label_selector: str = "",
        follow: bool = True,
        since_seconds: int = 600,
        tail_lines: int = 25,
        max_containers: int = 10,
        **kwargs,
    ) -> None:
        """Initialize the application.

        Args:
            initial_namespaces: Initial namespace filters.
            include_pattern: Initial include pattern.
            exclude_pattern: Initial exclude pattern.
            label_selector: Initial label selector.
            follow: Whether to follow logs in real-time.
            since_seconds: Time window for log retrieval.
            tail_lines: Number of initial lines to fetch.
            max_containers: Maximum concurrent container streams.
            **kwargs: Additional arguments passed to App.
        """
        super().__init__(**kwargs)

        self.state = AppState(
            namespaces=initial_namespaces or [],
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
            label_selector=label_selector,
            follow_mode=follow,
            since_seconds=since_seconds,
            tail_lines=tail_lines,
            max_containers=max_containers,
        )

        self._client: KuloClient | None = None
        self._manager: LogManager | None = None
        self._streaming_task: asyncio.Task | None = None
        self._show_expanded_help = False
        self._show_pod_panel = True

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()

        yield LogPanel(state=self.state, id="log-panel")
        yield PodLegend(state=self.state, id="pod-legend")
        yield HelpBar(id="help-bar")
        yield ExpandedHelp(id="expanded-help", classes="hidden")

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the application on mount."""
        # Set up state references in widgets
        log_panel = self.query_one("#log-panel", LogPanel)
        pod_legend = self.query_one("#pod-legend", PodLegend)

        log_panel.set_state(self.state)
        pod_legend.set_state(self.state)

        # Start the connection and streaming (calls the @work decorated method)
        self._initialize_and_stream()

    @work(exclusive=True)
    async def _initialize_and_stream(self) -> None:
        """Initialize K8s connection and start streaming."""
        try:
            async with KuloClient.create() as client:
                self._client = client

                # Resolve namespaces
                namespaces = await self._resolve_namespaces(client)
                if not namespaces:
                    self.notify("No namespaces found", severity="warning")
                    return

                self.state.namespaces = namespaces

                # Discover pods
                await self._discover_and_stream(client)

        except KuloClientError as e:
            self.notify(f"Kubernetes error: {e}", severity="error")
            logger.error(f"Kubernetes client error: {e}")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            logger.exception(f"Unexpected error: {e}")

    async def _resolve_namespaces(self, client: KuloClient) -> list[str]:
        """Resolve namespace filters to actual namespace names.

        Args:
            client: The KuloClient instance.

        Returns:
            List of resolved namespace names.
        """
        if not self.state.namespaces:
            # Use current context namespace
            current_ns = await client.get_current_namespace()
            return [current_ns]

        # Check if any namespace arg contains regex patterns
        has_regex = any(is_regex_pattern(ns) for ns in self.state.namespaces)

        if has_regex:
            import re

            resolved: list[str] = []
            exact_names: list[str] = []
            regex_patterns: list[re.Pattern[str]] = []

            for ns_arg in self.state.namespaces:
                if is_regex_pattern(ns_arg):
                    try:
                        regex_patterns.append(re.compile(ns_arg, re.IGNORECASE))
                    except re.error as e:
                        self.notify(f"Invalid regex: {ns_arg}: {e}", severity="error")
                        return []
                else:
                    exact_names.append(ns_arg)

            # Validate exact names
            for ns in exact_names:
                if await client.check_namespace_exists(ns):
                    resolved.append(ns)
                else:
                    self.notify(f"Namespace '{ns}' not found", severity="warning")

            # Resolve regex patterns
            if regex_patterns:
                try:
                    all_namespaces = await client.list_all_namespaces()
                    for ns in all_namespaces:
                        if ns not in resolved:
                            if any(p.search(ns) for p in regex_patterns):
                                resolved.append(ns)
                except PermissionDeniedError as e:
                    self.notify(str(e), severity="error")
                    return []

            return resolved
        else:
            # Exact namespace names - validate they exist
            resolved = []
            for ns in self.state.namespaces:
                if await client.check_namespace_exists(ns):
                    resolved.append(ns)
                else:
                    self.notify(f"Namespace '{ns}' not found", severity="warning")
            return resolved

    async def _discover_and_stream(self, client: KuloClient) -> None:
        """Discover pods and start streaming logs.

        Args:
            client: The KuloClient instance.
        """
        # Discover pods
        all_pods: list[PodInfo] = []
        for ns in self.state.namespaces:
            try:
                selector = self.state.label_selector or None
                pods = await client.list_pods(ns, selector)
                all_pods.extend(pods)
            except Exception as e:
                self.notify(f"Error listing pods in {ns}: {e}", severity="error")
                logger.error(f"Error listing pods in {ns}: {e}")

        # Apply regex filters
        filtered_pods = self._filter_pods(all_pods)

        if not filtered_pods and not self.state.follow_mode:
            self.notify("No pods found matching criteria", severity="warning")
            return

        # Update state with discovered pods
        self.state.update_pods(filtered_pods)

        # Update UI
        log_panel = self.query_one("#log-panel", LogPanel)
        pod_legend = self.query_one("#pod-legend", PodLegend)

        log_panel.configure_output(
            namespaces=self.state.namespaces,
            show_container=self._should_show_container(filtered_pods),
        )
        pod_legend.refresh_pods()

        # Get all containers
        containers = self._get_containers(filtered_pods)

        if not containers and not self.state.follow_mode:
            self.notify("No containers found in matching pods", severity="warning")
            return

        # Apply throttling
        if len(containers) > self.state.max_containers:
            containers = containers[: self.state.max_containers]
            self.notify(
                f"Limited to {self.state.max_containers} containers",
                severity="information",
            )

        # Update status
        ns_display = ", ".join(self.state.namespaces)
        self.sub_title = f"{ns_display} | {len(filtered_pods)} pods | {len(containers)} containers"

        # Start streaming
        self._manager = LogManager(client)
        self.post_message(StreamingStarted())

        await self._manager.run(
            containers=containers,
            ui=self,  # We'll handle the UI ourselves
            follow=self.state.follow_mode,
            since_seconds=self.state.since_seconds,
            tail_lines=self.state.tail_lines,
            max_concurrent=self.state.max_containers,
            label_selector=self.state.label_selector or None,
            namespaces=self.state.namespaces,
            on_new_container=self._on_new_container,
        )

        self.post_message(StreamingStopped())

    def _filter_pods(self, pods: list[PodInfo]) -> list[PodInfo]:
        """Filter pods based on include/exclude patterns.

        Args:
            pods: List of pods to filter.

        Returns:
            Filtered list of pods.
        """
        try:
            include_patterns = compile_patterns(self.state.include_pattern or None)
        except ValueError:
            include_patterns = []

        try:
            exclude_patterns = compile_patterns(self.state.exclude_pattern or None)
        except ValueError:
            exclude_patterns = []

        result = []

        for pod in pods:
            # Include filter
            if include_patterns and not matches_any(pod.name, include_patterns):
                continue

            # Exclude filter
            if exclude_patterns and matches_any(pod.name, exclude_patterns):
                continue

            result.append(pod)

        return result

    def _get_containers(self, pods: list[PodInfo]) -> list[ContainerInfo]:
        """Get all containers from a list of pods.

        Args:
            pods: List of pods.

        Returns:
            List of ContainerInfo objects.
        """
        containers: list[ContainerInfo] = []

        for pod in pods:
            if pod.phase not in ("Running", "Succeeded", "Failed"):
                continue

            pod_containers = pod.get_all_containers()
            containers.extend(pod_containers)

        return containers

    def _should_show_container(self, pods: list[PodInfo]) -> bool:
        """Determine if container names should be shown.

        Args:
            pods: List of pods.

        Returns:
            True if any pod has multiple containers.
        """
        for pod in pods:
            total = (
                len(pod.containers)
                + len(pod.init_containers)
                + len(pod.ephemeral_containers)
            )
            if total > 1:
                return True
        return False

    def _on_new_container(self, container: ContainerInfo) -> None:
        """Handle new container discovery.

        Args:
            container: The new container.
        """
        color = self.state.color_assigner.update_for_new_pod(container.pod_name)
        self.notify(
            f"New container: {container.pod_name}/{container.container_name}",
            severity="information",
        )

        # Refresh pod legend
        pod_legend = self.query_one("#pod-legend", PodLegend)
        pod_legend.refresh_pods()

    # Compatibility methods for LogManager
    def print_log_entry(self, entry: LogEntry) -> None:
        """Handle log entry from LogManager.

        Args:
            entry: The log entry.
        """
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.add_log_entry(entry)

    def print_new_container(self, container: ContainerInfo) -> None:
        """Handle new container notification.

        Args:
            container: The new container.
        """
        self._on_new_container(container)

    # Action handlers
    def action_namespace(self) -> None:
        """Open namespace filter modal."""

        def on_namespace_result(result: list[str] | None) -> None:
            if result is not None:
                self.state.namespaces = result
                self.notify(f"Namespaces: {', '.join(result) or 'current context'}")
                self._restart_streaming_sync()

        self.push_screen(
            NamespaceModal(current_namespaces=self.state.namespaces),
            on_namespace_result,
        )

    def action_include(self) -> None:
        """Open include filter modal."""

        def on_include_result(result: str | None) -> None:
            if result is not None:
                self.state.include_pattern = result
                self.notify(f"Include filter: {result or '(none)'}")
                self._restart_streaming_sync()

        self.push_screen(
            FilterModal(filter_type="include", current_value=self.state.include_pattern),
            on_include_result,
        )

    def action_exclude(self) -> None:
        """Open exclude filter modal."""

        def on_exclude_result(result: str | None) -> None:
            if result is not None:
                self.state.exclude_pattern = result
                self.notify(f"Exclude filter: {result or '(none)'}")
                self._restart_streaming_sync()

        self.push_screen(
            FilterModal(filter_type="exclude", current_value=self.state.exclude_pattern),
            on_exclude_result,
        )

    def action_labels(self) -> None:
        """Open label selector modal."""

        def on_labels_result(result: str | None) -> None:
            if result is not None:
                self.state.label_selector = result
                self.notify(f"Label selector: {result or '(none)'}")
                self._restart_streaming_sync()

        self.push_screen(
            FilterModal(filter_type="label", current_value=self.state.label_selector),
            on_labels_result,
        )

    def action_toggle_pods(self) -> None:
        """Toggle pod panel visibility."""
        pod_legend = self.query_one("#pod-legend", PodLegend)
        self._show_pod_panel = not self._show_pod_panel

        if self._show_pod_panel:
            pod_legend.remove_class("hidden")
        else:
            pod_legend.add_class("hidden")

    def action_all_on(self) -> None:
        """Enable all pods."""
        pod_legend = self.query_one("#pod-legend", PodLegend)
        pod_legend.toggle_all(True)
        self.notify("All pods enabled")

    def action_all_off(self) -> None:
        """Disable all pods."""
        pod_legend = self.query_one("#pod-legend", PodLegend)
        pod_legend.toggle_all(False)
        self.notify("All pods disabled")

    def action_clear_logs(self) -> None:
        """Clear the log display."""
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.clear()
        self.notify("Logs cleared")

    def action_toggle_scroll(self) -> None:
        """Toggle auto-scroll."""
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.auto_scroll = not log_panel.auto_scroll
        status = "enabled" if log_panel.auto_scroll else "disabled"
        self.notify(f"Auto-scroll {status}")

    def action_help(self) -> None:
        """Toggle expanded help panel."""
        expanded_help = self.query_one("#expanded-help", ExpandedHelp)
        self._show_expanded_help = not self._show_expanded_help

        if self._show_expanded_help:
            expanded_help.remove_class("hidden")
        else:
            expanded_help.add_class("hidden")

    def action_close_overlay(self) -> None:
        """Close any open overlay."""
        if self._show_expanded_help:
            self.action_help()

    def action_quit(self) -> None:
        """Quit the application."""
        if self._manager:
            self._manager.request_shutdown()
        self.exit()

    def _restart_streaming_sync(self) -> None:
        """Restart log streaming with new filters (sync version for callbacks)."""
        if self._manager:
            self._manager.request_shutdown()

        # Clear logs
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.clear()

        # Restart (the @work decorator handles async execution)
        self._initialize_and_stream()

    async def _restart_streaming(self) -> None:
        """Restart log streaming with new filters (async version)."""
        if self._manager:
            self._manager.request_shutdown()
            # Wait a bit for cleanup
            await asyncio.sleep(0.5)

        # Clear logs
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.clear()

        # Restart
        self._initialize_and_stream()

    @on(PodToggled)
    def on_pod_toggled(self, event: PodToggled) -> None:
        """Handle pod toggle events.

        Args:
            event: The pod toggled event.
        """
        status = "enabled" if event.enabled else "disabled"
        self.notify(f"{event.pod_name} {status}")


def run_tui(
    namespaces: list[str] | None = None,
    include_pattern: str = "",
    exclude_pattern: str = "",
    label_selector: str = "",
    follow: bool = True,
    since_seconds: int = 600,
    tail_lines: int = 25,
    max_containers: int = 10,
) -> None:
    """Run the KuLo TUI application.

    Args:
        namespaces: Initial namespace filters.
        include_pattern: Initial include pattern.
        exclude_pattern: Initial exclude pattern.
        label_selector: Initial label selector.
        follow: Whether to follow logs in real-time.
        since_seconds: Time window for log retrieval.
        tail_lines: Number of initial lines to fetch.
        max_containers: Maximum concurrent container streams.
    """
    app = KuloApp(
        initial_namespaces=namespaces,
        include_pattern=include_pattern,
        exclude_pattern=exclude_pattern,
        label_selector=label_selector,
        follow=follow,
        since_seconds=since_seconds,
        tail_lines=tail_lines,
        max_containers=max_containers,
    )
    app.run()

