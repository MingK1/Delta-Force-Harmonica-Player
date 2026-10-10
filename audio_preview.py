"""独立的 MIDI 音频试听线程。

试听只调用 MidiAudio，不调用 input_sender，因此不会产生键盘或鼠标模拟输入。
"""
from __future__ import annotations

import threading
import time
from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Optional

from midi_audio import MidiAudio
from note_mapper import MappedNote


@dataclass(frozen=True)
class AudioEvent:
    t: float
    pitch: int
    velocity: int
    down: bool


def _build_events(notes: list[MappedNote]) -> list[AudioEvent]:
    events: list[AudioEvent] = []
    for note in notes:
        if not 0 <= note.pitch <= 127:
            continue
        start = max(0.0, note.start)
        end = max(start + 0.02, note.end)
        events.append(AudioEvent(start, note.pitch, 96, True))
        events.append(AudioEvent(end, note.pitch, 0, False))
    events.sort(key=lambda event: (event.t, event.down))
    return events


class AudioPreview:
    """按音乐时间播放 MappedNote，和键鼠播放完全分离。"""

    def __init__(self, on_finished: Optional[Callable[[], None]] = None) -> None:
        self._audio = MidiAudio()
        self._events: list[AudioEvent] = []
        self._speed = 1.0
        self._running = False
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._music_now = 0.0
        self._total_music = 0.0
        self._next_index = 0
        self.on_finished = on_finished

    @property
    def available(self) -> bool:
        return self._audio.available

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        self._speed = max(0.1, min(float(value), 5.0))

    @property
    def elapsed(self) -> float:
        with self._lock:
            return min(self._music_now, self._total_music)

    @property
    def total(self) -> float:
        with self._lock:
            return self._total_music

    def start(self, notes: list[MappedNote], speed: float = 1.0) -> bool:
        if not self.available:
            return False
        events = _build_events(notes)
        if not events:
            return False
        self.stop()
        with self._lock:
            self._events = events
            self._music_now = 0.0
            self._total_music = events[-1].t
            self._next_index = 0
            self.speed = speed
            self._cancel.clear()
            self._running = True
            self._thread = threading.Thread(
                target=self._worker, name="AudioPreviewWorker", daemon=True
            )
            self._thread.start()
        return True

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._cancel.set()
        self._audio.reset()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        self._thread = None

    def seek_fraction(self, fraction: float) -> None:
        """试听中定位到比例位置，并从该位置继续发送音符。"""
        with self._lock:
            if not self._running or not self._events:
                return
            fraction = max(0.0, min(float(fraction), 1.0))
            self._music_now = fraction * self._total_music
            event_times = [event.t for event in self._events]
            self._next_index = bisect_right(event_times, self._music_now)
            active: set[int] = set()
            for event in self._events[:self._next_index]:
                if event.down:
                    active.add(event.pitch)
                else:
                    active.discard(event.pitch)
        self._audio.reset()
        for pitch in active:
            self._audio.note_on(pitch, 96)

    def close(self) -> None:
        self.stop()
        self._audio.close()

    def _worker(self) -> None:
        last_physical = time.perf_counter()
        try:
            while self._running:
                now = time.perf_counter()
                delta = max(0.0, now - last_physical)
                last_physical = now
                with self._lock:
                    self._music_now += delta * self._speed
                    music_now = self._music_now
                    index = self._next_index
                while self._running and index < len(self._events):
                    event = self._events[index]
                    if event.t > music_now:
                        break
                    if event.down:
                        self._audio.note_on(event.pitch, event.velocity)
                    else:
                        self._audio.note_off(event.pitch)
                    index += 1
                with self._lock:
                    self._next_index = index
                if index >= len(self._events):
                    break
                remain = max(0.001, (self._events[index].t - music_now) / self._speed)
                self._cancel.wait(min(remain, 0.02))
        finally:
            self._audio.reset()
            self._running = False
            if self.on_finished:
                self.on_finished()
