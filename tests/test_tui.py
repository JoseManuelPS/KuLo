"""Unit tests for KuLo TUI components.

These tests validate the Textual-based TUI components without requiring
a real Kubernetes cluster or terminal. All external dependencies are mocked.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.text import Text

from kulo.models import ContainerInfo, LogEntry, PodInfo
from kulo.state import AppState
from kulo.utils import ColorAssigner


# ============================================================================
# AppState Tests
# ============================================================================


class TestAppState:
    """Tests for the AppState class."""

    def test_default_initialization(self) -> None:
        """Test default state initialization."""
        state = AppState()

        assert state.namespaces == []
        assert state.filter_pattern == ""
        assert state.exclude_pattern == ""
        assert state.label_selector == ""
        assert state.active_containers == {}
        assert state.pods_info == []
        assert state.since_seconds == 600
        assert state.tail_lines == 25
        assert state.max_containers == 10
        assert state.is_paused is False
        assert state.no_color_logs is False

    def test_custom_initialization(self) -> None:
        """Test state with custom values."""
        state = AppState(
            namespaces=["default", "kube-system"],
            filter_pattern="api-.*",
            exclude_pattern="test-.*",
            label_selector="app=web",
            since_seconds=3600,
            tail_lines=100,
            max_containers=20,
            no_color_logs=True,
        )

        assert state.namespaces == ["default", "kube-system"]
        assert state.filter_pattern == "api-.*"
        assert state.exclude_pattern == "test-.*"
        assert state.label_selector == "app=web"
        assert state.since_seconds == 3600
        assert state.tail_lines == 100
        assert state.max_containers == 20
        assert state.no_color_logs is True

    def test_max_containers_zero_unlimited(self) -> None:
        """Test that max_containers=0 is accepted (unlimited mode)."""
        state = AppState(max_containers=0)

        assert state.max_containers == 0

    def test_update_pods(self) -> None:
        """Test updating pods list and initializing containers."""
        state = AppState()

        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-b", phase="Running", containers=["main", "sidecar"]),
        ]

        state.update_pods(pods)

        assert len(state.pods_info) == 2
        
        # Check defaults
        assert state.is_container_active("default", "pod-a", "main")
        assert state.is_container_active("default", "pod-b", "main")
        assert state.is_container_active("default", "pod-b", "sidecar")
        
        assert state.color_assigner.assigned_count == 2 # Colors assigned per pod

    def test_update_pods_preserves_existing_states(self) -> None:
        """Test that updating pods preserves existing active states."""
        state = AppState()

        # Initial pods
        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
        ]
        state.update_pods(pods)

        # Toggle pod-a/main off
        state.toggle_container("default", "pod-a", "main")
        assert not state.is_container_active("default", "pod-a", "main")

        # Update pods (pod-a still exists)
        new_pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-c", phase="Running", containers=["main"]),
        ]
        state.update_pods(new_pods)

        # pod-a/main should still be inactive
        assert not state.is_container_active("default", "pod-a", "main")
        # pod-c/main should be active (new)
        assert state.is_container_active("default", "pod-c", "main")

    def test_toggle_container(self) -> None:
        """Test toggling container state."""
        state = AppState()
        pod = PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"])
        state.update_pods([pod])

        # Toggle off
        result = state.toggle_container("default", "pod-a", "main")
        assert result is False
        assert not state.is_container_active("default", "pod-a", "main")

        # Toggle on
        result = state.toggle_container("default", "pod-a", "main")
        assert result is True
        assert state.is_container_active("default", "pod-a", "main")

    def test_toggle_nonexistent_container(self) -> None:
        """Test toggling a container that doesn't exist."""
        state = AppState()
        result = state.toggle_container("default", "nonexistent", "main")
        assert result is False

    def test_get_pod_color(self) -> None:
        """Test getting pod color."""
        state = AppState()
        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
        ]
        state.update_pods(pods)

        color = state.get_pod_color("pod-a")
        assert isinstance(color, str)
        assert len(color) > 0

    def test_set_all_containers_active(self) -> None:
        """Test setting all containers active/inactive."""
        state = AppState()
        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-b", phase="Running", containers=["sidecar"]),
        ]
        state.update_pods(pods)
        
        # Set all inactive
        state.set_all_containers_active(False)
        assert all(not v for v in state.active_containers.values())

        # Set all active
        state.set_all_containers_active(True)
        assert all(v for v in state.active_containers.values())

    def test_copy_with(self) -> None:
        """Test creating a copy with overrides."""
        state = AppState(
            namespaces=["default"],
            filter_pattern="api-.*",
            exclude_pattern="test-.*",
            label_selector="app=web",
        )
        state.active_containers = {"default/pod-a/main": True}

        # Create copy with new namespaces
        new_state = state.copy_with(namespaces=["production"])

        assert new_state.namespaces == ["production"]
        assert new_state.filter_pattern == "api-.*"  # Preserved
        assert new_state.exclude_pattern == "test-.*"  # Preserved
        assert new_state.active_containers == {"default/pod-a/main": True}  # Preserved

        # Original unchanged
        assert state.namespaces == ["default"]

    def test_is_paused_toggle(self) -> None:
        """Test that is_paused can be toggled."""
        state = AppState()

        assert state.is_paused is False

        state.is_paused = True
        assert state.is_paused is True

        state.is_paused = False
        assert state.is_paused is False


