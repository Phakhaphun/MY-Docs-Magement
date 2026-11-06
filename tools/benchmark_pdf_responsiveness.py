"""Compare desktop Python scheduling stalls during dense-vector PDF conversion."""

import json
from pathlib import Path
import random
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from doc_app import DocumentAPI
from pdf_to_jpg import convert_pdf_to_images
from pdf_worker import convert_in_process
from tools.test_workspace import test_workspace


def main():
    with test_workspace() as folder:
        folder = Path(folder)
        pdf = folder / "dense-vector.pdf"
        randomizer = random.Random(42)
        with pymupdf.open() as document:
            for _ in range(3):
                page = document.new_page()
                shape = page.new_shape()
                for _ in range(18000):
                    x, y = randomizer.random() * 580, randomizer.random() * 820
                    shape.draw_line((x, y), (x + 10, y + 10))
                shape.finish(color=(.2, .4, .7), width=.7)
                shape.commit()
            document.save(pdf)
        results = {}
        for name, converter in [("thread", convert_pdf_to_images), ("process", convert_in_process)]:
            api = DocumentAPI(folder / f"{name}.json")
            api._add_files([pdf])
            api._state["output"] = str(folder / name)
            intervals = []
            started = time.perf_counter()
            last = started
            with patch("doc_app.convert_pdf_to_images", converter):
                api.start_conversion(300, 95)
                while api.get_state()["running"]:
                    time.sleep(.01)
                    now = time.perf_counter()
                    intervals.append((now - last) * 1000)
                    last = now
                api._thread.join(10)
            assert api.get_state()["result"]["images"] == 3
            results[name] = {"seconds": round(time.perf_counter() - started, 2),
                             "maximum_heartbeat_gap_ms": round(max(intervals), 1),
                             "samples": len(intervals)}
        evidence = Path(__file__).resolve().parents[1] / ".runtime-tmp"
        evidence.mkdir(exist_ok=True)
        (evidence / "pdf-responsiveness.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
