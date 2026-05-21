"""
生成 seamless 循环的沙沙声 wav。

技术要点:
- 22050Hz mono 16-bit (体积小,SoundPool 1MB 上限内)
- 高通过滤白噪声 y[i] = x[i] - 0.7*x[i-1] (沙沙感)
- 15 秒长度 (减少边界出现频次)
- 1 秒 crossfade overlap-add (确保边界处样本是自然连续的)

为什么 crossfade 比 "filter wrap" 更好:
旧版本只让滤波器状态在 i=0 时取 whites[-1] 来保持连续,但白噪声序列本身在
boundary 是离散跳变 (whites[n-1] 跟 whites[0] 完全无关),量化到 int16 会
产生微小但可听的 click。crossfade 让 sample[0] = filtered[n] (噪声序列
的自然延续),sample[crossfade-1] 平滑过渡到 filtered[crossfade-1]。
"""
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

    # overlap-add: 把 [n..n+crossfade-1] 渐变叠到 [0..crossfade-1] 上
    # 让 sample[0] = filtered[n] (loop 边界的自然延续),sample[crossfade-1] ≈ filtered[crossfade-1]
    samples = list(filtered[:n])
    for i in range(crossfade):
        t = i / crossfade  # 0 → 1
        samples[i] = filtered[n + i] * (1 - t) + filtered[i] * t

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