# ============================================================================
# LogPanel Tests
# ============================================================================


class TestLogPanel:
    """Tests for the LogPanel widget."""

    def test_format_log_line_plain_text(self) -> None:
        """Test formatting plain text log lines."""
        from kulo.widgets.log_panel import LogPanel

        state = AppState()
        pods = [PodInfo(namespace="default", name="my-pod", phase="Running", containers=["main"])]
        state.update_pods(pods)

        panel = LogPanel(state=state)
        panel.show_namespace = True
        panel.show_container = True

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="my-pod",
            container_name="main",
            message="Hello world",
        )

        formatted = panel._format_log_line(entry)

        assert isinstance(formatted, Text)
        assert "Hello world" in formatted.plain

    def test_format_log_line_json(self) -> None:
        """Test formatting JSON log lines."""
        from kulo.widgets.log_panel import LogPanel

        state = AppState()
        pods = [PodInfo(namespace="default", name="api", phase="Running", containers=["main"])]
        state.update_pods(pods)

        panel = LogPanel(state=state)

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="api",
            container_name="main",
            message='{"level":"INFO","msg":"Request received","path":"/api"}',
        )

        formatted = panel._format_log_line(entry)

        assert isinstance(formatted, Text)
        assert "Request received" in formatted.plain

    def test_try_parse_json_valid(self) -> None:
        """Test JSON parsing with valid JSON."""
        from kulo.widgets.log_panel import LogPanel

        panel = LogPanel()

        result = panel._try_parse_json('{"level":"INFO","msg":"test"}')
        assert result == {"level": "INFO", "msg": "test"}

    def test_try_parse_json_invalid(self) -> None:
        """Test JSON parsing with invalid JSON."""
        from kulo.widgets.log_panel import LogPanel

        panel = LogPanel()

        assert panel._try_parse_json("not json") is None
        assert panel._try_parse_json("") is None
        assert panel._try_parse_json("plain log message") is None

    def test_detect_log_level_from_text(self) -> None:
        """Test log level detection from plain text."""
        from kulo.widgets.log_panel import LogPanel

        panel = LogPanel()

        assert panel._detect_log_level_from_text("ERROR: Something failed") == "red"
        assert panel._detect_log_level_from_text("WARN: Slow response") == "yellow"
        assert panel._detect_log_level_from_text("DEBUG: Trace info") == "dim"
        assert panel._detect_log_level_from_text("Normal log") == "default"

    def test_filters_inactive_pods(self) -> None:
        """Test that logs from inactive pods are filtered."""
        from kulo.widgets.log_panel import LogPanel

        state = AppState()
        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-b", phase="Running", containers=["main"]),
        ]
        state.update_pods(pods)
        state.toggle_container("default", "pod-b", "main")  # Deactivate pod-b

        panel = LogPanel(state=state)

        # Mock the write method
        panel.write = MagicMock()

        # Add entry from active pod
        entry_a = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="pod-a",
            container_name="main",
            message="From pod-a",
        )
        panel.add_log_entry(entry_a)
        assert panel.write.called

        panel.write.reset_mock()

        # Add entry from inactive pod
        entry_b = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="pod-b",
            container_name="main",
            message="From pod-b",
        )
        panel.add_log_entry(entry_b)
        assert not panel.write.called  # Should be filtered

    def test_no_color_logs_disables_coloring(self) -> None:
        """Test that no_color_logs disables log coloring in LogPanel."""
        from kulo.widgets.log_panel import LogPanel

        state = AppState(no_color_logs=True)
        pods = [PodInfo(namespace="default", name="my-pod", phase="Running", containers=["main"])]
        state.update_pods(pods)

        panel = LogPanel(state=state)

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="my-pod",
            container_name="main",
            message="Plain log message",
        )

        formatted = panel._format_log_line(entry)
        assert "Plain log message" in formatted.plain

        # Test JSON log
        entry2 = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="my-pod",
            container_name="main",
            message='{"level":"ERROR","msg":"Error occurred"}',
        )

        formatted2 = panel._format_log_line(entry2)
        assert "[ERROR]" in formatted2.plain
        assert "Error occurred" in formatted2.plain

    def test_json_log_uses_pod_color_for_message(self) -> None:
        """Test that JSON logs use pod color for message, level color for tag."""
        from kulo.widgets.log_panel import LogPanel

        state = AppState()
        pods = [PodInfo(namespace="default", name="api-pod", phase="Running", containers=["main"])]
        state.update_pods(pods)

        panel = LogPanel(state=state)

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="api-pod",
            container_name="main",
            message='{"level":"INFO","msg":"Request received"}',
        )

        formatted = panel._format_log_line(entry)
        # Should contain both [INFO] tag and message
        assert "[INFO]" in formatted.plain
        assert "Request received" in formatted.plain


