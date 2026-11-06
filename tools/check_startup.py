"""Launch the real splash and app, measure readiness, then close the test app."""

from pathlib import Path
import runpy
import sys
import time
import tkinter as tk

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


def main():
    module = runpy.run_path(str(BASE_DIR / "launch_app.pyw"), run_name="startup_check")
    started = time.perf_counter()
    root = tk.Tk()
    app = module["StartupWindow"](root)
    result = []
    original_close = app.close

    def close():
        if app.finished:
            result.append(True)
            print(f"PASS: splash to connected workspace in {time.perf_counter() - started:.2f} seconds")
        original_close()
        if app.process is not None and app.process.poll() is None:
            app.process.terminate()
            app.process.wait(timeout=10)

    app.close = close

    def watchdog():
        print("FAIL: startup did not finish within 45 seconds")
        if app.log_path.exists():
            print(app.log_path.read_text(encoding="utf-8", errors="replace")[-3000:])
        app.cancel()

    root.after(45000, watchdog)
    root.update()
    print(f"Loading screen displayed in {time.perf_counter() - started:.2f} seconds")
    root.mainloop()
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
