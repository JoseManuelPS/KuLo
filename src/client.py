"""Asynchronous Kubernetes client wrapper for KuLo.

This module provides a high-level async interface for Kubernetes operations:
- Loading kubeconfig and authentication
- Discovering pods and containers
- Streaming logs with reconnection support

Uses kubernetes_asyncio for true async I/O operations.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException
from kubernetes_asyncio.watch import Watch

from kulo.models import ContainerInfo, PodInfo, StreamContext
from kulo.utils import calculate_backoff


logger = logging.getLogger(__name__)


class KuloClientError(Exception):
    """Base exception for KuloClient errors."""

    pass


class NamespaceNotFoundError(KuloClientError):
    """Raised when a namespace does not exist."""

    pass


class PodNotFoundError(KuloClientError):
    """Raised when a pod does not exist or was deleted."""

    pass


class PermissionDeniedError(KuloClientError):
    """Raised when the client lacks permission for an operation."""

    pass


class KuloClient:
    """Asynchronous Kubernetes client for log operations.

    This client handles:
    - Loading kubeconfig from ~/.kube/config
    - Discovering pods based on namespace and label selectors
    - Streaming container logs with automatic reconnection

    Attributes:
        core_api: The Kubernetes CoreV1Api client.
        _api_client: The underlying API client instance.

    Example:
        async with KuloClient.create() as client:
            pods = await client.list_pods("default")
            async for line in client.stream_logs(context):
                print(line)
    """

    def __init__(self, api_client: client.ApiClient) -> None:
        """Initialize the client with an API client instance.

        Args:
            api_client: The kubernetes_asyncio ApiClient instance.
        """
        self._api_client = api_client
        self.core_api = client.CoreV1Api(api_client)

    @classmethod
    @asynccontextmanager
    async def create(cls) -> AsyncIterator[Self]:
        """Create and initialize a KuloClient from kubeconfig.

        This is the recommended way to create a KuloClient, as it properly
        manages the lifecycle of the underlying API client.

        Yields:
            An initialized KuloClient instance.

        Raises:
            KuloClientError: If kubeconfig cannot be loaded.

        Example:
            async with KuloClient.create() as client:
                pods = await client.list_pods("default")
        """
        try:
            await config.load_kube_config()
        except Exception as e:
            raise KuloClientError(
                f"Failed to load kubeconfig from ~/.kube/config: {e}"
            ) from e

        api_client = client.ApiClient()
        try:
            yield cls(api_client)
        finally:
            await api_client.close()

    async def get_current_namespace(self) -> str:
        """Get the namespace from the current kubeconfig context.

        Returns:
            The namespace from the current context, or 'default' if not set.
        """
        try:
            _, active_context = await asyncio.to_thread(
                config.list_kube_config_contexts
            )
            if active_context and "namespace" in active_context.get("context", {}):
                return active_context["context"]["namespace"]
        except Exception as e:
            logger.debug(f"Could not get namespace from context: {e}")

        return "default"

    async def list_pods(
        self,
        namespace: str,
        label_selector: str | None = None,
    ) -> list[PodInfo]:
        """List pods in a namespace with optional label filtering.

        Args:
            namespace: The namespace to list pods from.
            label_selector: Optional Kubernetes label selector (e.g., 'app=frontend').

        Returns:
            List of PodInfo objects for matching pods.

        Raises:
            NamespaceNotFoundError: If the namespace does not exist.
            PermissionDeniedError: If access to the namespace is denied.
            KuloClientError: For other API errors.
        """
        try:
            if label_selector:
                response = await self.core_api.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector,
                )
            else:
                response = await self.core_api.list_namespaced_pod(
                    namespace=namespace,
                )
        except ApiException as e:
            if e.status == 404:
                raise NamespaceNotFoundError(
                    f"Namespace '{namespace}' not found"
                ) from e
            if e.status == 403:
                raise PermissionDeniedError(
                    f"Permission denied for namespace '{namespace}'"
                ) from e
            raise KuloClientError(f"Failed to list pods: {e}") from e

        pods: list[PodInfo] = []
        for item in response.items:
            pods.append(self._parse_pod(item, namespace))

        return pods

    async def watch_pods(
        self,
        namespace: str,
        label_selector: str | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[tuple[str, PodInfo]]:
        """Watch for pod changes in a namespace.

        Yields tuples of (event_type, pod_info) where event_type is one of:
        'ADDED', 'MODIFIED', 'DELETED'.

        Args:
            namespace: The namespace to watch.
            label_selector: Optional label selector for filtering.
            stop_event: Optional event to signal when to stop watching.

        Yields:
            Tuples of (event_type, PodInfo) for each pod event.

        Raises:
            KuloClientError: If the watch fails.
        """
        watch = Watch()

        try:
            kwargs = {"namespace": namespace}
            if label_selector:
                kwargs["label_selector"] = label_selector

            async for event in watch.stream(
                self.core_api.list_namespaced_pod,
                **kwargs,
            ):
                if stop_event and stop_event.is_set():
                    break

                event_type = event["type"]
                pod = event["object"]
                pod_info = self._parse_pod(pod, namespace)

                yield event_type, pod_info

        except ApiException as e:
            if e.status == 410:
                # Gone - resource version too old, need to re-list
                logger.debug("Watch expired, will need to re-establish")
                return
            raise KuloClientError(f"Watch failed: {e}") from e
        finally:
            await watch.close()

    async def stream_logs(
        self,
        context: StreamContext,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Stream logs from a container with automatic reconnection.

        Implements exponential backoff for reconnection attempts in follow mode.

        Args:
            context: The stream context containing container info and parameters.
            stop_event: Optional event to signal when to stop streaming.

        Yields:
            Log lines as strings.

        Raises:
            PodNotFoundError: If the pod does not exist.
            PermissionDeniedError: If access is denied.
            KuloClientError: For other errors.
        """
        container = context.container
        max_retries = 10  # For follow mode

        while True:
            try:
                async for line in self._stream_logs_internal(context, stop_event):
                    context.reset_retries()
                    yield line

                # Stream ended normally (EOF in non-follow mode)
                if not context.follow:
                    return

                # In follow mode, stream ended - pod might have terminated
                if stop_event and stop_event.is_set():
                    return

            except PodNotFoundError:
                # Pod was deleted - don't retry
                logger.info(
                    f"Pod {container.namespace}/{container.pod_name} was deleted"
                )
                raise

            except (ApiException, KuloClientError) as e:
                if not context.follow:
                    raise

                retry_count = context.increment_retries()
                if retry_count > max_retries:
                    logger.error(
                        f"Max retries ({max_retries}) exceeded for "
                        f"{container.unique_id}"
                    )
                    raise

                backoff = calculate_backoff(retry_count - 1)
                logger.warning(
                    f"Stream error for {container.unique_id}: {e}. "
                    f"Retrying in {backoff:.1f}s (attempt {retry_count}/{max_retries})"
                )

                if stop_event:
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(),
                            timeout=backoff,
                        )
                        return  # Stop event was set during backoff
                    except asyncio.TimeoutError:
                        pass  # Backoff completed, retry
                else:
                    await asyncio.sleep(backoff)

    async def _stream_logs_internal(
        self,
        context: StreamContext,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Internal method to stream logs without reconnection logic.

        Args:
            context: The stream context.
            stop_event: Optional stop event.

        Yields:
            Log lines as strings.
        """
        container = context.container

        try:
            # Build API call parameters
            kwargs: dict = {
                "name": container.pod_name,
                "namespace": container.namespace,
                "container": container.container_name,
                "follow": context.follow,
                "timestamps": False,
                "_preload_content": False,
            }

            if context.tail_lines > 0:
                kwargs["tail_lines"] = context.tail_lines

            if context.since_seconds > 0:
                kwargs["since_seconds"] = context.since_seconds

            response = await self.core_api.read_namespaced_pod_log(**kwargs)

            # Handle streaming response
            if context.follow:
                async for line in response.content:
                    if stop_event and stop_event.is_set():
                        break

                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")

                    # Remove trailing newline
                    line = line.rstrip("\n\r")
                    if line:
                        yield line
            else:
                # Non-streaming response - read all content
                content = await response.read()
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="replace")

                for line in content.splitlines():
                    if line:
                        yield line

        except ApiException as e:
            if e.status == 404:
                raise PodNotFoundError(
                    f"Pod {container.namespace}/{container.pod_name} not found"
                ) from e
            if e.status == 403:
                raise PermissionDeniedError(
                    f"Permission denied for pod {container.namespace}/{container.pod_name}"
                ) from e
            if e.status == 400:
                # Bad request - container might not be ready
                logger.warning(
                    f"Container {container.container_name} in "
                    f"{container.pod_name} may not be ready: {e.reason}"
                )
                return
            raise KuloClientError(
                f"Failed to stream logs from {container.unique_id}: {e}"
            ) from e

    def _parse_pod(self, pod: client.V1Pod, namespace: str) -> PodInfo:
        """Parse a V1Pod object into a PodInfo dataclass.

        Args:
            pod: The Kubernetes V1Pod object.
            namespace: The namespace (for fallback).

        Returns:
            A PodInfo object with parsed data.
        """
        metadata = pod.metadata
        spec = pod.spec
        status = pod.status

        # Extract container names
        containers: list[str] = []
        if spec.containers:
            containers = [c.name for c in spec.containers]

        init_containers: list[str] = []
        if spec.init_containers:
            init_containers = [c.name for c in spec.init_containers]

        ephemeral_containers: list[str] = []
        if spec.ephemeral_containers:
            ephemeral_containers = [c.name for c in spec.ephemeral_containers]

        return PodInfo(
            namespace=metadata.namespace or namespace,
            name=metadata.name,
            phase=status.phase if status else "Unknown",
            containers=containers,
            init_containers=init_containers,
            ephemeral_containers=ephemeral_containers,
            labels=dict(metadata.labels) if metadata.labels else {},
        )

    async def check_namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists.

        Args:
            namespace: The namespace to check.

        Returns:
            True if the namespace exists, False otherwise.
        """
        try:
            await self.core_api.read_namespace(name=namespace)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            if e.status == 403:
                # Can't verify, assume it exists
                logger.warning(f"Cannot verify namespace '{namespace}' exists: permission denied")
                return True
            raise KuloClientError(f"Failed to check namespace: {e}") from e

    async def list_all_namespaces(self) -> list[str]:
        """List all namespaces in the cluster.

        Returns:
            List of namespace names.

        Raises:
            PermissionDeniedError: If access to list namespaces is denied.
            KuloClientError: For other API errors.
        """
        try:
            response = await self.core_api.list_namespace()
            return [ns.metadata.name for ns in response.items]
        except ApiException as e:
            if e.status == 403:
                raise PermissionDeniedError(
                    "Permission denied to list namespaces. "
                    "Use explicit namespace names instead of regex patterns."
                ) from e
            raise KuloClientError(f"Failed to list namespaces: {e}") from e

