"""Pytest configuration and shared fixtures for KuLo tests."""

import asyncio
from datetime import datetime
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from kulo.models import ContainerInfo, LogEntry, PodInfo


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers",
        "e2e: End-to-end tests requiring a real Kubernetes cluster",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip e2e tests unless explicitly requested."""
    if not config.getoption("-m", default=""):
        skip_e2e = pytest.mark.skip(
            reason="E2E tests require -m e2e flag and a real cluster"
        )
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_pod_info() -> PodInfo:
    """Create a sample PodInfo for testing."""
    return PodInfo(
        namespace="default",
        name="frontend-abc123",
        phase="Running",
        containers=["nginx", "sidecar"],
        init_containers=["init-config"],
        ephemeral_containers=[],
        labels={"app": "frontend", "tier": "web"},
    )


@pytest.fixture
def sample_single_container_pod() -> PodInfo:
    """Create a pod with a single container."""
    return PodInfo(
        namespace="production",
        name="api-server-xyz789",
        phase="Running",
        containers=["api"],
        init_containers=[],
        ephemeral_containers=[],
        labels={"app": "api"},
    )


@pytest.fixture
def sample_container_info() -> ContainerInfo:
    """Create a sample ContainerInfo for testing."""
    return ContainerInfo(
        namespace="default",
        pod_name="frontend-abc123",
        container_name="nginx",
        container_type="regular",
    )


@pytest.fixture
def sample_log_entry() -> LogEntry:
    """Create a sample LogEntry for testing."""
    return LogEntry(
        timestamp=datetime(2024, 1, 15, 10, 30, 0),
        namespace="default",
        pod_name="frontend-abc123",
        container_name="nginx",
        message="Starting nginx server on port 8080",
    )


@pytest.fixture
def sample_json_log_entry() -> LogEntry:
    """Create a sample JSON LogEntry for testing."""
    return LogEntry(
        timestamp=datetime(2024, 1, 15, 10, 30, 0),
        namespace="default",
        pod_name="api-server-xyz",
        container_name="api",
        message='{"level":"INFO","msg":"Request received","path":"/api/users","method":"GET"}',
    )


@pytest.fixture
def multiple_pods() -> list[PodInfo]:
    """Create multiple pods for testing."""
    return [
        PodInfo(
            namespace="frontend",
            name="web-abc123",
            phase="Running",
            containers=["nginx"],
            init_containers=[],
            ephemeral_containers=[],
            labels={"app": "web"},
        ),
        PodInfo(
            namespace="frontend",
            name="web-def456",
            phase="Running",
            containers=["nginx"],
            init_containers=[],
            ephemeral_containers=[],
            labels={"app": "web"},
        ),
        PodInfo(
            namespace="backend",
            name="api-ghi789",
            phase="Running",
            containers=["api", "sidecar"],
            init_containers=["init"],
            ephemeral_containers=[],
            labels={"app": "api"},
        ),
    ]


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_k8s_api() -> MagicMock:
    """Create a mock Kubernetes CoreV1Api."""
    api = MagicMock()
    api.list_namespaced_pod = AsyncMock()
    api.read_namespaced_pod_log = AsyncMock()
    api.read_namespace = AsyncMock()
    return api


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Create a mock API client."""
    client = MagicMock()
    client.close = AsyncMock()
    return client


# ============================================================================
# Async Helpers
# ============================================================================


async def async_generator(items: list) -> AsyncIterator:
    """Create an async generator from a list."""
    for item in items:
        yield item


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

