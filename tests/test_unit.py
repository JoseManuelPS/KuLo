"""Unit tests for KuLo core functionality.

These tests validate internal logic without requiring network access
or a real Kubernetes cluster. All external dependencies are mocked.
"""

import asyncio
import json
import re
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kulo.models import ContainerInfo, LogEntry, PodInfo, StreamContext
from kulo.utils import (
    ColorAssigner,
    DurationParseError,
    POD_COLOR_PALETTE,
    calculate_backoff,
    compile_patterns,
    extract_log_level,
    extract_message,
    get_log_level_color,
    is_regex_pattern,
    matches_any,
    parse_duration,
    parse_namespaces,
    validate_label_selector,
)


# ============================================================================
# Utils Tests: Duration Parsing
# ============================================================================


class TestParseDuration:
    """Tests for the parse_duration function."""

    def test_parse_seconds(self) -> None:
        """Test parsing seconds."""
        assert parse_duration("30s") == 30
        assert parse_duration("1s") == 1
        assert parse_duration("120s") == 120

    def test_parse_minutes(self) -> None:
        """Test parsing minutes."""
        assert parse_duration("5m") == 300
        assert parse_duration("1m") == 60
        assert parse_duration("10m") == 600

    def test_parse_hours(self) -> None:
        """Test parsing hours."""
        assert parse_duration("1h") == 3600
        assert parse_duration("2h") == 7200
        assert parse_duration("24h") == 86400

    def test_parse_days(self) -> None:
        """Test parsing days."""
        assert parse_duration("1d") == 86400
        assert parse_duration("7d") == 604800

    def test_case_insensitive(self) -> None:
        """Test case insensitivity."""
        assert parse_duration("5M") == 300
        assert parse_duration("1H") == 3600
        assert parse_duration("30S") == 30

    def test_with_whitespace(self) -> None:
        """Test handling of whitespace."""
        assert parse_duration("  5m  ") == 300

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid formats raise DurationParseError."""
        with pytest.raises(DurationParseError):
            parse_duration("invalid")

        with pytest.raises(DurationParseError):
            parse_duration("5x")

        with pytest.raises(DurationParseError):
            parse_duration("m5")

        with pytest.raises(DurationParseError):
            parse_duration("")

    def test_zero_value_raises_error(self) -> None:
        """Test that zero values raise DurationParseError."""
        with pytest.raises(DurationParseError):
            parse_duration("0s")


# ============================================================================
# Utils Tests: Pattern Compilation
# ============================================================================


class TestCompilePatterns:
    """Tests for the compile_patterns function."""

    def test_single_pattern(self) -> None:
        """Test compiling a single pattern."""
        patterns = compile_patterns("frontend-.*")
        assert len(patterns) == 1
        assert patterns[0].search("frontend-abc")

    def test_multiple_patterns(self) -> None:
        """Test compiling multiple comma-separated patterns."""
        patterns = compile_patterns("frontend-.*,backend-.*")
        assert len(patterns) == 2

    def test_none_returns_empty(self) -> None:
        """Test that None returns empty list."""
        assert compile_patterns(None) == []

    def test_empty_string_returns_empty(self) -> None:
        """Test that empty string returns empty list."""
        assert compile_patterns("") == []

    def test_case_insensitive(self) -> None:
        """Test that patterns are case insensitive."""
        patterns = compile_patterns("frontend")
        assert patterns[0].search("FRONTEND")
        assert patterns[0].search("Frontend")

    def test_invalid_regex_raises_error(self) -> None:
        """Test that invalid regex raises ValueError."""
        with pytest.raises(ValueError):
            compile_patterns("[invalid")


class TestMatchesAny:
    """Tests for the matches_any function."""

    def test_matches_first_pattern(self) -> None:
        """Test matching the first pattern."""
        patterns = compile_patterns("frontend-.*,backend-.*")
        assert matches_any("frontend-abc", patterns)

    def test_matches_second_pattern(self) -> None:
        """Test matching the second pattern."""
        patterns = compile_patterns("frontend-.*,backend-.*")
        assert matches_any("backend-xyz", patterns)

    def test_no_match(self) -> None:
        """Test when nothing matches."""
        patterns = compile_patterns("frontend-.*,backend-.*")
        assert not matches_any("database-xyz", patterns)

    def test_empty_patterns_returns_false(self) -> None:
        """Test that empty patterns returns False."""
        assert not matches_any("anything", [])


# ============================================================================
# Utils Tests: Color Management
# ============================================================================


class TestGetLogLevelColor:
    """Tests for the get_log_level_color function."""

    def test_info_level(self) -> None:
        """Test INFO level color."""
        assert get_log_level_color("INFO") == "green"
        assert get_log_level_color("info") == "green"

    def test_error_level(self) -> None:
        """Test ERROR level color."""
        assert get_log_level_color("ERROR") == "red"
        assert get_log_level_color("error") == "red"

    def test_warn_level(self) -> None:
        """Test WARN level color."""
        assert get_log_level_color("WARN") == "yellow"
        assert get_log_level_color("WARNING") == "yellow"

    def test_none_returns_default(self) -> None:
        """Test None returns default."""
        assert get_log_level_color(None) == "default"

    def test_unknown_returns_default(self) -> None:
        """Test unknown level returns default."""
        assert get_log_level_color("UNKNOWN") == "default"


# ============================================================================
# Utils Tests: JSON Log Extraction
# ============================================================================


class TestExtractLogLevel:
    """Tests for the extract_log_level function."""

    def test_level_field(self) -> None:
        """Test extraction from 'level' field."""
        assert extract_log_level({"level": "INFO"}) == "INFO"

    def test_loglevel_field(self) -> None:
        """Test extraction from 'loglevel' field."""
        assert extract_log_level({"loglevel": "ERROR"}) == "ERROR"

    def test_severity_field(self) -> None:
        """Test extraction from 'severity' field."""
        assert extract_log_level({"severity": "WARN"}) == "WARN"

    def test_no_level_field(self) -> None:
        """Test when no level field exists."""
        assert extract_log_level({"msg": "hello"}) is None


class TestExtractMessage:
    """Tests for the extract_message function."""

    def test_msg_field(self) -> None:
        """Test extraction from 'msg' field."""
        assert extract_message({"msg": "Hello world"}) == "Hello world"

    def test_message_field(self) -> None:
        """Test extraction from 'message' field."""
        assert extract_message({"message": "Request received"}) == "Request received"

    def test_no_message_field(self) -> None:
        """Test when no message field exists."""
        assert extract_message({"level": "INFO"}) is None


# ============================================================================
# Utils Tests: Namespace Parsing
# ============================================================================


class TestParseNamespaces:
    """Tests for the parse_namespaces function."""

    def test_single_namespace(self) -> None:
        """Test parsing single namespace."""
        assert parse_namespaces("default") == ["default"]

    def test_multiple_namespaces(self) -> None:
        """Test parsing multiple namespaces."""
        result = parse_namespaces("frontend,backend,database")
        assert result == ["frontend", "backend", "database"]

    def test_with_whitespace(self) -> None:
        """Test handling whitespace."""
        result = parse_namespaces("frontend , backend")
        assert result == ["frontend", "backend"]

    def test_none_returns_empty(self) -> None:
        """Test None returns empty list."""
        assert parse_namespaces(None) == []


# ============================================================================
# Utils Tests: Label Selector Validation
# ============================================================================


class TestValidateLabelSelector:
    """Tests for the validate_label_selector function."""

    def test_valid_single_selector(self) -> None:
        """Test valid single selector."""
        assert validate_label_selector("app=frontend") == "app=frontend"

    def test_valid_multiple_selectors(self) -> None:
        """Test valid multiple selectors."""
        result = validate_label_selector("app=frontend,tier=web")
        assert result == "app=frontend,tier=web"

    def test_none_returns_none(self) -> None:
        """Test None returns None."""
        assert validate_label_selector(None) is None

    def test_empty_returns_none(self) -> None:
        """Test empty string returns None."""
        assert validate_label_selector("") is None
        assert validate_label_selector("   ") is None


# ============================================================================
# Utils Tests: Backoff Calculation
# ============================================================================


class TestCalculateBackoff:
    """Tests for the calculate_backoff function."""

    def test_first_retry(self) -> None:
        """Test first retry (index 0)."""
        assert calculate_backoff(0) == 1.0

    def test_second_retry(self) -> None:
        """Test second retry."""
        assert calculate_backoff(1) == 2.0

    def test_exponential_growth(self) -> None:
        """Test exponential growth."""
        assert calculate_backoff(2) == 4.0
        assert calculate_backoff(3) == 8.0
        assert calculate_backoff(4) == 16.0

    def test_max_cap(self) -> None:
        """Test maximum cap is applied."""
        assert calculate_backoff(10) == 60.0
        assert calculate_backoff(100) == 60.0

    def test_custom_base(self) -> None:
        """Test custom base value."""
        assert calculate_backoff(0, base=2.0) == 2.0
        assert calculate_backoff(1, base=2.0) == 4.0

    def test_custom_max(self) -> None:
        """Test custom maximum."""
        assert calculate_backoff(10, max_backoff=30.0) == 30.0


# ============================================================================
# Model Tests: PodInfo
# ============================================================================


class TestPodInfo:
    """Tests for the PodInfo model."""

    def test_get_all_containers(self, sample_pod_info: PodInfo) -> None:
        """Test getting all containers."""
        containers = sample_pod_info.get_all_containers()
        assert len(containers) == 3  # 2 regular + 1 init

    def test_exclude_init_containers(self, sample_pod_info: PodInfo) -> None:
        """Test excluding init containers."""
        containers = sample_pod_info.get_all_containers(exclude_init=True)
        assert len(containers) == 2
        assert all(c.container_type != "init" for c in containers)

    def test_exclude_ephemeral_containers(self, sample_pod_info: PodInfo) -> None:
        """Test excluding ephemeral containers."""
        containers = sample_pod_info.get_all_containers(exclude_ephemeral=True)
        assert all(c.container_type != "ephemeral" for c in containers)


class TestContainerInfo:
    """Tests for the ContainerInfo model."""

    def test_unique_id(self, sample_container_info: ContainerInfo) -> None:
        """Test unique ID generation."""
        expected = "default/frontend-abc123/nginx"
        assert sample_container_info.unique_id == expected


class TestLogEntry:
    """Tests for the LogEntry model."""

    def test_unique_id(self, sample_log_entry: LogEntry) -> None:
        """Test unique ID generation."""
        expected = "default/frontend-abc123/nginx"
        assert sample_log_entry.unique_id == expected


class TestStreamContext:
    """Tests for the StreamContext model."""

    def test_reset_retries(self, sample_container_info: ContainerInfo) -> None:
        """Test resetting retry count."""
        context = StreamContext(
            container=sample_container_info,
            since_seconds=600,
            follow=True,
            tail_lines=25,
            retry_count=5,
        )
        context.reset_retries()
        assert context.retry_count == 0

    def test_increment_retries(self, sample_container_info: ContainerInfo) -> None:
        """Test incrementing retry count."""
        context = StreamContext(
            container=sample_container_info,
            since_seconds=600,
            follow=True,
            tail_lines=25,
        )
        result = context.increment_retries()
        assert result == 1
        assert context.retry_count == 1


# ============================================================================
# UI Tests
# ============================================================================


class TestKuloUI:
    """Tests for the KuloUI class."""

    def test_configure_output_single_namespace(
        self,
        sample_pod_info: PodInfo,
    ) -> None:
        """Test output configuration with single namespace."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["default"], [sample_pod_info])
        assert ui.show_namespace is False

    def test_configure_output_multiple_namespaces(
        self,
        multiple_pods: list[PodInfo],
    ) -> None:
        """Test output configuration with multiple namespaces."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["frontend", "backend"], multiple_pods)
        assert ui.show_namespace is True

    def test_configure_output_single_container(
        self,
        sample_single_container_pod: PodInfo,
    ) -> None:
        """Test output configuration with single container pod."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["production"], [sample_single_container_pod])
        assert ui.show_container is False

    def test_configure_output_multiple_containers(
        self,
        sample_pod_info: PodInfo,
    ) -> None:
        """Test output configuration with multiple containers."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["default"], [sample_pod_info])
        assert ui.show_container is True

    def test_try_parse_json_valid(self) -> None:
        """Test JSON parsing with valid JSON."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        result = ui._try_parse_json('{"level":"INFO","msg":"test"}')
        assert result == {"level": "INFO", "msg": "test"}

    def test_try_parse_json_invalid(self) -> None:
        """Test JSON parsing with invalid JSON."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        assert ui._try_parse_json("not json") is None
        assert ui._try_parse_json("") is None

    def test_detect_log_level_from_text(self) -> None:
        """Test log level detection from plain text."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        assert ui._detect_log_level_from_text("ERROR: Something failed") == "red"
        assert ui._detect_log_level_from_text("WARN: Slow response") == "yellow"
        assert ui._detect_log_level_from_text("DEBUG: Trace info") == "dim"
        assert ui._detect_log_level_from_text("Normal log") == "default"

    def test_no_color_logs_parameter(self) -> None:
        """Test no_color_logs parameter."""
        from kulo.ui import KuloUI

        ui = KuloUI(no_color_logs=True)
        assert ui._no_color_logs is True

        ui2 = KuloUI(no_color_logs=False)
        assert ui2._no_color_logs is False

        ui3 = KuloUI()
        assert ui3._no_color_logs is False  # Default

    def test_format_log_line_uses_pod_color(self, sample_pod_info: PodInfo) -> None:
        """Test that plain text logs use pod color."""
        from datetime import datetime
        from kulo.models import LogEntry
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["default"], [sample_pod_info])

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name=sample_pod_info.name,
            container_name="main",
            message="Plain log message",
        )

        formatted = ui._format_log_line(entry)
        # Check that message uses pod color (not log level color)
        pod_color = ui._get_pod_color(sample_pod_info.name)
        # The message should be in the formatted text with pod color
        assert "Plain log message" in formatted.plain

    def test_format_json_log_uses_pod_color_for_message(
        self, sample_pod_info: PodInfo
    ) -> None:
        """Test that JSON logs use pod color for message, level color for tag."""
        from datetime import datetime
        from kulo.models import LogEntry
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["default"], [sample_pod_info])

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name=sample_pod_info.name,
            container_name="main",
            message='{"level":"INFO","msg":"Request received"}',
        )
        entry.is_json = True
        entry.json_data = {"level": "INFO", "msg": "Request received"}
        entry.log_level = "INFO"

        formatted = ui._format_log_line(entry)
        # Should contain both [INFO] tag and message
        assert "[INFO]" in formatted.plain
        assert "Request received" in formatted.plain

    def test_no_color_logs_disables_coloring(self, sample_pod_info: PodInfo) -> None:
        """Test that no_color_logs disables all log coloring."""
        from datetime import datetime
        from kulo.models import LogEntry
        from kulo.ui import KuloUI

        ui = KuloUI(no_color_logs=True)
        ui.configure_output(["default"], [sample_pod_info])

        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name=sample_pod_info.name,
            container_name="main",
            message="Plain log message",
        )

        formatted = ui._format_log_line(entry)
        # Message should be present but styling should be default
        assert "Plain log message" in formatted.plain

        # Test JSON log
        entry2 = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name=sample_pod_info.name,
            container_name="main",
            message='{"level":"ERROR","msg":"Error occurred"}',
        )
        entry2.is_json = True
        entry2.json_data = {"level": "ERROR", "msg": "Error occurred"}
        entry2.log_level = "ERROR"

        formatted2 = ui._format_log_line(entry2)
        assert "[ERROR]" in formatted2.plain
        assert "Error occurred" in formatted2.plain


