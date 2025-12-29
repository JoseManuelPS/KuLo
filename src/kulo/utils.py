"""Utility functions for KuLo.

This module provides helper functions for:
- Time duration parsing (e.g., '10s', '5m', '1h' to seconds)
- Regex pattern compilation and matching
- Consistent color assignment for pods
- Input validation
"""

import re
from functools import lru_cache


# Time unit multipliers (in seconds)
TIME_UNITS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}

# Duration pattern: number followed by unit (s, m, h, d)
DURATION_PATTERN = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)

# Rich-compatible color palette for pod differentiation
# These colors are chosen for good contrast and visibility in terminals
POD_COLOR_PALETTE: list[str] = [
    "cyan",
    "magenta",
    "yellow",
    "green",
    "blue",
    "red",
    "bright_cyan",
    "bright_magenta",
    "bright_yellow",
    "bright_green",
    "bright_blue",
    "bright_red",
    "dark_orange",
    "purple",
    "gold1",
    "spring_green1",
    "deep_sky_blue1",
    "hot_pink",
    "medium_purple1",
    "chartreuse1",
]

# Log level color mapping
LOG_LEVEL_COLORS: dict[str, str] = {
    "debug": "dim",
    "info": "green",
    "warn": "yellow",
    "warning": "yellow",
    "error": "red",
    "fatal": "bold red",
    "critical": "bold red",
    "panic": "bold red",
    "trace": "dim cyan",
}

# Common JSON field names for log level
LOG_LEVEL_FIELDS: list[str] = ["level", "loglevel", "log_level", "severity", "lvl"]

# Common JSON field names for message
MESSAGE_FIELDS: list[str] = ["msg", "message", "text", "body", "log"]


class DurationParseError(ValueError):
    """Raised when a duration string cannot be parsed."""

    pass


def parse_duration(duration_str: str) -> int:
    """Parse a human-readable duration string into seconds.

    Supports formats like '10s', '5m', '1h', '2d' (case-insensitive).

    Args:
        duration_str: The duration string to parse (e.g., '10m', '1h').

    Returns:
        The duration in seconds as an integer.

    Raises:
        DurationParseError: If the duration string is invalid.

    Examples:
        >>> parse_duration('30s')
        30
        >>> parse_duration('5m')
        300
        >>> parse_duration('1h')
        3600
        >>> parse_duration('2d')
        172800
    """
    if not duration_str:
        raise DurationParseError("Duration string cannot be empty")

    duration_str = duration_str.strip().lower()
    match = DURATION_PATTERN.match(duration_str)

    if not match:
        raise DurationParseError(
            f"Invalid duration format: '{duration_str}'. "
            f"Expected format: <number><unit> where unit is s, m, h, or d. "
            f"Examples: '30s', '5m', '1h', '2d'"
        )

    value = int(match.group(1))
    unit = match.group(2)

    if value <= 0:
        raise DurationParseError(f"Duration must be positive, got: {value}")

    return value * TIME_UNITS[unit]


def compile_patterns(patterns: str | None) -> list[re.Pattern[str]]:
    """Compile comma-separated regex patterns into a list of compiled patterns.

    Patterns are compiled with case-insensitive matching by default.

    Args:
        patterns: Comma-separated regex patterns, or None.

    Returns:
        List of compiled regex patterns (empty if patterns is None or empty).

    Raises:
        ValueError: If any pattern is an invalid regex.

    Examples:
        >>> patterns = compile_patterns('frontend-.*,backend-.*')
        >>> len(patterns)
        2
        >>> compile_patterns(None)
        []
    """
    if not patterns:
        return []

    compiled: list[re.Pattern[str]] = []

    for pattern in patterns.split(","):
        pattern = pattern.strip()
        if not pattern:
            continue

        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e

    return compiled


def matches_any(name: str, patterns: list[re.Pattern[str]]) -> bool:
    """Check if a name matches any of the given regex patterns.

    Args:
        name: The string to check.
        patterns: List of compiled regex patterns.

    Returns:
        True if the name matches at least one pattern, False otherwise.
        Returns False if patterns list is empty.

    Examples:
        >>> patterns = compile_patterns('frontend-.*,backend-.*')
        >>> matches_any('frontend-abc', patterns)
        True
        >>> matches_any('database-xyz', patterns)
        False
    """
    if not patterns:
        return False

    return any(pattern.search(name) for pattern in patterns)


