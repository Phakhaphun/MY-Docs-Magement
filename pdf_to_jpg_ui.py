"""Desktop interface for PDF to JPG conversion (Python standard-library UI)."""

from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

from pdf_to_jpg import BASE_DIR, convert_pdf_to_jpg
from ui_settings import SETTINGS_PATH, load_recent_paths, save_recent_paths


class PDFConverterApp:
    def __init__(self, root, settings_path=SETTINGS_PATH):
        self.root = root
        self.settings_path = Path(settings_path)
        self.recent_paths = load_recent_paths(self.settings_path)
        self.files = []
        self.running = False
        self.events = Queue()
        self.controls = []
        root.title("PDF to JPG")
        root.geometry("820x540")
        root.minsize(760, 520)
        root.configure(background="#F5F6FA")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.output = tk.StringVar(value=self.recent_paths.get("output_dir", str(BASE_DIR / "output")))
        self.dpi = tk.StringVar(value="200")
        self.quality = tk.StringVar(value="95")
        self.status = tk.StringVar(value="Choose PDF files to get started")
        self.count = tk.StringVar(value="0 files")
        self.detail = tk.StringVar(value="Use Ctrl or Shift to select multiple files")
        families = set(tkfont.families(root))
        self.font_family = next((f for f in ("Segoe UI", "Leelawadee UI", "Tahoma") if f in families), "TkDefaultFont")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            tkfont.nametofont(name).configure(family=self.font_family, size=9)
        root.option_add("*Font", (self.font_family, 9))
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self.style.configure(".", font=(self.font_family, 9), background="#FFFFFF", foreground="#20263A")
        self.style.configure("TFrame", background="#FFFFFF")
        self.style.configure("TLabel", background="#FFFFFF", foreground="#20263A")
        self.style.configure("TButton", padding=(10, 6), borderwidth=0, background="#EEF0F8", foreground="#3C4661", font=(self.font_family, 9))
        self.style.map("TButton", background=[("disabled", "#F0F1F5"), ("active", "#E0E4F2")], foreground=[("disabled", "#A0A6B7")])
        self.style.configure("Primary.TButton", background="#5850D9", foreground="white", font=(self.font_family, 10, "bold"), padding=(14, 9))
        self.style.map("Primary.TButton", background=[("disabled", "#C7C5EB"), ("active", "#463CC2")], foreground=[("disabled", "#FFFFFF")])
        self.style.configure("Ghost.TButton", background="#FFFFFF", foreground="#667085", padding=(6, 5))
        self.style.map("Ghost.TButton", background=[("active", "#F0F2F8"), ("disabled", "#FFFFFF")])
        self.style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", borderwidth=0, rowheight=32, font=(self.font_family, 9))
        self.style.configure("Treeview.Heading", background="#F7F8FC", foreground="#737D91", borderwidth=0, padding=(8, 7), font=(self.font_family, 9))
        self.style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        self.style.map("Treeview", background=[("selected", "#EEEDFF")], foreground=[("selected", "#4138A7")])
        self.style.configure("TSpinbox", padding=5, arrowsize=12, fieldbackground="#F7F8FC", bordercolor="#E3E6EF")
        self.style.configure("Horizontal.TProgressbar", background="#655BE8", troughcolor="#ECEEF5", borderwidth=0, thickness=6)
        self.style.configure("TScrollbar", background="#DDE1EE", troughcolor="#F7F8FC", borderwidth=0, arrowsize=10)
        self.style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        self.style.layout("Horizontal.TScrollbar", [("Horizontal.Scrollbar.trough", {"sticky": "we", "children": [("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        self.style.layout("Horizontal.TProgressbar", [("Horizontal.Progressbar.trough", {"sticky": "nswe", "children": [("Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})])

        frame = tk.Frame(root, bg="#F5F6FA", padx=16, pady=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        header = tk.Frame(frame, bg="#F5F6FA")
        header.grid(row=0, sticky="ew", pady=(0, 12))
        tk.Label(header, text="PDF  →  JPG", bg="#F5F6FA", fg="#20263A", font=(self.font_family, 20, "bold")).pack(anchor="w")
        tk.Label(header, text="Convert documents to images.", bg="#F5F6FA", fg="#737D91", font=(self.font_family, 9)).pack(anchor="w", pady=(2, 0))
        badge = tk.Label(header, text="  Works offline  ", bg="#E7F4EE", fg="#287656", font=(self.font_family, 9), padx=6, pady=4)
        badge.place(relx=1, rely=0.35, anchor="e")

        body = tk.Frame(frame, bg="#F5F6FA")
        body.grid(row=1, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        files_card = tk.Frame(body, bg="white", highlightbackground="#E5E8F1", highlightthickness=1, padx=12, pady=12)
        files_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        files_card.columnconfigure(0, weight=1)
        files_card.rowconfigure(2, weight=1)
        file_header = tk.Frame(files_card, bg="white")
        file_header.grid(row=0, sticky="ew")
        tk.Label(file_header, text="Files", bg="white", fg="#20263A", font=(self.font_family, 11, "bold")).pack(side="left")
        tk.Label(file_header, textvariable=self.count, bg="#EFEDFF", fg="#6554C0", padx=10, pady=3, font=(self.font_family, 9)).pack(side="right")
        actions = tk.Frame(files_card, bg="white")
        actions.grid(row=1, sticky="ew", pady=(10, 10))
        self.button(actions, "+ Add PDFs", self.choose_files).pack(side="left")
        self.button(actions, "Remove", self.remove_selected, "Ghost.TButton").pack(side="right")
        self.button(actions, "Clear", self.clear_files, "Ghost.TButton").pack(side="right", padx=4)

        table = ttk.Frame(files_card)
        table.grid(row=2, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table, columns=("file", "status"), show="headings", selectmode="extended",
        )
        self.tree.heading("file", text="PDF file")
        self.tree.heading("status", text="Status")
        self.tree.column("file", width=240, minwidth=130)
        self.tree.column("status", width=130, minwidth=100)
        self.tree.grid(sticky="nsew")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.tag_configure("success", foreground="#23835C")
        self.tree.tag_configure("error", foreground="#BF4356")
        self.tree.tag_configure("working", foreground="#6251D2")
        self.tree.bind("<<TreeviewSelect>>", self.show_file_detail)
        self.empty = tk.Frame(table, bg="white")
        tk.Label(self.empty, text="Add your PDFs", bg="white", fg="#343C53", font=(self.font_family, 12, "bold")).pack()
        tk.Label(self.empty, text="Select one or multiple files", bg="white", fg="#8C93A5", font=(self.font_family, 9)).pack(pady=(5, 10))
        self.button(self.empty, "Choose files…", self.choose_files).pack()
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.detail_label = tk.Label(files_card, textvariable=self.detail, bg="white", fg="#8C93A5", font=(self.font_family, 9), anchor="w", wraplength=420, justify="left", height=2)
        self.detail_label.grid(row=3, sticky="ew", pady=(8, 0))
        self.detail_label.bind("<Configure>", lambda event: self.detail_label.configure(wraplength=max(100, event.width)))

        sidebar = tk.Frame(body, bg="white", width=230, highlightbackground="#E5E8F1", highlightthickness=1, padx=14, pady=12)
        sidebar.grid(row=0, column=1, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        tk.Label(sidebar, text="Image settings", bg="white", fg="#20263A", font=(self.font_family, 11, "bold")).grid(sticky="w")
        tk.Label(sidebar, text="JPG / JPEG", bg="#F4F3FC", fg="#6554C0", font=(self.font_family, 10, "bold"), padx=10, pady=7, anchor="w").grid(row=2, sticky="ew", pady=(10, 0))
        options = tk.Frame(sidebar, bg="white")
        options.grid(row=3, sticky="ew", pady=(10, 0))
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="DPI").grid(row=0, column=0, sticky="w")
        dpi_box = ttk.Spinbox(options, from_=36, to=600, textvariable=self.dpi, width=6)
        dpi_box.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=(0, 10))
        ttk.Label(options, text="Quality (1–100)").grid(row=0, column=1, sticky="w")
        quality_box = ttk.Spinbox(options, from_=1, to=100, textvariable=self.quality, width=6)
        quality_box.grid(row=1, column=1, sticky="ew", pady=(5, 0))
        self.controls.extend([dpi_box, quality_box])
        tk.Label(sidebar, text="200 DPI: standard · 300: sharper", bg="white", fg="#8C93A5", justify="left", font=(self.font_family, 8)).grid(row=4, sticky="w", pady=(7, 12))
        ttk.Separator(sidebar).grid(row=5, sticky="ew")
        tk.Label(sidebar, text="Output folder", bg="white", fg="#20263A", font=(self.font_family, 11, "bold")).grid(row=6, sticky="w", pady=(12, 8))
        ttk.Entry(sidebar, textvariable=self.output, state="readonly", width=22).grid(row=7, sticky="ew", ipady=4)
        self.button(sidebar, "Browse…", self.choose_output).grid(row=8, sticky="ew", pady=(8, 0))
        self.button(sidebar, "Open folder ↗", self.open_output, "Ghost.TButton").grid(row=9, sticky="ew", pady=(4, 0))
        sidebar.rowconfigure(10, weight=1)

        footer = tk.Frame(frame, bg="white", highlightbackground="#E5E8F1", highlightthickness=1, padx=12, pady=10)
        footer.grid(row=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        tk.Label(footer, textvariable=self.status, bg="white", fg="#667085", anchor="w", wraplength=430, justify="left", font=(self.font_family, 9), height=2).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 16))
        self.button(footer, "Convert to JPG →", self.start, "Primary.TButton").grid(row=0, column=1, rowspan=2, sticky="ns")
        root.after(100, self.poll_events)

    def button(self, parent, text, command, style="TButton"):
        button = ttk.Button(parent, text=text, command=command, style=style)
        self.controls.append(button)
        return button

    def update_file_summary(self):
        self.count.set(f"{len(self.files)} files")
        self.status.set(f"Ready to convert {len(self.files)} files" if self.files else "Choose PDF files to get started")
        if self.files:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.show_file_detail()

    def show_file_detail(self, event=None):
        selection = self.tree.selection()
        paths = dict(zip(self.tree.get_children(), self.files))
        self.detail.set(str(paths[selection[0]]) if selection and selection[0] in paths else "Use Ctrl or Shift to select multiple files")

    def open_output(self):
        folder = Path(self.output.get())
        if not folder.is_dir():
            messagebox.showinfo("Output folder", "This folder will be created when conversion starts.", parent=self.root)
            return
        try:
            os.startfile(str(folder))
        except OSError as exc:
            messagebox.showerror("Cannot open folder", str(exc), parent=self.root)

    def choose_files(self):
        default_input = BASE_DIR / "input"
        initial_dir = self.recent_paths.get("input_dir", str(default_input if default_input.is_dir() else BASE_DIR))
        paths = filedialog.askopenfilenames(
            parent=self.root, title="Choose PDFs (Ctrl or Shift to select multiple files)",
            initialdir=initial_dir, filetypes=[("PDF files", "*.pdf")],
        )
        if paths:
            self.recent_paths["input_dir"] = str(Path(paths[-1]).resolve().parent)
            self.remember_paths()
        for name in paths:
            path = Path(name).resolve()
            if path not in self.files:
                self.files.append(path)
                self.tree.insert("", "end", values=(path.name, "Waiting"))
        self.update_file_summary()

    def remove_selected(self):
        paths = dict(zip(self.tree.get_children(), self.files))
        for item in self.tree.selection():
            self.files.remove(paths[item])
            self.tree.delete(item)
        self.update_file_summary()

    def clear_files(self):
        self.files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.update_file_summary()

    def choose_output(self):
        folder = filedialog.askdirectory(
            parent=self.root, title="Choose output folder", initialdir=self.output.get(),
        )
        if folder:
            self.output.set(str(Path(folder).resolve()))
            self.recent_paths["output_dir"] = self.output.get()
            self.remember_paths()

    def remember_paths(self):
        try:
            save_recent_paths(self.recent_paths, self.settings_path)
        except OSError as exc:
            messagebox.showwarning(
                "Could not save recent folders",
                f"You can continue using the app, but recent folders could not be saved.\n{exc}",
                parent=self.root,
            )

    def start(self):
        if self.running:
            return
        if not self.files:
            messagebox.showwarning("No files selected", "Please choose at least one PDF file.", parent=self.root)
            return
        try:
            dpi, quality = int(self.dpi.get()), int(self.quality.get())
            if not 36 <= dpi <= 600 or not 1 <= quality <= 100:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Invalid settings", "DPI must be an integer from 36 to 600, and quality from 1 to 100.",
                parent=self.root,
            )
            return
        if not self.output.get().strip():
            messagebox.showwarning("No output folder", "Please choose an output folder.", parent=self.root)
            return
        jobs = list(zip(self.tree.get_children(), self.files))
        self.running = True
        for control in self.controls:
            control.configure(state="disabled")
        for item, _ in jobs:
            self.tree.set(item, "status", "Waiting")
            self.tree.item(item, tags=())
        self.progress.configure(maximum=len(jobs), value=0)
        self.status.set("Starting conversion…")
        Thread(
            target=self.convert_batch, args=(jobs, self.output.get(), dpi, quality), daemon=True,
        ).start()

    def convert_batch(self, jobs, output, dpi, quality):
        # Worker only touches the queue; all Tk updates run on the UI thread.
        successes = failures = 0
        for item, path in jobs:
            self.events.put(("start", item, path.name))
            try:
                images = convert_pdf_to_jpg(path, output, dpi=dpi, quality=quality)
            except Exception as exc:
                failures += 1
                self.events.put(("error", item, str(exc)))
            else:
                successes += 1
                self.events.put(("success", item, len(images)))
        self.events.put(("finished", successes, failures))

    def poll_events(self):
        try:
            while True:
                kind, first, second = self.events.get_nowait()
                if kind == "start":
                    self.tree.item(first, tags=("working",))
                    self.tree.set(first, "status", "Converting…")
                    self.tree.see(first)
                    self.status.set(f"Converting: {second}")
                elif kind == "success":
                    self.tree.item(first, tags=("success",))
                    self.tree.set(first, "status", f"Done · {second} images")
                    self.progress.configure(value=float(self.progress["value"]) + 1)
                elif kind == "error":
                    self.tree.item(first, tags=("error",))
                    self.tree.set(first, "status", f"Error: {second}")
                    self.progress.configure(value=float(self.progress["value"]) + 1)
                elif kind == "finished":
                    self.running = False
                    for control in self.controls:
                        control.configure(state="normal")
                    self.progress.configure(value=first + second)
                    summary = f"Finished: {first} succeeded / {second} failed"
                    self.status.set(summary)
                    if second:
                        messagebox.showwarning(
                            "Conversion finished", summary + "\nSee the Status column for errors.", parent=self.root,
                        )
                    else:
                        messagebox.showinfo(
                            "Conversion finished", summary + f"\nSaved to: {self.output.get()}", parent=self.root,
                        )
        except Empty:
            pass
        self.root.after(100, self.poll_events)

    def close(self):
        if self.running:
            messagebox.showinfo("Conversion in progress", "Please wait until conversion finishes before closing.", parent=self.root)
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    PDFConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
