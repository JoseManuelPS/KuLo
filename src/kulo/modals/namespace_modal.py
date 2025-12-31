"""Namespace selection modal for KuLo TUI.

This module provides a modal dialog for changing namespace filters.
"""

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class NamespaceChanged(Message):
    """Message sent when namespaces are changed."""

    def __init__(self, namespaces: list[str]) -> None:
        """Initialize the message.

        Args:
            namespaces: The new list of namespaces.
        """
        super().__init__()
        self.namespaces = namespaces


class NamespaceModal(ModalScreen[list[str] | None]):
    """Modal dialog for namespace selection.

    Allows entering comma-separated namespaces or regex patterns.
    """

    DEFAULT_CSS = """
    NamespaceModal {
        align: center middle;
    }

    NamespaceModal > Vertical {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    NamespaceModal .title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding-bottom: 1;
    }

    NamespaceModal .help-text {
        color: $text-muted;
        padding-bottom: 1;
    }

    NamespaceModal Input {
        width: 100%;
        margin-bottom: 1;
    }

    NamespaceModal .current {
        color: $text-muted;
        text-style: italic;
        padding-bottom: 1;
    }

    NamespaceModal Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }

    NamespaceModal Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Apply"),
    ]

    def __init__(
        self,
        current_namespaces: list[str] | None = None,
        **kwargs,
    ) -> None:
        """Initialize the modal.

        Args:
            current_namespaces: Current namespace filter values.
            **kwargs: Additional arguments passed to ModalScreen.
        """
        super().__init__(**kwargs)
        self._current = current_namespaces or []

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        with Vertical():
            yield Static("Namespace Filter", classes="title")
            yield Static(
                "Enter comma-separated namespaces or regex patterns.\n"
                "Examples: default, frontend,backend, dev-.*",
                classes="help-text",
            )

            if self._current:
                yield Static(
                    f"Current: {', '.join(self._current)}",
                    classes="current",
                )

            yield Input(
                value=",".join(self._current),
                placeholder="namespace1, namespace2, pattern-.*",
                id="namespace-input",
            )

            with Horizontal():
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#namespace-input", Input).focus()

    @on(Button.Pressed, "#apply")
    def on_apply(self) -> None:
        """Handle apply button press."""
        self._submit()

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Handle escape key."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Handle enter key."""
        self._submit()

    def _submit(self) -> None:
        """Submit the current input value."""
        input_widget = self.query_one("#namespace-input", Input)
        value = input_widget.value.strip()

        if not value:
            # Empty input - use current context namespace
            self.dismiss([])
            return

        # Parse comma-separated namespaces
        namespaces = [ns.strip() for ns in value.split(",")]
        namespaces = [ns for ns in namespaces if ns]

        self.dismiss(namespaces)

