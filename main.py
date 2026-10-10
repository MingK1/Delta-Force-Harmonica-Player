"""DFPlayer MIDI 演奏器主界面。

轻量音乐播放器：选择乐谱目录 → 单击选中曲目 → 双击播放 → 自动停止。
每首曲目独立保存：声部、倍速、旋律提取模式。
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import config as cfg
import input_sender as isnd
from hotkeys import HotkeyManager, VK_CODE_TO_NAME, VK_NAME_TO_CODE
from note_mapper import MelodyMode
from player import Player
from playback_engine import PlaybackEngine

MIDI_EXTS = {".mid", ".midi", ".kar", ".rmi"}


def _scan_midi_dir(folder: str) -> list[str]:
    """递归扫描目录下所有 MIDI 文件，返回排序后的路径列表。"""
    if not folder or not os.path.isdir(folder):
        return []
    found: list[str] = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in MIDI_EXTS:
                found.append(os.path.join(root, f))
    found.sort(key=lambda p: os.path.basename(p).lower())
    return found


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("DFPlayer")
        root.geometry("980x600")
        root.minsize(900, 560)
        root.configure(bg="#F5F5F7")

        self.engine = PlaybackEngine()
        self.player = Player(self.engine)
        self.hotkeys = HotkeyManager()

        self._cfg = cfg.load()
        self.player.options = cfg.apply_to_options(self._cfg)
        self._midi_dir = self._cfg.get("midi_dir", "")
        self._song_settings: dict[str, dict] = self._cfg.get("song_settings", {})

        self.engine.on_log = lambda m: self.root.after(0, self._log, m)
        self.engine.on_note = lambda s: self.root.after(0, self._set_current_note, s)

        self._seeking = False
        self._filtered_indices: list[int] = []
        self._search_var = tk.StringVar()
        self._status_var = tk.StringVar(value="就绪")
        self._directory_var = tk.StringVar(value="未选择乐谱目录")
        self._current_song_var = tk.StringVar(value="未选择曲目")
        self._current_path_var = tk.StringVar(value="")
        self._log_visible = False
        self._hotkey_snapshot: dict[str, str] | None = None
        self._action_buttons: dict[str, ttk.Button] = {}
        self._workspace = None
        self._empty_state = None
        self._hk_dialog: tk.Toplevel | None = None
        self._hk_listening: str | None = None  # 正在改键的动作名
        self._hk_labels: dict[str, ttk.Label] = {}
        self._configure_style()
        self._build_ui()
        self._setup_hotkeys()
        self._restore_dir()

        self._tick()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _song_key(self, path: str) -> str:
        """用相对乐谱目录的路径保存设置，避免不同子目录同名冲突。"""
        try:
            base = os.path.abspath(self._midi_dir)
            key = os.path.relpath(os.path.abspath(path), base)
        except (OSError, ValueError):
            key = os.path.abspath(path)
        return os.path.normcase(key).replace(os.sep, "/")

    def _apply_song_settings(self, song) -> None:
        """把已保存的曲目设置恢复到 Song 对象上。"""
        key = self._song_key(song.path)
        s = self._song_settings.get(key)
        if s is None:
            # 兼容旧版本按 basename 保存的配置。
            s = self._song_settings.get(os.path.basename(song.path))
        if s:
            if isinstance(s.get("part"), int) and s["part"] >= 0:
                song.selected_part_index = s["part"]
            if isinstance(s.get("speed"), (int, float)):
                song.speed = float(s["speed"])
            try:
                song.melody_mode = MelodyMode[s.get("melody_mode", "RAW")]
            except KeyError:
                song.melody_mode = MelodyMode.RAW

    def _restore_dir(self) -> None:
        if not self._midi_dir or not os.path.isdir(self._midi_dir):
            return
        self._directory_var.set(self._short_path(self._midi_dir))
        files = _scan_midi_dir(self._midi_dir)
        if files:
            self.player.add(files)
            # 恢复每首曲目的独立设置
            for song in self.player.songs:
                self._apply_song_settings(song)
            self._refresh_song_list()
            self._log(f"已从目录载入 {len(files)} 首 MIDI：{self._midi_dir}")
        else:
            self._log(f"目录下未找到 MIDI 文件：{self._midi_dir}")

    # ================= UI =================
    def _configure_style(self) -> None:
        """建立轻量的 macOS 风格视觉基础，仍使用系统 ttk 控件。"""
        self._colors = {
            "app": "#F5F5F7",
            "card": "#FFFFFF",
            "text": "#1D1D1F",
            "muted": "#6E6E73",
            "line": "#D2D2D7",
            "blue": "#0A84FF",
            "blue_dark": "#0068D9",
            "green": "#248A3D",
            "red": "#D70015",
            "status": "#E9E9ED",
        }
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=self._colors["app"])
        style.configure("Card.TFrame", background=self._colors["card"])
        style.configure("Toolbar.TFrame", background=self._colors["app"])
        style.configure("Status.TFrame", background=self._colors["status"])
        style.configure("Title.TLabel", background=self._colors["app"],
                        foreground=self._colors["text"],
                        font=("Segoe UI Semibold", 20))
        style.configure("Subtitle.TLabel", background=self._colors["app"],
                        foreground=self._colors["muted"], font=("Segoe UI", 9))
        style.configure("Section.TLabel", background=self._colors["card"],
                        foreground=self._colors["text"], font=("Segoe UI Semibold", 12))
        style.configure("Card.TLabel", background=self._colors["card"],
                        foreground=self._colors["text"], font=("Segoe UI", 10))
        style.configure("Muted.Card.TLabel", background=self._colors["card"],
                        foreground=self._colors["muted"], font=("Segoe UI", 9))
        style.configure("Current.TLabel", background=self._colors["card"],
                        foreground=self._colors["green"], font=("Segoe UI Semibold", 11))
        style.configure("Status.TLabel", background=self._colors["status"],
                        foreground=self._colors["muted"], font=("Segoe UI", 9))
        style.configure("Accent.TButton", background=self._colors["blue"],
                        foreground="#FFFFFF", borderwidth=0, padding=(12, 7),
                        font=("Segoe UI Semibold", 9))
        style.map("Accent.TButton", background=[("active", self._colors["blue_dark"]),
                                                  ("disabled", "#B8D8FA")])
        style.configure("Secondary.TButton", background=self._colors["card"],
                        foreground=self._colors["text"], borderwidth=1,
                        relief="solid", padding=(10, 6), font=("Segoe UI", 9))
        style.map("Secondary.TButton", background=[("active", "#E5E5EA"),
                                                    ("disabled", "#F0F0F2")],
                  foreground=[("disabled", "#A1A1A6")])
        style.configure("Ghost.TButton", background=self._colors["app"],
                        foreground=self._colors["blue"], borderwidth=0,
                        padding=(8, 5), font=("Segoe UI", 9))
        style.map("Ghost.TButton", background=[("active", "#E5E5EA")])
        style.configure("Card.TLabelframe", background=self._colors["card"],
                        borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", background=self._colors["card"],
                        foreground=self._colors["text"], font=("Segoe UI Semibold", 10))
        style.configure("TEntry", padding=(8, 6), fieldbackground="#FFFFFF")
        style.configure("TCombobox", padding=(6, 5))
        style.configure("TCheckbutton", background=self._colors["card"],
                        foreground=self._colors["text"])
        style.configure("Horizontal.TScale", background=self._colors["card"],
                        troughcolor="#D2D2D7")

    def _build_ui(self) -> None:
        opts = self.player.options
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(18, 14, 18, 10))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="DFPlayer", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(toolbar, textvariable=self._directory_var, style="Subtitle.TLabel",
                  anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        toolbar_actions = ttk.Frame(toolbar, style="Toolbar.TFrame")
        toolbar_actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self.select_dir_btn = ttk.Button(toolbar_actions, text="选择乐谱目录",
                                         style="Accent.TButton", command=self._select_dir)
        self.select_dir_btn.pack(side="left")
        self.refresh_btn = ttk.Button(toolbar_actions, text="↻ 刷新",
                                      style="Secondary.TButton", command=self._refresh_dir)
        self.refresh_btn.pack(side="left", padx=(8, 0))
        self.hotkey_btn = ttk.Button(toolbar_actions, text="⌘ 热键",
                                     style="Secondary.TButton", command=self._open_hotkey_settings)
        self.hotkey_btn.pack(side="left", padx=(8, 0))

        content = ttk.Frame(self.root, style="App.TFrame", padding=(18, 0, 18, 12))
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, minsize=240, weight=0)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        left = ttk.Frame(content, style="Card.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        left_header = ttk.Frame(left, style="Card.TFrame")
        left_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        left_header.columnconfigure(0, weight=1)
        ttk.Label(left_header, text="歌单", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.song_count_label = ttk.Label(left_header, text="0 首曲目", style="Muted.Card.TLabel")
        self.song_count_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        clear_btn = ttk.Button(left_header, text="清空", style="Ghost.TButton", command=self._clear_list)
        clear_btn.grid(row=0, column=1, rowspan=2, sticky="e")
        search = ttk.Entry(left, textvariable=self._search_var)
        search.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        search.insert(0, "搜索曲目")
        search.configure(foreground=self._colors["muted"])
        search.bind("<FocusIn>", lambda _event: self._clear_search_placeholder(search))
        search.bind("<FocusOut>", lambda _event: self._restore_search_placeholder(search))
        search.bind("<KeyRelease>", self._on_search)
        self.search_entry = search
        list_frame = ttk.Frame(left, style="Card.TFrame")
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.song_list = tk.Listbox(
            list_frame, height=10, relief="flat", borderwidth=0,
            highlightthickness=0, bg=self._colors["card"], fg=self._colors["text"],
            selectbackground=self._colors["blue"], selectforeground="#FFFFFF",
            font=("Segoe UI", 10), activestyle="none", exportselection=False)
        self.song_list.grid(row=0, column=0, sticky="nsew")
        self.song_list.bind("<<ListboxSelect>>", self._on_select_song)
        self.song_list.bind("<Double-Button-1>", self._on_double_click)
        sb = ttk.Scrollbar(list_frame, command=self.song_list.yview)
        sb.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.song_list.config(yscrollcommand=sb.set)

        right = ttk.Frame(content, style="Card.TFrame", padding=20)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self._empty_state = ttk.Frame(right, style="Card.TFrame", padding=30)
        self._empty_state.grid(row=0, column=0, sticky="nsew")
        ttk.Label(self._empty_state, text="还没有乐谱", style="Section.TLabel").pack(pady=(90, 8))
        ttk.Label(self._empty_state, text="选择一个目录，DFPlayer 会自动载入 MIDI 文件。",
                  style="Muted.Card.TLabel").pack()
        ttk.Label(self._empty_state, text="支持 .mid、.midi、.kar、.rmi", style="Muted.Card.TLabel").pack(pady=(4, 18))
        ttk.Button(self._empty_state, text="选择乐谱目录", style="Accent.TButton",
                   command=self._select_dir).pack()

        self._workspace = ttk.Frame(right, style="Card.TFrame")
        self._workspace.columnconfigure(0, weight=1)
        self._workspace.grid(row=0, column=0, sticky="nsew")
        header = ttk.Frame(self._workspace, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self._current_song_var, style="Section.TLabel").grid(
            row=0, column=0, sticky="w")
        self._current_path_label = ttk.Label(header, textvariable=self._current_path_var,
                                             style="Muted.Card.TLabel", anchor="w")
        self._current_path_label.grid(row=1, column=0, sticky="ew", pady=(3, 0))

        track_frame = ttk.LabelFrame(self._workspace, text="主旋律声部", style="Card.TLabelframe", padding=10)
        track_frame.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        track_frame.columnconfigure(0, weight=1)
        self.track_combo = ttk.Combobox(track_frame, state="readonly")
        self.track_combo.grid(row=0, column=0, sticky="ew")
        self.track_combo.bind("<<ComboboxSelected>>", self._on_track_selected)

        prog = ttk.Frame(self._workspace, style="Card.TFrame")
        prog.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        prog.columnconfigure(1, weight=1)
        self.time_label = ttk.Label(prog, text="00:00 / 00:00", width=13,
                                    style="Muted.Card.TLabel")
        self.time_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Scale(prog, from_=0, to=1000, orient="horizontal",
                                 style="Horizontal.TScale")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.progress.bind("<ButtonPress-1>", lambda _event: setattr(self, "_seeking", True))
        self.progress.bind("<ButtonRelease-1>", self._on_seek)

        ctrl = ttk.Frame(self._workspace, style="Card.TFrame")
        ctrl.grid(row=3, column=0, sticky="w", pady=(14, 0))
        self.prev_btn = ttk.Button(ctrl, text="⏮ 上一首", style="Secondary.TButton", command=self._prev)
        self.prev_btn.pack(side="left")
        self.play_btn = ttk.Button(ctrl, text="▶ 播放", style="Accent.TButton", command=self._play_pause)
        self.play_btn.pack(side="left", padx=8)
        self.next_btn = ttk.Button(ctrl, text="⏭ 下一首", style="Secondary.TButton", command=self._next)
        self.next_btn.pack(side="left")
        self.stop_btn = ttk.Button(ctrl, text="⏹ 停止", style="Secondary.TButton", command=self._stop)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self._action_buttons = {"prev": self.prev_btn, "play": self.play_btn,
                                "next": self.next_btn, "stop": self.stop_btn}

        note_card = ttk.Frame(self._workspace, style="Card.TFrame")
        note_card.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        self.note_label = ttk.Label(note_card, text="当前音：—", style="Current.TLabel", anchor="w")
        self.note_label.pack(fill="x")

        params = ttk.LabelFrame(self._workspace, text="演奏参数", style="Card.TLabelframe", padding=12)
        params.grid(row=5, column=0, sticky="new", pady=(18, 0))
        for col in range(6):
            params.columnconfigure(col, weight=1 if col in (1, 4) else 0)
        ttk.Label(params, text="倍速", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.speed_var = tk.StringVar(value=str(opts.speed))
        speed_spin = ttk.Spinbox(params, from_=0.1, to=3.0, increment=0.05, width=6,
                                 textvariable=self.speed_var, command=self._on_speed)
        speed_spin.grid(row=0, column=1, sticky="w", padx=(8, 4))
        speed_spin.bind("<FocusOut>", self._on_speed)
        speed_spin.bind("<Return>", self._on_speed)
        ttk.Label(params, text="×", style="Muted.Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Label(params, text="移调", style="Card.TLabel").grid(row=0, column=3, sticky="w", padx=(22, 0))
        self.transpose_var = tk.IntVar(value=opts.transpose)
        transpose_spin = ttk.Spinbox(params, from_=-24, to=24, width=6,
                                     textvariable=self.transpose_var, command=self._on_transpose)
        transpose_spin.grid(row=0, column=4, sticky="w", padx=(8, 4))
        transpose_spin.bind("<FocusOut>", lambda _event: self._on_transpose())
        ttk.Button(params, text="一键进音域", style="Ghost.TButton",
                   command=self._one_key_transpose).grid(row=0, column=5, sticky="e")
        ttk.Label(params, text="旋律提取", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.melody_var = tk.StringVar(value=opts.melody_mode.value)
        melody_combo = ttk.Combobox(params, textvariable=self.melody_var, state="readonly",
                                    width=12, values=[m.value for m in MelodyMode])
        melody_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(12, 0))
        melody_combo.bind("<<ComboboxSelected>>", self._on_melody_mode)
        self.trim_var = tk.BooleanVar(value=opts.trim_leading)
        ttk.Checkbutton(params, text="去除开头空拍", variable=self.trim_var,
                        command=self._on_toggle).grid(row=1, column=3, columnspan=3,
                                                       sticky="w", padx=(22, 0), pady=(12, 0))

        log_header = ttk.Frame(self._workspace, style="Card.TFrame")
        log_header.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        ttk.Label(log_header, text="诊断日志", style="Muted.Card.TLabel").pack(side="left")
        self.log_toggle_btn = ttk.Button(log_header, text="显示日志", style="Ghost.TButton",
                                         command=self._toggle_log)
        self.log_toggle_btn.pack(side="right")
        self.log_frame = ttk.Frame(self._workspace, style="Card.TFrame")
        self.log_text = tk.Text(self.log_frame, height=4, state="disabled", wrap="word",
                                relief="flat", borderwidth=0, bg="#F7F7F9",
                                fg=self._colors["muted"], font=("Consolas", 9), padx=8, pady=8)
        self.log_text.pack(fill="both", expand=True)

        status = ttk.Frame(self.root, style="Status.TFrame", padding=(18, 7))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self._status_var, style="Status.TLabel", anchor="w").grid(
            row=0, column=0, sticky="ew")
        hk = self._cfg["hotkeys"]
        self._log(f"就绪。热键：{hk['play_pause']}=播放/暂停 {hk['prev']}=上一首 "
                  f"{hk['next']}=下一首 {hk['stop']}=停止")
        if not isnd.IS_WINDOWS:
            self._log("非 Windows 环境，仅可预览界面。")
        self._refresh_song_list()

    def _clear_search_placeholder(self, entry: ttk.Entry) -> None:
        if self._search_var.get() == "搜索曲目":
            self._search_var.set("")
            entry.configure(foreground=self._colors["text"])

    def _restore_search_placeholder(self, entry: ttk.Entry) -> None:
        if not self._search_var.get().strip():
            self._search_var.set("搜索曲目")
            entry.configure(foreground=self._colors["muted"])

    def _on_search(self, _event=None) -> None:
        self._refresh_song_list()

    @staticmethod
    def _short_path(path: str, limit: int = 72) -> str:
        if len(path) <= limit:
            return path
        return "…" + path[-(limit - 1):]

    def _set_workspace_visibility(self) -> None:
        has_song = self.player.current is not None
        if has_song:
            self._empty_state.grid_remove()
            self._workspace.grid()
        else:
            self._workspace.grid_remove()
            self._empty_state.grid()

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_frame.grid(row=7, column=0, sticky="nsew", pady=(6, 0))
            self.log_toggle_btn.config(text="隐藏日志")
        else:
            self.log_frame.grid_remove()
            self.log_toggle_btn.config(text="显示日志")

    def _update_action_state(self) -> None:
        has_song = bool(self.player.songs) and self.player.current is not None
        self._action_buttons["play"].configure(state="normal" if has_song else "disabled")
        self._action_buttons["prev"].configure(state="normal" if has_song else "disabled")
        self._action_buttons["next"].configure(state="normal" if has_song else "disabled")
        self._action_buttons["stop"].configure(
            state="normal" if self.engine.is_running else "disabled")

    # ================= 热键 =================
    def _setup_hotkeys(self) -> None:
        hk = self._cfg["hotkeys"]
        self.hotkeys.clear()
        self.hotkeys.bind(hk["play_pause"], lambda: self.root.after(0, self._play_pause))
        self.hotkeys.bind(hk["prev"], lambda: self.root.after(0, self._prev))
        self.hotkeys.bind(hk["next"], lambda: self.root.after(0, self._next))
        self.hotkeys.bind(hk["stop"], lambda: self.root.after(0, self._stop))
        self.hotkeys.start()

    # ================= 热键设置 =================
    _HK_ACTIONS = [
        ("play_pause", "播放/暂停"),
        ("prev", "上一首"),
        ("next", "下一首"),
        ("stop", "停止"),
    ]

    def _open_hotkey_settings(self) -> None:
        if self._hk_dialog is not None and self._hk_dialog.winfo_exists():
            self._hk_dialog.lift()
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("热键设置")
        dlg.geometry("340x240")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        self._hk_dialog = dlg
        self._hk_listening = None
        self._hk_labels = {}
        self._hotkey_snapshot = dict(self._cfg["hotkeys"])

        ttk.Label(dlg, text="点击「改键」后按下新热键", foreground=self._colors["muted"]).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))

        for i, (key, label) in enumerate(self._HK_ACTIONS):
            r = i + 1
            ttk.Label(dlg, text=label).grid(row=r, column=0, sticky="w", padx=12, pady=6)
            key_lbl = ttk.Label(dlg, text=self._cfg["hotkeys"].get(key, "F6"),
                                width=8, relief="sunken", anchor="center")
            key_lbl.grid(row=r, column=1, padx=4)
            self._hk_labels[key] = key_lbl
            ttk.Button(dlg, text="改键",
                       command=lambda k=key: self._start_hotkey_listen(dlg, k)).grid(
                row=r, column=2, padx=8)

        btn_row = len(self._HK_ACTIONS) + 1
        ttk.Button(dlg, text="保存", style="Accent.TButton",
                   command=lambda: self._save_hotkeys(dlg)).grid(
            row=btn_row, column=1, sticky="e", padx=4, pady=12)
        ttk.Button(dlg, text="取消", style="Secondary.TButton",
                   command=lambda: self._cancel_hotkeys(dlg)).grid(
            row=btn_row, column=2, sticky="w", padx=8, pady=12)

        dlg.protocol("WM_DELETE_WINDOW", lambda: self._cancel_hotkeys(dlg))

    def _start_hotkey_listen(self, dlg: tk.Toplevel, action: str) -> None:
        self._hk_listening = action
        self._hk_labels[action].config(text="请按键…", foreground=self._colors["red"])
        dlg.bind("<Key>", self._on_hotkey_press)
        dlg.focus_set()

    def _on_hotkey_press(self, event) -> None:
        if self._hk_listening is None:
            return
        vk = getattr(event, "keycode", None)
        name = VK_CODE_TO_NAME.get(vk)
        if name is None:
            # 回退：用 keysym（F6/a/5 等）
            ks = getattr(event, "keysym", "").upper()
            name = ks if ks in VK_NAME_TO_CODE else None
        if name is None:
            self._hk_labels[self._hk_listening].config(text="无效键", foreground=self._colors["red"])
            return
        # 查重
        for k, v in self._cfg["hotkeys"].items():
            if k != self._hk_listening and v == name:
                messagebox.showwarning("键位冲突", f"该键已被「{dict(self._HK_ACTIONS)[k]}」占用。")
                return
        self._cfg["hotkeys"][self._hk_listening] = name
        self._hk_labels[self._hk_listening].config(text=name, foreground=self._colors["text"])
        self._hk_listening = None
        if self._hk_dialog is not None:
            self._hk_dialog.unbind("<Key>")

    def _save_hotkeys(self, dlg: tk.Toplevel) -> None:
        self._setup_hotkeys()
        self._log(f"热键已更新：{self._cfg['hotkeys']}")
        self._hotkey_snapshot = None
        self._hk_dialog = None
        dlg.destroy()

    def _cancel_hotkeys(self, dlg: tk.Toplevel) -> None:
        if self._hotkey_snapshot is not None:
            self._cfg["hotkeys"] = dict(self._hotkey_snapshot)
        self._hotkey_snapshot = None
        self._hk_listening = None
        dlg.unbind("<Key>")
        self._hk_dialog = None
        dlg.destroy()

    # ================= 歌单 =================
    def _select_dir(self) -> None:
        folder = filedialog.askdirectory(title="选择乐谱目录")
        if not folder:
            return
        self._midi_dir = folder
        self._directory_var.set(self._short_path(folder))
        self._search_var.set("")
        self._restore_search_placeholder(self.search_entry)
        self._load_dir()

    def _refresh_dir(self) -> None:
        if not self._midi_dir:
            self._log("请先选择乐谱目录。")
            return
        self._load_dir()

    def _load_dir(self) -> None:
        self._directory_var.set(self._short_path(self._midi_dir) if self._midi_dir else "未选择乐谱目录")
        files = _scan_midi_dir(self._midi_dir)
        self.player.clear()
        self.track_combo.set("")
        self.track_combo["values"] = []
        if not files:
            self._refresh_song_list()
            self._log(f"目录下未找到 MIDI 文件：{self._midi_dir}")
            return
        self.player.add(files)
        for song in self.player.songs:
            self._apply_song_settings(song)
        self._refresh_song_list()
        self._log(f"已载入 {len(files)} 首 MIDI（来自 {self._midi_dir}）")

    def _clear_list(self) -> None:
        self.player.clear()
        self._refresh_song_list()
        self.track_combo.set("")
        self.track_combo["values"] = []
        self._current_song_var.set("未选择曲目")
        self._current_path_var.set("")
        self._log("歌单已清空。")

    def _refresh_song_list(self) -> None:
        query = self._search_var.get().strip().casefold()
        if query == "搜索曲目":
            query = ""
        self._filtered_indices = [
            index for index, song in enumerate(self.player.songs)
            if not query
            or query in song.name.casefold()
            or query in os.path.relpath(song.path, self._midi_dir or os.path.dirname(song.path)).casefold()
        ]
        self.song_list.delete(0, "end")
        for source_index in self._filtered_indices:
            song = self.player.songs[source_index]
            self.song_list.insert("end", song.name)
        total = len(self.player.songs)
        visible = len(self._filtered_indices)
        self.song_count_label.config(
            text=f"{visible} / {total} 首曲目" if query else f"{total} 首曲目")
        if self.player.current_index in self._filtered_indices:
            self._select_song_row(self.player.current_index)
        else:
            self.song_list.selection_clear(0, "end")
        if self.player.current:
            current = self.player.current
            self._current_song_var.set(current.name)
            self._current_path_var.set(self._short_path(current.path))
            self._refresh_track_combo(self.player.current_index)
        self._set_workspace_visibility()
        self._update_action_state()

    def _select_song_row(self, index: int) -> None:
        self.song_list.selection_clear(0, "end")
        if index in self._filtered_indices:
            row = self._filtered_indices.index(index)
            self.song_list.selection_set(row)
            self.song_list.see(row)

    def _on_select_song(self, _evt=None) -> None:
        """单击选中曲目：加载其独立设置到 UI。"""
        sel = self.song_list.curselection()
        if not sel:
            return
        row = sel[0]
        if not (0 <= row < len(self._filtered_indices)):
            return
        idx = self._filtered_indices[row]
        if idx == self.player.current_index:
            return  # 同一首
        self.player.current_index = idx
        song = self.player.current
        if not song:
            return
        # 加载曲目设置到 options（供 UI 显示）
        self.player.options.speed = song.speed
        self.player.options.melody_mode = song.melody_mode
        self.player.options.transpose = self.player.options.transpose  # 不移调
        # 刷新 UI 控件
        self.speed_var.set(str(song.speed))
        self.melody_var.set(song.melody_mode.value)
        self._current_song_var.set(song.name)
        self._current_path_var.set(self._short_path(song.path))
        self._refresh_track_combo(idx)
        self._log(f"选中：{song.name}")
        self._update_action_state()

    def _on_double_click(self, _evt=None) -> None:
        """双击播放。"""
        sel = self.song_list.curselection()
        if sel and 0 <= sel[0] < len(self._filtered_indices):
            self.player.play_index(self._filtered_indices[sel[0]])

    def _refresh_track_combo(self, song_index: int) -> None:
        song = self.player.songs[song_index] if 0 <= song_index < len(self.player.songs) else None
        if not song:
            return
        song.ensure_loaded()
        if not song.midi:
            return
        values = []
        for p in song.midi.parts:
            state = " [打击乐]" if p.is_drum else ""
            values.append(p.label() + state)
        self.track_combo["values"] = values
        if 0 <= song.selected_part_index < len(values):
            self.track_combo.current(song.selected_part_index)

    def _on_track_selected(self, _evt=None) -> None:
        song = self.player.current
        if not song or not song.midi:
            return
        idx = self.track_combo.current()
        if 0 <= idx < len(song.midi.parts):
            if song.midi.parts[idx].is_drum:
                messagebox.showinfo("提示", "打击乐轨不适合作为旋律，请另选。")
                self._refresh_track_combo(self.player.current_index)
                return
            song.selected_part_index = idx
            if self.engine.is_running:
                self.player.apply_transpose_live()
            self._log(f"声部已切换：{song.midi.parts[idx].label()}")

    # ================= 播放 =================
    def _play_pause(self) -> None:
        if not self.player.songs:
            self._log("歌单为空，请先选择乐谱目录。")
            return
        if self.player.play():
            self._log(f"正在播放：{self.player.current.name}" if self.player.current else "播放中。")
        self._update_action_state()

    def _stop(self) -> None:
        self.player.stop()
        self._log("已停止。")
        self._update_action_state()

    def _next(self) -> None:
        if not self._filtered_indices:
            return
        current = self.player.current_index
        try:
            position = self._filtered_indices.index(current)
        except ValueError:
            position = -1
        target = self._filtered_indices[min(position + 1, len(self._filtered_indices) - 1)]
        if self.player.play_index(target):
            self._after_play_change()

    def _prev(self) -> None:
        if not self._filtered_indices:
            return
        current = self.player.current_index
        try:
            position = self._filtered_indices.index(current)
        except ValueError:
            position = len(self._filtered_indices)
        target = self._filtered_indices[max(position - 1, 0)]
        if self.player.play_index(target):
            self._after_play_change()

    def _after_play_change(self) -> None:
        """播放曲目变更后刷新 UI。"""
        idx = self.player.current_index
        song = self.player.current
        if song:
            self._select_song_row(idx)
            self._refresh_track_combo(idx)
            self.speed_var.set(str(song.speed))
            self.melody_var.set(song.melody_mode.value)
            self._current_song_var.set(song.name)
            self._current_path_var.set(self._short_path(song.path))
            self._log(f"♪ 正在演奏：{song.name}")
        self._update_action_state()

    def _on_speed(self, _evt=None) -> None:
        try:
            v = float(self.speed_var.get())
            v = max(0.1, min(v, 3.0))
        except (ValueError, TypeError):
            v = self.player.options.speed
            self.speed_var.set(str(v))
        self.player.options.speed = v
        # 保存到当前曲目
        song = self.player.current
        if song:
            song.speed = v
        if self.engine.is_running:
            self.engine.speed = v

    def _on_transpose(self) -> None:
        try:
            value = max(-24, min(24, int(self.transpose_var.get())))
        except (TypeError, ValueError):
            value = self.player.options.transpose
        self.transpose_var.set(value)
        self.player.options.transpose = value
        if self.engine.is_running:
            self.player.apply_transpose_live()

    def _one_key_transpose(self) -> None:
        if not self.player.current and self.player.songs:
            self.player.current_index = 0
        if not self.player.current:
            self._log("请先选择一首曲目。")
            return
        t = self.player.one_key_transpose()
        self.transpose_var.set(t)
        self._log(f"一键移调：{t:+d} 半音")
        if self.engine.is_running:
            self.player.apply_transpose_live()

    def _on_toggle(self) -> None:
        self.player.options.trim_leading = self.trim_var.get()

    def _on_melody_mode(self, _evt=None) -> None:
        for m in MelodyMode:
            if m.value == self.melody_var.get():
                self.player.options.melody_mode = m
                # 保存到当前曲目
                song = self.player.current
                if song:
                    song.melody_mode = m
                self._log(f"旋律提取模式：{m.value}")
                break

    def _on_seek(self, _evt=None) -> None:
        if self.engine.is_running and self.engine.total > 0:
            frac = self.progress.get() / 1000.0
            self.engine.seek_fraction(frac)
        self._seeking = False

    # ================= 刷新 =================
    def _set_current_note(self, s: str) -> None:
        self.note_label.config(text=f"当前音：{s or '—'}")

    def _tick(self) -> None:
        if self.engine.is_running and self.engine.total > 0:
            elapsed, total = self.engine.elapsed, self.engine.total
            if not self._seeking:
                self.progress.set(min(1000, elapsed / total * 1000))
            self.time_label.config(text=f"{self._fmt(elapsed)} / {self._fmt(total)}")
            self.play_btn.config(text="▶ 继续" if self.engine.is_paused else "⏸ 暂停")
        else:
            self.play_btn.config(text="▶ 播放")
        self._update_action_state()
        self.root.after(100, self._tick)

    @staticmethod
    def _fmt(sec: float) -> str:
        sec = max(0, int(sec))
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self._status_var.set(msg)

    # ================= 退出 =================
    def _collect_config(self) -> dict:
        # 收集每首曲目的当前设置
        settings = {}
        for song in self.player.songs:
            key = self._song_key(song.path)
            settings[key] = {
                "part": song.selected_part_index,
                "speed": song.speed,
                "melody_mode": song.melody_mode.name,
            }
        return {
            "speed": self.player.options.speed,
            "transpose": self.player.options.transpose,
            "trim_leading": self.player.options.trim_leading,
            "melody_mode": self.player.options.melody_mode.name,
            "hotkeys": self._cfg["hotkeys"],
            "midi_dir": self._midi_dir,
            "song_settings": settings,
        }

    def _on_close(self) -> None:
        try:
            self.engine.stop()
            self.hotkeys.stop()
            cfg.save(self._collect_config())
        finally:
            isnd.release_everything()
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
