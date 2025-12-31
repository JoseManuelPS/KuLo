"""Filter modal for KuLo TUI.

This module provides a reusable modal dialog for regex filter patterns
(include/exclude pod filters and label selectors).
"""

import re

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class FilterChanged(Message):
    """Message sent when a filter is changed."""

    def __init__(self, filter_type: str, pattern: str) -> None:
        """Initialize the message.

        Args:
            filter_type: The type of filter (include, exclude, label).
            pattern: The new filter pattern.
        """
        super().__init__()
        self.filter_type = filter_type
        self.pattern = pattern


class FilterModal(ModalScreen[str | None]):
    """Modal dialog for regex filter patterns.

    Reusable for include, exclude, and label selector filters.
    Provides real-time regex validation.
    """

    DEFAULT_CSS = """
    FilterModal {
        align: center middle;
    }

    FilterModal > Vertical {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    FilterModal .title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding-bottom: 1;
    }

    FilterModal .help-text {
        color: $text-muted;
        padding-bottom: 1;
    }

    FilterModal Input {
        width: 100%;
        margin-bottom: 1;
    }

    FilterModal .current {
        color: $text-muted;
        text-style: italic;
        padding-bottom: 1;
    }

    FilterModal .error {
        color: $error;
        padding-bottom: 1;
    }

    FilterModal .valid {
        color: $success;
        padding-bottom: 1;
    }

    FilterModal Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }

    FilterModal Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Apply"),
    ]

    # Filter type configurations
    FILTER_CONFIGS = {
        "include": {
            "title": "Include Filter",
            "help": (
                "Enter comma-separated regex patterns to include pods.\n"
                "Only pods matching at least one pattern will be shown.\n"
                "Examples: frontend-.*, api-server, worker-[0-9]+"
            ),
            "placeholder": "pattern1, pattern2, ...",
            "is_regex": True,
        },
        "exclude": {
            "title": "Exclude Filter",
            "help": (
                "Enter comma-separated regex patterns to exclude pods.\n"
                "Pods matching any pattern will be hidden.\n"
                "Examples: test-.*, debug-.*, .*-canary"
            ),
            "placeholder": "pattern1, pattern2, ...",
            "is_regex": True,
        },
        "label": {
            "title": "Label Selector",
            "help": (
                "Enter a Kubernetes label selector for server-side filtering.\n"
                "Examples: app=web, tier=frontend, env!=prod"
            ),
            "placeholder": "app=web, tier=frontend",
            "is_regex": False,
        },
    }

    def __init__(
        self,
        filter_type: str = "include",
        current_value: str = "",
        **kwargs,
    ) -> None:
        """Initialize the modal.

        Args:
            filter_type: Type of filter (include, exclude, label).
            current_value: Current filter value.
            **kwargs: Additional arguments passed to ModalScreen.
        """
        super().__init__(**kwargs)
        self._filter_type = filter_type
        self._current = current_value
        self._config = self.FILTER_CONFIGS.get(filter_type, self.FILTER_CONFIGS["include"])
        self._is_valid = True
        self._error_message = ""

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        with Vertical():
            yield Static(self._config["title"], classes="title")
            yield Static(self._config["help"], classes="help-text")

            if self._current:
                yield Static(f"Current: {self._current}", classes="current")

            yield Input(
                value=self._current,
                placeholder=self._config["placeholder"],
                id="filter-input",
            )

            yield Static("", id="validation-status")

            with Horizontal():
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Clear", variant="warning", id="clear")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#filter-input", Input).focus()

    @on(Input.Changed, "#filter-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        """Validate input as user types.

        Args:
            event: The input changed event.
        """
        self._validate_input(event.value)

    def _validate_input(self, value: str) -> None:
        """Validate the input value.

        Args:
            value: The input value to validate.
        """
        status_widget = self.query_one("#validation-status", Static)

        if not value.strip():
            self._is_valid = True
            status_widget.update("")
            status_widget.remove_class("error", "valid")
            return

        if not self._config["is_regex"]:
            # For label selectors, just check basic format
            self._is_valid = True
            status_widget.update("")
            return

        # Validate regex patterns
        patterns = [p.strip() for p in value.split(",") if p.strip()]
        errors = []

        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"'{pattern}': {e}")

        if errors:
            self._is_valid = False
            self._error_message = "; ".join(errors)
            status_widget.update(f"Invalid: {self._error_message}")
            status_widget.remove_class("valid")
            status_widget.add_class("error")
        else:
            self._is_valid = True
            status_widget.update(f"Valid: {len(patterns)} pattern(s)")
            status_widget.remove_class("error")
            status_widget.add_class("valid")

    @on(Button.Pressed, "#apply")
    def on_apply(self) -> None:
        """Handle apply button press."""
        if self._is_valid:
            self._submit()

    @on(Button.Pressed, "#clear")
    def on_clear(self) -> None:
        """Handle clear button press."""
        self.dismiss("")

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Handle escape key."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Handle enter key."""
        if self._is_valid:
            self._submit()

    def _submit(self) -> None:
        """Submit the current input value."""
        input_widget = self.query_one("#filter-input", Input)
        value = input_widget.value.strip()
        self.dismiss(value)