# ============================================================================
# PodLegend Tests
# ============================================================================


class TestPodLegend:
    """Tests for the PodLegend widget."""

    def test_format_pod_option_enabled(self) -> None:
        """Test formatting enabled pod option."""
        from kulo.widgets.pod_legend import PodLegend

        pod = PodInfo(
            namespace="default",
            name="my-pod",
            phase="Running",
            containers=["main"],
        )
        container = pod.get_all_containers()[0]

        state = AppState()
        state.update_pods([pod])

        legend = PodLegend(state=state)
        legend._state = state

        # Single container pod formatting
        formatted = legend._format_single_pod_option(pod, container, "cyan", True)

        assert isinstance(formatted, Text)
        assert "●" in formatted.plain
        assert "my-pod" in formatted.plain

    def test_format_pod_option_disabled(self) -> None:
        """Test formatting disabled pod option."""
        from kulo.widgets.pod_legend import PodLegend

        pod = PodInfo(
            namespace="default",
            name="my-pod",
            phase="Running",
            containers=["main"],
        )
        container = pod.get_all_containers()[0]

        state = AppState()
        state.update_pods([pod])
        state.toggle_container("default", "my-pod", "main")

        legend = PodLegend(state=state)
        legend._state = state

        formatted = legend._format_single_pod_option(pod, container, "cyan", False)

        assert isinstance(formatted, Text)
        assert "○" in formatted.plain
        assert "my-pod" in formatted.plain

    def test_format_pod_option_with_namespace(self) -> None:
        """Test formatting pod option with namespace shown."""
        from kulo.widgets.pod_legend import PodLegend

        pods = [
            PodInfo(namespace="ns1", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="ns2", name="pod-b", phase="Running", containers=["main"]),
        ]

        state = AppState()
        state.pods_info = pods
        state.update_pods(pods)

        legend = PodLegend(state=state)
        legend._state = state
        legend._update_display_settings()

        # With multiple namespaces, should show namespace
        assert legend._show_namespace is True
        
        container = pods[0].get_all_containers()[0]
        formatted = legend._format_single_pod_option(pods[0], container, "cyan", True)
        assert "[ns1]" in formatted.plain

    def test_format_pod_option_with_multi_container(self) -> None:
        """Test formatting pod option with multiple containers."""
        from kulo.widgets.pod_legend import PodLegend

        pod = PodInfo(
            namespace="default",
            name="my-pod",
            phase="Running",
            containers=["main", "sidecar"],
        )

        state = AppState()
        state.pods_info = [pod]
        state.update_pods([pod])

        legend = PodLegend(state=state)
        legend._state = state
        legend._update_display_settings()
        
        # Test header formatting
        header = legend._format_pod_header(pod, 2)
        assert "my-pod" in header.plain
        # assert "(2c)" in header.plain - Removed by design
        assert "●" in header.plain # Added dot to header
        
        # Test container formatting
        container = pod.get_all_containers()[0]
        formatted = legend._format_container_option(container, "cyan", True, indent=True)
        assert "main" in formatted.plain
        assert "  " in formatted.plain # Indentation

    def test_format_pod_header_with_namespace_color(self) -> None:
        """Test that the namespace in the pod header has the correct color."""
        from kulo.widgets.pod_legend import PodLegend
        from rich.text import Span

        pod = PodInfo(
            namespace="demo",
            name="multi-pod",
            phase="Running",
            containers=["c1", "c2"],
        )

        state = AppState()
        state.update_pods([pod])

        legend = PodLegend(state=state)
        legend._state = state
        legend._show_namespace = True # Force show namespace
        
        color = state.get_pod_color("multi-pod")
        header = legend._format_pod_header(pod, 2)
        
        assert "[demo]" in header.plain
        
        # Find the span for [demo]
        ns_start = header.plain.find("[demo]")
        ns_end = ns_start + len("[demo]")
        
        # Check if any span covering this range has the pod color
        found_color = False
        for span in header.spans:
            if span.start <= ns_start and span.end >= ns_end:
                if span.style == color:
                    found_color = True
                    break
        
        assert found_color, f"Namespace style should be {color}, but spans are: {header.spans}"

    def test_refresh_pods(self) -> None:
        """Test refreshing pods list."""
        from kulo.widgets.pod_legend import PodLegend

        pod1 = PodInfo(
            namespace="default",
            name="pod-1",
            phase="Running",
            containers=["main"],
        )
        pod2 = PodInfo(
            namespace="kube-system",
            name="pod-2",
            phase="Running",
            containers=["main", "sidecar"],
        )

        state = AppState()
        state.pods_info = [pod1, pod2]
        state.update_pods([pod1, pod2])

        legend = PodLegend(state=state)
        legend.set_state(state) # This calls refresh_pods
        
        # Check generated options
        assert legend.option_count > 0
        
        # Check ID formats
        # We can't access .options directly as it's private in OptionList usually, 
        # but we can try get_option_at_index
        
        # pod-1 (single container)
        # We don't know the exact order easily without iterating, but PodLegend adds them in order of state.pods_info
        
        # Assuming order is preserved
        # Index 0: pod-1
        opt0 = legend.get_option_at_index(0)
        assert opt0.id == "default/pod-1/main"
        
        # Index 1: pod-2 header (disabled)
        opt1 = legend.get_option_at_index(1)
        assert opt1.disabled is True
        
        # Index 2: pod-2/main
        opt2 = legend.get_option_at_index(2)
        assert opt2.id == "kube-system/pod-2/main"
        
        # Index 3: pod-2/sidecar
        opt3 = legend.get_option_at_index(3)
        assert opt3.id == "kube-system/pod-2/sidecar"



