"""Data models for KuLo.

This module contains all the dataclasses used throughout the application
for type-safe data passing between components.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


ContainerType = Literal["init", "regular", "ephemeral"]


@dataclass(frozen=True, slots=True)
class ContainerInfo:
    """Information about a specific container within a pod.

    Attributes:
        namespace: The Kubernetes namespace containing the pod.
        pod_name: The name of the pod.
        container_name: The name of the container.
        container_type: The type of container (init, regular, or ephemeral).
    """

    namespace: str
    pod_name: str
    container_name: str
    container_type: ContainerType

    @property
    def unique_id(self) -> str:
        """Return a unique identifier for this container."""
        return f"{self.namespace}/{self.pod_name}/{self.container_name}"


@dataclass(frozen=True, slots=True)
class PodInfo:
    """Information about a Kubernetes pod and its containers.

    Attributes:
        namespace: The Kubernetes namespace containing the pod.
        name: The name of the pod.
        phase: The current phase of the pod (Running, Pending, etc.).
        containers: List of regular container names.
        init_containers: List of init container names.
        ephemeral_containers: List of ephemeral container names.
        labels: Pod labels as a dictionary.
    """

    namespace: str
    name: str
    phase: str
    containers: list[str] = field(default_factory=list)
    init_containers: list[str] = field(default_factory=list)
    ephemeral_containers: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    def get_all_containers(
        self,
        exclude_init: bool = False,
        exclude_ephemeral: bool = False,
    ) -> list[ContainerInfo]:
        """Get all containers as ContainerInfo objects.

        Args:
            exclude_init: If True, exclude init containers.
            exclude_ephemeral: If True, exclude ephemeral containers.

        Returns:
            List of ContainerInfo objects for all requested container types.
        """
        result: list[ContainerInfo] = []

        # Regular containers are always included
        for name in self.containers:
            result.append(
                ContainerInfo(
                    namespace=self.namespace,
                    pod_name=self.name,
                    container_name=name,
                    container_type="regular",
                )
            )

        # Init containers (optional)
        if not exclude_init:
            for name in self.init_containers:
                result.append(
                    ContainerInfo(
                        namespace=self.namespace,
                        pod_name=self.name,
                        container_name=name,
                        container_type="init",
                    )
                )

        # Ephemeral containers (optional)
        if not exclude_ephemeral:
            for name in self.ephemeral_containers:
                result.append(
                    ContainerInfo(
                        namespace=self.namespace,
                        pod_name=self.name,
                        container_name=name,
                        container_type="ephemeral",
                    )
                )

        return result


@dataclass(slots=True)
class LogEntry:
    """A single log entry from a container.

    Attributes:
        timestamp: When the log entry was received.
        namespace: The Kubernetes namespace.
        pod_name: The name of the pod.
        container_name: The name of the container.
        message: The raw log message.
        is_json: Whether the message is valid JSON.
        log_level: Extracted log level (INFO, WARN, ERROR, DEBUG, etc.).
        json_data: Parsed JSON data if is_json is True.
    """

    timestamp: datetime
    namespace: str
    pod_name: str
    container_name: str
    message: str
    is_json: bool = False
    log_level: str | None = None
    json_data: dict | None = None

    @property
    def unique_id(self) -> str:
        """Return a unique identifier for the source container."""
        return f"{self.namespace}/{self.pod_name}/{self.container_name}"


@dataclass(slots=True)
class StreamContext:
    """Context for a log stream, used for tracking and reconnection.

    Attributes:
        container: The container being streamed.
        since_seconds: Time window for log retrieval.
        follow: Whether to follow the stream.
        tail_lines: Number of initial lines to retrieve.
        retry_count: Current retry attempt count.
        last_timestamp: Timestamp of the last received log line.
    """

    container: ContainerInfo
    since_seconds: int
    follow: bool
    tail_lines: int
    retry_count: int = 0
    last_timestamp: datetime | None = None

    def reset_retries(self) -> None:
        """Reset the retry counter after a successful connection."""
        self.retry_count = 0

    def increment_retries(self) -> int:
        """Increment and return the retry counter."""
        self.retry_count += 1
        return self.retry_count