@lru_cache(maxsize=256)
def get_color_for_pod(pod_name: str, palette_size: int | None = None) -> str:
    """Get a consistent color for a pod based on its name.

    Uses a hash of the pod name to select a color from the palette,
    ensuring the same pod always gets the same color.

    Args:
        pod_name: The name of the pod.
        palette_size: Optional size limit for the palette (for testing).

    Returns:
        A Rich-compatible color string.

    Examples:
        >>> color1 = get_color_for_pod('my-pod-abc')
        >>> color2 = get_color_for_pod('my-pod-abc')
        >>> color1 == color2
        True
    """
    palette = POD_COLOR_PALETTE
    if palette_size is not None:
        palette = palette[:palette_size]

    # Use hash for consistent color assignment
    color_index = hash(pod_name) % len(palette)
    return palette[color_index]


def get_log_level_color(level: str | None) -> str:
    """Get the color for a log level.

    Args:
        level: The log level string (case-insensitive).

    Returns:
        A Rich-compatible color/style string.

    Examples:
        >>> get_log_level_color('INFO')
        'green'
        >>> get_log_level_color('error')
        'red'
        >>> get_log_level_color(None)
        'default'
    """
    if not level:
        return "default"

    return LOG_LEVEL_COLORS.get(level.lower(), "default")


def extract_log_level(json_data: dict) -> str | None:
    """Extract the log level from a JSON log entry.

    Checks common field names for log level information.

    Args:
        json_data: Parsed JSON log data.

    Returns:
        The log level string if found, None otherwise.

    Examples:
        >>> extract_log_level({'level': 'INFO', 'msg': 'hello'})
        'INFO'
        >>> extract_log_level({'severity': 'ERROR'})
        'ERROR'
    """
    for field in LOG_LEVEL_FIELDS:
        if field in json_data:
            value = json_data[field]
            if isinstance(value, str):
                return value
    return None


def extract_message(json_data: dict) -> str | None:
    """Extract the main message from a JSON log entry.

    Checks common field names for the log message.

    Args:
        json_data: Parsed JSON log data.

    Returns:
        The message string if found, None otherwise.

    Examples:
        >>> extract_message({'msg': 'Hello world', 'level': 'INFO'})
        'Hello world'
        >>> extract_message({'message': 'Request received'})
        'Request received'
    """
    for field in MESSAGE_FIELDS:
        if field in json_data:
            value = json_data[field]
            if isinstance(value, str):
                return value
    return None


def parse_namespaces(namespace_arg: str | None) -> list[str]:
    """Parse comma-separated namespace argument into a list.

    Args:
        namespace_arg: Comma-separated namespace string, or None.

    Returns:
        List of namespace strings (empty list if None or empty).

    Examples:
        >>> parse_namespaces('frontend,backend')
        ['frontend', 'backend']
        >>> parse_namespaces(None)
        []
    """
    if not namespace_arg:
        return []

    namespaces = [ns.strip() for ns in namespace_arg.split(",")]
    return [ns for ns in namespaces if ns]


def validate_label_selector(selector: str | None) -> str | None:
    """Validate a Kubernetes label selector format.

    Basic validation to catch common errors before API call.

    Args:
        selector: The label selector string (e.g., 'app=frontend,tier=backend').

    Returns:
        The validated selector string, or None if empty.

    Raises:
        ValueError: If the selector format is obviously invalid.

    Examples:
        >>> validate_label_selector('app=frontend')
        'app=frontend'
        >>> validate_label_selector('app=frontend,tier=backend')
        'app=frontend,tier=backend'
    """
    if not selector:
        return None

    selector = selector.strip()
    if not selector:
        return None

    # Basic validation: each part should have key=value or key!=value or key format
    # Full validation is done by the K8s API
    label_pattern = re.compile(r"^[a-zA-Z0-9_./-]+(=[a-zA-Z0-9_./-]+|!=[a-zA-Z0-9_./-]+)?$")

    for part in selector.split(","):
        part = part.strip()
        if not part:
            continue
        # Handle 'in' and 'notin' operators
        if " in " in part.lower() or " notin " in part.lower():
            continue
        if not label_pattern.match(part):
            raise ValueError(
                f"Invalid label selector part: '{part}'. "
                f"Expected format: key=value, key!=value, or key"
            )

    return selector