# ============================================================================
# HelpBar Tests
# ============================================================================


class TestHelpBar:
    """Tests for the HelpBar widget."""

    def test_keybindings_defined(self) -> None:
        """Test that keybindings are properly defined."""
        from kulo.widgets.help_bar import HelpBar

        bar = HelpBar()

        assert len(bar.KEYBINDINGS) > 0
        assert any(k == "n" for k, _ in bar.KEYBINDINGS)  # Namespace
        assert any(k == "f" for k, _ in bar.KEYBINDINGS)  # Filter
        assert any(k == "e" for k, _ in bar.KEYBINDINGS)  # Exclude
        assert any(k == "m" for k, _ in bar.KEYBINDINGS)  # Max Containers
        assert any(k == "q" for k, _ in bar.KEYBINDINGS)  # Quit
        assert any(k == "Space" for k, _ in bar.KEYBINDINGS)  # Pause

    def test_pause_keybinding_present(self) -> None:
        """Test that Space/Pause keybinding is properly defined."""
        from kulo.widgets.help_bar import HelpBar

        bar = HelpBar()

        space_binding = next((k, v) for k, v in bar.KEYBINDINGS if k == "Space")
        assert space_binding is not None
        assert space_binding[1] == "Pause/Resume"

    def test_filter_keybinding_present(self) -> None:
        """Test that f/Filter keybinding is properly defined."""
        from kulo.widgets.help_bar import HelpBar

        bar = HelpBar()

        filter_binding = next((k, v) for k, v in bar.KEYBINDINGS if k == "f")
        assert filter_binding is not None
        assert filter_binding[1] == "Filter"


