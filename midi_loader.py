"""MIDI 加载：解析文件、按 (轨道,声道) 列出声部、自动推荐主旋律轨。

用 mido 读取，把 note_on/note_off 配对成绝对秒时间的音符。
载入容错：忽略无法解析的 meta/sysex，坏 tempo 用默认值兜底，不让整首打不开。
"""
from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field

import mido

from note_mapper import RawNote

DEFAULT_TEMPO = 500000  # 120 BPM，微秒/四分音符


def _fix_encoding(name: str) -> str:
    """mido 按 latin-1 解码轨名；很多 MIDI 实际是 UTF-8/GBK，这里尝试还原。"""
    if not name:
        return name
    try:
        raw = name.encode("latin-1")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


@dataclass
class Part:
    """一个声部 = (轨道号, 声道号) 下的一串音符。"""
    track_index: int
    channel: int
    track_name: str
    notes: list[RawNote] = field(default_factory=list)
    is_drum: bool = False          # 声道 9（打击乐）→ 不适合演奏
    recommended: bool = False      # 自动推荐的主旋律轨

    @property
    def duration(self) -> float:
        return max((n.end for n in self.notes), default=0.0)

    @property
    def note_count(self) -> int:
        return len(self.notes)

    def label(self) -> str:
        name = self.track_name or f"轨{self.track_index}"
        star = "★ " if self.recommended else ""
        drum = "（打击乐）" if self.is_drum else ""
        return f"{star}{name} · 声道{self.channel}{drum} · {self.note_count}音 · {self.duration:.0f}s"


class MidiFile:
    """加载后的 MIDI，持有全部声部。"""

    def __init__(self, path: str):
        self.path = path
        self.parts: list[Part] = []
        self._load()

    def _load(self) -> None:
        mid = mido.MidiFile(self.path, clip=True)
        tpb = mid.ticks_per_beat or 480
        shared_tempo_segments = (
            self._build_tempo_segments(mid.tracks, tpb) if mid.type != 2 else None
        )
        # 格式 0/1 的轨道共享 tempo；格式 2 的每条轨道是独立序列。
        for ti, track in enumerate(mid.tracks):
            tempo_segments = (
                self._build_tempo_segments([track], tpb)
                if mid.type == 2 else shared_tempo_segments
            )
            tempo_ticks = [segment[0] for segment in tempo_segments]

            def tick_to_seconds(tick: int) -> float:
                index = bisect_right(tempo_ticks, tick) - 1
                segment_tick, segment_seconds, tempo = tempo_segments[max(index, 0)]
                return segment_seconds + mido.tick2second(
                    max(0, tick - segment_tick), tpb, tempo
                )

            track_name = ""
            # 每条轨可能有多个声道，用 dict 分组
            parts: dict[int, Part] = {}
            # note_on 待配对：同音重叠时按先进先出配对
            pending: dict[tuple[int, int], deque[tuple[int, int]]] = {}

            abs_tick = 0
            for msg in track:
                abs_tick += msg.time

                if msg.type == "track_name":
                    track_name = _fix_encoding(msg.name)
                    continue
                if msg.type == "set_tempo":
                    continue
                if msg.is_meta or msg.type == "sysex":
                    continue

                if msg.type == "note_on" and msg.velocity > 0:
                    pending.setdefault((msg.channel, msg.note), deque()).append(
                        (abs_tick, msg.velocity)
                    )
                elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                    key = (msg.channel, msg.note)
                    if pending.get(key):
                        start_tick, vel = pending[key].popleft()
                        if not pending[key]:
                            del pending[key]
                        p = parts.get(msg.channel)
                        if p is None:
                            p = Part(ti, msg.channel, track_name, is_drum=(msg.channel == 9))
                            parts[msg.channel] = p
                        start = tick_to_seconds(start_tick)
                        end = tick_to_seconds(abs_tick)
                        p.notes.append(RawNote(msg.note, start, max(end, start + 0.02), vel))

            # 对缺失 note_off 的音符收尾到轨道末尾，避免静默丢音。
            for (channel, pitch), notes in pending.items():
                p = parts.get(channel)
                if p is None:
                    p = Part(ti, channel, track_name, is_drum=(channel == 9))
                    parts[channel] = p
                end = tick_to_seconds(abs_tick)
                for start_tick, vel in notes:
                    start = tick_to_seconds(start_tick)
                    p.notes.append(RawNote(pitch, start, max(end, start + 0.02), vel))

            # 收尾：轨名可能在事件流后面才出现，补写
            for p in parts.values():
                if not p.track_name:
                    p.track_name = track_name
                p.notes.sort(key=lambda n: n.start)
                if p.notes:
                    self.parts.append(p)

        self._recommend()

    @staticmethod
    def _build_tempo_segments(tracks, tpb: int) -> list[tuple[int, float, int]]:
        """构建全局 tempo 分段： (起始 tick, 起始秒数, tempo)。"""
        tempo_events: list[tuple[int, int, int]] = []
        sequence = 0
        for track in tracks:
            abs_tick = 0
            for msg in track:
                abs_tick += msg.time
                if msg.type == "set_tempo":
                    tempo = msg.tempo if msg.tempo > 0 else DEFAULT_TEMPO
                    tempo_events.append((abs_tick, sequence, tempo))
                    sequence += 1

        tempo_events.sort(key=lambda item: (item[0], item[1]))
        segments: list[tuple[int, float, int]] = [(0, 0.0, DEFAULT_TEMPO)]
        current_tick = 0
        current_seconds = 0.0
        current_tempo = DEFAULT_TEMPO
        for tick, _sequence, tempo in tempo_events:
            if tick > current_tick:
                current_seconds += mido.tick2second(
                    tick - current_tick, tpb, current_tempo
                )
                current_tick = tick
            current_tempo = tempo
            if segments[-1][0] == tick:
                segments[-1] = (tick, current_seconds, current_tempo)
            else:
                segments.append((tick, current_seconds, current_tempo))
        return segments

    def _recommend(self) -> None:
        """自动推荐主旋律轨：非打击乐、音符多、音域适中、平均音高偏高者优先。"""
        candidates = [p for p in self.parts if not p.is_drum and p.note_count > 0]
        if not candidates:
            return

        def score(p: Part) -> float:
            avg_pitch = sum(n.pitch for n in p.notes) / p.note_count
            # 旋律通常音符较多、平均音高偏高（60~84 之间最像主旋律）
            pitch_fit = 1.0 - abs(avg_pitch - 72) / 48.0
            return p.note_count * 0.02 + pitch_fit
        best = max(candidates, key=score)
        best.recommended = True
