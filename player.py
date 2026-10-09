"""歌单播放器：管理曲目列表，串起 MIDI 加载与播放引擎。

职责：维护歌单顺序与当前曲目指针，把选定曲目的主旋律映射后交给 PlaybackEngine 演奏。
演奏时序细节全在引擎里。播放完一曲自动停止，不会有自动切歌行为。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

import note_mapper as nm
from midi_loader import MidiFile, Part
from note_mapper import MelodyMode
from playback_engine import PlaybackEngine


@dataclass
class Song:
    """歌单里的一首曲子。MIDI 延迟加载，选中时才解析。"""
    path: str
    midi: Optional[MidiFile] = None
    selected_part_index: int = -1
    speed: float = 1.0
    melody_mode: MelodyMode = MelodyMode.RAW

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def ensure_loaded(self) -> None:
        if self.midi is None:
            self.midi = MidiFile(self.path)
            if self.selected_part_index < 0:
                for i, p in enumerate(self.midi.parts):
                    if p.recommended:
                        self.selected_part_index = i
                        break
            if not (0 <= self.selected_part_index < len(self.midi.parts)) and self.midi.parts:
                self.selected_part_index = 0

    @property
    def selected_part(self) -> Optional[Part]:
        if self.midi and 0 <= self.selected_part_index < len(self.midi.parts):
            return self.midi.parts[self.selected_part_index]
        return None


@dataclass
class PlayOptions:
    """演奏参数。"""
    speed: float = 1.0
    transpose: int = 0
    trim_leading: bool = True
    melody_mode: MelodyMode = MelodyMode.RAW


class Player:
    def __init__(self, engine: PlaybackEngine):
        self.engine = engine
        self.songs: list[Song] = []
        self.current_index = -1
        self.options = PlayOptions()

        self.on_song_changed: Optional[Callable[[int], None]] = None

        # 引擎自然播完 → 停止
        self.engine.on_finished = self._on_engine_finished

    # ---- 歌单管理 ----
    def add(self, paths: list[str]) -> None:
        for p in paths:
            self.songs.append(Song(p))
        if self.current_index < 0 and self.songs:
            self.current_index = 0

    def clear(self) -> None:
        self.stop()
        self.songs.clear()
        self.current_index = -1

    def load_song_settings(self) -> None:
        """把当前曲目的设置同步到 options，供 UI 显示。"""
        song = self.current
        if song:
            self.options.speed = song.speed
            self.options.melody_mode = song.melody_mode

    @property
    def current(self) -> Optional[Song]:
        if 0 <= self.current_index < len(self.songs):
            return self.songs[self.current_index]
        return None

    # ---- 旋律清洗 ----
    def cleaned_notes(self, song: Song) -> list[nm.RawNote]:
        """按曲目自身选项清洗出单音旋律，不含移调。"""
        song.ensure_loaded()
        part = song.selected_part
        if part is None or not part.notes:
            return []
        notes = list(part.notes)
        # 旋律提取：使用曲目自身保存的模式
        mode = song.melody_mode
        if mode == MelodyMode.RAW:
            notes = sorted(notes, key=lambda n: n.start)
        elif mode == MelodyMode.SKYLINE:
            notes = nm.extract_skyline(notes)
        else:
            notes = nm.chord_root_only(notes)
        if self.options.trim_leading:
            notes = nm.trim_leading_silence(notes)
        return notes

    def _build_mapped(self, song: Song):
        notes = self.cleaned_notes(song)
        if not notes:
            return None
        return nm.map_notes(notes, self.options.transpose)

    # ---- 播放控制 ----
    def play_index(self, index: int) -> bool:
        if not (0 <= index < len(self.songs)):
            return False
        self.current_index = index
        song = self.songs[index]
        res = self._build_mapped(song)
        if res is None:
            return False
        self.engine.play(res.notes, song.speed)
        if self.on_song_changed:
            self.on_song_changed(index)
        return True

    def play(self) -> bool:
        """播放/暂停切换。空闲则从当前曲开始。"""
        if self.engine.is_running:
            if self.engine.is_paused:
                self.engine.resume()
            else:
                self.engine.pause()
            return True
        idx = self.current_index if self.current_index >= 0 else (0 if self.songs else -1)
        return self.play_index(idx)

    def stop(self) -> None:
        self.engine.stop()

    def next(self) -> bool:
        """切到下一首并播放。到末尾则停在最后一首。"""
        if not self.songs:
            return False
        nxt = min(self.current_index + 1, len(self.songs) - 1)
        return self.play_index(nxt)

    def prev(self) -> bool:
        """切到上一首并播放。到开头则停在第一首。"""
        if not self.songs:
            return False
        prv = max(self.current_index - 1, 0)
        return self.play_index(prv)

    def apply_transpose_live(self) -> None:
        """播放中实时移调。"""
        song = self.current
        if song and self.engine.is_running:
            res = self._build_mapped(song)
            if res is not None:
                self.engine.update_notes(res.notes)

    def one_key_transpose(self) -> int:
        """一键移调进音域：计算并写回 options.transpose，返回半音数。"""
        song = self.current
        if not song:
            return self.options.transpose
        song.ensure_loaded()
        part = song.selected_part
        if part is None or not part.notes:
            return self.options.transpose
        notes = nm.chord_root_only(part.notes) if self.options.melody_mode == MelodyMode.HIGHEST \
                else nm.extract_skyline(part.notes)
        self.options.transpose = nm.suggest_transpose_into_range([n.pitch for n in notes])
        return self.options.transpose

    def _on_engine_finished(self) -> None:
        self.stop()