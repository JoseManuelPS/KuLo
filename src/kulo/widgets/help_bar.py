"""Help bar widget for KuLo TUI.

This module provides the bottom help bar showing available keybindings.
"""

from rich.text import Text
from textual.widgets import Static


class HelpBar(Static):
    """Bottom help bar showing keybindings.

    Displays available keyboard shortcuts in a compact format.
    """

    DEFAULT_CSS = """
    HelpBar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    # Default keybindings to display
    KEYBINDINGS = [
        ("n", "Namespace"),
        ("i", "Include"),
        ("e", "Exclude"),
        ("l", "Labels"),
        ("p", "Pods"),
        ("a", "All On"),
        ("z", "All Off"),
        ("?", "Help"),
        ("q", "Quit"),
    ]

    def __init__(self, **kwargs) -> None:
        """Initialize the help bar.

        Args:
            **kwargs: Additional arguments passed to Static.
        """
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        """Update the help bar content on mount."""
        self.update_content()

    def update_content(self, extra_info: str = "") -> None:
        """Update the help bar content.

        Args:
            extra_info: Optional extra information to display.
        """
        text = Text()

        for i, (key, action) in enumerate(self.KEYBINDINGS):
            if i > 0:
                text.append("  ", style="dim")

            text.append(f"[{key}]", style="bold cyan")
            text.append(f" {action}", style="white")

        if extra_info:
            text.append("  │  ", style="dim")
            text.append(extra_info, style="yellow")

        self.update(text)

    def show_mode(self, mode: str) -> None:
        """Show the current mode in the help bar.

        Args:
            mode: The mode name to display.
        """
        self.update_content(mode)


class ExpandedHelp(Static):
    """Expanded help panel showing all keybindings with descriptions."""

    DEFAULT_CSS = """
    ExpandedHelp {
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 50%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    """

    HELP_TEXT = """
[bold cyan]Keyboard Shortcuts[/]

[bold]Navigation & Filters[/]
  [cyan]n[/]  Change namespace filter (supports regex)
  [cyan]i[/]  Set include pattern (regex for pod names)
  [cyan]e[/]  Set exclude pattern (regex for pod names)
  [cyan]l[/]  Set label selector (e.g., app=web)

[bold]Pod Control[/]
  [cyan]p[/]  Toggle pod panel visibility
  [cyan]a[/]  Enable all pods
  [cyan]z[/]  Disable all pods
  [cyan]Enter[/]  Toggle selected pod on/off

[bold]View[/]
  [cyan]c[/]  Clear log display
  [cyan]s[/]  Toggle auto-scroll
  [cyan]?[/]  Toggle this help panel

[bold]Application[/]
  [cyan]q[/]  Quit application
  [cyan]Esc[/]  Close modal/panel

[dim]Press [?] or [Esc] to close this help[/]
"""

    def __init__(self, **kwargs) -> None:
        """Initialize the expanded help panel.

        Args:
            **kwargs: Additional arguments passed to Static.
        """
        super().__init__(self.HELP_TEXT, **kwargs)

