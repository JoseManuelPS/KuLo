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

    # Keybindings to display, sorted alphabetically by action name
    # Keybindings to display, grouped by function
    KEYBINDINGS = [
        ("n", "Namespace"),
        ("l", "Labels"),
        ("f", "Filter"),
        ("e", "Exclude"),
        ("Space", "Pause/Resume"),
        ("s", "Auto-scroll"),
        ("c", "Clear"),
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

    def on_resize(self) -> None:
        """Update the help bar content on resize."""
        self.update_content()

    def update_content(self, extra_info: str = "") -> None:
        """Update the help bar content.

        Args:
            extra_info: Optional extra information to display.
        """
        text = Text()
        # Use available width or a reasonable default
        available_width = self.size.width or 80
        if extra_info:
            available_width -= len(extra_info) + 5

        current_width = 0
        for i, (key, action) in enumerate(self.KEYBINDINGS):
            # Calculate width of this item plus separator
            item = f"[{key}] {action}"
            item_width = len(item) + (2 if i > 0 else 0)

            if current_width + item_width > available_width:
                break

            if i > 0:
                text.append("  ", style="dim")
                current_width += 2

            text.append(f"[{key}]", style="bold cyan")
            text.append(f" {action}", style="white")
            current_width += len(f"[{key}] {action}")

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

[bold]Filtering & Context[/]
  [cyan]n[/]  Namespace filter (supports regex)
  [cyan]l[/]  Label selector (e.g. app=web)
  [cyan]f[/]  Filter pattern (regex for pod names)
  [cyan]e[/]  Exclude pattern (regex for pod names)

[bold]Streaming & View[/]
  [cyan]Space[/]  Pause/Resume log streaming
  [cyan]s[/]      Toggle auto-scroll
  [cyan]c[/]      Clear log display

[bold]Pod Management[/]
  [cyan]p[/]  Toggle pod panel visibility
  [cyan]a[/]  Enable all pods (All On)
  [cyan]z[/]  Disable all pods (All Off)

[bold]System[/]
  [cyan]?[/]  Toggle this help panel
  [cyan]q[/]  Quit application
  [cyan]Esc[/] Close any open modal/panel

[dim]Press [?] or [Esc] to close this help[/]
"""

    def __init__(self, **kwargs) -> None:
        """Initialize the expanded help panel.

        Args:
            **kwargs: Additional arguments passed to Static.
        """
        super().__init__(self.HELP_TEXT, **kwargs)

