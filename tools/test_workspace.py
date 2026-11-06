"""Test output directories with ordinary inherited Windows permissions."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import time
from uuid import uuid4


@contextmanager
def test_workspace():
    root = Path(__file__).resolve().parents[1] / "output"
    root.mkdir(exist_ok=True)
    folder = root / f"test_{uuid4().hex}"
    folder.mkdir()
    try:
        yield folder
    finally:
        if folder.resolve().parent != root.resolve() or not folder.name.startswith("test_"):
            raise ValueError("Unexpected test cleanup path")
        # WebView2 may release its profile handles just after its window closes.
        for attempt in range(30):
            try:
                shutil.rmtree(folder)
                break
            except PermissionError:
                if attempt == 29:
                    raise
                time.sleep(.1)
