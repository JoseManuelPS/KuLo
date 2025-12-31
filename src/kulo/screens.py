"""Screen definitions for KuLo TUI.

This module provides screen layouts for the KuLo TUI application.
Currently provides the main screen with a three-panel layout.
"""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from kulo.state import AppState
from kulo.widgets import HelpBar, LogPanel, PodLegend
from kulo.widgets.help_bar import ExpandedHelp


class MainScreen(Screen):
    """Main application screen with log viewer and pod legend.

    Provides a three-panel layout:
    - Left: Log panel (main content area)
    - Right: Pod legend (toggleable)
    - Bottom: Help bar with keybindings
    """

    CSS = """
    MainScreen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 30;
        grid-rows: 1fr auto;
    }

    #log-panel {
        column-span: 1;
        row-span: 1;
    }

    #pod-legend {
        column-span: 1;
        row-span: 1;
    }

    #help-bar {
        column-span: 2;
        row-span: 1;
    }

    #expanded-help {
        layer: overlay;
    }

    .hidden {
        display: none;
    }
    """

    def __init__(
        self,
        state: AppState,
        **kwargs,
    ) -> None:
        """Initialize the main screen.

        Args:
            state: The application state.
            **kwargs: Additional arguments passed to Screen.
        """
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        """Compose the screen layout."""
        yield Header()

        yield LogPanel(state=self._state, id="log-panel")
        yield PodLegend(state=self._state, id="pod-legend")
        yield HelpBar(id="help-bar")
        yield ExpandedHelp(id="expanded-help", classes="hidden")

        yield Footer()

    def on_mount(self) -> None:
        """Set up the screen on mount."""
        # Ensure widgets have state reference
        log_panel = self.query_one("#log-panel", LogPanel)
        pod_legend = self.query_one("#pod-legend", PodLegend)

        log_panel.set_state(self._state)
        pod_legend.set_state(self._state)


class LoadingScreen(Screen):
    """Loading screen shown while connecting to Kubernetes."""

    CSS = """
    LoadingScreen {
        align: center middle;
    }

    LoadingScreen Static {
        width: auto;
        height: auto;
        padding: 2 4;
        background: $surface;
        border: thick $primary;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the loading screen."""
        yield Static("Connecting to Kubernetes cluster...")


class ErrorScreen(Screen):
    """Error screen for displaying fatal errors."""

    CSS = """
    ErrorScreen {
        align: center middle;
    }

    ErrorScreen > Vertical {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $error;
        padding: 2 4;
    }

    ErrorScreen .title {
        text-align: center;
        text-style: bold;
        color: $error;
        padding-bottom: 1;
    }

    ErrorScreen .message {
        text-align: center;
        padding-bottom: 1;
    }

    ErrorScreen Button {
        width: 100%;
    }
    """

    def __init__(
        self,
        error_message: str,
        **kwargs,
    ) -> None:
        """Initialize the error screen.

        Args:
            error_message: The error message to display.
            **kwargs: Additional arguments passed to Screen.
        """
        super().__init__(**kwargs)
        self._error_message = error_message

    def compose(self) -> ComposeResult:
        """Compose the error screen."""
        with Vertical():
            yield Static("Error", classes="title")
            yield Static(self._error_message, classes="message")
            yield Button("Quit", variant="error", id="quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button pressed event.
        """
        if event.button.id == "quit":
            self.app.exit(1)