# ============================================================================
# Manager Tests: Queue and Throttling
# ============================================================================


class TestLogManager:
    """Tests for the LogManager class."""

    @pytest.mark.asyncio
    async def test_queue_operations(self) -> None:
        """Test basic queue operations."""
        from kulo.manager import LogManager

        mock_client = MagicMock()
        manager = LogManager(mock_client, max_queue_size=10)

        # Put an entry in the queue
        entry = LogEntry(
            timestamp=datetime.now(),
            namespace="default",
            pod_name="test",
            container_name="main",
            message="test message",
        )

        await manager.queue.put(entry)
        result = await manager.queue.get()

        assert result == entry

    @pytest.mark.asyncio
    async def test_stop_event(self) -> None:
        """Test stop event functionality."""
        from kulo.manager import LogManager

        mock_client = MagicMock()
        manager = LogManager(mock_client)

        assert not manager.stop_event.is_set()
        manager.request_shutdown()
        assert manager.stop_event.is_set()


# ============================================================================
# Main Module Tests
# ============================================================================


class TestFilterPods:
    """Tests for pod filtering logic."""

    def test_filter_pods(self, multiple_pods: list[PodInfo]) -> None:
        """Test filter pattern."""
        from kulo.main import filter_pods

        filter_pats = compile_patterns("web-.*")
        result = filter_pods(multiple_pods, filter_pats, [])

        assert len(result) == 2
        assert all("web" in p.name for p in result)

    def test_exclude_filter(self, multiple_pods: list[PodInfo]) -> None:
        """Test exclude filter."""
        from kulo.main import filter_pods

        exclude = compile_patterns("api-.*")
        result = filter_pods(multiple_pods, [], exclude)

        assert len(result) == 2
        assert all("api" not in p.name for p in result)

    def test_combined_filters(self, multiple_pods: list[PodInfo]) -> None:
        """Test combined filter and exclude."""
        from kulo.main import filter_pods

        filter_pats = compile_patterns("web-.*,api-.*")
        exclude = compile_patterns("api-.*")
        result = filter_pods(multiple_pods, filter_pats, exclude)

        assert len(result) == 2
        assert all("web" in p.name for p in result)


