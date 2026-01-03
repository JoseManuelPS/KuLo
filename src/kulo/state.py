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
    active_pods: dict[str, bool] = field(default_factory=dict)
    pods_info: list[PodInfo] = field(default_factory=list)
    color_assigner: ColorAssigner = field(default_factory=ColorAssigner)
    since_seconds: int = 600
    tail_lines: int = 25
    max_containers: int = 10
    is_paused: bool = False
    no_color_logs: bool = False

    def update_pods(self, pods: list[PodInfo]) -> None:
        """Update the pods list and initialize active states.

        Args:
            pods: List of discovered pods.
        """
        self.pods_info = pods

        # Initialize color assignments
        pod_names = [pod.name for pod in pods]
        self.color_assigner.initialize(pod_names)

        # Set all pods as active by default, preserving existing states
        for pod in pods:
            if pod.name not in self.active_pods:
                self.active_pods[pod.name] = True

        # Remove pods that no longer exist
        current_names = {pod.name for pod in pods}
        self.active_pods = {
            name: enabled
            for name, enabled in self.active_pods.items()
            if name in current_names
        }

    def toggle_pod(self, pod_name: str) -> bool:
        """Toggle the active state of a pod.

        Args:
            pod_name: The name of the pod to toggle.

        Returns:
            The new state of the pod.
        """
        if pod_name in self.active_pods:
            self.active_pods[pod_name] = not self.active_pods[pod_name]
            return self.active_pods[pod_name]
        return False

    def is_pod_active(self, pod_name: str) -> bool:
        """Check if a pod is active.

        Args:
            pod_name: The name of the pod.

        Returns:
            True if the pod is active, False otherwise.
        """
        return self.active_pods.get(pod_name, True)

    def get_pod_color(self, pod_name: str) -> str:
        """Get the color for a pod.

        Args:
            pod_name: The name of the pod.

        Returns:
            A Rich-compatible color string.
        """
        return self.color_assigner.get_color(pod_name)

    def get_active_pods(self) -> list[PodInfo]:
        """Get the list of active pods.

        Returns:
            List of PodInfo for active pods only.
        """
        return [pod for pod in self.pods_info if self.is_pod_active(pod.name)]

    def set_all_pods_active(self, active: bool) -> None:
        """Set all pods to active or inactive.

        Args:
            active: Whether to activate or deactivate all pods.
        """
        for pod_name in self.active_pods:
            self.active_pods[pod_name] = active

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
        return AppState(
            namespaces=namespaces if namespaces is not None else self.namespaces.copy(),
            filter_pattern=filter_pattern if filter_pattern is not None else self.filter_pattern,
            exclude_pattern=exclude_pattern if exclude_pattern is not None else self.exclude_pattern,
            label_selector=label_selector if label_selector is not None else self.label_selector,
            active_pods=self.active_pods.copy(),
            pods_info=self.pods_info.copy(),
            color_assigner=self.color_assigner,
            since_seconds=self.since_seconds,
            tail_lines=self.tail_lines,
            max_containers=self.max_containers,
            no_color_logs=self.no_color_logs,
        )