class TestExpandedHelp:
    """Tests for the ExpandedHelp widget."""

    def test_help_text_defined(self) -> None:
        """Test that help text is properly defined."""
        from kulo.widgets.help_bar import ExpandedHelp

        help_widget = ExpandedHelp()

        assert len(help_widget.HELP_TEXT) > 0
        assert "Keyboard Shortcuts" in help_widget.HELP_TEXT

    def test_help_text_contains_streaming_control(self) -> None:
        """Test that help text includes streaming control section."""
        from kulo.widgets.help_bar import ExpandedHelp

        help_widget = ExpandedHelp()

        assert "Streaming & View" in help_widget.HELP_TEXT
        assert "Space" in help_widget.HELP_TEXT
        assert "Pause/Resume" in help_widget.HELP_TEXT


# ============================================================================
# Modal Tests
# ============================================================================


class TestNamespaceModal:
    """Tests for the NamespaceModal."""

    def test_initial_value(self) -> None:
        """Test that initial namespaces are set."""
        from kulo.modals.namespace_modal import NamespaceModal

        modal = NamespaceModal(current_namespaces=["default", "production"])

        assert modal._current == ["default", "production"]


class TestFilterModal:
    """Tests for the FilterModal."""

    def test_filter_config(self) -> None:
        """Test filter configuration."""
        from kulo.modals.filter_modal import FilterModal

        modal = FilterModal(filter_type="filter", current_value="api-.*")

        assert modal._filter_type == "filter"
        assert modal._current == "api-.*"
        assert modal._config["is_regex"] is True

    def test_exclude_config(self) -> None:
        """Test exclude filter configuration."""
        from kulo.modals.filter_modal import FilterModal

        modal = FilterModal(filter_type="exclude", current_value="test-.*")

        assert modal._filter_type == "exclude"
        assert modal._current == "test-.*"

    def test_label_config(self) -> None:
        """Test label selector configuration."""
        from kulo.modals.filter_modal import FilterModal

        modal = FilterModal(filter_type="label", current_value="app=web")

        assert modal._filter_type == "label"
        assert modal._current == "app=web"
        assert modal._config["is_regex"] is False

    def test_default_filter_type(self) -> None:
        """Test that default filter type is 'filter'."""
        from kulo.modals.filter_modal import FilterModal

        modal = FilterModal(current_value="test-.*")

        assert modal._filter_type == "filter"


