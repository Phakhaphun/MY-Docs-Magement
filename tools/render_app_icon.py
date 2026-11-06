"""Render the vector logo at high resolution; build native multi-size icons."""

import base64
from io import BytesIO
import json
from pathlib import Path
import traceback

from PIL import Image
import webview


def main():
    assets = Path(__file__).resolve().parents[1] / "ui" / "assets"
    svg = (assets / "docspace.svg").read_text(encoding="utf-8")
    window = webview.create_window("Render Docspace icon", html=f"<style>body{{margin:0;background:transparent}}svg{{width:512px;height:512px}}</style>{svg}",
                                   width=600, height=600)
    failures = []

    def render():
        try:
            from System import Action
            if not window.events.loaded.wait(20):
                raise RuntimeError("Icon renderer did not load")
            control = window.native.webview
            def cdp(method, parameters):
                tasks = []
                control.Invoke(Action(lambda: tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(parameters)))))
                if not tasks[0].Wait(10000):
                    raise RuntimeError("Icon render timed out")
                return json.loads(tasks[0].Result)
            cdp("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
            capture = cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                         "clip": {"x": 0, "y": 0, "width": 512, "height": 512, "scale": 1}})
            with Image.open(BytesIO(base64.b64decode(capture["data"]))) as image:
                image = image.convert("RGBA").resize((512, 512), Image.Resampling.LANCZOS)
                image.save(assets / "docspace.png")
                image.save(assets / "docspace.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
            print("PASS: SVG rendered to 512px PNG and 9-size Windows ICO")
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            window.destroy()

    storage = assets.parents[1] / ".runtime-tmp" / "icon-render"
    webview.start(render, gui="edgechromium", storage_path=str(storage))
    if failures:
        raise RuntimeError("\n".join(failures))


if __name__ == "__main__":
    main()
