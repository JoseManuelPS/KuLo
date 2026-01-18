"""Utility functions for KuLo.

This module provides helper functions for:
- Time duration parsing (e.g., '10s', '5m', '1h' to seconds)
- Regex pattern compilation and matching
- Consistent color assignment for pods
- Input validation
"""

import re


# Time unit multipliers (in seconds)
TIME_UNITS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}

# Duration pattern: number followed by unit (s, m, h, d)
DURATION_PATTERN = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)

# Kelly's 22 colors of maximum contrast (excluding white/black for terminal compatibility)
# Source: Kenneth Kelly, "Twenty-two colors of maximum contrast", Color Engineering, 1965
# These colors are scientifically optimized for maximum perceptual distinction.
# Optimized palette for dark backgrounds (High Luminance, Neon/Pastel)
# Rule: Luminance > 60%, no dark/muddy colors.
POD_COLOR_PALETTE_DARK: list[str] = [
    "#FFD700",  # Gold / Bright Yellow
    "#00FFFF",  # Cyan
    "#FF00FF",  # Magenta
    "#00FF00",  # Lime
    "#FF69B4",  # Hot Pink
    "#FFA500",  # Orange
    "#BA55D3",  # Medium Orchid
    "#7FFFD4",  # Aquamarine
    "#FF6347",  # Tomato (Bright Red-Orange)
    "#40E0D0",  # Turquoise
    "#9370DB",  # Medium Purple
    "#F0E68C",  # Khaki
    "#ADFF2F",  # Green Yellow
    "#FFB6C1",  # Light Pink
    "#87CEEB",  # Sky Blue
]

# Optimized palette for light backgrounds (Low Luminance, Deep/Saturated)
# Rule: Luminance < 40%, no light/washed-out colors.
POD_COLOR_PALETTE_LIGHT: list[str] = [
    "#C71585",  # Medium Violet Red
    "#000080",  # Navy
    "#006400",  # Dark Green
    "#8B0000",  # Dark Red
    "#4B0082",  # Indigo
    "#8B4513",  # Saddle Brown
    "#2F4F4F",  # Dark Slate Gray
    "#800080",  # Purple
    "#008B8B",  # Dark Cyan
    "#A52A2A",  # Brown
    "#556B2F",  # Dark Olive Green
    "#B22222",  # Firebrick
    "#00008B",  # Dark Blue
    "#800000",  # Maroon
    "#20B2AA",  # Light Sea Green (Darker variant)
]

# Default palette aliases
POD_COLOR_PALETTE = POD_COLOR_PALETTE_DARK

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
    """Color assigner using Kelly's palette of maximum contrast.

    Assigns colors to pods in arrival order, ensuring:
    - Colors are assigned sequentially from Kelly's scientifically optimized palette
    - No color repetition until the palette (20 colors) is exhausted
    - When palette is exhausted, colors cycle from the beginning
    - Dynamic pods get the next available color

    Attributes:
        _assignment_indices: Map of pod names to color indices.
        _used_indices: Set of color indices currently in use.
        _next_index: Index of the next color to assign.
    """

    def __init__(self) -> None:
        """Initialize the color assigner."""
        self._assignment_indices: dict[str, int] = {}
        self._used_indices: set[int] = set()
        self._next_index: int = 0

    def initialize(self, pod_names: list[str]) -> None:
        """Initialize color assignments for a known set of pods.

        Assigns colors in arrival order. When the same pods exist across
        executions, they will get consistent colors as long as they arrive
        in the same order (which is typical for Kubernetes API responses).

        Args:
            pod_names: List of pod names to assign colors to (in arrival order).
        """
        self._assignment_indices.clear()
        self._used_indices.clear()
        self._next_index = 0

        # Assign colors in arrival order (no sorting)
        for pod_name in pod_names:
            self._assign_next_color(pod_name)

    def get_color(self, pod_name: str, theme: str = "dark") -> str:
        """Get the color for a pod, assigning one if needed.

        Args:
            pod_name: The name of the pod.
            theme: The theme name ("dark" or "light").

        Returns:
            A Rich-compatible color string.
        """
        if pod_name not in self._assignment_indices:
            self._assign_next_color(pod_name)

        index = self._assignment_indices[pod_name]

        if theme == "light":
            palette = POD_COLOR_PALETTE_LIGHT
        else:
            palette = POD_COLOR_PALETTE_DARK

        # Use modulo safe access in case palettes differ in length (though they shouldn't)
        return palette[index % len(palette)]

    def _assign_next_color(self, pod_name: str) -> None:
        """Assign the next available color index to a pod.

        Args:
            pod_name: The name of the pod.
        """
        if pod_name in self._assignment_indices:
            return

        # Find the next unused color index (based on default palette size)
        base_palette_len = len(POD_COLOR_PALETTE_DARK)
        color_index = self._next_index % base_palette_len

        # If we've cycled through all colors, just use the next in sequence
        # This ensures deterministic behavior even when palette is exhausted
        if self._next_index < base_palette_len:
            # Still have unused colors
            self._used_indices.add(color_index)
        # else: we're cycling, which is fine

        self._assignment_indices[pod_name] = color_index
        self._next_index += 1

    def update_for_new_pod(self, pod_name: str) -> str:
        """Handle a dynamically discovered pod.

        Assigns the next available color without disrupting existing assignments.

        Args:
            pod_name: The name of the new pod.

        Returns:
            The assigned color (using default theme, typically not used by caller).
        """
        # We return default dark theme color for compatibility,
        # but the meaningful change is the internal state update.
        return self.get_color(pod_name)

    @property
    def assigned_count(self) -> int:
        """Return the number of pods with assigned colors."""
        return len(self._assignment_indices)

    def get_all_assignments(self, theme: str = "dark") -> dict[str, str]:
        """Return a copy of all current color assignments for a theme.

        Args:
            theme: The theme to get colors for.

        Returns:
            Dictionary mapping pod names to colors.
        """
        result = {}
        for pod_name in self._assignment_indices:
            result[pod_name] = self.get_color(pod_name, theme)
        return result

