"""End-to-end tests for KuLo.

These tests require a real Kubernetes cluster (kind or minikube)
with an active kubeconfig context. They create real resources,
execute KuLo against them, and validate the output.

Run these tests with: pytest -m e2e tests/test_e2e.py

Requirements:
- A running Kubernetes cluster accessible via kubectl
- Permissions to create/delete namespaces and pods
"""

import asyncio
import subprocess
import time
from typing import Generator

import pytest


# Mark all tests in this module as e2e
pytestmark = pytest.mark.e2e


# ============================================================================
# Test Fixtures
# ============================================================================


TEST_NAMESPACE = "kulo-e2e-test"
PLAIN_TEXT_POD = "plain-logger"
JSON_POD = "json-logger"


@pytest.fixture(scope="module")
def k8s_cluster_ready() -> Generator[bool, None, None]:
    """Verify Kubernetes cluster is accessible."""
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip("Kubernetes cluster not accessible")
    except FileNotFoundError:
        pytest.skip("kubectl not found")
    except subprocess.TimeoutExpired:
        pytest.skip("kubectl timed out")

    yield True


@pytest.fixture(scope="module")
def test_namespace(k8s_cluster_ready: bool) -> Generator[str, None, None]:
    """Create and cleanup a test namespace."""
    # Create namespace
    subprocess.run(
        ["kubectl", "create", "namespace", TEST_NAMESPACE],
        capture_output=True,
    )

    yield TEST_NAMESPACE

    # Cleanup
    subprocess.run(
        ["kubectl", "delete", "namespace", TEST_NAMESPACE, "--wait=false"],
        capture_output=True,
    )


@pytest.fixture(scope="module")
def plain_text_pod(test_namespace: str) -> Generator[str, None, None]:
    """Create a pod that logs plain text."""
    pod_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {PLAIN_TEXT_POD}
  namespace: {test_namespace}
  labels:
    app: plain-logger
    test: kulo-e2e
spec:
  containers:
  - name: logger
    image: busybox:latest
    command:
    - /bin/sh
    - -c
    - |
      i=0
      while true; do
        echo "Plain text log message $i"
        i=$((i + 1))
        sleep 1
      done
  restartPolicy: Always
"""

    # Apply manifest
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=pod_manifest,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to create plain text pod: {result.stderr}")

    # Wait for pod to be running
    _wait_for_pod_ready(test_namespace, PLAIN_TEXT_POD)

    yield PLAIN_TEXT_POD

    # Cleanup handled by namespace deletion


@pytest.fixture(scope="module")
def json_pod(test_namespace: str) -> Generator[str, None, None]:
    """Create a pod that logs JSON."""
    pod_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {JSON_POD}
  namespace: {test_namespace}
  labels:
    app: json-logger
    test: kulo-e2e
spec:
  containers:
  - name: logger
    image: busybox:latest
    command:
    - /bin/sh
    - -c
    - |
      i=0
      while true; do
        echo '{{"level":"INFO","msg":"JSON log message '$i'","count":'$i'}}'
        i=$((i + 1))
        sleep 1
      done
  restartPolicy: Always
"""

    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=pod_manifest,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to create JSON pod: {result.stderr}")

    _wait_for_pod_ready(test_namespace, JSON_POD)

    yield JSON_POD


def _wait_for_pod_ready(namespace: str, pod_name: str, timeout: int = 60) -> None:
    """Wait for a pod to be in Running state."""
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            [
                "kubectl", "get", "pod", pod_name,
                "-n", namespace,
                "-o", "jsonpath={.status.phase}",
            ],
            capture_output=True,
            text=True,
        )
        if result.stdout == "Running":
            # Give container a moment to start logging
            time.sleep(2)
            return
        time.sleep(1)

    pytest.fail(f"Pod {pod_name} did not become ready within {timeout}s")


# ============================================================================
# Kubernetes Client Tests
# ============================================================================


