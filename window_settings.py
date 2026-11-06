"""Remember the desktop window in logical pixels, including its restored bounds."""

import json
from pathlib import Path

from ui_settings import save_settings


class WindowSettings:
    def __init__(self, path):
        self.path = Path(path)
        self.maximized = False

    def options(self, screens=()):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        def integer(key, default, low, high):
            value = data.get(key)
            return value if type(value) is int and low <= value <= high else default
        options = {"width": integer("width", 1280, 1080, 10000),
                   "height": integer("height", 820, 700, 10000),
                   "maximized": data.get("maximized") is True}
        self.maximized = options["maximized"]
        x, y = integer("x", None, -50000, 50000), integer("y", None, -50000, 50000)
        if screens:
            screen = next((s for s in screens if x is not None and y is not None
                           and s.x <= x < s.x + s.width - 80 and s.y <= y < s.y + s.height - 80), screens[0])
            options["width"] = min(options["width"], max(1080, screen.width))
            options["height"] = min(options["height"], max(700, screen.height))
            if x is not None and y is not None:
                options["x"] = max(screen.x, min(x, screen.x + max(0, screen.width - options["width"])))
                options["y"] = max(screen.y, min(y, screen.y + max(0, screen.height - options["height"])))
        elif x is not None and y is not None:
            options.update(x=x, y=y)
        return options

    def bind(self, window):
        self.window = window
        window.events.maximized += self._maximize
        window.events.restored += self._restore

    def _maximize(self):
        self.maximized = True

    def _restore(self):
        self.maximized = False

    def save(self):
        """Read native normal bounds even when closed while maximized/minimized."""
        form = self.window.native
        snapshot = {}
        def capture():
            state = str(form.WindowState)
            bounds = form.Bounds if state == "Normal" else form.RestoreBounds
            scale = form._scale
            snapshot.update(width=round(bounds.Width / scale), height=round(bounds.Height / scale),
                            x=round(bounds.X / scale), y=round(bounds.Y / scale),
                            maximized=state == "Maximized" or (state == "Minimized" and self.maximized))
        if form.InvokeRequired:
            from System import Action
            form.Invoke(Action(capture))
        else:
            capture()
        try:
            save_settings(snapshot, self.path)
        except OSError:
            pass  # A read-only settings folder should not prevent closing.
