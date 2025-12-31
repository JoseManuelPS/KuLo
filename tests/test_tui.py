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
        assert state.include_pattern == ""
        assert state.exclude_pattern == ""
        assert state.label_selector == ""
        assert state.active_pods == {}
        assert state.pods_info == []
        assert state.follow_mode is True
        assert state.since_seconds == 600
        assert state.tail_lines == 25
        assert state.max_containers == 10

    def test_custom_initialization(self) -> None:
        """Test state with custom values."""
        state = AppState(
            namespaces=["default", "kube-system"],
            include_pattern="api-.*",
            exclude_pattern="test-.*",
            label_selector="app=web",
            follow_mode=False,
            since_seconds=3600,
            tail_lines=100,
            max_containers=20,
        )

        assert state.namespaces == ["default", "kube-system"]
        assert state.include_pattern == "api-.*"
        assert state.exclude_pattern == "test-.*"
        assert state.label_selector == "app=web"
        assert state.follow_mode is False
        assert state.since_seconds == 3600
        assert state.tail_lines == 100
        assert state.max_containers == 20

    def test_update_pods(self) -> None:
        """Test updating pods list."""
        state = AppState()

        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-b", phase="Running", containers=["main"]),
        ]

        state.update_pods(pods)

        assert len(state.pods_info) == 2
        assert state.is_pod_active("pod-a")
        assert state.is_pod_active("pod-b")
        assert state.color_assigner.assigned_count == 2

    def test_update_pods_preserves_existing_states(self) -> None:
        """Test that updating pods preserves existing active states."""
        state = AppState()

        # Initial pods
        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-b", phase="Running", containers=["main"]),
        ]
        state.update_pods(pods)

        # Toggle pod-a off
        state.toggle_pod("pod-a")
        assert not state.is_pod_active("pod-a")

        # Update pods (pod-a still exists)
        new_pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-c", phase="Running", containers=["main"]),
        ]
        state.update_pods(new_pods)

        # pod-a should still be inactive
        assert not state.is_pod_active("pod-a")
        # pod-c should be active (new)
        assert state.is_pod_active("pod-c")
        # pod-b should be removed
        assert "pod-b" not in state.active_pods

    def test_toggle_pod(self) -> None:
        """Test toggling pod state."""
        state = AppState()
        state.active_pods = {"pod-a": True, "pod-b": True}

        # Toggle off
        result = state.toggle_pod("pod-a")
        assert result is False
        assert not state.is_pod_active("pod-a")

        # Toggle on
        result = state.toggle_pod("pod-a")
        assert result is True
        assert state.is_pod_active("pod-a")

    def test_toggle_nonexistent_pod(self) -> None:
        """Test toggling a pod that doesn't exist."""
        state = AppState()

        result = state.toggle_pod("nonexistent")
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

    def test_get_active_pods(self) -> None:
        """Test getting only active pods."""
        state = AppState()
        pods = [
            PodInfo(namespace="default", name="pod-a", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-b", phase="Running", containers=["main"]),
            PodInfo(namespace="default", name="pod-c", phase="Running", containers=["main"]),
        ]
        state.update_pods(pods)

        # Deactivate pod-b
        state.toggle_pod("pod-b")

        active = state.get_active_pods()
        assert len(active) == 2
        assert all(p.name != "pod-b" for p in active)

    def test_set_all_pods_active(self) -> None:
        """Test setting all pods active/inactive."""
        state = AppState()
        state.active_pods = {"pod-a": True, "pod-b": False, "pod-c": True}

        # Set all inactive
        state.set_all_pods_active(False)
        assert all(not v for v in state.active_pods.values())

        # Set all active
        state.set_all_pods_active(True)
        assert all(v for v in state.active_pods.values())

    def test_copy_with(self) -> None:
        """Test creating a copy with overrides."""
        state = AppState(
            namespaces=["default"],
            include_pattern="api-.*",
            exclude_pattern="test-.*",
            label_selector="app=web",
        )
        state.active_pods = {"pod-a": True}

        # Create copy with new namespaces
        new_state = state.copy_with(namespaces=["production"])

        assert new_state.namespaces == ["production"]
        assert new_state.include_pattern == "api-.*"  # Preserved
        assert new_state.exclude_pattern == "test-.*"  # Preserved
        assert new_state.active_pods == {"pod-a": True}  # Preserved

        # Original unchanged
        assert state.namespaces == ["default"]


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
        state.toggle_pod("pod-b")  # Deactivate pod-b

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

        state = AppState()
        state.active_pods = {"my-pod": True}
        state.color_assigner.initialize(["my-pod"])
        state.pods_info = [pod]

        legend = PodLegend(state=state)
        legend._state = state

        formatted = legend._format_pod_option(pod, "cyan", True)

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

        state = AppState()
        state.active_pods = {"my-pod": False}
        state.color_assigner.initialize(["my-pod"])
        state.pods_info = [pod]

        legend = PodLegend(state=state)
        legend._state = state

        formatted = legend._format_pod_option(pod, "cyan", False)

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

        formatted = legend._format_pod_option(pods[0], "cyan", True)
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

        formatted = legend._format_pod_option(pod, "cyan", True)

        # Should show container count
        assert "(2c)" in formatted.plain


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
        assert any(k == "i" for k, _ in bar.KEYBINDINGS)  # Include
        assert any(k == "e" for k, _ in bar.KEYBINDINGS)  # Exclude
        assert any(k == "q" for k, _ in bar.KEYBINDINGS)  # Quit


class TestExpandedHelp:
    """Tests for the ExpandedHelp widget."""

    def test_help_text_defined(self) -> None:
        """Test that help text is properly defined."""
        from kulo.widgets.help_bar import ExpandedHelp

        help_widget = ExpandedHelp()

        assert len(help_widget.HELP_TEXT) > 0
        assert "Keyboard Shortcuts" in help_widget.HELP_TEXT


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

    def test_include_config(self) -> None:
        """Test include filter configuration."""
        from kulo.modals.filter_modal import FilterModal

        modal = FilterModal(filter_type="include", current_value="api-.*")

        assert modal._filter_type == "include"
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
# Main TUI Mode Selection Tests
# ============================================================================


class TestTuiModeSelection:
    """Tests for TUI mode selection logic."""

    def test_should_use_tui_with_follow(self) -> None:
        """Test that TUI is used by default with -f."""
        from argparse import Namespace
        from kulo.main import should_use_tui

        args = Namespace(follow=True, tui=False, no_tui=False)
        assert should_use_tui(args) is True

    def test_should_use_cli_without_follow(self) -> None:
        """Test that CLI is used by default without -f."""
        from argparse import Namespace
        from kulo.main import should_use_tui

        args = Namespace(follow=False, tui=False, no_tui=False)
        assert should_use_tui(args) is False

    def test_force_tui_with_flag(self) -> None:
        """Test that --tui forces TUI mode."""
        from argparse import Namespace
        from kulo.main import should_use_tui

        args = Namespace(follow=False, tui=True, no_tui=False)
        assert should_use_tui(args) is True

    def test_force_cli_with_flag(self) -> None:
        """Test that --no-tui forces CLI mode."""
        from argparse import Namespace
        from kulo.main import should_use_tui

        args = Namespace(follow=True, tui=False, no_tui=True)
        assert should_use_tui(args) is False

    def test_tui_flag_takes_precedence(self) -> None:
        """Test that --tui takes precedence over --no-tui."""
        from argparse import Namespace
        from kulo.main import should_use_tui

        args = Namespace(follow=False, tui=True, no_tui=True)
        # --tui should win
        assert should_use_tui(args) is True


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

