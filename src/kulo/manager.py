"""Log stream manager implementing Producer-Consumer pattern.

This module coordinates:
- Producer tasks that read from Kubernetes log streams
- A single consumer task that updates the UI (Rich or Textual TUI)
- Pod rotation detection in follow mode
- Graceful shutdown via signals

The decoupled architecture prevents UI blocking from network I/O.
"""

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from kulo.client import KuloClient, PodNotFoundError
from kulo.models import ContainerInfo, LogEntry, PodInfo, StreamContext


if TYPE_CHECKING:
    from kulo.ui import KuloUI


@runtime_checkable
class LogRenderer(Protocol):
    """Protocol for objects that can render log entries.

    Supports both the classic KuloUI and the new KuloApp TUI.
    """

    def print_log_entry(self, entry: LogEntry) -> None:
        """Render a log entry.

        Args:
            entry: The log entry to render.
        """
        ...


logger = logging.getLogger(__name__)


class LogManager:
    """Manages log streaming using the Producer-Consumer pattern.

    Producers are async tasks that read from Kubernetes log streams and
    push LogEntry objects to an asyncio.Queue. The consumer task reads
    from the queue and updates the UI.

    Attributes:
        client: The KuloClient for Kubernetes operations.
        queue: The async queue for log entries.
        stop_event: Event to signal shutdown.
        producer_tasks: Set of active producer tasks.

    Example:
        async with KuloClient.create() as client:
            manager = LogManager(client)
            await manager.run(containers, ui, follow=True)
    """

    def __init__(
        self,
        client: KuloClient,
        max_queue_size: int = 1000,
    ) -> None:
        """Initialize the log manager.

        Args:
            client: The KuloClient instance for K8s operations.
            max_queue_size: Maximum size of the log entry queue.
        """
        self.client = client
        self.queue: asyncio.Queue[LogEntry | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self.stop_event = asyncio.Event()
        self.producer_tasks: set[asyncio.Task] = set()
        self._consumer_task: asyncio.Task | None = None
        self._watcher_task: asyncio.Task | None = None
        self._active_containers: set[str] = set()
        self._semaphore: asyncio.Semaphore | None = None

    async def run(
        self,
        containers: list[ContainerInfo],
        ui: "KuloUI | LogRenderer",
        follow: bool = False,
        since_seconds: int = 600,
        tail_lines: int = 25,
        max_concurrent: int = 10,
        label_selector: str | None = None,
        namespaces: list[str] | None = None,
        on_new_container: Callable[[ContainerInfo], None] | None = None,
    ) -> None:
        """Run the log streaming manager.

        Starts producer tasks for each container and a consumer task
        for UI updates. In follow mode, also watches for pod rotation.

        Args:
            containers: List of containers to stream logs from.
            ui: The UI instance for rendering (KuloUI or KuloApp TUI).
            follow: Whether to follow logs in real-time.
            since_seconds: Time window for log retrieval.
            tail_lines: Number of initial lines to fetch.
            max_concurrent: Maximum concurrent stream count.
            label_selector: Optional label selector for pod watching.
            namespaces: List of namespaces to watch for new pods.
            on_new_container: Callback when new containers are discovered.
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._setup_signal_handlers()

        try:
            # Start consumer task first
            self._consumer_task = asyncio.create_task(
                self._consume_logs(ui),
                name="consumer",
            )

            # Start producers for initial containers
            for container in containers:
                await self._start_producer(
                    container,
                    follow=follow,
                    since_seconds=since_seconds,
                    tail_lines=tail_lines,
                )

            # In follow mode, watch for pod rotation
            if follow and namespaces:
                self._watcher_task = asyncio.create_task(
                    self._watch_pod_rotation(
                        namespaces=namespaces,
                        label_selector=label_selector,
                        since_seconds=since_seconds,
                        tail_lines=tail_lines,
                        on_new_container=on_new_container,
                    ),
                    name="pod-watcher",
                )

            # Wait for all producers to complete or stop event
            await self._wait_for_completion(follow)

        finally:
            await self._cleanup()

    async def _start_producer(
        self,
        container: ContainerInfo,
        follow: bool,
        since_seconds: int,
        tail_lines: int,
    ) -> asyncio.Task | None:
        """Start a producer task for a container.

        Args:
            container: The container to stream from.
            follow: Whether to follow the stream.
            since_seconds: Time window for logs.
            tail_lines: Initial lines to fetch.

        Returns:
            The created task, or None if already streaming.
        """
        container_id = container.unique_id

        if container_id in self._active_containers:
            logger.debug(f"Already streaming from {container_id}")
            return None

        self._active_containers.add(container_id)

        context = StreamContext(
            container=container,
            since_seconds=since_seconds,
            follow=follow,
            tail_lines=tail_lines,
        )

        task = asyncio.create_task(
            self._produce_logs(context),
            name=f"producer-{container_id}",
        )
        self.producer_tasks.add(task)
        task.add_done_callback(self._on_producer_done)

        logger.debug(f"Started producer for {container_id}")
        return task

    def _on_producer_done(self, task: asyncio.Task) -> None:
        """Callback when a producer task completes.

        Args:
            task: The completed task.
        """
        self.producer_tasks.discard(task)

        # Extract container ID from task name
        if task.get_name().startswith("producer-"):
            container_id = task.get_name()[9:]
            self._active_containers.discard(container_id)

        # Check for exceptions
        if not task.cancelled():
            exc = task.exception()
            if exc and not isinstance(exc, PodNotFoundError):
                logger.error(f"Producer task failed: {exc}")

    async def _produce_logs(self, context: StreamContext) -> None:
        """Producer coroutine that streams logs to the queue.

        Args:
            context: The stream context for this producer.
        """
        container = context.container
        assert self._semaphore is not None

        async with self._semaphore:
            try:
                async for line in self.client.stream_logs(
                    context,
                    stop_event=self.stop_event,
                ):
                    if self.stop_event.is_set():
                        break

                    entry = LogEntry(
                        timestamp=datetime.now(),
                        namespace=container.namespace,
                        pod_name=container.pod_name,
                        container_name=container.container_name,
                        message=line,
                    )

                    await self.queue.put(entry)

            except PodNotFoundError:
                logger.info(f"Pod {container.pod_name} was deleted")
                raise
            except Exception as e:
                logger.error(f"Producer error for {container.unique_id}: {e}")

    async def _consume_logs(self, ui: "KuloUI | LogRenderer") -> None:
        """Consumer coroutine that renders log entries.

        Args:
            ui: The UI instance for rendering (KuloUI or KuloApp TUI).
        """
        try:
            while True:
                try:
                    # Use timeout to check stop event periodically
                    entry = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=0.5,
                    )

                    if entry is None:
                        # Shutdown signal
                        break

                    ui.print_log_entry(entry)
                    self.queue.task_done()

                except asyncio.TimeoutError:
                    if self.stop_event.is_set() and self.queue.empty():
                        break
                    continue

        except asyncio.CancelledError:
            pass

    async def _watch_pod_rotation(
        self,
        namespaces: list[str],
        label_selector: str | None,
        since_seconds: int,
        tail_lines: int,
        on_new_container: Callable[[ContainerInfo], None] | None = None,
    ) -> None:
        """Watch for new pods and start producers for them.

        Args:
            namespaces: Namespaces to watch.
            label_selector: Optional label selector.
            since_seconds: Time window for new pod logs.
            tail_lines: Initial lines for new pods.
            on_new_container: Callback for new containers.
        """
        watchers = [
            self._watch_namespace_pods(
                namespace=ns,
                label_selector=label_selector,
                since_seconds=since_seconds,
                tail_lines=tail_lines,
                on_new_container=on_new_container,
            )
            for ns in namespaces
        ]

        await asyncio.gather(*watchers, return_exceptions=True)

    async def _watch_namespace_pods(
        self,
        namespace: str,
        label_selector: str | None,
        since_seconds: int,
        tail_lines: int,
        on_new_container: Callable[[ContainerInfo], None] | None = None,
    ) -> None:
        """Watch pods in a specific namespace.

        Args:
            namespace: The namespace to watch.
            label_selector: Optional label selector.
            since_seconds: Time window for logs.
            tail_lines: Initial lines to fetch.
            on_new_container: Callback for new containers.
        """
        try:
            async for event_type, pod_info in self.client.watch_pods(
                namespace=namespace,
                label_selector=label_selector,
                stop_event=self.stop_event,
            ):
                if self.stop_event.is_set():
                    break

                if event_type == "ADDED":
                    # New pod appeared
                    await self._handle_new_pod(
                        pod_info=pod_info,
                        since_seconds=since_seconds,
                        tail_lines=tail_lines,
                        on_new_container=on_new_container,
                    )

                elif event_type == "MODIFIED":
                    # Pod was modified - check for new containers
                    if pod_info.phase == "Running":
                        await self._handle_new_pod(
                            pod_info=pod_info,
                            since_seconds=since_seconds,
                            tail_lines=tail_lines,
                            on_new_container=on_new_container,
                        )

        except Exception as e:
            if not self.stop_event.is_set():
                logger.error(f"Watch error for namespace {namespace}: {e}")

    async def _handle_new_pod(
        self,
        pod_info: PodInfo,
        since_seconds: int,
        tail_lines: int,
        on_new_container: Callable[[ContainerInfo], None] | None = None,
    ) -> None:
        """Handle a newly discovered pod.

        Args:
            pod_info: Information about the new pod.
            since_seconds: Time window for logs.
            tail_lines: Initial lines to fetch.
            on_new_container: Callback for new containers.
        """
        if pod_info.phase != "Running":
            return

        for container in pod_info.get_all_containers():
            if container.unique_id not in self._active_containers:
                logger.info(
                    f"Discovered new container: {container.unique_id}"
                )

                if on_new_container:
                    on_new_container(container)

                await self._start_producer(
                    container=container,
                    follow=True,
                    since_seconds=since_seconds,
                    tail_lines=tail_lines,
                )

    async def _wait_for_completion(self, follow: bool) -> None:
        """Wait for producers to complete or stop event.

        Args:
            follow: Whether we're in follow mode.
        """
        if follow:
            # In follow mode, wait until stop event
            await self.stop_event.wait()
        else:
            # In snapshot mode, wait for all producers
            if self.producer_tasks:
                await asyncio.gather(*self.producer_tasks, return_exceptions=True)

    async def _cleanup(self) -> None:
        """Clean up all tasks and resources."""
        logger.debug("Cleaning up log manager...")

        # Signal shutdown
        self.stop_event.set()

        # Cancel producer tasks
        for task in self.producer_tasks:
            if not task.done():
                task.cancel()

        if self.producer_tasks:
            await asyncio.gather(*self.producer_tasks, return_exceptions=True)

        # Cancel watcher
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

        # Signal consumer to stop
        await self.queue.put(None)

        # Wait for consumer
        if self._consumer_task and not self._consumer_task.done():
            try:
                await asyncio.wait_for(self._consumer_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._consumer_task.cancel()
                try:
                    await self._consumer_task
                except asyncio.CancelledError:
                    pass

        logger.debug("Log manager cleanup complete")

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def handle_signal() -> None:
            logger.info("Received interrupt signal, shutting down...")
            self.stop_event.set()

        # Register for SIGINT and SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

    def request_shutdown(self) -> None:
        """Request a graceful shutdown of the manager."""
        self.stop_event.set()

