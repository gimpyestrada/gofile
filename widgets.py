"""Small reusable Tkinter widgets."""

import tkinter as tk


class Tooltip:
    """Hover tooltip for a Tkinter widget."""

    def __init__(self, widget, text: str):
        """
        Attach a tooltip to a widget.

        Parameters
        ----------
        widget : tkinter.Widget
            The widget the tooltip describes.
        text : str
            The text to show on hover.
        """
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0

        self.widget.bind("<Enter>", self.showtip, add=True)
        self.widget.bind("<Leave>", self.hidetip, add=True)

    def showtip(self, _event=None) -> None:
        """Display the tooltip below the widget."""
        if self.tipwindow or not self.text:
            return

        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(tw, text=self.text, background="lightyellow",
                         relief=tk.SOLID, borderwidth=1, font=("Arial", 8))
        label.pack(ipadx=5, ipady=2)

    def hidetip(self, _event=None) -> None:
        """Hide the tooltip."""
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()