def calculate_backoff(retry_count: int, base: float = 1.0, max_backoff: float = 60.0) -> float:
    """Calculate exponential backoff delay.

    Args:
        retry_count: The current retry attempt number (0-indexed).
        base: The base delay in seconds.
        max_backoff: The maximum delay in seconds.

    Returns:
        The delay in seconds before the next retry.

    Examples:
        >>> calculate_backoff(0)
        1.0
        >>> calculate_backoff(1)
        2.0
        >>> calculate_backoff(5)
        32.0
        >>> calculate_backoff(10)  # Capped at max
        60.0
    """
    delay = base * (2**retry_count)
    return min(delay, max_backoff)


# Regex metacharacters that indicate a pattern is a regex
REGEX_METACHARACTERS = re.compile(r"[.*+?^${}()|[\]\\]")


def is_regex_pattern(pattern: str) -> bool:
    """Check if a string contains regex metacharacters.

    Args:
        pattern: The string to check.

    Returns:
        True if the string appears to be a regex pattern.

    Examples:
        >>> is_regex_pattern('dev-team1')
        False
        >>> is_regex_pattern('dev-.*')
        True
        >>> is_regex_pattern('^prod$')
        True
    """
    return bool(REGEX_METACHARACTERS.search(pattern))


class ColorAssigner:
    """Deterministic color assigner that avoids repetition.

    Assigns colors to pods in a deterministic way based on sorted pod names,
    ensuring:
    - Same pods always get the same colors across executions
    - No color repetition until the palette is exhausted
    - Dynamic pods get the next available color

    Attributes:
        palette: The color palette to use.
        _assignments: Map of pod names to assigned colors.
        _used_colors: Set of colors currently in use.
        _next_index: Index of the next color to assign.

    Example:
        assigner = ColorAssigner()
        assigner.initialize(['pod-a', 'pod-b', 'pod-c'])
        color = assigner.get_color('pod-a')  # Returns first color
    """

    def __init__(self, palette: list[str] | None = None) -> None:
        """Initialize the color assigner.

        Args:
            palette: Optional custom color palette. Uses POD_COLOR_PALETTE if None.
        """
        self.palette = palette if palette is not None else POD_COLOR_PALETTE.copy()
        self._assignments: dict[str, str] = {}
        self._used_indices: set[int] = set()
        self._next_index: int = 0

    def initialize(self, pod_names: list[str]) -> None:
        """Initialize color assignments for a known set of pods.

        Sorts pods alphabetically and assigns colors in order for
        deterministic results across executions.

        Args:
            pod_names: List of pod names to assign colors to.

        Example:
            assigner = ColorAssigner()
            assigner.initialize(['pod-c', 'pod-a', 'pod-b'])
            # pod-a gets color[0], pod-b gets color[1], pod-c gets color[2]
        """
        self._assignments.clear()
        self._used_indices.clear()
        self._next_index = 0

        # Sort pods for deterministic ordering
        sorted_pods = sorted(pod_names)

        for pod_name in sorted_pods:
            self._assign_next_color(pod_name)

    def get_color(self, pod_name: str) -> str:
        """Get the color for a pod, assigning one if needed.

        Args:
            pod_name: The name of the pod.

        Returns:
            A Rich-compatible color string.

        Example:
            color = assigner.get_color('my-pod')
        """
        if pod_name not in self._assignments:
            self._assign_next_color(pod_name)

        return self._assignments[pod_name]

    def _assign_next_color(self, pod_name: str) -> str:
        """Assign the next available color to a pod.

        Args:
            pod_name: The name of the pod.

        Returns:
            The assigned color.
        """
        if pod_name in self._assignments:
            return self._assignments[pod_name]

        # Find the next unused color index
        color_index = self._next_index % len(self.palette)

        # If we've cycled through all colors, just use the next in sequence
        # This ensures deterministic behavior even when palette is exhausted
        if self._next_index < len(self.palette):
            # Still have unused colors
            self._used_indices.add(color_index)
        # else: we're cycling, which is fine

        color = self.palette[color_index]
        self._assignments[pod_name] = color
        self._next_index += 1

        return color

    def update_for_new_pod(self, pod_name: str) -> str:
        """Handle a dynamically discovered pod.

        Assigns the next available color without disrupting existing assignments.

        Args:
            pod_name: The name of the new pod.

        Returns:
            The assigned color.
        """
        return self.get_color(pod_name)

    @property
    def assigned_count(self) -> int:
        """Return the number of pods with assigned colors."""
        return len(self._assignments)

    def get_all_assignments(self) -> dict[str, str]:
        """Return a copy of all current color assignments.

        Returns:
            Dictionary mapping pod names to colors.
        """
        return self._assignments.copy()