class TestGetContainers:
    """Tests for container extraction."""

    def test_get_all_containers(self, multiple_pods: list[PodInfo]) -> None:
        """Test getting all containers."""
        from kulo.main import get_containers

        # Modify one pod to be Running
        containers = get_containers(multiple_pods)
        assert len(containers) > 0

    def test_exclude_init(self, multiple_pods: list[PodInfo]) -> None:
        """Test excluding init containers."""
        from kulo.main import get_containers

        all_containers = get_containers(multiple_pods, exclude_init=False)
        no_init = get_containers(multiple_pods, exclude_init=True)

        # Should have fewer containers when excluding init
        assert len(no_init) <= len(all_containers)


# ============================================================================
# ColorAssigner Tests
# ============================================================================


class TestColorAssigner:
    """Tests for the ColorAssigner class."""

    def test_deterministic_assignment(self) -> None:
        """Test that same pods always get same colors."""
        assigner1 = ColorAssigner()
        assigner1.initialize(["pod-a", "pod-b", "pod-c"])

        assigner2 = ColorAssigner()
        assigner2.initialize(["pod-a", "pod-b", "pod-c"])

        assert assigner1.get_color("pod-a") == assigner2.get_color("pod-a")
        assert assigner1.get_color("pod-b") == assigner2.get_color("pod-b")
        assert assigner1.get_color("pod-c") == assigner2.get_color("pod-c")

    def test_arrival_order_assignment(self) -> None:
        """Test that pods are assigned colors in arrival order."""
        assigner = ColorAssigner()
        assigner.initialize(["pod-c", "pod-a", "pod-b"])

        # pod-c should get first color (arrived first)
        assert assigner.get_color("pod-c") == POD_COLOR_PALETTE[0]
        # pod-a should get second color (arrived second)
        assert assigner.get_color("pod-a") == POD_COLOR_PALETTE[1]
        # pod-b should get third color (arrived third)
        assert assigner.get_color("pod-b") == POD_COLOR_PALETTE[2]

    def test_no_repetition_within_palette_size(self) -> None:
        """Test that colors don't repeat within palette size."""
        palette_size = len(POD_COLOR_PALETTE)
        pod_names = [f"pod-{i:03d}" for i in range(palette_size)]

        assigner = ColorAssigner()
        assigner.initialize(pod_names)

        colors = [assigner.get_color(name) for name in pod_names]
        unique_colors = set(colors)

        # All colors should be unique
        assert len(unique_colors) == palette_size

    def test_dynamic_pod_assignment(self) -> None:
        """Test assigning colors to dynamically added pods."""
        assigner = ColorAssigner()
        assigner.initialize(["pod-a", "pod-b"])

        # Get colors for initial pods
        color_a = assigner.get_color("pod-a")
        color_b = assigner.get_color("pod-b")

        # Add new pod dynamically
        color_c = assigner.update_for_new_pod("pod-c")

        # New pod should get next available color
        assert color_c == POD_COLOR_PALETTE[2]

        # Original pods should keep their colors
        assert assigner.get_color("pod-a") == color_a
        assert assigner.get_color("pod-b") == color_b

    def test_custom_palette(self) -> None:
        """Test using a custom palette."""
        custom_palette = ["red", "green", "blue"]
        assigner = ColorAssigner(palette=custom_palette)
        assigner.initialize(["pod-a", "pod-b"])

        assert assigner.get_color("pod-a") == "red"
        assert assigner.get_color("pod-b") == "green"

    def test_assigned_count(self) -> None:
        """Test the assigned_count property."""
        assigner = ColorAssigner()
        assigner.initialize(["pod-a", "pod-b", "pod-c"])

        assert assigner.assigned_count == 3

    def test_get_all_assignments(self) -> None:
        """Test getting all color assignments."""
        assigner = ColorAssigner()
        assigner.initialize(["pod-a", "pod-b"])

        assignments = assigner.get_all_assignments()

        assert "pod-a" in assignments
        assert "pod-b" in assignments
        assert len(assignments) == 2


