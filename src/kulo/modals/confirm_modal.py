"""Confirmation modal for KuLo TUI.

This module provides a simple confirmation dialog.
"""

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """Simple confirmation modal dialog.

    Returns True if confirmed, False if cancelled.
    """

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }

    ConfirmModal > Vertical {
        width: 50;
        height: auto;
        background: $surface;
        border: thick $warning;
        padding: 1 2;
    }

    ConfirmModal .title {
        text-align: center;
        text-style: bold;
        color: $warning;
        padding-bottom: 1;
    }

    ConfirmModal .message {
        text-align: center;
        padding-bottom: 1;
    }

    ConfirmModal Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }

    ConfirmModal Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(
        self,
        title: str = "Confirm",
        message: str = "Are you sure?",
        confirm_label: str = "Yes",
        cancel_label: str = "No",
        **kwargs,
    ) -> None:
        """Initialize the modal.

        Args:
            title: The dialog title.
            message: The confirmation message.
            confirm_label: Label for the confirm button.
            cancel_label: Label for the cancel button.
            **kwargs: Additional arguments passed to ModalScreen.
        """
        super().__init__(**kwargs)
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        with Vertical():
            yield Static(self._title, classes="title")
            yield Static(self._message, classes="message")

            with Horizontal():
                yield Button(self._confirm_label, variant="warning", id="confirm")
                yield Button(self._cancel_label, variant="default", id="cancel")

    @on(Button.Pressed, "#confirm")
    def on_confirm_pressed(self) -> None:
        """Handle confirm button press."""
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self) -> None:
        """Handle cancel button press."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """Handle confirm action."""
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Handle cancel action."""
        self.dismiss(False)

