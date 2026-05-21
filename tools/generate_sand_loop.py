"""
生成 seamless 循环的沙沙声 wav。

技术要点:
- 22050Hz mono 16-bit (体积小,SoundPool 1MB 上限内)
- 高通过滤白噪声 y[i] = x[i] - 0.7*x[i-1] (沙沙感)
- 15 秒长度 (减少边界出现频次)
- 1 秒 equal-power crossfade (cos²+sin²=1, 能量恒定)

为什么用 equal-power 不用 linear:
linear fade 在 t=0.5 处 a²+b² = 0.5²+0.5² = 0.5,叠加后 rms 降到 0.707σ (-3dB),
听起来 fade 区间能量"凹陷"。equal-power 用 cos/sin: 任意 t 处 cos²(tπ/2)+sin²(tπ/2) = 1,
两个独立信号叠加后 rms 恒等 σ,听不出 fade 边界。
"""
import math
import os
import random
import struct
import wave

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sand_loop.wav")
SAMPLE_RATE = 22050
DURATION = 15.0
CROSSFADE_SEC = 1.0


def generate(path, duration=DURATION, crossfade_sec=CROSSFADE_SEC):
    n = int(SAMPLE_RATE * duration)
    crossfade = int(SAMPLE_RATE * crossfade_sec)
    n_extended = n + crossfade

    rng = random.Random(42)
    whites = [rng.uniform(-1, 1) for _ in range(n_extended)]

    filtered = [0.0] * n_extended
    filtered[0] = whites[0] - 0.7 * whites[-1]
    for i in range(1, n_extended):
        filtered[i] = whites[i] - 0.7 * whites[i - 1]

    # equal-power overlap-add: 让 sample[0] = filtered[n] (loop 边界的自然延续),
    # sample[crossfade-1] ≈ filtered[crossfade-1]
    samples = list(filtered[:n])
    for i in range(crossfade):
        t = (i + 0.5) / crossfade  # 0 → 1
        a = math.cos(t * math.pi / 2)  # fade-out tail (filtered[n+i])
        b = math.sin(t * math.pi / 2)  # fade-in head (filtered[i])
        samples[i] = filtered[n + i] * a + filtered[i] * b

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        buf = bytearray()
        for s in samples:
            v = max(-32767, min(32767, int(s * 5000)))
            buf.extend(struct.pack("<h", v))
        wf.writeframes(bytes(buf))


if __name__ == "__main__":
    generate(OUT)
    size_kb = os.path.getsize(OUT) / 1024
    print(f"OK -> {OUT}  ({size_kb:.0f} KB, {DURATION}s)")