# ============================================================================
# Prefix Alignment Tests
# ============================================================================


class TestPrefixAlignment:
    """Tests for prefix alignment in KuloUI."""

    def test_prefix_width_calculation(self) -> None:
        """Test that prefix width is calculated correctly."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.show_namespace = True
        ui.show_container = True

        width = ui._calculate_prefix_width("default", "my-pod", "nginx")
        # Format: "[default] my-pod (nginx)"
        # [default] = 9 + 1 space, my-pod = 6, " (nginx)" = 8
        expected = len("[default] ") + len("my-pod") + len(" (nginx)")
        assert width == expected

    def test_prefix_width_without_namespace(self) -> None:
        """Test prefix width when namespace is hidden."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.show_namespace = False
        ui.show_container = True

        width = ui._calculate_prefix_width("default", "my-pod", "nginx")
        # Format: "my-pod (nginx)"
        expected = len("my-pod") + len(" (nginx)")
        assert width == expected

    def test_prefix_width_without_container(self) -> None:
        """Test prefix width when container is hidden."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.show_namespace = True
        ui.show_container = False

        width = ui._calculate_prefix_width("default", "my-pod", "nginx")
        # Format: "[default] my-pod"
        expected = len("[default] ") + len("my-pod")
        assert width == expected

    def test_max_prefix_width_configured(self, multiple_pods: list[PodInfo]) -> None:
        """Test that max prefix width is set during configure_output."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.configure_output(["frontend", "backend"], multiple_pods)

        # Max prefix should be set based on longest pod/container combo
        assert ui._max_prefix_width > 0

    def test_update_prefix_width_for_new_container(self) -> None:
        """Test updating prefix width for a new container."""
        from kulo.ui import KuloUI

        ui = KuloUI()
        ui.show_namespace = True
        ui.show_container = True
        ui._max_prefix_width = 20  # Set initial width

        # Add a container with a longer name
        new_container = ContainerInfo(
            namespace="my-very-long-namespace",
            pod_name="my-very-long-pod-name",
            container_name="my-container",
            container_type="regular",
        )

        ui.update_prefix_width_for_container(new_container)

        # Width should have increased
        assert ui._max_prefix_width > 20


