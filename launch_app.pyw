"""Show a lightweight loading window while the desktop application initializes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent


class StartupWindow:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.log = None
        self.finished = False
        self.started = time.perf_counter()
        self.channel = BASE_DIR / ".webview" / f"startup_{uuid4().hex}.json"
        self.log_path = BASE_DIR / ".webview" / "startup.log"
        root.title("Docspace")
        root.resizable(False, False)
        root.configure(bg="#f3f8fd")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.cancel)
        width, height = 400, 320
        root.geometry(f"{width}x{height}+{max(0, (root.winfo_screenwidth()-width)//2)}+{max(0, (root.winfo_screenheight()-height)//2)}")
        try:
            root.iconbitmap(str(BASE_DIR / "ui" / "assets" / "docspace.ico"))
        except tk.TclError:
            pass
        frame = tk.Frame(root, bg="#f3f8fd", padx=30, pady=24)
        frame.pack(fill="both", expand=True)
        self.logo = tk.PhotoImage(file=str(BASE_DIR / "ui" / "assets" / "docspace.png"))
        tk.Label(frame, image=self.logo, bg="#f3f8fd").pack()
        tk.Label(frame, text="Docspace", bg="#f3f8fd", fg="#18324d", font=("Segoe UI", 22, "bold")).pack(pady=(9, 0))
        tk.Label(frame, text="Documents & Temperature Heatmap", bg="#f3f8fd", fg="#647c94", font=("Segoe UI", 10)).pack(pady=(2, 20))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Startup.Horizontal.TProgressbar", background="#398fe9", troughcolor="#deE8f2", borderwidth=0, lightcolor="#398fe9", darkcolor="#398fe9")
        self.progress = ttk.Progressbar(frame, mode="indeterminate", style="Startup.Horizontal.TProgressbar", length=310)
        self.progress.pack(fill="x")
        self.progress.start(15)
        self.message = tk.StringVar(value="Starting Docspace…")
        tk.Label(frame, textvariable=self.message, bg="#f3f8fd", fg="#647c94", font=("Segoe UI", 9), wraplength=330).pack(pady=(12, 0))
        self.actions = tk.Frame(frame, bg="#f3f8fd")
        self.root.after(30, self.start_app)

    def start_app(self):
        try:
            self.channel.parent.mkdir(parents=True, exist_ok=True)
            self.log = self.log_path.open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, str(BASE_DIR / "main_app.py"), "--startup-channel", str(self.channel)],
                cwd=BASE_DIR, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError as exc:
            self.fail(f"Could not start Docspace: {exc}")
            return
        self.root.after(80, self.poll)

    def poll(self):
        try:
            data = json.loads(self.channel.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("status") == "ready":
            self.finished = True
            self.close()
            return
        if data.get("status") == "error" or self.process.poll() is not None:
            self.fail(data.get("message", "Docspace closed before startup completed."))
            return
        self.message.set(data.get("message", "Starting Docspace…"))
        if time.perf_counter() - self.started > 20:
            self.message.set("Still preparing your workspace. Please wait…")
        self.root.after(80, self.poll)

    def fail(self, message):
        self.progress.stop()
        self.root.geometry(f"400x350+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.message.set(message)
        self.actions.pack(pady=(12, 0))
        ttk.Button(self.actions, text="Open startup log", command=self.open_log).pack(side="left", padx=4)
        ttk.Button(self.actions, text="Close", command=self.cancel).pack(side="left", padx=4)

    def open_log(self):
        if self.log_path.is_file():
            os.startfile(str(self.log_path))

    def cancel(self):
        if self.process is not None and not self.finished and self.process.poll() is None:
            self.process.terminate()
        self.close()

    def close(self):
        self.progress.stop()
        if self.log is not None:
            self.log.close()
        try:
            self.channel.unlink(missing_ok=True)
        except OSError:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    StartupWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