class TestConfirmModal:
    """Tests for the ConfirmModal."""

    def test_custom_messages(self) -> None:
        """Test custom title and message."""
        from kulo.modals.confirm_modal import ConfirmModal

        modal = ConfirmModal(
            title="Delete Logs",
            message="Are you sure you want to delete all logs?",
            confirm_label="Delete",
            cancel_label="Keep",
        )

        assert modal._title == "Delete Logs"
        assert modal._message == "Are you sure you want to delete all logs?"
        assert modal._confirm_label == "Delete"
        assert modal._cancel_label == "Keep"


# ============================================================================
# Mode Selection Tests
# ============================================================================


class TestModeSelection:
    """Tests for mode selection logic."""

    def test_default_is_follow_mode(self) -> None:
        """Test that default mode is follow (TUI) when --snap is not set."""
        from argparse import Namespace
        from kulo.main import is_snapshot_mode

        args = Namespace(snap=False)
        assert is_snapshot_mode(args) is False

    def test_snap_flag_enables_snapshot_mode(self) -> None:
        """Test that --snap enables snapshot mode."""
        from argparse import Namespace
        from kulo.main import is_snapshot_mode

        args = Namespace(snap=True)
        assert is_snapshot_mode(args) is True

    def test_cli_parser_snap_argument(self) -> None:
        """Test that CLI parser accepts --snap argument."""
        from kulo.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["--snap"])
        assert args.snap is True

    def test_cli_parser_default_no_snap(self) -> None:
        """Test that --snap defaults to False."""
        from kulo.main import create_parser

        parser = create_parser()
        args = parser.parse_args([])
        assert args.snap is False

    def test_cli_parser_filter_argument(self) -> None:
        """Test that CLI parser accepts -f/--filter argument."""
        from kulo.main import create_parser

        parser = create_parser()

        # Test short form
        args = parser.parse_args(["-f", "api-.*"])
        assert args.filter == "api-.*"

        # Test long form
        args = parser.parse_args(["--filter", "web-.*"])
        assert args.filter == "web-.*"


    def test_cli_parser_max_containers_argument(self) -> None:
        """Test that CLI parser accepts -m/--max-containers argument."""
        from kulo.main import create_parser

        parser = create_parser()

        # Test short form
        args = parser.parse_args(["-m", "20"])
        assert args.max_containers == 20

        # Test long form
        args = parser.parse_args(["--max-containers", "30"])
        assert args.max_containers == 30

    def test_cli_parser_no_follow_or_tui_flags(self) -> None:
        """Test that --follow, --tui, --no-tui flags are removed."""
        from kulo.main import create_parser

        parser = create_parser()

        # These should not be recognized anymore
        import argparse

        # --follow should fail (we're using -f for --filter now)
        with pytest.raises(SystemExit):
            parser.parse_args(["--follow"])

        with pytest.raises(SystemExit):
            parser.parse_args(["--tui"])

        with pytest.raises(SystemExit):
            parser.parse_args(["--no-tui"])


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_pods() -> list[PodInfo]:
    """Create sample pods for testing."""
    return [
        PodInfo(
            namespace="default",
            name="api-server-abc123",
            phase="Running",
            containers=["main", "sidecar"],
            init_containers=["init"],
        ),
        PodInfo(
            namespace="default",
            name="web-frontend-xyz789",
            phase="Running",
            containers=["nginx"],
        ),
        PodInfo(
            namespace="production",
            name="db-primary-def456",
            phase="Running",
            containers=["postgres"],
        ),
    ]


@pytest.fixture
def sample_state(sample_pods: list[PodInfo]) -> AppState:
    """Create a sample AppState for testing."""
    state = AppState(namespaces=["default", "production"])
    state.update_pods(sample_pods)
    return state

