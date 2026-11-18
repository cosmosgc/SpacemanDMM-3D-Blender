"""Windows desktop picker/launcher for the DMM-to-Blender exporter."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from time import monotonic
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


PROJECT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = Path(__file__).resolve().parent / "generate_blender.py"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
SETTINGS_NAME = "SpacemanDMM-Blender-3D-Maps"
MAP_SWITCHES = ("map", "compile")
BLENDER_MODES = ("High fidelity", "Both versions", "Performance only (fast)")
LAYOUT_MODES = ("Type", "Area", "Chunk (32 tiles)")
GLB_MODES = {
    "Match Blender": "match",
    "High fidelity": "high",
    "Performance only": "performance",
    "Both versions": "both",
    "None": "none",
}


def _registered_blender() -> str:
    """Use the Windows file association, which the Blender installer registers."""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"blendfile\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
    except OSError:
        return ""
    match = re.search(r'"([^"]+\.exe)"', command, re.IGNORECASE) or re.search(r"(\S+\.exe)", command, re.IGNORECASE)
    path = Path(match.group(1)) if match else None
    return str(path) if path and path.is_file() else ""


def find_blender() -> str:
    """Return the newest installed Blender, if one can be found."""
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    registered = _registered_blender()
    if registered:
        return registered
    installations = [
        path
        for root in (Path(r"C:\Program Files\Blender Foundation"), Path(r"C:\Program Files (x86)\Blender Foundation"))
        if root.is_dir()
        for path in root.glob("Blender */blender.exe")
    ]
    return str(max(installations, key=lambda path: path.parent.name)) if installations else ""


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / SETTINGS_NAME / "launcher.json"


def load_settings() -> dict[str, str]:
    """Read the previous run's paths and dropdown choices; ignore a damaged file."""
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict):
        return {}
    return {key: value for key, value in saved.items() if isinstance(value, str)}


def save_settings(values: dict[str, str]) -> None:
    try:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def remembered(settings: dict[str, str], key: str, options: tuple[str, ...], default: str) -> str:
    """Fall back when a saved choice no longer exists in the dropdown."""
    value = settings.get(key)
    return value if value in options else default


class MapLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DMM to Blender 3D maps")
        self.geometry("1160x720")
        self.minsize(850, 540)
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.map_paths: list[Path] = []
        self.tree_paths: dict[str, Path] = {}
        self.running = False
        self.process_lock = threading.Lock()
        self.process = None
        self.cancel_requested = False
        self.started = 0.0
        self.stage = ""

        saved = load_settings()
        self.codebase_var = tk.StringVar(value=saved.get("codebase") or os.environ.get("SS13_CODEBASE", ""))
        self.blender_var = tk.StringVar(value=saved.get("blender") or find_blender())
        self.output_var = tk.StringVar(value=saved.get("output") or str(DEFAULT_OUTPUT))
        self.filter_var = tk.StringVar()
        self.switch_var = tk.StringVar(value=remembered(saved, "map_switch", MAP_SWITCHES, "map"))
        self.export_var = tk.StringVar(value=remembered(saved, "blender_files", BLENDER_MODES, "High fidelity"))
        self.layout_var = tk.StringVar(value=remembered(saved, "organize_by", LAYOUT_MODES, "Type"))
        self.glb_var = tk.StringVar(value=remembered(saved, "glb_files", tuple(GLB_MODES), "Match Blender"))
        self.status_var = tk.StringVar(value="Select a map to begin.")
        self.progress_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.refresh_maps()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._process_messages)

    def _save_settings(self):
        save_settings({
            "codebase": self.codebase_var.get(),
            "blender": self.blender_var.get(),
            "output": self.output_var.get(),
            "map_switch": self.switch_var.get(),
            "blender_files": self.export_var.get(),
            "organize_by": self.layout_var.get(),
            "glb_files": self.glb_var.get(),
        })

    def _close(self):
        self._save_settings()
        self.destroy()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        paths = ttk.LabelFrame(self, text="Paths", padding=10)
        paths.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        paths.columnconfigure(1, weight=1)

        self._path_row(paths, 0, "Codebase", self.codebase_var, self._browse_codebase)
        self._path_row(paths, 1, "Blender", self.blender_var, self._browse_blender)
        self._path_row(paths, 2, "Output root", self.output_var, self._browse_output)

        maps_frame = ttk.LabelFrame(self, text="Choose a DMM map", padding=10)
        maps_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        maps_frame.columnconfigure(0, weight=1)
        maps_frame.rowconfigure(1, weight=1)
        filter_row = ttk.Frame(maps_frame)
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filter_row.columnconfigure(1, weight=1)
        ttk.Label(filter_row, text="Filter").grid(row=0, column=0, padx=(0, 8))
        filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var)
        filter_entry.grid(row=0, column=1, sticky="ew")
        filter_entry.bind("<KeyRelease>", lambda _event: self._filter_maps())
        ttk.Button(filter_row, text="Refresh", command=self.refresh_maps).grid(
            row=0, column=2, padx=(8, 0)
        )

        list_frame = ttk.Frame(maps_frame)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        columns = ("size", "modified", "exports", "output_modified")
        self.map_list = ttk.Treeview(list_frame, columns=columns, selectmode="browse")
        for column, label, width in (
            ("#0", "Map / folder", 275),
            ("size", "DMM size", 85),
            ("modified", "DMM modified", 136),
            ("exports", "Existing exports", 245),
            ("output_modified", "Latest export", 136),
        ):
            self.map_list.heading(column, text=label)
            self.map_list.column(column, width=width, minwidth=65, stretch=column in ("#0", "exports"))
        self.map_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.map_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.map_list.configure(yscrollcommand=scrollbar.set)
        self.map_list.bind("<<TreeviewSelect>>", self._selection_changed)
        self.map_list.bind("<Double-Button-1>", self._open_map_row)
        self.map_list.bind("<Return>", self._open_map_row)
        self.output_var.trace_add("write", self._schedule_output_refresh)

        controls = ttk.Frame(self, padding=(12, 4, 12, 8))
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="MAP_SWITCH").grid(row=0, column=0, padx=(0, 8))
        ttk.Combobox(
            controls,
            textvariable=self.switch_var,
            values=MAP_SWITCHES,
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(controls, text="Blender files").grid(row=1, column=0, sticky="w", pady=(7, 0))
        export_mode = ttk.Combobox(
            controls, textvariable=self.export_var,
            values=BLENDER_MODES,
            state="readonly", width=24,
        )
        export_mode.grid(row=1, column=1, sticky="w", pady=(7, 0))
        ttk.Label(controls, text="Organize by").grid(row=2, column=0, sticky="w", pady=(7, 0))
        layout = ttk.Combobox(
            controls, textvariable=self.layout_var,
            values=LAYOUT_MODES, state="readonly", width=24,
        )
        layout.grid(row=2, column=1, sticky="w", pady=(7, 0))
        ttk.Label(controls, text="GLB files").grid(row=3, column=0, sticky="w", pady=(7, 0))
        glb_mode = ttk.Combobox(
            controls, textvariable=self.glb_var, values=tuple(GLB_MODES),
            state="readonly", width=24,
        )
        glb_mode.grid(row=3, column=1, sticky="w", pady=(7, 0))

        def update_layout(_event):
            high = (self.export_var.get() != "Performance only (fast)"
                    or GLB_MODES[self.glb_var.get()] in ("high", "both"))
            layout.configure(state="readonly" if high else "disabled")

        export_mode.bind("<<ComboboxSelected>>", update_layout)
        glb_mode.bind("<<ComboboxSelected>>", update_layout)
        self.generate_button = ttk.Button(
            controls, text="Generate selected map", command=self.generate
        )
        self.generate_button.grid(row=0, column=2, sticky="e")
        self.cancel_button = ttk.Button(
            controls, text="Cancel generation", command=self.cancel_generation, state="disabled"
        )
        self.cancel_button.grid(row=0, column=3, sticky="e", padx=(8, 0))

        log_frame = ttk.LabelFrame(self, text="Exporter output", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.log = tk.Text(log_frame, height=9, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(
            row=4, column=0, sticky="ew", padx=14, pady=(0, 8)
        )
        progress_row = ttk.Frame(self, padding=(14, 0, 14, 10))
        progress_row.grid(row=5, column=0, sticky="ew")
        progress_row.columnconfigure(0, weight=1)
        ttk.Label(progress_row, textvariable=self.progress_var).grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(progress_row, mode="determinate", maximum=1)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    @staticmethod
    def _path_row(parent, row, label, variable, browse):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=4
        )
        ttk.Button(parent, text="Browse…", command=browse).grid(
            row=row, column=2, padx=(8, 0), pady=4
        )

    def _browse_codebase(self):
        selected = filedialog.askdirectory(
            title="Select the SS13 codebase",
            initialdir=self.codebase_var.get() or str(Path.home()),
        )
        if selected:
            self.codebase_var.set(selected)
            self.refresh_maps()

    def _browse_blender(self):
        current = Path(self.blender_var.get()).expanduser() if self.blender_var.get().strip() else None
        start = current.parent if current and current.parent.is_dir() else Path.home()
        selected = filedialog.askopenfilename(
            title="Select blender.exe",
            initialdir=str(start),
            filetypes=(("Blender executable", "blender.exe"), ("All files", "*.*")),
        )
        if selected:
            self.blender_var.set(selected)
            self._save_settings()

    def _browse_output(self):
        selected = filedialog.askdirectory(
            title="Select output directory",
            initialdir=self.output_var.get() or str(PROJECT_DIR),
        )
        if selected:
            self.output_var.set(selected)

    def _codebase(self) -> Path | None:
        value = self.codebase_var.get().strip()
        return Path(value).expanduser() if value else None

    def refresh_maps(self):
        root = self._codebase()
        if root is None:
            self.map_paths = []
            self._filter_maps()
            self.status_var.set("Choose the SS13 codebase folder to list its maps.")
            return
        maps_dir = root / "_maps"
        if not maps_dir.is_dir():
            self.map_paths = []
            self._filter_maps()
            self.status_var.set(f"Maps folder not found: {maps_dir}")
            return
        self.map_paths = sorted(
            (path for path in maps_dir.rglob("*.dmm") if path.is_file()),
            key=lambda path: str(path.relative_to(maps_dir)).casefold(),
        )
        self._filter_maps()
        self.status_var.set(f"Found {len(self.map_paths):,} DMM files in {maps_dir}")

    def _filter_maps(self):
        query = self.filter_var.get().strip().casefold()
        root = self._codebase()
        previous = self._selected_path()
        self.map_list.delete(*self.map_list.get_children())
        self.tree_paths.clear()
        if root is None:
            return
        visible = [
            path for path in self.map_paths
            if query in str(path.relative_to(root)).casefold()
        ]
        folders = {Path("."): ""}
        exports = {}
        output = Path(self.output_var.get()).expanduser()
        for path in visible:
            relative = path.relative_to(root)
            folder = Path(".")
            for part in relative.parts[:-1]:
                child = folder / part
                if child not in folders:
                    folders[child] = self.map_list.insert(
                        folders[folder], "end", text=part, open=bool(query)
                    )
                folder = child
            try:
                source = path.stat()
                size = f"{source.st_size / 1024:,.1f} KiB"
                modified = self._format_modified(source.st_mtime)
            except OSError:
                size = modified = "—"
            if path.stem not in exports:
                exports[path.stem] = self._export_info(output, path.stem)
            item = self.map_list.insert(
                folders[folder], "end", text=path.name,
                values=(size, modified, *exports[path.stem]),
            )
            self.tree_paths[item] = path
            if path == previous:
                self.map_list.selection_set(item)
                self.map_list.see(item)
        self.status_var.set(f"Showing {len(visible):,} of {len(self.map_paths):,} maps")

    @staticmethod
    def _format_modified(timestamp):
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def _export_info(cls, output, name):
        folder = output / name / "files"
        artifacts = []
        modified = []
        for suffix, label in (
            (".blend", "Blend"), (".glb", "GLB"),
            (".performance.blend", "Fast Blend"), (".performance.glb", "Fast GLB"),
        ):
            try:
                artifact = folder / f"{name}{suffix}"
                if artifact.is_file():
                    modified.append(artifact.stat().st_mtime)
                    artifacts.append(label)
            except OSError:
                continue
        return (
            ", ".join(artifacts) if artifacts else "Not exported",
            cls._format_modified(max(modified)) if modified else "—",
        )

    def _schedule_output_refresh(self, *_):
        if getattr(self, "_output_refresh", None) is not None:
            self.after_cancel(self._output_refresh)
        self._output_refresh = self.after(250, self._refresh_output_columns)

    def _refresh_output_columns(self):
        self._output_refresh = None
        output = Path(self.output_var.get()).expanduser()
        exports = {}
        for item, path in self.tree_paths.items():
            if path.stem not in exports:
                exports[path.stem] = self._export_info(output, path.stem)
            labels, modified = exports[path.stem]
            self.map_list.set(item, "exports", labels)
            self.map_list.set(item, "output_modified", modified)

    def _open_map_row(self, event):
        item = self.map_list.identify_row(event.y) if event.type == tk.EventType.ButtonPress else self.map_list.focus()
        if item in self.tree_paths:
            self.map_list.selection_set(item)
            self.generate()
            return "break"

    def _selected_path(self):
        selection = self.map_list.selection()
        return self.tree_paths.get(selection[0]) if selection else None

    def _selection_changed(self, _event=None):
        selected = self._selected_path()
        if selected:
            self.status_var.set(f"Selected: {selected}")

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def generate(self):
        if self.running:
            return
        selected = self._selected_path()
        if not selected:
            messagebox.showinfo("Choose a map", "Select a .dmm map from the list first.")
            return
        blender_text = self.blender_var.get().strip()
        codebase_text = self.codebase_var.get().strip()
        output = Path(self.output_var.get()).expanduser()
        if not blender_text:
            messagebox.showerror("Blender not set", "Choose your Blender executable first.")
            return
        if not codebase_text:
            messagebox.showerror("Codebase not set", "Choose the folder that contains tgstation.dme.")
            return
        blender = Path(blender_text).expanduser()
        codebase = Path(codebase_text).expanduser()
        if not blender.is_file():
            messagebox.showerror("Blender not found", f"Could not find:\n{blender}")
            return
        if not (codebase / "tgstation.dme").is_file():
            messagebox.showerror(
                "Codebase not found",
                f"Could not find tgstation.dme under:\n{codebase}",
            )
            return

        command = [
            str(blender),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(SCRIPT_PATH),
            "--",
            "--dmm",
            str(selected),
            "--codebase",
            str(codebase),
            "--output",
            str(output),
            "--map-switch",
            self.switch_var.get(),
        ]
        if self.export_var.get() == "Both versions":
            command.append("--performance-mode")
        elif self.export_var.get() == "Performance only (fast)":
            command.append("--performance-only")
        command.extend(("--glb", GLB_MODES[self.glb_var.get()]))
        command.extend(("--organize-by", self.layout_var.get().split()[0].lower()))
        self.running = True
        self.cancel_requested = False
        self.started = monotonic()
        self._save_settings()
        self.stage = "Starting Blender"
        self.progress_var.set(self.stage)
        self.progress_bar.configure(value=0)
        self.generate_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._append_log(f"\n> {subprocess.list2cmdline(command)}\n")
        threading.Thread(target=self._run_command, args=(command,), daemon=True).start()

    def cancel_generation(self):
        with self.process_lock:
            if not self.running or self.cancel_requested:
                return
            if self.process is not None:
                if self.process.poll() is not None:
                    return
                try:
                    self.process.terminate()
                except OSError as error:
                    self._append_log(f"\nCould not cancel Blender: {error}\n")
                    return
            self.cancel_requested = True
        self.cancel_button.configure(state="disabled")
        self.stage = "Cancelling export"
        self.progress_var.set(self.stage)

    def _run_command(self, command):
        try:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            with self.process_lock:
                self.process = process
                if self.cancel_requested and process.poll() is None:
                    process.terminate()
            assert process.stdout is not None
            for line in process.stdout:
                if line.startswith("PROGRESS "):
                    self.messages.put(("progress", line.strip()))
                elif not any(marker in line for marker in (
                    " | INFO: Extracting primitive:", " | INFO: Primitives created:",
                    "WARNING: More than one shader node tex image",
                )):
                    self.messages.put(("log", line))
            return_code = process.wait()
            with self.process_lock:
                self.messages.put(("cancelled" if self.cancel_requested else "done", str(return_code)))
        except Exception as error:
            self.messages.put(("error", str(error)))

    def _process_messages(self):
        lines = []
        for _ in range(400):
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                lines.append(value)
            elif kind == "progress" and not self.cancel_requested:
                _, fraction, self.stage = value.split(" ", 2)
                current, total = map(int, fraction.split("/"))
                self.progress_bar.configure(maximum=total, value=current)
            elif kind in ("done", "error", "cancelled"):
                elapsed = self._elapsed()
                self.running = False
                with self.process_lock:
                    self.process = None
                self.generate_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self._refresh_output_columns()
                if kind == "done" and value == "0":
                    self.progress_bar.configure(value=self.progress_bar.cget("maximum"))
                    self.progress_var.set(f"Export complete · {elapsed}")
                elif kind == "done":
                    self.progress_var.set(f"Export failed (exit code {value}) · {elapsed}")
                elif kind == "cancelled":
                    self.progress_var.set(f"Export cancelled · {elapsed}")
                else:
                    self.progress_var.set("Could not run Blender")
                    lines.append(f"\nERROR: {value}\n")
        if lines:
            self._append_log("".join(lines))
        if self.running:
            self.progress_var.set(f"{self.stage} · {self._elapsed()} elapsed")
        self.after(100, self._process_messages)

    def _elapsed(self):
        minutes, seconds = divmod(int(monotonic() - self.started), 60)
        return f"{minutes}:{seconds:02d}"


if __name__ == "__main__":
    MapLauncher().mainloop()