class TestKuloClientE2E:
    """End-to-end tests for KuloClient."""

    @pytest.mark.asyncio
    async def test_list_pods_in_namespace(
        self,
        test_namespace: str,
        plain_text_pod: str,
    ) -> None:
        """Test listing pods in a namespace."""
        from kulo.client import KuloClient

        async with KuloClient.create() as client:
            pods = await client.list_pods(test_namespace)

            assert len(pods) >= 1
            pod_names = [p.name for p in pods]
            assert plain_text_pod in pod_names

    @pytest.mark.asyncio
    async def test_list_pods_with_label_selector(
        self,
        test_namespace: str,
        plain_text_pod: str,
        json_pod: str,
    ) -> None:
        """Test listing pods with label selector."""
        from kulo.client import KuloClient

        async with KuloClient.create() as client:
            # Filter to only plain logger
            pods = await client.list_pods(
                test_namespace,
                label_selector="app=plain-logger",
            )

            assert len(pods) == 1
            assert pods[0].name == plain_text_pod

    @pytest.mark.asyncio
    async def test_get_current_namespace(self) -> None:
        """Test getting current namespace from context."""
        from kulo.client import KuloClient

        async with KuloClient.create() as client:
            namespace = await client.get_current_namespace()
            # Should return a string (might be 'default' or configured namespace)
            assert isinstance(namespace, str)
            assert len(namespace) > 0

    @pytest.mark.asyncio
    async def test_check_namespace_exists(self, test_namespace: str) -> None:
        """Test namespace existence check."""
        from kulo.client import KuloClient

        async with KuloClient.create() as client:
            assert await client.check_namespace_exists(test_namespace)
            assert not await client.check_namespace_exists("nonexistent-ns-xyz")

    @pytest.mark.asyncio
    async def test_stream_logs_snapshot(
        self,
        test_namespace: str,
        plain_text_pod: str,
    ) -> None:
        """Test streaming logs in snapshot mode."""
        from kulo.client import KuloClient
        from kulo.models import ContainerInfo, StreamContext

        async with KuloClient.create() as client:
            container = ContainerInfo(
                namespace=test_namespace,
                pod_name=plain_text_pod,
                container_name="logger",
                container_type="regular",
            )

            context = StreamContext(
                container=container,
                since_seconds=60,
                follow=False,
                tail_lines=5,
            )

            lines = []
            async for line in client.stream_logs(context):
                lines.append(line)
                if len(lines) >= 5:
                    break

            assert len(lines) > 0
            assert any("Plain text log" in line for line in lines)

    @pytest.mark.asyncio
    async def test_stream_logs_json(
        self,
        test_namespace: str,
        json_pod: str,
    ) -> None:
        """Test streaming JSON logs."""
        from kulo.client import KuloClient
        from kulo.models import ContainerInfo, StreamContext
        import json

        async with KuloClient.create() as client:
            container = ContainerInfo(
                namespace=test_namespace,
                pod_name=json_pod,
                container_name="logger",
                container_type="regular",
            )

            context = StreamContext(
                container=container,
                since_seconds=60,
                follow=False,
                tail_lines=5,
            )

            lines = []
            async for line in client.stream_logs(context):
                lines.append(line)
                if len(lines) >= 3:
                    break

            assert len(lines) > 0

            # Verify JSON structure
            for line in lines:
                data = json.loads(line)
                assert "level" in data
                assert "msg" in data


# ============================================================================
# Manager Tests
# ============================================================================


