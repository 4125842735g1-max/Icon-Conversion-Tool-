from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pefile
from PIL import Image, ImageOps, ImageTk
import tkinter as tk
from tkinter import filedialog, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - optional dependency
    DND_FILES = None
    TkinterDnD = None


DND_AVAILABLE = TkinterDnD is not None and DND_FILES is not None


SUPPORTED_ICON_SOURCES = {".png", ".jpg", ".jpeg", ".ico", ".exe"}
SUPPORTED_TARGETS = {".lnk", ".exe"}
PREVIEW_SIZE = 56
PREVIEW_BOX_SIZE = 72
BG = "#0D131A"
PANEL = "#15202B"
INPUT_BG = "#0F1821"
TEXT = "#EEF4FA"
MUTED = "#98A9BA"
HINT = "#74869A"
ACCENT = "#90C4FF"
SUCCESS = "#CBE9A7"
ERROR = "#FFB5A9"
ICON_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "IconConversionTool" / "icons"
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "IconConversionTool"
DEFAULT_LANGUAGE = "zh-CN"


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


LANG_DIR = app_base_dir() / "lang"
SETTINGS_FILE = APP_DATA_DIR / ".icon-tool-settings.json"


def parse_drop_paths(data: str) -> list[Path]:
    paths: list[Path] = []
    current: list[str] = []
    in_braces = False
    for char in data.strip():
        if char == "{":
            in_braces = True
            current = []
            continue
        if char == "}":
            in_braces = False
            if current:
                paths.append(Path("".join(current)))
            current = []
            continue
        if char == " " and not in_braces:
            if current:
                paths.append(Path("".join(current)))
                current = []
            continue
        current.append(char)
    if current:
        paths.append(Path("".join(current)))
    return paths


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def shell_refresh(path: Path) -> None:
    script = """
$signature = @'
using System;
using System.Runtime.InteropServices;
public static class NativeMethods {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
}
'@
Add-Type -TypeDefinition $signature -ErrorAction SilentlyContinue | Out-Null
[NativeMethods]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
"""
    run_powershell(script)


def clear_file_attributes(path: Path) -> None:
    if path.exists():
        subprocess.run(["attrib", "-h", "-s", "-r", str(path)], check=False)


def disable_maximize_button(root: tk.Tk) -> None:
    if sys.platform != "win32":
        return

    hwnd = root.winfo_id()
    gwl_style = -16
    ws_maximizebox = 0x00010000
    ws_thickframe = 0x00040000
    swp_no_move = 0x0002
    swp_no_size = 0x0001
    swp_no_z_order = 0x0004
    swp_frame_changed = 0x0020

    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, gwl_style)
    style &= ~ws_maximizebox
    style &= ~ws_thickframe
    user32.SetWindowLongW(hwnd, gwl_style, style)
    user32.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        swp_no_move | swp_no_size | swp_no_z_order | swp_frame_changed,
    )


