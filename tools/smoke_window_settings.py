"""Check window size/position and maximized state across real process restarts."""

import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.test_workspace import test_workspace
from window_settings import WindowSettings


def child(path, phase):
    import webview
    layout = WindowSettings(path)
    options = layout.options(webview.screens)
    if phase != "save":
        assert options["width"] == 1120 and options["height"] == 740, options
        assert options["x"] == 40 and options["y"] == 60, options
        assert options["maximized"] == (phase == "restore"), options
    window = webview.create_window("Docspace · Window settings check", html="<h2>Window settings check</h2>",
                                   **options, min_size=(1080, 700))
    layout.bind(window)
    window.events.closing += layout.save
    failures = []

    def run():
        try:
            assert window.events.loaded.wait(20)
            if phase == "save":
                window.resize(1120, 740)
                window.move(40, 60)
            elif phase == "maximize":
                assert window.width == 1120 and window.height == 740
                window.maximize()
            else:
                assert str(window.native.WindowState) == "Maximized"
                window.restore()
            time.sleep(.3)
            if phase == "restore":
                assert window.width == 1120 and window.height == 740, (window.width, window.height)
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            window.destroy()

    webview.start(run, gui="edgechromium", storage_path=str(Path(path).parent / "webview"))
    if failures:
        raise AssertionError("\n".join(failures))
    saved = json.loads(Path(path).read_text())
    assert saved["width"] == 1120 and saved["height"] == 740, saved
    assert saved["maximized"] == (phase == "maximize"), saved


def main():
    with test_workspace() as folder:
        for phase in ("save", "maximize", "restore"):
            result = subprocess.run([sys.executable, __file__, str(Path(folder) / "window.json"), phase],
                                    capture_output=True, text=True, timeout=45)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
    print("PASS: window size/position restored after restart; maximized state and normal bounds restored")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        child(sys.argv[1], sys.argv[2])
    else:
        main()
