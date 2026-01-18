"""Application state management for KuLo TUI.

This module provides a reactive state container that notifies widgets
when filters or pod states change, enabling dynamic UI updates.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kulo.models import PodInfo
from kulo.utils import ColorAssigner

if TYPE_CHECKING:
    from kulo.app import KuloApp


@dataclass
class AppState:
    """Reactive application state for the TUI.

    Holds all filter state and pod information. Changes to this state
    trigger UI updates and log stream re-subscription.

    Note: The TUI always operates in follow/streaming mode.

    Attributes:
        namespaces: List of active namespace filters.
        filter_pattern: Regex pattern for filtering/including pods.
        exclude_pattern: Regex pattern for excluding pods.
        label_selector: Kubernetes label selector string.
        active_pods: Map of pod names to enabled state.
        pods_info: List of discovered PodInfo objects.
        color_assigner: ColorAssigner for deterministic pod colors.
        since_seconds: Time window for log retrieval.
        tail_lines: Number of initial lines to fetch.
        max_containers: Maximum concurrent container streams.
        is_paused: Whether streaming is currently paused.
        no_color_logs: Whether to disable log message colorization.
    """

    namespaces: list[str] = field(default_factory=list)
    filter_pattern: str = ""
    exclude_pattern: str = ""
    label_selector: str = ""
    active_containers: dict[str, bool] = field(default_factory=dict)
    pods_info: list[PodInfo] = field(default_factory=list)
    color_assigner: ColorAssigner = field(default_factory=ColorAssigner)
    since_seconds: int = 600
    tail_lines: int = 25
    max_containers: int = 10
    is_paused: bool = False
    no_color_logs: bool = False
    theme: str = "dark"

    def update_pods(self, pods: list[PodInfo]) -> None:
        """Update the pods list and initialize active states.

        Args:
            pods: List of discovered pods.
        """
        self.pods_info = pods

        # Initialize color assignments
        pod_names = [pod.name for pod in pods]
        self.color_assigner.initialize(pod_names)

        # distinct container IDs in current pods
        current_container_ids = set()

        for pod in pods:
            for container in pod.get_all_containers():
                cid = container.unique_id
                current_container_ids.add(cid)
                # Initialize new containers as active
                if cid not in self.active_containers:
                    self.active_containers[cid] = True

        # Remove containers that no longer exist
        self.active_containers = {
            cid: enabled
            for cid, enabled in self.active_containers.items()
            if cid in current_container_ids
        }

    def toggle_container(self, namespace: str, pod_name: str, container_name: str) -> bool:
         """Toggle the active state of a container.

         Args:
             namespace: The namespace.
             pod_name: The name of the pod.
             container_name: The name of the container.

         Returns:
             The new state of the container.
         """
         unique_id = f"{namespace}/{pod_name}/{container_name}"
         if unique_id in self.active_containers:
             self.active_containers[unique_id] = not self.active_containers[unique_id]
             return self.active_containers[unique_id]
         return False

    def is_container_active(self, namespace: str, pod_name: str, container_name: str) -> bool:
        """Check if a container is active.

        Args:
            namespace: The namespace.
            pod_name: The name of the pod.
            container_name: The name of the container.

        Returns:
            True if the container is active.
        """
        unique_id = f"{namespace}/{pod_name}/{container_name}"
        return self.active_containers.get(unique_id, True)

    def get_pod_color(self, pod_name: str) -> str:
        """Get the color for a pod.

        Args:
            pod_name: The name of the pod.

        Returns:
            A Rich-compatible color string.
        """
        return self.color_assigner.get_color(pod_name, self.theme)

    def set_all_containers_active(self, active: bool) -> None:
        """Set all containers to active or inactive.

        Args:
            active: Whether to activate or deactivate all containers.
        """
        for cid in self.active_containers:
            self.active_containers[cid] = active

    def copy_with(
        self,
        namespaces: list[str] | None = None,
        filter_pattern: str | None = None,
        exclude_pattern: str | None = None,
        label_selector: str | None = None,
    ) -> "AppState":
        """Create a copy of this state with optional overrides.

        Args:
            namespaces: New namespace list, or None to keep current.
            filter_pattern: New filter pattern, or None to keep current.
            exclude_pattern: New exclude pattern, or None to keep current.
            label_selector: New label selector, or None to keep current.

        Returns:
            A new AppState with the specified changes.
        """
        new_state = AppState(
            namespaces=namespaces if namespaces is not None else self.namespaces.copy(),
            filter_pattern=filter_pattern if filter_pattern is not None else self.filter_pattern,
            exclude_pattern=exclude_pattern if exclude_pattern is not None else self.exclude_pattern,
            label_selector=label_selector if label_selector is not None else self.label_selector,
            # active_containers logic handled by init default then copying
            pods_info=self.pods_info.copy(),
            color_assigner=self.color_assigner,
            since_seconds=self.since_seconds,
            tail_lines=self.tail_lines,
            max_containers=self.max_containers,
            no_color_logs=self.no_color_logs,
            theme=self.theme,
        )
        new_state.active_containers = self.active_containers.copy()
        return new_state