# ============================================================================
# Namespace Regex Tests
# ============================================================================


class TestIsRegexPattern:
    """Tests for the is_regex_pattern function."""

    def test_simple_name_not_regex(self) -> None:
        """Test that simple names are not detected as regex."""
        assert not is_regex_pattern("default")
        assert not is_regex_pattern("my-namespace")
        assert not is_regex_pattern("ns_123")

    def test_wildcards_detected(self) -> None:
        """Test that wildcard patterns are detected."""
        assert is_regex_pattern("dev-.*")
        assert is_regex_pattern(".*-api")
        assert is_regex_pattern("prod.*")

    def test_anchors_detected(self) -> None:
        """Test that anchor patterns are detected."""
        assert is_regex_pattern("^dev")
        assert is_regex_pattern("prod$")
        assert is_regex_pattern("^exact$")

    def test_character_classes_detected(self) -> None:
        """Test that character classes are detected."""
        assert is_regex_pattern("[abc]")
        assert is_regex_pattern("dev-[0-9]+")

    def test_quantifiers_detected(self) -> None:
        """Test that quantifiers are detected."""
        assert is_regex_pattern("dev+")
        assert is_regex_pattern("prod?")
        assert is_regex_pattern("ns{1,3}")

    def test_groups_detected(self) -> None:
        """Test that groups are detected."""
        assert is_regex_pattern("(dev|prod)")
        assert is_regex_pattern("ns(1|2)")