def sha_token(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def fit_square(image: Image.Image, size: int) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    return ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def convert_image_to_ico(source: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        base = fit_square(image, 256)
        base.save(
            output_path,
            format="ICO",
            sizes=[(256, 256), (128, 128), (96, 96), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
        )
    return output_path


def normalize_existing_ico(source: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        base = fit_square(image, 256)
        base.save(
            output_path,
            format="ICO",
            sizes=[(256, 256), (128, 128), (96, 96), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
        )
    return output_path


def _get_resource_directory(pe: pefile.PE, resource_type: int):
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        raise RuntimeError("No readable icon resources were found in this EXE.")
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id == resource_type:
            return entry.directory
    raise RuntimeError("No readable icon resources were found in this EXE.")


def _resource_data(pe: pefile.PE, data_entry) -> bytes:
    offset = data_entry.data.struct.OffsetToData
    size = data_entry.data.struct.Size
    return pe.get_memory_mapped_image()[offset : offset + size]


def extract_best_icon_from_exe(source: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pe = pefile.PE(str(source), fast_load=False)
    try:
        group_dir = _get_resource_directory(pe, pefile.RESOURCE_TYPE["RT_GROUP_ICON"])
        icon_dir = _get_resource_directory(pe, pefile.RESOURCE_TYPE["RT_ICON"])

        icon_blobs: dict[int, bytes] = {}
        for icon_entry in icon_dir.entries:
            resource_id = icon_entry.id
            data_entry = icon_entry.directory.entries[0]
            icon_blobs[resource_id] = _resource_data(pe, data_entry)

        best_ico: bytes | None = None
        best_score = (-1, -1)

        for group_entry in group_dir.entries:
            data_entry = group_entry.directory.entries[0]
            group_data = _resource_data(pe, data_entry)
            reserved, icon_type, count = struct.unpack_from("<HHH", group_data, 0)
            if reserved != 0 or icon_type != 1 or count <= 0:
                continue

            entries = []
            score = (-1, -1)
            for index in range(count):
                start = 6 + index * 14
                width, height, color_count, reserved_byte, planes, bit_count, bytes_in_res, resource_id = struct.unpack_from(
                    "<BBBBHHIH", group_data, start
                )
                actual_width = 256 if width == 0 else width
                actual_height = 256 if height == 0 else height
                entries.append(
                    {
                        "width": width,
                        "height": height,
                        "color_count": color_count,
                        "reserved": reserved_byte,
                        "planes": planes,
                        "bit_count": bit_count,
                        "bytes_in_res": bytes_in_res,
                        "resource_id": resource_id,
                    }
                )
                score = max(score, (actual_width * actual_height, bit_count))

            if score <= best_score:
                continue

            image_offset = 6 + (16 * count)
            image_chunks = []
            directory_chunks = []
            for entry in entries:
                blob = icon_blobs.get(entry["resource_id"])
                if not blob:
                    continue
                directory_chunks.append(
                    struct.pack(
                        "<BBBBHHII",
                        entry["width"],
                        entry["height"],
                        entry["color_count"],
                        entry["reserved"],
                        entry["planes"],
                        entry["bit_count"],
                        len(blob),
                        image_offset,
                    )
                )
                image_chunks.append(blob)
                image_offset += len(blob)

            if len(directory_chunks) != count:
                continue

            best_ico = b"".join([struct.pack("<HHH", 0, 1, count), *directory_chunks, *image_chunks])
            best_score = score

        if not best_ico:
            raise RuntimeError("Unable to extract a native icon resource from this EXE.")

        output_path.write_bytes(best_ico)
        return output_path
    finally:
        pe.close()


def materialize_icon(source: Path, namespace: str) -> Path:
    ICON_ROOT.mkdir(parents=True, exist_ok=True)
    output = ICON_ROOT / f"{namespace}-{source.stem}-{sha_token(source)}.ico"
    suffix = source.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return convert_image_to_ico(source, output)
    if suffix == ".ico":
        return normalize_existing_ico(source, output)
    if suffix == ".exe":
        return extract_best_icon_from_exe(source, output)
    raise ValueError("Icon sources only support png, jpg, jpeg, ico, and exe files.")


def apply_icon_to_shortcut(target: Path, source: Path) -> Path:
    icon_path = materialize_icon(source, f"shortcut-{target.stem}")
    shortcut_literal = str(target).replace("'", "''")
    icon_literal = str(icon_path).replace("'", "''")
    script = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut('{shortcut_literal}')
$shortcut.IconLocation = '{icon_literal},0'
$shortcut.Save()
"""
    result = run_powershell(script)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to update the shortcut icon.")
    shell_refresh(target)
    return icon_path


def create_shortcut_for_exe(target: Path, source: Path) -> tuple[Path, Path]:
    if not os.access(target.parent, os.W_OK):
        raise PermissionError("The EXE directory is not writable, so a shortcut cannot be created there.")
    shortcut = target.with_name(f"{target.stem} - Custom Icon.lnk")
    icon_path = materialize_icon(source, f"exe-{target.stem}")
    shortcut_literal = str(shortcut).replace("'", "''")
    target_literal = str(target).replace("'", "''")
    icon_literal = str(icon_path).replace("'", "''")
    workdir_literal = str(target.parent).replace("'", "''")
    script = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut('{shortcut_literal}')
$shortcut.TargetPath = '{target_literal}'
$shortcut.WorkingDirectory = '{workdir_literal}'
$shortcut.IconLocation = '{icon_literal},0'
$shortcut.Save()
"""
    result = run_powershell(script)
    if result.returncode != 0 or not shortcut.exists():
        raise RuntimeError(result.stderr.strip() or "Failed to create the EXE shortcut.")
    shell_refresh(shortcut)
    return shortcut, icon_path


def apply_icon_to_folder(target: Path, source: Path) -> Path:
    icon_path = materialize_icon(source, f"folder-{target.name}")
    desktop_ini = target / "desktop.ini"
    clear_file_attributes(desktop_ini)
    ini_content = (
        "[.ShellClassInfo]\r\n"
        f"IconResource={icon_path},0\r\n"
        f"IconFile={icon_path}\r\n"
        "IconIndex=0\r\n"
        "ConfirmFileOp=0\r\n"
    )
    desktop_ini.write_bytes(ini_content.encode("utf-16"))
    subprocess.run(["attrib", "+r", str(target)], check=True)
    subprocess.run(["attrib", "+s", str(target)], check=True)
    subprocess.run(["attrib", "+h", "+s", str(desktop_ini)], check=True)
    shell_refresh(target)
    return icon_path


def detect_source_kind(path: Path, tr: Callable[[str], str]) -> str:
    suffix = path.suffix.lower()
    if suffix == ".ico":
        return "ICO"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return tr("source_kind_image")
    if suffix == ".exe":
        return "EXE"
    return tr("source_kind_unknown")


def preview_image_from_source(source: Path) -> Image.Image:
    icon_path = materialize_icon(source, f"preview-{source.stem}")
    with Image.open(icon_path) as image:
        return fit_square(image, PREVIEW_SIZE)


def load_available_languages() -> dict[str, dict[str, Any]]:
    languages: dict[str, dict[str, Any]] = {}
    for path in sorted(LANG_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        code = payload["meta"]["code"]
        languages[code] = payload
    if DEFAULT_LANGUAGE not in languages:
        raise RuntimeError(f"Missing default language file: {DEFAULT_LANGUAGE}")
    return languages


def load_saved_language() -> str:
    if not SETTINGS_FILE.exists():
        return DEFAULT_LANGUAGE
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_LANGUAGE
    return str(payload.get("language", DEFAULT_LANGUAGE))


def save_language(code: str) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({"language": code}, ensure_ascii=False, indent=2), encoding="utf-8")


def create_root() -> tk.Tk:
    global DND_AVAILABLE
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk()
        except Exception:
            DND_AVAILABLE = False
    return tk.Tk()


class PathCard(ttk.Frame):
    def __init__(self, master: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.on_change = on_change
        self.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(self, style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.desc_label = ttk.Label(self, style="Body.TLabel", wraplength=420, justify="left")
        self.desc_label.grid(row=1, column=0, sticky="w", pady=(4, 6))

        self.value_var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.value_var, style="Path.TEntry")
        self.entry.grid(row=2, column=0, sticky="ew", ipady=4)
        self.entry.bind("<KeyRelease>", lambda _event: self.on_change())

        self.button_row = ttk.Frame(self, style="Panel.TFrame")
        self.button_row.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.buttons: list[ttk.Button] = []

        self.hint_label = ttk.Label(self, style="Hint.TLabel")
        self.hint_label.grid(row=4, column=0, sticky="w", pady=(6, 0))

    def set_copy(self, title: str, desc: str, button_specs: list[tuple[str, Callable[[], None]]], hint: str) -> None:
        self.title_label.configure(text=title)
        self.desc_label.configure(text=desc)
        self.hint_label.configure(text=hint)
        for button in self.buttons:
            button.destroy()
        self.buttons.clear()
        for index, (label, command) in enumerate(button_specs):
            button = ttk.Button(self.button_row, text=label, command=command, style="Tool.TButton")
            button.grid(row=0, column=index, padx=(0, 6))
            self.buttons.append(button)

    def enable_drop(self) -> None:
        if not DND_AVAILABLE:
            return
        for widget in (self, self.entry, self.button_row):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event: object) -> None:
        paths = parse_drop_paths(getattr(event, "data", ""))
        if paths:
            self.set_path(paths[0])

    def set_path(self, path: Path) -> None:
        self.value_var.set(str(path))
        self.on_change()

    def get_path(self) -> Path | None:
        raw = self.value_var.get().strip().strip('"')
        return Path(raw) if raw else None


class SummaryCard(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.configure(width=264)
        self.grid_propagate(False)
        self.title_label = ttk.Label(self, style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.target_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.target_label = ttk.Label(self, textvariable=self.target_var, style="Info.TLabel", wraplength=250, justify="left")
        self.target_label.grid(row=1, column=0, sticky="w", pady=(6, 2))
        self.source_label = ttk.Label(self, textvariable=self.source_var, style="Hint.TLabel", wraplength=250, justify="left")
        self.source_label.grid(row=2, column=0, sticky="w")

    def set_title(self, text: str) -> None:
        self.title_label.configure(text=text)

    def update_target(self, text: str) -> None:
        self.target_var.set(text)

    def update_source(self, text: str) -> None:
        self.source_var.set(text)


class PreviewCard(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.configure(width=264, height=132)
        self.grid_propagate(False)
        row = ttk.Frame(self, style="Panel.TFrame")
        row.grid(row=0, column=0, sticky="w")
        self.title_label = ttk.Label(row, style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.preview_canvas = tk.Canvas(
            row,
            width=PREVIEW_BOX_SIZE,
            height=PREVIEW_BOX_SIZE,
            bg=INPUT_BG,
            bd=0,
            highlightbackground="#2A3948",
            highlightthickness=1,
        )
        self.preview_canvas.grid(row=0, column=1, padx=(10, 0))
        self.desc_var = tk.StringVar()
        self.desc_label = ttk.Label(self, textvariable=self.desc_var, style="Hint.TLabel", wraplength=250, justify="left")
        self.desc_label.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.photo: ImageTk.PhotoImage | None = None

    def set_copy(self, title: str, description: str) -> None:
        self.title_label.configure(text=title)
        self.desc_var.set(description)

    def clear(self) -> None:
        self.photo = None
        self.preview_canvas.delete("all")

    def show(self, image: Image.Image) -> None:
        self.photo = ImageTk.PhotoImage(image)
        center = PREVIEW_BOX_SIZE // 2
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(center, center, image=self.photo)


class IconToolApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.languages = load_available_languages()
        requested_code = load_saved_language()
        self.language_code = requested_code if requested_code in self.languages else DEFAULT_LANGUAGE
        self.messages = self.languages[self.language_code]["messages"]
        self.root.geometry("900x480")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.status_var = tk.StringVar()
        self.language_var = tk.StringVar(value=self.language_code)

        self._build_styles()
        self._build_ui()
        self._bind_drop_support()
        self.apply_language()
        self.refresh_panels()
        self.root.after(50, lambda: disable_maximize_button(self.root))

    def tr(self, key: str, **kwargs: Any) -> str:
        text = self.messages[key]
        if kwargs:
            return text.format(**kwargs)
        return text

    def language_label(self, code: str) -> str:
        return self.languages[code]["meta"]["label"]

    def _build_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Root.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Hero.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Body.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Hint.TLabel", background=PANEL, foreground=HINT, font=("Microsoft YaHei UI", 9))
        style.configure("Info.TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Path.TEntry", fieldbackground=INPUT_BG, foreground=TEXT, insertcolor=TEXT, bordercolor="#2A3948", lightcolor="#2A3948", darkcolor="#2A3948")
        style.configure("Tool.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(10, 5))
        style.configure("Apply.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(14, 7))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=0)
        outer.rowconfigure(2, weight=1)

        self.hero_label = ttk.Label(outer, style="Hero.TLabel")
        self.hero_label.grid(row=0, column=0, sticky="w")

        header_row = ttk.Frame(outer, style="Root.TFrame")
        header_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        header_row.columnconfigure(0, weight=1)

        self.sub_label = ttk.Label(header_row, style="Sub.TLabel")
        self.sub_label.grid(row=0, column=0, sticky="w")

        language_row = ttk.Frame(header_row, style="Root.TFrame")
        language_row.grid(row=0, column=1, sticky="e")
        self.language_title = ttk.Label(language_row, style="Sub.TLabel")
        self.language_title.grid(row=0, column=0, sticky="e", padx=(0, 8))
        self.language_box = ttk.Combobox(
            language_row,
            textvariable=self.language_var,
            state="readonly",
            width=18,
            values=list(self.languages.keys()),
        )
        self.language_box.grid(row=0, column=1, sticky="e")
        self.language_box.bind("<<ComboboxSelected>>", self.change_language)

        left = ttk.Frame(outer, style="Root.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)

        self.target_card = PathCard(left, self.refresh_panels)
        self.target_card.grid(row=0, column=0, sticky="ew")

        self.source_card = PathCard(left, self.refresh_panels)
        self.source_card.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        right = ttk.Frame(outer, style="Root.TFrame")
        right.grid(row=2, column=1, sticky="ne")

        self.summary = SummaryCard(right)
        self.summary.grid(row=0, column=0, sticky="ew")
        self.preview = PreviewCard(right)
        self.preview.grid(row=1, column=0, sticky="nw", pady=(8, 0))

        bottom = ttk.Frame(outer, style="Root.TFrame")
        bottom.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            bottom,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            font=("Microsoft YaHei UI", 9),
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.apply_button = ttk.Button(bottom, command=self.apply_change, style="Apply.TButton")
        self.apply_button.grid(row=0, column=1, sticky="e")

    def _bind_drop_support(self) -> None:
        self.target_card.enable_drop()
        self.source_card.enable_drop()

    def apply_language(self) -> None:
        self.messages = self.languages[self.language_code]["messages"]
        self.root.title(self.tr("app_title"))
        self.hero_label.configure(text=self.tr("hero_title"))
        self.sub_label.configure(text=self.tr("hero_subtitle"))
        self.language_title.configure(text=self.tr("language_label"))
        self.language_box.configure(values=[self.language_label(code) for code in self.languages])
        selected_index = list(self.languages.keys()).index(self.language_code)
        self.language_box.current(selected_index)

        self.target_card.set_copy(
            self.tr("target_title"),
            self.tr("target_desc"),
            [
                (self.tr("target_pick_folder"), self.pick_target_folder),
                (self.tr("target_pick_file"), self.pick_target_file),
            ],
            self.tr("drop_hint_enabled") if DND_AVAILABLE else self.tr("drop_hint_disabled"),
        )
        self.source_card.set_copy(
            self.tr("source_title"),
            self.tr("source_desc"),
            [(self.tr("source_pick"), self.pick_source)],
            self.tr("drop_hint_enabled") if DND_AVAILABLE else self.tr("drop_hint_disabled"),
        )
        self.summary.set_title(self.tr("summary_title"))
        self.preview.set_copy(self.tr("preview_title"), self.tr("preview_desc"))
        self.apply_button.configure(text=self.tr("apply_button"))
        self.set_status(self.tr("status_ready"), MUTED)
        self.refresh_panels()

    def change_language(self, _event: object) -> None:
        labels = [self.language_label(code) for code in self.languages]
        index = self.language_box.current()
        if index < 0 or index >= len(labels):
            return
        self.language_code = list(self.languages.keys())[index]
        save_language(self.language_code)
        self.apply_language()

    def pick_target_folder(self) -> None:
        selected = filedialog.askdirectory(title=self.tr("dialog_pick_folder"))
        if selected:
            self.target_card.set_path(Path(selected))

    def pick_target_file(self) -> None:
        selected = filedialog.askopenfilename(
            title=self.tr("dialog_pick_target_file"),
            filetypes=[
                (self.tr("dialog_target_filter"), "*.lnk *.exe"),
                (self.tr("dialog_all_files"), "*.*"),
            ],
        )
        if selected:
            self.target_card.set_path(Path(selected))

    def pick_source(self) -> None:
        selected = filedialog.askopenfilename(
            title=self.tr("dialog_pick_source"),
            filetypes=[
                (self.tr("dialog_source_filter"), "*.png *.jpg *.jpeg *.ico *.exe"),
                (self.tr("dialog_all_files"), "*.*"),
            ],
        )
        if selected:
            self.source_card.set_path(Path(selected))

    def set_status(self, text: str, color: str = MUTED) -> None:
        self.status_var.set(text)
        self.status_label.configure(fg=color)
        self.root.update_idletasks()

    def validate_target(self, path: Path) -> None:
        if not path.exists():
            raise ValueError(self.tr("error_target_missing"))
        if path.is_dir():
            return
        if path.suffix.lower() not in SUPPORTED_TARGETS:
            raise ValueError(self.tr("error_target_unsupported"))

    def validate_source(self, path: Path) -> None:
        if not path.exists() or path.is_dir():
            raise ValueError(self.tr("error_source_missing"))
        if path.suffix.lower() not in SUPPORTED_ICON_SOURCES:
            raise ValueError(self.tr("error_source_unsupported"))

    def refresh_panels(self) -> None:
        target = self.target_card.get_path()
        source = self.source_card.get_path()

        if not target:
            self.summary.update_target(self.tr("summary_target_empty"))
        elif not target.exists():
            self.summary.update_target(self.tr("summary_target_missing"))
        elif target.is_dir():
            self.summary.update_target(self.tr("summary_target_folder", name=target.name))
        elif target.suffix.lower() == ".lnk":
            self.summary.update_target(self.tr("summary_target_shortcut", name=target.name))
        else:
            self.summary.update_target(self.tr("summary_target_exe", name=target.name))

        if not source:
            self.summary.update_source(self.tr("summary_source_empty"))
            self.preview.clear()
        elif not source.exists():
            self.summary.update_source(self.tr("summary_source_missing"))
            self.preview.clear()
        else:
            kind = detect_source_kind(source, self.tr)
            self.summary.update_source(self.tr("summary_source_value", kind=kind, name=source.name))
            try:
                self.preview.show(preview_image_from_source(source))
            except Exception:
                self.preview.clear()

    def apply_change(self) -> None:
        target = self.target_card.get_path()
        source = self.source_card.get_path()
        if not target or not source:
            self.set_status(self.tr("error_missing_paths"), ERROR)
            return
        try:
            self.validate_target(target)
            self.validate_source(source)
            self.set_status(self.tr("status_processing"), ACCENT)
            if target.is_dir():
                icon_path = apply_icon_to_folder(target, source)
                self.set_status(self.tr("status_done_folder", icon_path=icon_path), SUCCESS)
            elif target.suffix.lower() == ".lnk":
                icon_path = apply_icon_to_shortcut(target, source)
                self.set_status(self.tr("status_done_shortcut", icon_path=icon_path), SUCCESS)
            else:
                shortcut, icon_path = create_shortcut_for_exe(target, source)
                self.set_status(self.tr("status_done_exe", shortcut_name=shortcut.name, icon_path=icon_path), SUCCESS)
        except Exception as exc:
            self.set_status(self.tr("status_failed", error=exc), ERROR)


def main() -> int:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    ICON_ROOT.mkdir(parents=True, exist_ok=True)
    root = create_root()
    IconToolApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
