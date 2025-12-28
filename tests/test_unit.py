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
    DurationParseError,
    calculate_backoff,
    compile_patterns,
    extract_log_level,
    extract_message,
    get_color_for_pod,
    get_log_level_color,
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


class TestGetColorForPod:
    """Tests for the get_color_for_pod function."""

    def test_consistent_color(self) -> None:
        """Test that same pod always gets same color."""
        color1 = get_color_for_pod("my-pod-abc")
        color2 = get_color_for_pod("my-pod-abc")
        assert color1 == color2

    def test_different_pods_can_have_different_colors(self) -> None:
        """Test that different pods can have different colors."""
        # With enough pods, at least some should differ
        colors = {get_color_for_pod(f"pod-{i}") for i in range(100)}
        assert len(colors) > 1


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

    def test_include_filter(self, multiple_pods: list[PodInfo]) -> None:
        """Test include filter."""
        from kulo.main import filter_pods

        include = compile_patterns("web-.*")
        result = filter_pods(multiple_pods, include, [])

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
        """Test combined include and exclude."""
        from kulo.main import filter_pods

        include = compile_patterns("web-.*,api-.*")
        exclude = compile_patterns("api-.*")
        result = filter_pods(multiple_pods, include, exclude)

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