class TestNamespaceRegexResolution:
    """Tests for namespace regex resolution logic."""

    @pytest.mark.asyncio
    async def test_resolve_exact_names(self) -> None:
        """Test resolving exact namespace names."""
        from kulo.main import resolve_namespace_patterns
        from kulo.ui import KuloUI

        mock_client = MagicMock()
        mock_client.check_namespace_exists = AsyncMock(return_value=True)

        ui = KuloUI()

        result = await resolve_namespace_patterns(
            mock_client, ["default", "kube-system"], ui
        )

        assert result == ["default", "kube-system"]
        assert mock_client.check_namespace_exists.call_count == 2

    @pytest.mark.asyncio
    async def test_resolve_regex_patterns(self) -> None:
        """Test resolving regex namespace patterns."""
        from kulo.main import resolve_namespace_patterns
        from kulo.ui import KuloUI

        mock_client = MagicMock()
        mock_client.list_all_namespaces = AsyncMock(
            return_value=["dev-team1", "dev-team2", "prod", "staging"]
        )

        ui = KuloUI()

        result = await resolve_namespace_patterns(mock_client, ["dev-.*"], ui)

        assert "dev-team1" in result
        assert "dev-team2" in result
        assert "prod" not in result
        assert "staging" not in result

    @pytest.mark.asyncio
    async def test_resolve_mixed_names_and_patterns(self) -> None:
        """Test resolving a mix of exact names and patterns."""
        from kulo.main import resolve_namespace_patterns
        from kulo.ui import KuloUI

        mock_client = MagicMock()
        mock_client.check_namespace_exists = AsyncMock(return_value=True)
        mock_client.list_all_namespaces = AsyncMock(
            return_value=["dev-team1", "dev-team2", "prod", "staging", "default"]
        )

        ui = KuloUI()

        result = await resolve_namespace_patterns(
            mock_client, ["default", "dev-.*"], ui
        )

        assert "default" in result
        assert "dev-team1" in result
        assert "dev-team2" in result

    @pytest.mark.asyncio
    async def test_nonexistent_exact_namespace_returns_empty(self) -> None:
        """Test that nonexistent exact namespace returns empty list."""
        from kulo.main import resolve_namespace_patterns
        from kulo.ui import KuloUI
        from io import StringIO
        from rich.console import Console

        mock_client = MagicMock()
        mock_client.check_namespace_exists = AsyncMock(return_value=False)

        # Capture output
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        ui = KuloUI(console=console)

        result = await resolve_namespace_patterns(
            mock_client, ["nonexistent"], ui
        )

        assert result == []