class TestLogManagerE2E:
    """End-to-end tests for LogManager."""

    @pytest.mark.asyncio
    async def test_snapshot_mode(
        self,
        test_namespace: str,
        plain_text_pod: str,
    ) -> None:
        """Test snapshot mode collects logs."""
        from kulo.client import KuloClient
        from kulo.manager import LogManager
        from kulo.models import ContainerInfo
        from kulo.ui import KuloUI
        from io import StringIO
        from rich.console import Console

        async with KuloClient.create() as client:
            # Create UI with captured output
            output = StringIO()
            console = Console(file=output, force_terminal=True)
            ui = KuloUI(console=console)

            manager = LogManager(client)

            container = ContainerInfo(
                namespace=test_namespace,
                pod_name=plain_text_pod,
                container_name="logger",
                container_type="regular",
            )

            # Run in snapshot mode
            await manager.run(
                containers=[container],
                ui=ui,
                follow=False,
                since_seconds=60,
                tail_lines=5,
                max_concurrent=10,
            )

            # Verify output was captured
            output_text = output.getvalue()
            assert len(output_text) > 0


# ============================================================================
# Chaos Tests
# ============================================================================


class TestChaosScenarios:
    """Chaos engineering tests for resilience."""

    @pytest.mark.asyncio
    async def test_pod_deletion_during_stream(
        self,
        test_namespace: str,
    ) -> None:
        """Test handling of pod deletion during streaming."""
        from kulo.client import KuloClient, PodNotFoundError
        from kulo.models import ContainerInfo, StreamContext

        # Create a temporary pod
        temp_pod_name = "temp-chaos-pod"
        pod_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {temp_pod_name}
  namespace: {test_namespace}
spec:
  containers:
  - name: logger
    image: busybox:latest
    command: ["sh", "-c", "while true; do echo 'log'; sleep 0.5; done"]
  restartPolicy: Never
"""

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=pod_manifest,
            capture_output=True,
            text=True,
        )

        _wait_for_pod_ready(test_namespace, temp_pod_name)

        async with KuloClient.create() as client:
            container = ContainerInfo(
                namespace=test_namespace,
                pod_name=temp_pod_name,
                container_name="logger",
                container_type="regular",
            )

            context = StreamContext(
                container=container,
                since_seconds=60,
                follow=True,
                tail_lines=5,
            )

            stop_event = asyncio.Event()
            lines_received = 0

            async def stream_and_delete() -> None:
                nonlocal lines_received
                try:
                    async for line in client.stream_logs(context, stop_event):
                        lines_received += 1
                        if lines_received >= 3:
                            # Delete the pod while streaming
                            subprocess.run(
                                [
                                    "kubectl", "delete", "pod",
                                    temp_pod_name, "-n", test_namespace,
                                    "--wait=false",
                                ],
                                capture_output=True,
                            )
                except PodNotFoundError:
                    # Expected behavior
                    pass

            # Give it max 15 seconds
            try:
                await asyncio.wait_for(stream_and_delete(), timeout=15.0)
            except asyncio.TimeoutError:
                stop_event.set()

            # Should have received some logs before deletion
            assert lines_received >= 1


# ============================================================================
# CLI Integration Tests
# ============================================================================


class TestCLIIntegration:
    """Tests for the CLI interface."""

    def test_help_output(self) -> None:
        """Test --help output."""
        result = subprocess.run(
            ["python", "-m", "kulo.main", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "KuLo" in result.stdout
        assert "--namespace" in result.stdout
        assert "--follow" in result.stdout

    def test_version_output(self) -> None:
        """Test --version output."""
        result = subprocess.run(
            ["python", "-m", "kulo.main", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "kulo" in result.stdout.lower()

    def test_invalid_namespace(self, k8s_cluster_ready: bool) -> None:
        """Test error handling for invalid namespace."""
        result = subprocess.run(
            [
                "python", "-m", "kulo.main",
                "-n", "nonexistent-namespace-xyz123",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should exit with error
        assert result.returncode != 0

    def test_snapshot_mode_with_label(
        self,
        test_namespace: str,
        plain_text_pod: str,
    ) -> None:
        """Test snapshot mode with label selector."""
        result = subprocess.run(
            [
                "python", "-m", "kulo.main",
                "-n", test_namespace,
                "-l", "app=plain-logger",
                "-t", "3",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should succeed and show output
        assert result.returncode == 0
        # Output should contain pod reference
        assert plain_text_pod in result.stdout or "plain" in result.stdout.lower()

