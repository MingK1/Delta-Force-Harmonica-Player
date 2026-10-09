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
        root.title("DFPlayer MIDI Player")
        root.geometry("760x440")
        root.minsize(600, 380)

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
        self._hk_dialog: tk.Toplevel | None = None
        self._hk_listening: str | None = None  # 正在改键的动作名
        self._hk_labels: dict[str, ttk.Label] = {}
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
    def _build_ui(self) -> None:
        opts = self.player.options

        # --- 顶部 ---
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="选择乐谱目录", command=self._select_dir).pack(side="left")
        ttk.Button(top, text="刷新", command=self._refresh_dir).pack(side="left", padx=4)
        ttk.Button(top, text="清空歌单", command=self._clear_list).pack(side="left")
        ttk.Button(top, text="热键设置", command=self._open_hotkey_settings).pack(side="right")

        # --- 歌单 ---
        list_frame = ttk.LabelFrame(self.root, text="歌单（单击选中 / 双击播放）", padding=4)
        list_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.song_list = tk.Listbox(list_frame, height=6, activestyle="dotbox")
        self.song_list.pack(side="left", fill="both", expand=True)
        self.song_list.bind("<<ListboxSelect>>", self._on_select_song)
        self.song_list.bind("<Double-Button-1>", self._on_double_click)
        sb = ttk.Scrollbar(list_frame, command=self.song_list.yview)
        sb.pack(side="right", fill="y")
        self.song_list.config(yscrollcommand=sb.set)

        # --- 主旋律声部 ---
        track_frame = ttk.LabelFrame(self.root, text="主旋律声部", padding=4)
        track_frame.pack(fill="x", padx=8, pady=2)
        self.track_combo = ttk.Combobox(track_frame, state="readonly")
        self.track_combo.pack(side="left", fill="x", expand=True)
        self.track_combo.bind("<<ComboboxSelected>>", self._on_track_selected)

        # --- 播放控制 ---
        ctrl = ttk.Frame(self.root, padding=6)
        ctrl.pack(fill="x")
        ttk.Button(ctrl, text="⏮ 上一首", command=self._prev).pack(side="left")
        self.play_btn = ttk.Button(ctrl, text="▶ 播放/暂停", command=self._play_pause)
        self.play_btn.pack(side="left", padx=4)
        ttk.Button(ctrl, text="⏭ 下一首", command=self._next).pack(side="left")
        ttk.Button(ctrl, text="⏹ 停止", command=self._stop).pack(side="left", padx=4)

        # --- 进度条 ---
        prog = ttk.Frame(self.root, padding=(8, 2))
        prog.pack(fill="x")
        self.time_label = ttk.Label(prog, text="00:00 / 00:00", width=14)
        self.time_label.pack(side="left")
        self.progress = ttk.Scale(prog, from_=0, to=1000, orient="horizontal")
        self.progress.pack(side="left", fill="x", expand=True, padx=6)
        self.progress.bind("<ButtonPress-1>", lambda e: setattr(self, "_seeking", True))
        self.progress.bind("<ButtonRelease-1>", self._on_seek)

        self.note_label = ttk.Label(self.root, text="当前音：—", anchor="w", foreground="#1a6")
        self.note_label.pack(fill="x", padx=8)

        # --- 参数面板 ---
        params = ttk.LabelFrame(self.root, text="演奏参数", padding=6)
        params.pack(fill="x", padx=8, pady=4)

        # 倍速
        ttk.Label(params, text="倍速").grid(row=0, column=0, sticky="w")
        self.speed_var = tk.StringVar(value=str(opts.speed))
        speed_spin = ttk.Spinbox(params, from_=0.1, to=3.0, increment=0.05,
                                 width=5, textvariable=self.speed_var,
                                 command=self._on_speed)
        speed_spin.grid(row=0, column=1, sticky="w", padx=4)
        speed_spin.bind("<FocusOut>", self._on_speed)
        speed_spin.bind("<Return>", self._on_speed)
        ttk.Label(params, text="×").grid(row=0, column=2, sticky="w")

        # 移调
        ttk.Label(params, text="移调(半音)").grid(row=0, column=3, sticky="w", padx=(12, 0))
        self.transpose_var = tk.IntVar(value=opts.transpose)
        ttk.Spinbox(params, from_=-24, to=24, width=5, textvariable=self.transpose_var,
                    command=self._on_transpose).grid(row=0, column=4, padx=4)
        ttk.Button(params, text="一键进音域", command=self._one_key_transpose).grid(row=0, column=5)

        # 旋律提取模式
        ttk.Label(params, text="旋律提取").grid(row=1, column=0, sticky="w", pady=4)
        self.melody_var = tk.StringVar(value=opts.melody_mode.value)
        melody_combo = ttk.Combobox(params, textvariable=self.melody_var, state="readonly",
                                    width=12, values=[m.value for m in MelodyMode])
        melody_combo.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)
        melody_combo.bind("<<ComboboxSelected>>", self._on_melody_mode)

        # 去空拍
        self.trim_var = tk.BooleanVar(value=opts.trim_leading)
        ttk.Checkbutton(params, text="去除开头空拍", variable=self.trim_var,
                        command=self._on_toggle).grid(row=1, column=3, columnspan=3, sticky="w", pady=4)

        # --- 日志 ---
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=2)
        log_frame.pack(fill="both", expand=False, padx=8, pady=(2, 6))
        self.log_text = tk.Text(log_frame, height=4, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

        hk = self._cfg["hotkeys"]
        self._log(f"就绪。热键：{hk['play_pause']}=播放/暂停 {hk['prev']}=上一首 "
                  f"{hk['next']}=下一首 {hk['stop']}=停止")
        if not isnd.IS_WINDOWS:
            self._log("非 Windows 环境，仅可预览界面。")

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

        ttk.Label(dlg, text="点击「改键」后按下新热键", foreground="#666").grid(
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
        ttk.Button(dlg, text="保存", command=lambda: self._save_hotkeys(dlg)).grid(
            row=btn_row, column=1, sticky="e", padx=4, pady=12)
        ttk.Button(dlg, text="取消", command=dlg.destroy).grid(
            row=btn_row, column=2, sticky="w", padx=8, pady=12)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    def _start_hotkey_listen(self, dlg: tk.Toplevel, action: str) -> None:
        self._hk_listening = action
        self._hk_labels[action].config(text="请按键…", foreground="#c00")
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
            self._hk_labels[self._hk_listening].config(text="无效键", foreground="#c00")
            return
        # 查重
        for k, v in self._cfg["hotkeys"].items():
            if k != self._hk_listening and v == name:
                messagebox.showwarning("键位冲突", f"该键已被「{dict(self._HK_ACTIONS)[k]}」占用。")
                return
        self._cfg["hotkeys"][self._hk_listening] = name
        self._hk_labels[self._hk_listening].config(text=name, foreground="#000")
        self._hk_listening = None
        if self._hk_dialog is not None:
            self._hk_dialog.unbind("<Key>")

    def _save_hotkeys(self, dlg: tk.Toplevel) -> None:
        self._setup_hotkeys()
        self._log(f"热键已更新：{self._cfg['hotkeys']}")
        dlg.destroy()

    # ================= 歌单 =================
    def _select_dir(self) -> None:
        folder = filedialog.askdirectory(title="选择乐谱目录")
        if not folder:
            return
        self._midi_dir = folder
        self._load_dir()

    def _refresh_dir(self) -> None:
        if not self._midi_dir:
            self._log("请先选择乐谱目录。")
            return
        self._load_dir()

    def _load_dir(self) -> None:
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

    def _refresh_song_list(self) -> None:
        self.song_list.delete(0, "end")
        for i, s in enumerate(self.player.songs):
            self.song_list.insert("end", f"{i + 1}. {s.name}")
        if self.player.current_index >= 0:
            self._select_song_row(self.player.current_index)

    def _select_song_row(self, index: int) -> None:
        self.song_list.selection_clear(0, "end")
        if 0 <= index < self.song_list.size():
            self.song_list.selection_set(index)
            self.song_list.see(index)

    def _on_select_song(self, _evt=None) -> None:
        """单击选中曲目：加载其独立设置到 UI。"""
        sel = self.song_list.curselection()
        if not sel:
            return
        idx = sel[0]
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
        self._refresh_track_combo(idx)
        self._log(f"选中：{song.name}")

    def _on_double_click(self, _evt=None) -> None:
        """双击播放。"""
        sel = self.song_list.curselection()
        if sel:
            self.player.play_index(sel[0])

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

    # ================= 播放 =================
    def _play_pause(self) -> None:
        if not self.player.songs:
            self._log("歌单为空，请先选择乐谱目录。")
            return
        self.player.play()

    def _stop(self) -> None:
        self.player.stop()

    def _next(self) -> None:
        if self.player.next():
            self._after_play_change()

    def _prev(self) -> None:
        if self.player.prev():
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
            self._log(f"♪ 正在演奏：{song.name}")

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
        self.player.options.transpose = int(self.transpose_var.get())
        if self.engine.is_running:
            self.player.apply_transpose_live()

    def _one_key_transpose(self) -> None:
        if not self.player.current and self.player.songs:
            self.player.current_index = 0
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
            self.play_btn.config(text="▶ 播放/暂停")
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