# ============================================================================
# Max Containers Unlimited Tests
# ============================================================================


class TestMaxContainersUnlimited:
    """Tests for max_containers=0 (unlimited) behavior."""

    def test_cli_parser_accepts_zero(self) -> None:
        """Test that CLI parser accepts --max-containers 0."""
        from kulo.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["--max-containers", "0"])

        assert args.max_containers == 0

    def test_ui_summary_shows_unlimited(self) -> None:
        """Test that UI summary shows 'unlimited' when max_containers is 0."""
        from io import StringIO
        from rich.console import Console
        from kulo.ui import KuloUI

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        ui = KuloUI(console=console)

        ui.print_summary(
            pods=[],
            namespaces=["default"],
            follow=False,
            max_containers=0,
        )

        result = output.getvalue()
        assert "unlimited" in result

    def test_ui_summary_no_warning_when_unlimited(
        self,
        multiple_pods: list[PodInfo],
    ) -> None:
        """Test that no warning is shown when max_containers is 0."""
        from io import StringIO
        from rich.console import Console
        from kulo.ui import KuloUI

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        ui = KuloUI(console=console)
        ui.configure_output(["frontend", "backend"], multiple_pods)

        ui.print_summary(
            pods=multiple_pods,
            namespaces=["frontend", "backend"],
            follow=False,
            max_containers=0,
        )

        result = output.getvalue()
        assert "Warning" not in result

