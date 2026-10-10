#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoMind MVP 音乐合成脚本
--------------------------
用程序合成 10 首氛围音乐（22050Hz 单声道 WAV），全部无版权争议。

合成手法（每首通用）：
  1. 和弦铺底：正弦叠加，泛音按 1/n^2 衰减，慢 attack / release
  2. 五声音阶稀疏拨弦：三角波形，指数衰减
  3. 轻微噪声"空气感"：低通白噪声 + 慢速 LFO 调制
  4. 简单延迟回声：前馈式 3 抽头（0.31s / 0.62s / 0.93s）
  5. 首尾淡入淡出，峰值归一化到 0.95 防削波

按"调节阶段"设计 5 种质感：
  释放：C 大调、稍明亮、拨弦稍密
  稳定：F 大调、60bpm 感的柔和低音脉动 + 稀疏拨弦
  放松：降 B 大调、极稀疏、泛音更少、90 秒
  专注：极简铺底 + 极高频稀疏点缀、90 秒
  能量：稍明亮 + 温暖低音脉动

输出：
  ../static/audio/trackNN.wav      音频
  ../static/covers/coverNN.png     封面（蓝紫渐变 + 柔光圆形）
  tracks.json                      种子数据（供 tools/seed.py 使用）
并打印每首的 时长 / 峰值 / RMS / 频谱质心 自检。
"""

import json
import math
import os
import wave
from pathlib import Path

import numpy as np

SR = 22050  # 采样率
BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "static" / "audio"
COVER_DIR = BASE_DIR / "static" / "covers"


# ---------------------------------------------------------------------------
# 基础乐理工具
# ---------------------------------------------------------------------------
def midi_to_freq(midi: float) -> float:
    """MIDI 音高转频率。"""
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


# 五声音阶（C 宫调式）：C D E G A
PENTA = [0, 2, 4, 7, 9]


# ---------------------------------------------------------------------------
# 合成单元
# ---------------------------------------------------------------------------
def sine_pad(note_midis, n_samples, harmonics=8, base_amp=0.16):
    """
    和弦铺底：每个音符 = 基频正弦 + 泛音（振幅按 1/n^2 衰减）。
    返回叠加后的波形（未做包络）。
    """
    t = np.arange(n_samples) / SR
    out = np.zeros(n_samples, dtype=np.float64)
    for midi in note_midis:
        f = midi_to_freq(midi)
        sig = np.zeros(n_samples, dtype=np.float64)
        for n in range(1, harmonics + 1):
            sig += np.sin(2.0 * math.pi * f * n * t) / (n * n)
        out += sig * base_amp
    return out


def smooth_envelope(n_samples, attack_s, release_s):
    """慢 attack / 慢 release 的平滑包络（raised-cosine）。"""
    a = max(1, int(attack_s * SR))
    r = max(1, int(release_s * SR))
    env = np.ones(n_samples, dtype=np.float64)
    env[:a] = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    env[-r:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(r) / r)
    return env


def triangle_wave(freq, n_samples):
    """三角波（奇次谐波 1/k^2 叠加，k 取到 9）。"""
    t = np.arange(n_samples) / SR
    out = np.zeros(n_samples, dtype=np.float64)
    for k in (1, 3, 5, 7, 9):
        out += ((-1) ** ((k - 1) // 2)) * np.sin(2.0 * math.pi * freq * k * t) / (k * k)
    return out * (8.0 / (math.pi ** 2))


def add_pluck(out, midi, start_s, tau=1.0, amp=0.35):
    """在 out 上叠加一个拨弦音（三角波 + 指数衰减）。"""
    start = int(start_s * SR)
    dur = int(min(4.0, len(out) / SR - start_s) * SR)  # 单个拨弦最多 4 秒
    if dur <= 0 or start >= len(out):
        return
    f = midi_to_freq(midi)
    wave_ = triangle_wave(f, dur)
    env = np.exp(-np.arange(dur) / (tau * SR))
    out[start:start + dur] += wave_ * env * amp


def add_bass_pulse(out, root_midi, duration_s, interval_s=1.0, amp=0.22, bright=False):
    """
    柔和低音脉动：每隔 interval_s 一个正弦低音（60bpm 感 = 每秒一次）。
    bright=True 时叠加一个高八度，质感更明亮（能量阶段用）。
    """
    t_pulse = np.arange(int(0.9 * SR)) / SR
    env = np.sin(np.pi * np.minimum(t_pulse / 0.9, 1.0)) ** 1.5  # 柔和凸起包络
    pulse = np.sin(2.0 * math.pi * midi_to_freq(root_midi) * t_pulse) * env
    if bright:
        pulse += 0.4 * np.sin(2.0 * math.pi * midi_to_freq(root_midi + 12) * t_pulse) * env
    n = len(pulse)
    t = 0.0
    while t < duration_s:
        s = int(t * SR)
        if s + n <= len(out):
            out[s:s + n] += pulse * amp
        t += interval_s


def air_noise(n_samples, rng, lfo_rate=0.08, amp=0.035):
    """空气感噪声：低通白噪声 + 慢速 LFO 幅度调制。"""
    noise = rng.standard_normal(n_samples)
    # FFT 低通（800Hz 拐点）
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n_samples, 1.0 / SR)
    spec *= 1.0 / (1.0 + (freqs / 800.0) ** 2)
    smooth = np.fft.irfft(spec, n_samples)
    smooth /= max(1e-9, np.abs(smooth).max())
    t = np.arange(n_samples) / SR
    lfo = 0.5 + 0.5 * np.sin(2.0 * math.pi * lfo_rate * t)
    return smooth * lfo * amp


def feedforward_echo(x):
    """简单延迟回声：前馈 3 抽头（0.31s / 0.62s / 0.93s），增益递减。"""
    out = x.copy()
    for delay_s, gain in ((0.31, 0.25), (0.62, 0.0625), (0.93, 0.0156)):
        d = int(delay_s * SR)
        out[d:] += x[:-d] * gain
    return out


def spectral_centroid(x):
    """频谱质心（Hz），用于自检音色明暗。"""
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(np.sum(freqs * spec) / max(1e-9, np.sum(spec)))


def write_wav(path, x):
    """写 16-bit 单声道 WAV。"""
    pcm = np.clip(x, -1.0, 1.0)
    pcm16 = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm16.tobytes())


# ---------------------------------------------------------------------------
# 封面生成（PIL）：蓝紫渐变 + 柔光圆形
# ---------------------------------------------------------------------------
def make_cover(path, hue_seed):
    from PIL import Image

    rng = np.random.default_rng(hue_seed)
    S = 512
    # 垂直渐变：浅蓝 → 蓝紫
    top = np.array([191, 214, 240], dtype=np.float64)     # 浅蓝
    bottom = np.array([108, 99, 190], dtype=np.float64)   # 蓝紫
    ys = np.linspace(0, 1, S).reshape(S, 1, 1)
    img = top * (1 - ys) + bottom * ys
    img = np.repeat(img, S, axis=1)
    # 2~3 个柔光圆形（高斯光斑，screen 混合提亮）
    yy, xx = np.mgrid[0:S, 0:S]
    for _ in range(3):
        cx, cy = rng.uniform(0.2, 0.8, 2) * S
        sigma = rng.uniform(70, 160)
        glow = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
        tint = np.array(rng.uniform([200, 220, 255], [255, 255, 255]))
        glow3 = glow[:, :, None] * tint[None, None, :] * 0.35
        img = 255 - (255 - img) * (255 - glow3) / 255.0  # screen blend
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)


# ---------------------------------------------------------------------------
# 10 首曲目定义
# ---------------------------------------------------------------------------
# 和弦进行（MIDI 音高）
CHORDS = {
    "release": [  # C 大调
        [60, 64, 67, 71],  # Cmaj7
        [57, 60, 64, 67],  # Am7
        [53, 57, 60, 65],  # Fmaj7
        [55, 59, 62, 67],  # G
    ],
    "stable": [  # F 大调
        [53, 57, 60, 65],  # Fmaj7
        [50, 53, 57, 62],  # Dm7
        [58, 62, 65, 69],  # Bbmaj7
        [55, 60, 64, 67],  # C
    ],
    "relax": [  # 降 B 大调
        [58, 62, 65, 69],  # Bbmaj7
        [55, 58, 62, 65],  # Gm7
        [51, 55, 58, 63],  # Ebmaj7
        [53, 57, 60, 65],  # Fmaj7
    ],
    "focus": [  # 极简：Am(add9) 与 Cmaj9 交替
        [57, 60, 64, 71],
        [60, 64, 67, 74],
    ],
    "energy": [  # C 大调，更明亮
        [48, 55, 60, 64, 67],
        [53, 57, 60, 65, 69],
        [55, 59, 62, 67, 71],
        [48, 55, 60, 64, 72],
    ],
}

# 每首曲目的合成参数 + 元数据
TRACK_DEFS = [
    dict(title="晨雾释放", stage="释放", stage_key="release", duration=75,
         scenes=["考试前", "演出前", "通用"], emotions=["紧张", "烦躁"],
         bpm=72, rhythm="渐进铺底 + 拨弦", stim="低", timbre="温暖弦乐铺底",
         pluck_mean=2.2, pluck_tau=0.9, harmonics=8, bass=False, bright=False,
         desc="C 大调，拨弦稍密，情绪出口"),
    dict(title="潮汐释放", stage="释放", stage_key="release", duration=75,
         scenes=["独处", "通勤", "通用"], emotions=["烦躁", "紧张"],
         bpm=72, rhythm="渐进铺底 + 拨弦", stim="低", timbre="温暖弦乐铺底",
         pluck_mean=2.6, pluck_tau=1.0, harmonics=8, bass=False, bright=False,
         desc="C 大调，起伏如潮汐"),
    dict(title="考前稳定", stage="稳定", stage_key="stable", duration=80,
         scenes=["考试前", "演出前"], emotions=["紧张"],
         bpm=60, rhythm="柔和低音脉动 + 稀疏拨弦", stim="低", timbre="柔和钢琴感拨弦",
         pluck_mean=4.0, pluck_tau=1.2, harmonics=7, bass=True, bright=False,
         desc="F 大调，60bpm 低音脉动"),
    dict(title="学境稳定", stage="稳定", stage_key="stable", duration=80,
         scenes=["学习", "写论文"], emotions=["难以专注", "紧张"],
         bpm=60, rhythm="柔和低音脉动 + 稀疏拨弦", stim="低", timbre="柔和钢琴感拨弦",
         pluck_mean=4.5, pluck_tau=1.2, harmonics=7, bass=True, bright=False,
         desc="F 大调，陪伴式稳定"),
    dict(title="晚风稳定", stage="稳定", stage_key="stable", duration=80,
         scenes=["睡前", "独处", "通用"], emotions=["紧张", "烦躁"],
         bpm=60, rhythm="柔和低音脉动 + 稀疏拨弦", stim="低", timbre="柔和钢琴感拨弦",
         pluck_mean=5.0, pluck_tau=1.3, harmonics=7, bass=True, bright=False,
         desc="F 大调，夜晚的安抚"),
    dict(title="夜海放松", stage="放松", stage_key="relax", duration=90,
         scenes=["睡前"], emotions=["烦躁", "低落"],
         bpm=50, rhythm="极稀疏铺底", stim="低", timbre="空灵泛音",
         pluck_mean=7.0, pluck_tau=1.6, harmonics=5, bass=False, bright=False,
         desc="降 B 大调，深夜海面"),
    dict(title="云端放松", stage="放松", stage_key="relax", duration=90,
         scenes=["通勤", "独处"], emotions=["烦躁", "疲惫"],
         bpm=50, rhythm="极稀疏铺底", stim="低", timbre="空灵泛音",
         pluck_mean=7.5, pluck_tau=1.6, harmonics=5, bass=False, bright=False,
         desc="降 B 大调，云端漂浮感"),
    dict(title="雾屿放松", stage="放松", stage_key="relax", duration=90,
         scenes=["通用"], emotions=["低落", "疲惫", "平静"],
         bpm=50, rhythm="极稀疏铺底", stim="低", timbre="空灵泛音",
         pluck_mean=8.0, pluck_tau=1.8, harmonics=5, bass=False, bright=False,
         desc="降 B 大调，雾中岛屿"),
    dict(title="澄澈专注", stage="专注", stage_key="focus", duration=90,
         scenes=["学习", "写论文", "考试前"], emotions=["难以专注"],
         bpm=48, rhythm="极简铺底 + 高频点缀", stim="低", timbre="极简高频点缀",
         pluck_mean=6.0, pluck_tau=2.0, harmonics=5, bass=False, bright=False,
         high_only=True, desc="极简铺底，高频如星"),
    dict(title="微光能量", stage="能量", stage_key="energy", duration=70,
         scenes=["恢复能量", "通用", "通勤"], emotions=["疲惫", "低落"],
         bpm=88, rhythm="明亮铺底 + 温暖低音脉动", stim="中低", timbre="明亮暖低音",
         pluck_mean=3.0, pluck_tau=1.0, harmonics=8, bass=True, bright=True,
         desc="C 大调，温柔地被点亮"),
]


def render_track(defn, idx):
    """渲染单首曲目，返回 (波形, 自检信息)。"""
    rng = np.random.default_rng(2026 + idx)
    dur = defn["duration"]
    n = int(dur * SR)
    out = np.zeros(n, dtype=np.float64)
    key = defn["stage_key"]
    chords = CHORDS[key]

    # 1) 和弦铺底：4 个和弦（focus 2 个交替），慢 attack/release 叠加
    n_chords = len(chords)
    seg = dur / n_chords
    for i, chord in enumerate(chords):
        s = int(i * seg * SR)
        e = int(min(dur, (i + 1) * seg + 3.0) * SR)  # 尾部多延 3s 交叉淡化
        pad = sine_pad(chord, e - s, harmonics=defn["harmonics"],
                       base_amp=0.16 / (len(chord) ** 0.5))
        pad *= smooth_envelope(e - s, attack_s=6.0, release_s=6.0)
        out[s:e] += pad

    # 2) 五声音阶稀疏拨弦
    t = 3.0
    base_oct = 72 if defn.get("high_only") else 60  # 专注：只用高八度
    while t < dur - 5.0:
        degree = rng.choice(PENTA)
        octave = rng.choice([0, 12] if not defn.get("high_only") else [12, 24])
        midi = base_oct + degree + octave
        add_pluck(out, midi, t, tau=defn["pluck_tau"], amp=0.30)
        t += rng.exponential(defn["pluck_mean"])

    # 3) 低音脉动（稳定 / 能量）
    if defn.get("bass"):
        root = chords[0][0] - 24  # 比和弦根音低两个八度
        add_bass_pulse(out, root, dur, interval_s=1.0,
                       amp=0.20, bright=defn.get("bright", False))

    # 4) 空气感噪声
    out += air_noise(n, rng)

    # 5) 延迟回声
    out = feedforward_echo(out)

    # 6) 首尾淡入淡出（5s）
    out *= smooth_envelope(n, attack_s=5.0, release_s=5.0)

    # 7) 峰值归一化到 0.95，防削波
    peak = float(np.abs(out).max())
    out = out / peak * 0.95

    rms = float(np.sqrt(np.mean(out ** 2)))
    centroid = spectral_centroid(out)
    return out, {"duration": dur, "peak": round(float(np.abs(out).max()), 4),
                 "rms": round(rms, 4), "centroid": round(centroid, 1)}


def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    COVER_DIR.mkdir(parents=True, exist_ok=True)

    tracks_meta = []
    print(f"{'#':<3} {'标题':<8} {'阶段':<4} {'时长':>6} {'峰值':>6} {'RMS':>7} {'频谱质心':>8}")
    print("-" * 60)
    for i, defn in enumerate(TRACK_DEFS, start=1):
        audio, check = render_track(defn, i)
        wav_name = f"track{i:02d}.wav"
        cover_name = f"cover{i:02d}.png"
        write_wav(AUDIO_DIR / wav_name, audio)
        make_cover(COVER_DIR / cover_name, hue_seed=1000 + i)

        tracks_meta.append({
            "id": i,
            "title": defn["title"],
            "file": f"audio/{wav_name}",
            "cover": f"covers/{cover_name}",
            "bpm": defn["bpm"],
            "rhythm_type": defn["rhythm"],
            "stimulation": defn["stim"],
            "timbre": defn["timbre"],
            "has_vocal": False,
            "emotion_tags": defn["emotions"],
            "scene_tags": defn["scenes"],
            "stage": defn["stage"],
            "enabled": True,
        })
        print(f"{i:<3} {defn['title']:<8} {defn['stage']:<4} "
              f"{check['duration']:>5}s {check['peak']:>6} {check['rms']:>7} "
              f"{check['centroid']:>7}Hz")
        # 断言：峰值 < 0.99（防削波），时长符合 60~90s
        assert check["peak"] < 0.99, "峰值超标！"
        assert 60 <= check["duration"] <= 90, "时长不符合要求！"

    meta_path = BASE_DIR / "tools" / "tracks.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(tracks_meta, f, ensure_ascii=False, indent=2)
    print("-" * 60)
    print(f"已生成 {len(tracks_meta)} 首，种子数据 -> {meta_path}")


if __name__ == "__main__":
    main()
