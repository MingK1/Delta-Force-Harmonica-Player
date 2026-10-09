"""MIDI 单音旋律清洗工具（命令行）。

把下载来的多轨/带和弦 MIDI 提纯成「只有一条主旋律的单音 MIDI」，
之后拖进软件演奏最干净、几乎不用再靠取最高音兜底。

清洗逻辑与软件演奏时完全一致（复用 midi_loader + note_mapper）：
  1) 自动挑主旋律声部（也可 --part 手动指定）
  2) 同刻多音取最高（单音乐器）
  3) 可选去掉开头空拍
再把结果写成一个单轨单声道 MIDI。

用法：
  python midi_cleaner.py 输入.mid                     # 自动选主旋律轨，输出 输入.melody.mid
  python midi_cleaner.py 输入.mid -o 干净.mid          # 指定输出名
  python midi_cleaner.py 输入.mid --list              # 只列出各声部，供你挑 --part
  python midi_cleaner.py 输入.mid --part 2            # 手动指定第2个声部为主旋律
  python midi_cleaner.py 输入.mid --skyline           # 使用天际线算法（追踪旋律连续性）
  python midi_cleaner.py 输入.mid --no-trim           # 保留开头空拍
"""
from __future__ import annotations

import argparse
import os
import sys

import mido

import note_mapper as nm
from midi_loader import MidiFile
from note_mapper import MelodyMode

# Windows 控制台默认 GBK，输出中文/符号可能报错；强制 UTF-8。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass

# 导出用的固定基准（120 BPM）。清洗只关心音高与相对时值，用固定 tempo 足够。
TICKS_PER_BEAT = 480
TEMPO = 500000  # 微秒/四分音符


def clean(path: str, part_index: int | None, trim: bool,
          melody_mode: MelodyMode = MelodyMode.HIGHEST) -> list[nm.RawNote]:
    """加载并清洗，返回单音旋律的 RawNote 列表（时间单位：秒）。"""
    midi = MidiFile(path)
    if not midi.parts:
        raise ValueError("这个 MIDI 里没有可用的音符声部。")

    if part_index is None:
        # 自动：优先推荐轨，否则第一条非打击乐
        chosen = next((p for p in midi.parts if p.recommended), None)
        if chosen is None:
            chosen = next((p for p in midi.parts if not p.is_drum), midi.parts[0])
    else:
        if not (0 <= part_index < len(midi.parts)):
            raise ValueError(f"--part 越界，本文件共 {len(midi.parts)} 个声部（从 0 开始）。")
        chosen = midi.parts[part_index]

    # 旋律提取：根据模式选择算法
    if melody_mode == MelodyMode.SKYLINE:
        notes = nm.extract_skyline(chosen.notes)
    else:
        notes = nm.chord_root_only(chosen.notes)
    if trim:
        notes = nm.trim_leading_silence(notes)
    return sorted(notes, key=lambda n: n.start)


def write_midi(notes: list[nm.RawNote], out_path: str) -> None:
    """把单音旋律写成单轨单声道 MIDI。"""
    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="Melody", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

    # 把 (秒) 事件转成按绝对 tick 排序的 note_on/note_off，再算 delta。
    events: list[tuple[int, int, int]] = []   # (tick, type: 1=on/0=off, pitch)
    for n in notes:
        on = int(round(mido.second2tick(max(0.0, n.start), TICKS_PER_BEAT, TEMPO)))
        off = int(round(mido.second2tick(max(n.start + 0.02, n.end), TICKS_PER_BEAT, TEMPO)))
        if off <= on:
            off = on + 1
        events.append((on, 1, n.pitch))
        events.append((off, 0, n.pitch))

    # 同一 tick 先处理 note_off（type 0 在前），避免同音瞬间叠触发
    events.sort(key=lambda e: (e[0], e[1]))

    prev = 0
    for tick, typ, pitch in events:
        delta = tick - prev
        prev = tick
        if typ == 1:
            track.append(mido.Message("note_on", note=pitch, velocity=96, time=delta))
        else:
            track.append(mido.Message("note_off", note=pitch, velocity=0, time=delta))

    mid.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="把多轨/带和弦 MIDI 清洗成单音旋律 MIDI")
    ap.add_argument("input", help="输入 MIDI 路径")
    ap.add_argument("-o", "--output", help="输出路径（默认 <输入名>.melody.mid）")
    ap.add_argument("--part", type=int, default=None, help="手动指定主旋律声部序号（从 0 开始）")
    ap.add_argument("--list", action="store_true", help="只列出各声部后退出")
    ap.add_argument("--no-trim", action="store_true", help="保留开头空拍")
    ap.add_argument("--skyline", action="store_true", help="使用天际线算法提取旋律（默认取最高音）")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print(f"找不到文件：{args.input}")
        return 1

    if args.list:
        midi = MidiFile(args.input)
        print(f"《{os.path.basename(args.input)}》共 {len(midi.parts)} 个声部：")
        for i, p in enumerate(midi.parts):
            print(f"  [{i}] {p.label()}")
        return 0

    try:
        mode = MelodyMode.SKYLINE if args.skyline else MelodyMode.HIGHEST
        notes = clean(args.input, args.part, trim=not args.no_trim, melody_mode=mode)
    except ValueError as e:
        print(f"错误：{e}")
        return 1

    if not notes:
        print("清洗后没有音符，请换个声部试试（--list 查看）。")
        return 1

    out = args.output or (os.path.splitext(args.input)[0] + ".melody.mid")
    write_midi(notes, out)
    dur = max(n.end for n in notes)
    print(f"✓ 已生成单音旋律：{out}")
    print(f"  {len(notes)} 个音，时长 ≈ {dur:.1f}s。直接拖进软件的歌单即可演奏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
