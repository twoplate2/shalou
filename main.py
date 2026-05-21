"""
沙漏 - Android Kivy 版本(精美化升级)

视觉层包含:沙顶曲线 + 漏斗坑、装饰颗粒、沙堆中央堆尖、玻璃高光、
木盖横纹、渐变粒子色、底部喇叭口、触底反弹/闪光、沙堆塌陷、完成尘埃、
水平层理、暂停遮罩、颈部涌出沙柱。
"""
import math
import os
import random
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase, Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, Line, Quad, Mesh
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform


_FONT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fonts",
    "NotoSansSC-Medium.otf",
)
try:
    if os.path.exists(_FONT_PATH):
        LabelBase.register(name="Roboto", fn_regular=_FONT_PATH)
except Exception:
    pass


SAND_BASE = "#d9a360"
SAND_DARK = "#b88040"
SAND_LIGHT = "#e6b870"
SAND_PRESETS = [
    ("金沙", "#d9a360", "#b88040", "#e6b870"),
    ("红沙", "#c4523e", "#8e3220", "#d97560"),
    ("蓝沙", "#4a8ec4", "#2e5e87", "#6dabd4"),
    ("绿沙", "#7ba83e", "#4d7820", "#97c45e"),
    ("紫沙", "#8e6db0", "#5d4280", "#a98ac4"),
    ("黑沙", "#4a4540", "#2a2520", "#6a6560"),
]
BG_COLOR = "#fdf6e3"
GLASS_FILL = "#eaf3f8"
GLASS_HIGHLIGHT = (0.97, 0.98, 0.99, 1.0)
GLASS_SHADOW = (0.78, 0.83, 0.85, 1.0)
WOOD_FILL = "#8b6f47"
WOOD_GRAIN = (0.435, 0.349, 0.22, 1.0)

# 上沙线性下降 (容器是截顶锥, 纯立方根会让前期下降不明显)
# 下沙立方根 + 0.9 因子 (3600s 时 fallen=0.001 → 高度 9% 立刻可见, 留 10% 空气)
UPPER_SAND_FACTOR = 1.0
LOWER_SAND_FACTOR = 0.9
WAV_FILENAME = "sand_loop.wav"

CURVE_STEPS = 16
TOP_DECOR_COUNT = 35
MOUND_DECOR_COUNT = 50
COLLAPSE_INTERVAL = (2.5, 4.0)
COLLAPSE_DURATION = 0.6
DUST_COUNT = 25
DUST_LIFETIME = 1.0


def hex_rgb(h):
    return (int(h[1:3], 16) / 255.0,
            int(h[3:5], 16) / 255.0,
            int(h[5:7], 16) / 255.0)


def lerp_rgb(c1, c2, t):
    return (c1[0] + (c2[0] - c1[0]) * t,
            c1[1] + (c2[1] - c1[1]) * t,
            c1[2] + (c2[2] - c1[2]) * t)


def resource_path(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def fg_for(hex_color):
    r, g, b = hex_rgb(hex_color)
    luma = r * 0.299 + g * 0.587 + b * 0.114
    return (0, 0, 0, 1) if luma > 0.59 else (1, 1, 1, 1)


class CenterTextInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(text=self._refresh_pad,
                  size=self._refresh_pad,
                  font_size=self._refresh_pad)
        Clock.schedule_once(self._refresh_pad, 0)

    def _refresh_pad(self, *_):
        try:
            cl = CoreLabel(text=self.text or "0",
                           font_size=self.font_size,
                           font_name=self.font_name or "Roboto")
            cl.refresh()
            tw, th = cl.content_size
        except Exception:
            tw, th = 0, 0
        pad_h = max(2, (self.width - tw) / 2)
        pad_v = max(2, (self.height - th) / 2)
        self.padding = [pad_h, pad_v, pad_h, pad_v]


class _SoundProxy:
    """音频抽象层。

    Android 走 SoundPool。短 wav 用 SoundPool.play(loop=-1) 在部分机型有
    ~10-30ms gap (loop 重启的硬件 buffer 缝隙) + wav 边界 click。
    解决:用 2 个并发 stream,错开 wav_duration - fade_overlap 交替播放,
    重叠 100ms 用 setVolume 做 equal-power crossfade,把 wav boundary
    完全藏在 fade 区间内。

    其他平台 (桌面预览) fallback 到 SoundLoader.loop=True。
    """

    _WAV_DURATION = 15.0      # 与 tools/generate_sand_loop.py DURATION 同步
    _FADE_OVERLAP = 0.1       # 100ms 交叉重叠
    _FADE_STEPS = 10          # fade 分 10 帧渐变

    def __init__(self, wav_path):
        self._is_android = (platform == "android")
        self._sp = None
        self._sound_id = None
        self._loaded = False
        self._listener = None
        self._kivy_sound = None

        # 双 stream 交替状态
        self._active = False
        self._current_stream = 0
        self._swap_event = None
        self._fade_events = []

        if self._is_android:
            try:
                self._init_soundpool(wav_path)
                return
            except Exception:
                self._sp = None

        try:
            from kivy.core.audio import SoundLoader
            self._kivy_sound = SoundLoader.load(wav_path)
            if self._kivy_sound is not None:
                self._kivy_sound.loop = True
        except Exception:
            self._kivy_sound = None

    def _init_soundpool(self, wav_path):
        from jnius import autoclass, PythonJavaClass, java_method
        SoundPool = autoclass('android.media.SoundPool')
        AudioAttributes = autoclass('android.media.AudioAttributes')

        attrs = (AudioAttributes.Builder()
                 .setUsage(AudioAttributes.USAGE_MEDIA)
                 .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                 .build())
        self._sp = (SoundPool.Builder()
                    .setMaxStreams(2)
                    .setAudioAttributes(attrs)
                    .build())
        self._sound_id = self._sp.load(wav_path, 1)

        outer = self

        class _Listener(PythonJavaClass):
            __javainterfaces__ = ['android/media/SoundPool$OnLoadCompleteListener']
            __javacontext__ = 'app'

            @java_method('(Landroid/media/SoundPool;II)V')
            def onLoadComplete(self, soundpool, sample_id, status):
                if status == 0:
                    outer._loaded = True

        self._listener = _Listener()
        self._sp.setOnLoadCompleteListener(self._listener)

    def play(self):
        if self._sp is not None:
            if self._active or not self._loaded:
                return
            self._active = True
            # 主 stream 用 loop=0 单次播放,不让单 stream 自己 loop click
            self._current_stream = self._sp.play(
                self._sound_id, 1.0, 1.0, 1, 0, 1.0)
            self._swap_event = Clock.schedule_once(
                self._swap, self._WAV_DURATION - self._FADE_OVERLAP)
            return
        if self._kivy_sound is not None:
            try:
                if self._kivy_sound.state != "play":
                    self._kivy_sound.play()
            except Exception:
                pass

    def _swap(self, _dt):
        if not self._active or self._sp is None:
            return
        # 启动新 stream 在 vol=0
        new_stream = self._sp.play(self._sound_id, 0.0, 0.0, 1, 0, 1.0)
        old_stream = self._current_stream
        # 100ms 内分 _FADE_STEPS 步 equal-power crossfade
        for k in range(1, self._FADE_STEPS + 1):
            t = k / self._FADE_STEPS
            old_vol = math.cos(t * math.pi / 2)
            new_vol = math.sin(t * math.pi / 2)
            ev = Clock.schedule_once(
                lambda _dt, o=old_stream, n=new_stream, ov=old_vol, nv=new_vol:
                    self._apply_volumes(o, n, ov, nv),
                self._FADE_OVERLAP * t)
            self._fade_events.append(ev)
        # fade 结束后停止 old stream
        ev = Clock.schedule_once(
            lambda _dt, sid=old_stream: self._safe_stop(sid),
            self._FADE_OVERLAP + 0.01)
        self._fade_events.append(ev)
        # 切换 current,排下一次 swap
        self._current_stream = new_stream
        self._swap_event = Clock.schedule_once(
            self._swap, self._WAV_DURATION - self._FADE_OVERLAP)

    def _apply_volumes(self, old_id, new_id, old_vol, new_vol):
        if not self._active or self._sp is None:
            return
        try:
            self._sp.setVolume(old_id, old_vol, old_vol)
            self._sp.setVolume(new_id, new_vol, new_vol)
        except Exception:
            pass

    def _safe_stop(self, stream_id):
        if self._sp is None or not stream_id:
            return
        try:
            self._sp.stop(stream_id)
        except Exception:
            pass

    def stop(self):
        if self._sp is not None:
            self._active = False
            if self._swap_event is not None:
                try:
                    self._swap_event.cancel()
                except Exception:
                    pass
                self._swap_event = None
            for ev in self._fade_events:
                try:
                    ev.cancel()
                except Exception:
                    pass
            self._fade_events = []
            if self._current_stream:
                self._safe_stop(self._current_stream)
                self._current_stream = 0
            return
        if self._kivy_sound is not None:
            try:
                self._kivy_sound.stop()
            except Exception:
                pass


class HourglassWidget(Widget):
    """沙漏画布。Kivy 坐标 y 向上,top_y > bot_y。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.duration = 60.0
        self.elapsed = 0.0
        self.running = False
        self.last_tick = None
        self.last_frame = time.time()

        self.sand_base = hex_rgb(SAND_BASE)
        self.sand_dark = hex_rgb(SAND_DARK)
        self.sand_light = hex_rgb(SAND_LIGHT)
        self._color_table = []
        self._rebuild_color_table()

        self.particles = []
        self.particle_acc = 0.0

        self.splashes = []
        self.flares = []
        self.dusts = []

        self.mound_peak_offset = 0.0

        self._collapse = None
        self._next_collapse = time.time() + random.uniform(*COLLAPSE_INTERVAL)

        self._completion_triggered = False

        self.sound_on = True
        try:
            self._sound = _SoundProxy(resource_path(WAV_FILENAME))
        except Exception:
            self._sound = None

        self._gen_static_decor()
        Clock.schedule_interval(self.tick, 1 / 60)

    def _rebuild_color_table(self):
        self._color_table = [
            lerp_rgb(self.sand_base, self.sand_light, i / 10.0)
            for i in range(11)
        ]

    def _gen_static_decor(self):
        rng = random.Random(7)
        self.top_surface = [
            (rng.random(), rng.uniform(-1.5, 1.5), rng.uniform(0.8, 3.5),
             rng.random() < 0.5)
            for _ in range(TOP_DECOR_COUNT)
        ]
        rng = random.Random(13)
        self.mound_surface = [
            (rng.random(), rng.uniform(-1.5, 1.5), rng.uniform(0.5, 3.0),
             rng.random() >= 0.6)
            for _ in range(MOUND_DECOR_COUNT)
        ]
        rng = random.Random(23)
        self.top_curve_noise = [rng.uniform(-1.2, 1.0) for _ in range(CURVE_STEPS + 1)]
        rng = random.Random(31)
        self.mound_curve_noise = [rng.uniform(-1.0, 1.5) for _ in range(CURVE_STEPS + 1)]

    # ---------- 几何 ----------
    def get_geom(self):
        x0, y0 = self.pos
        w, h = self.size
        cx = x0 + w / 2
        top_w = min(w * 0.40, h * 0.18)
        cap_h = max(dp(8), h * 0.025)
        glass_top = y0 + h - cap_h
        glass_bot = y0 + cap_h
        neck_y = (glass_top + glass_bot) / 2
        factor = (60.0 / max(1.0, self.duration)) ** 0.4
        neck_w = max(dp(2.5), min(dp(10), dp(5) * factor))
        return {
            "cx": cx, "top_y": glass_top, "neck_y": neck_y, "bot_y": glass_bot,
            "top_w": top_w, "neck_w": neck_w, "cap_h": cap_h,
        }

    def get_remaining(self):
        return max(0.0, 1 - self.elapsed / self.duration) if self.duration > 0 else 0

    def get_mound_top_y(self):
        g = self.get_geom()
        fallen = 1 - self.get_remaining()
        if fallen <= 0.001:
            return g["bot_y"]
        sand_h = (g["neck_y"] - g["bot_y"]) * (fallen ** (1.0 / 3.0)) * LOWER_SAND_FACTOR
        return g["bot_y"] + sand_h

    def _w_at_y(self, y, glass_top, neck_y, bot_y, top_w, neck_w):
        """玻璃在 y 处的横向半宽"""
        if y >= neck_y:
            t = (y - neck_y) / max(1e-3, glass_top - neck_y)
        else:
            t = 1 - (y - bot_y) / max(1e-3, neck_y - bot_y)
        t = max(0.0, min(1.0, t))
        return neck_w + (top_w - neck_w) * t

    # ---------- 控制 ----------
    def toggle(self):
        if self.running:
            self.running = False
            self._stop_sound()
        else:
            if self.elapsed >= self.duration:
                self.elapsed = 0
                self.particles = []
                self.splashes = []
                self.flares = []
                self.dusts = []
                self.mound_peak_offset = 0.0
                self._completion_triggered = False
            self.running = True
            self.last_tick = time.time()
            if self.sound_on:
                self._play_sound()

    def reset(self):
        self.elapsed = 0
        self.running = False
        self.last_tick = None
        self.particles = []
        self.particle_acc = 0.0
        self.splashes = []
        self.flares = []
        self.dusts = []
        self.mound_peak_offset = 0.0
        self._collapse = None
        self._completion_triggered = False
        self._stop_sound()

    def set_duration(self, d):
        try:
            d = float(d)
            if d > 0:
                self.duration = d
                self.reset()
                return True
        except (TypeError, ValueError):
            pass
        return False

    def set_sand_color(self, base, dark, light):
        self.sand_base = hex_rgb(base)
        self.sand_dark = hex_rgb(dark)
        self.sand_light = hex_rgb(light)
        self._rebuild_color_table()

    def toggle_sound(self):
        self.sound_on = not self.sound_on
        if self.sound_on and self.running:
            self._play_sound()
        elif not self.sound_on:
            self._stop_sound()
        return self.sound_on

    def _play_sound(self):
        if self._sound is not None:
            self._sound.play()

    def _stop_sound(self):
        if self._sound is not None:
            self._sound.stop()

    # ---------- tick / 物理 ----------
    def tick(self, _dt_kivy):
        now = time.time()
        dt = min(0.05, now - self.last_frame)
        self.last_frame = now
        if self.running:
            if self.last_tick is not None:
                self.elapsed += now - self.last_tick
            self.last_tick = now
            if self.elapsed >= self.duration:
                self.elapsed = self.duration
                self.running = False
                self._stop_sound()
                if not self._completion_triggered:
                    self._spawn_dust()
                    self._completion_triggered = True
        self.update_collapse(now)
        self.update_particles(dt)
        self.redraw()
        app = App.get_running_app()
        if app is not None:
            app.update_time(max(0.0, self.duration - self.elapsed), self.duration,
                            running=self.running)

    def update_collapse(self, now):
        if self._collapse is not None:
            if now >= self._collapse["end"]:
                self._collapse = None
                self._next_collapse = now + random.uniform(*COLLAPSE_INTERVAL)
        elif self.running:
            rem = self.get_remaining()
            if 0.05 < rem < 0.95 and now >= self._next_collapse:
                self._collapse = {
                    "tt": random.uniform(0.25, 0.75),
                    "magnitude": random.uniform(1.2, 2.4),
                    "start": now,
                    "end": now + COLLAPSE_DURATION,
                }

    def _collapse_y_offset(self, tt, now=None):
        """对 mound 表面颗粒/曲线求当前塌陷下沉量(Kivy y 向上,负值=向下沉)"""
        if self._collapse is None:
            return 0.0
        c = self._collapse
        if abs(tt - c["tt"]) > 0.18:
            return 0.0
        if now is None:
            now = time.time()
        progress = (now - c["start"]) / COLLAPSE_DURATION
        if progress < 0 or progress > 1:
            return 0.0
        # 0..0.18 快速下沉,0.18..1 慢慢恢复(被新沙补满)
        if progress < 0.18:
            factor = progress / 0.18
        else:
            factor = 1 - ((progress - 0.18) / 0.82) ** 0.6
        falloff = 1 - (abs(tt - c["tt"]) / 0.18) ** 2
        return -c["magnitude"] * factor * falloff

    def _spawn_dust(self):
        g = self.get_geom()
        mound_top = self.get_mound_top_y()
        cx = g["cx"]
        w_at_top = self._w_at_y(mound_top, g["top_y"], g["neck_y"], g["bot_y"],
                                g["top_w"], g["neck_w"])
        now = time.time()
        for _ in range(DUST_COUNT):
            self.dusts.append({
                "x": cx + random.uniform(-w_at_top * 0.7, w_at_top * 0.7),
                "y": mound_top + random.uniform(0, 5),
                "vx": random.uniform(-25, 25),
                "vy": random.uniform(20, 60),
                "end": now + DUST_LIFETIME,
            })

    def update_particles(self, dt):
        g = self.get_geom()
        cx = g["cx"]
        mound_top = self.get_mound_top_y()
        remaining = self.get_remaining()
        now = time.time()

        # 主流粒子生成 — 横向均匀分布(填满颈部缝隙)
        if self.running and remaining > 0:
            speed_factor = max(0.5, min(2.5, 60.0 / self.duration))
            rate = 200 * speed_factor
            if remaining < 0.08:
                rate *= max(0.1, (remaining / 0.08) ** 0.5)
            self.particle_acc += dt * rate
            x_clip = max(1.0, g["neck_w"] - 1)
            while self.particle_acc >= 1:
                self.particle_acc -= 1
                x_off = random.uniform(-x_clip, x_clip)  # 均匀,不再高斯
                self.particles.append({
                    "x": cx + x_off,
                    "x_offset": x_off,
                    "y": g["neck_y"] + random.uniform(-2, 1),  # 起点在颈部内
                    "vy": -random.uniform(60, 90),
                    "is_light": random.random() < 0.10,
                    "size": 2 if random.random() < 0.85 else 1,
                })

        # 主流粒子物理
        gforce = -700.0
        v0_abs = 75.0
        new_list = []
        for p in self.particles:
            p["vy"] += gforce * dt
            p["y"] += p["vy"] * dt

            fallen_dist = max(0.0, g["neck_y"] - p["y"])
            if fallen_dist < 6:
                shrink = 1.0  # 颈部下方 6px 内保持原宽
            else:
                eff_fallen = fallen_dist - 6
                v_at = (v0_abs ** 2 + 2 * 700.0 * eff_fallen) ** 0.5
                shrink = max(0.12, (v0_abs / v_at) ** 0.5)
                # 底部喇叭口
                dist_to_floor = p["y"] - mound_top
                if 0 < dist_to_floor < 30:
                    shrink *= 1 + (1 - dist_to_floor / 30) * 0.4

            p["x"] = cx + p["x_offset"] * shrink

            if p["y"] <= mound_top + 1:
                # EMA 更新中央堆尖
                if mound_top > g["bot_y"] + 1:
                    self.mound_peak_offset = (
                        self.mound_peak_offset * 0.97 + (p["x"] - cx) * 0.03
                    )
                if random.random() < 0.25:
                    self.flares.append({
                        "x": p["x"],
                        "y": mound_top,
                        "end": now + 0.08,
                    })
                if random.random() < 0.50:
                    self.splashes.append({
                        "x": p["x"],
                        "y": mound_top,
                        "vx": random.uniform(-35, 35),
                        "vy": random.uniform(55, 110),
                    })
                continue
            new_list.append(p)
        self.particles = new_list

        # splash 物理
        new_splashes = []
        for s in self.splashes:
            s["vy"] += gforce * dt
            s["y"] += s["vy"] * dt
            s["x"] += s["vx"] * dt
            half_w = self._w_at_y(s["y"], g["top_y"], g["neck_y"], g["bot_y"],
                                  g["top_w"], g["neck_w"])
            if abs(s["x"] - cx) > half_w - 1:
                continue
            if s["vy"] < 0 and s["y"] <= mound_top + 1:
                continue
            if s["y"] < g["bot_y"] or s["y"] > g["neck_y"] - 5:
                continue
            new_splashes.append(s)
        self.splashes = new_splashes

        # flares 过期
        self.flares = [f for f in self.flares if f["end"] > now]

        # dust 物理
        new_dusts = []
        for d in self.dusts:
            d["vy"] += gforce * dt
            d["y"] += d["vy"] * dt
            d["x"] += d["vx"] * dt
            if now > d["end"]:
                continue
            if d["y"] < mound_top - 1:
                continue
            new_dusts.append(d)
        self.dusts = new_dusts

    # ---------- 渲染 ----------
    def redraw(self):
        self.canvas.clear()
        g = self.get_geom()
        cx = g["cx"]
        top_y, neck_y, bot_y = g["top_y"], g["neck_y"], g["bot_y"]
        top_w, neck_w, cap_h = g["top_w"], g["neck_w"], g["cap_h"]
        remaining = self.get_remaining()
        fallen = 1 - remaining
        mound_top_base = self.get_mound_top_y()
        now = time.time()

        with self.canvas:
            # 1. 玻璃填充
            Color(*hex_rgb(GLASS_FILL))
            Quad(points=[cx - top_w, top_y, cx + top_w, top_y,
                         cx + neck_w, neck_y, cx - neck_w, neck_y])
            Quad(points=[cx - neck_w, neck_y, cx + neck_w, neck_y,
                         cx + top_w, bot_y, cx - top_w, bot_y])

            # 2. 玻璃左壁高光 + 右壁阴影
            Color(*GLASS_HIGHLIGHT)
            Line(points=[cx - top_w + 4, top_y - 4,
                         cx - neck_w + 3, neck_y + 2], width=1.5)
            Line(points=[cx - neck_w + 3, neck_y - 2,
                         cx - top_w + 4, bot_y + 4], width=1.5)
            Color(*GLASS_SHADOW)
            Line(points=[cx + top_w - 4, top_y - 4,
                         cx + neck_w - 3, neck_y + 2], width=1.0)
            Line(points=[cx + neck_w - 3, neck_y - 2,
                         cx + top_w - 4, bot_y + 4], width=1.0)

            # 3. 上沙体
            if remaining > 0.001:
                self._draw_top_sand(cx, top_y, neck_y, bot_y, top_w, neck_w,
                                    remaining, fallen)

            # 4. 下沙堆
            if fallen > 0.001:
                self._draw_mound_sand(cx, top_y, neck_y, bot_y, top_w, neck_w,
                                      mound_top_base, fallen)

            # 5. 颈部涌出沙柱
            if remaining > 0.001 and self.running:
                Color(*self.sand_base)
                spout_h = 5
                Rectangle(pos=(cx - neck_w, neck_y - spout_h),
                          size=(2 * neck_w, spout_h))

            # 6. 木盖 + 横纹
            Color(*hex_rgb(WOOD_FILL))
            cap_w = top_w + dp(8)
            Rectangle(pos=(cx - cap_w, top_y), size=(2 * cap_w, cap_h))
            Rectangle(pos=(cx - cap_w, bot_y - cap_h), size=(2 * cap_w, cap_h))
            Color(*WOOD_GRAIN)
            for cap_base_y in (top_y, bot_y - cap_h):
                Line(points=[cx - cap_w, cap_base_y + cap_h * 0.32,
                             cx + cap_w, cap_base_y + cap_h * 0.32], width=0.8)
                Line(points=[cx - cap_w, cap_base_y + cap_h * 0.65,
                             cx + cap_w, cap_base_y + cap_h * 0.65], width=0.8)

            # 7. 玻璃外描边
            Color(0.4, 0.4, 0.4, 1)
            Line(points=[cx - top_w, top_y, cx + top_w, top_y,
                         cx + neck_w, neck_y, cx + top_w, bot_y,
                         cx - top_w, bot_y, cx - neck_w, neck_y,
                         cx - top_w, top_y], width=1.2)

            # 8. 沙流粒子
            for p in self.particles:
                if p["is_light"]:
                    Color(*self.sand_light)
                else:
                    h_total = max(1.0, neck_y - bot_y)
                    idx = int((neck_y - p["y"]) / h_total * 10)
                    idx = max(0, min(10, idx))
                    Color(*self._color_table[idx])
                trail = max(2.0, abs(p["vy"]) * 0.05)
                Rectangle(pos=(p["x"] - p["size"] / 2, p["y"]),
                          size=(p["size"], trail))

            # 9. splash 粒子
            Color(*self.sand_light)
            for s in self.splashes:
                Rectangle(pos=(s["x"] - 0.75, s["y"] - 0.75),
                          size=(1.5, 1.5))

            # 10. flares 半透明闪光
            for f in self.flares:
                rem_life = max(0.0, f["end"] - now) / 0.08
                Color(self.sand_light[0], self.sand_light[1],
                      self.sand_light[2], 0.45 * rem_life)
                size = 4 + rem_life * 2
                Rectangle(pos=(f["x"] - size / 2, f["y"] - size / 2),
                          size=(size, size))

            # 11. 完成尘埃
            Color(*self.sand_light)
            for d in self.dusts:
                Rectangle(pos=(d["x"], d["y"]), size=(1, 1))

            # 12. 暂停遮罩
            if not self.running and 0 < self.elapsed < self.duration:
                Color(0.99, 0.96, 0.89, 0.55)
                Rectangle(pos=self.pos, size=self.size)

    def _draw_top_sand(self, cx, top_y, neck_y, bot_y, top_w, neck_w,
                       remaining, fallen):
        """画上沙体 Mesh + 侧壁描边 + 层理 + 装饰颗粒"""
        sand_top_y = neck_y + (top_y - neck_y) * remaining * UPPER_SAND_FACTOR
        w_at_top = self._w_at_y(sand_top_y, top_y, neck_y, bot_y, top_w, neck_w)

        # 漏斗坑深度,clip 到不能伸进颈部下方
        dip_depth = max(0.0, fallen - 0.05) * 14
        dip_depth = min(dip_depth, max(0.0, sand_top_y - neck_y - 2))

        n = CURVE_STEPS
        verts = [cx, neck_y, 0, 0]                   # fan center
        verts.extend([cx + neck_w, neck_y, 0, 0])    # 颈部右
        for i in range(n + 1):                        # 沙顶从右到左
            t = 1.0 - i / n
            x = cx - w_at_top + 2 * w_at_top * t
            local = 1 - 4 * (t - 0.5) ** 2
            y = sand_top_y - dip_depth * local
            if 0 < i < n:
                y += self.top_curve_noise[i]
            verts.extend([x, y, 0, 0])
        verts.extend([cx - neck_w, neck_y, 0, 0])    # 颈部左

        indices = list(range(len(verts) // 4))
        Color(*self.sand_base)
        Mesh(vertices=verts, indices=indices, mode='triangle_fan')

        # 侧壁描边
        Color(*self.sand_dark)
        Line(points=[cx - w_at_top, sand_top_y,
                     cx - neck_w, neck_y], width=1.0)
        Line(points=[cx + w_at_top, sand_top_y,
                     cx + neck_w, neck_y], width=1.0)

        # 水平层理
        if remaining > 0.18:
            Color(self.sand_dark[0], self.sand_dark[1], self.sand_dark[2], 0.18)
            band_total = sand_top_y - neck_y
            for ratio in (0.30, 0.55, 0.78):
                y_band = sand_top_y - band_total * ratio
                hw = self._w_at_y(y_band, top_y, neck_y, bot_y, top_w, neck_w)
                Line(points=[cx - hw + 2, y_band,
                             cx + hw - 2, y_band], width=0.8)

        # 装饰颗粒 (沙顶下方 1-4.5px)
        for tt, dx, dy, is_dark in self.top_surface:
            local = 1 - 4 * (tt - 0.5) ** 2
            base_x = cx - w_at_top + 2 * w_at_top * tt + dx
            base_y = sand_top_y - dip_depth * local - dy - 1
            limit_w = w_at_top - 1
            if abs(base_x - cx) > limit_w:
                continue
            if base_y < neck_y + 1 or base_y > sand_top_y - 0.5:
                continue
            if is_dark:
                Color(*self.sand_dark)
            else:
                Color(*self.sand_light)
            Rectangle(pos=(base_x - 0.75, base_y - 0.75), size=(1.5, 1.5))

    def _draw_mound_sand(self, cx, top_y, neck_y, bot_y, top_w, neck_w,
                         mound_top_y, fallen):
        """画下沙堆 Mesh + 中央堆尖 + 塌陷 + 装饰颗粒"""
        w_at_top = self._w_at_y(mound_top_y, top_y, neck_y, bot_y, top_w, neck_w)

        # 中央堆尖,clip 到不能高过颈部
        peak_height = max(0.0, fallen - 0.10) * 10
        peak_height = min(peak_height, max(0.0, neck_y - mound_top_y - 2))

        peak_center = 0.5 + max(-0.2, min(0.2, self.mound_peak_offset / max(1.0, w_at_top * 2)))

        n = CURVE_STEPS
        verts = [cx, bot_y, 0, 0]                    # fan center
        verts.extend([cx + top_w, bot_y, 0, 0])      # 底部右
        for i in range(n + 1):                        # 沙堆顶从右到左
            t = 1.0 - i / n
            x = cx - w_at_top + 2 * w_at_top * t
            peak = max(0.0, 1 - 16 * (t - peak_center) ** 2)
            y = mound_top_y + peak_height * peak
            if 0 < i < n:
                y += self.mound_curve_noise[i]
            y += self._collapse_y_offset(t)
            verts.extend([x, y, 0, 0])
        verts.extend([cx - top_w, bot_y, 0, 0])      # 底部左

        indices = list(range(len(verts) // 4))
        Color(*self.sand_base)
        Mesh(vertices=verts, indices=indices, mode='triangle_fan')

        # 侧壁描边
        Color(*self.sand_dark)
        Line(points=[cx - w_at_top, mound_top_y,
                     cx - top_w, bot_y], width=1.0)
        Line(points=[cx + w_at_top, mound_top_y,
                     cx + top_w, bot_y], width=1.0)

        # 水平层理
        if fallen > 0.18:
            Color(self.sand_dark[0], self.sand_dark[1], self.sand_dark[2], 0.18)
            band_total = mound_top_y - bot_y
            for ratio in (0.25, 0.55, 0.80):
                y_band = bot_y + band_total * ratio
                hw = self._w_at_y(y_band, top_y, neck_y, bot_y, top_w, neck_w)
                Line(points=[cx - hw + 2, y_band,
                             cx + hw - 2, y_band], width=0.8)

        # 装饰颗粒
        for tt, dx, dy, is_dark in self.mound_surface:
            peak = max(0.0, 1 - 16 * (tt - peak_center) ** 2)
            base_x = cx - w_at_top + 2 * w_at_top * tt + dx
            base_y = mound_top_y + peak_height * peak - dy - 1
            base_y += self._collapse_y_offset(tt)
            limit_w = w_at_top - 1
            if abs(base_x - cx) > limit_w:
                continue
            if base_y < bot_y + 1 or base_y > mound_top_y + peak_height - 0.5:
                continue
            if is_dark:
                Color(*self.sand_dark)
            else:
                Color(*self.sand_light)
            Rectangle(pos=(base_x - 0.75, base_y - 0.75), size=(1.5, 1.5))


class HourglassApp(App):
    title = "沙漏"

    def build(self):
        if platform != "android":
            try:
                Window.size = (420, 760)
            except Exception:
                pass

        Window.clearcolor = (*hex_rgb(BG_COLOR), 1)

        root = BoxLayout(orientation="vertical", spacing=dp(4),
                         padding=[dp(8), dp(8), dp(8), dp(8)])

        top1 = BoxLayout(orientation="horizontal", size_hint=(1, None),
                         height=dp(44), spacing=dp(6))
        top1.add_widget(Label(text="周期(秒):", size_hint=(None, 1), width=dp(70),
                              color=(0.2, 0.2, 0.2, 1), font_size=sp(14)))
        self.duration_input = CenterTextInput(text="60", multiline=False,
                                              size_hint=(None, 1), width=dp(90),
                                              font_size=sp(22),
                                              input_filter="float")
        self.duration_input.bind(on_text_validate=self._on_set_duration)
        top1.add_widget(self.duration_input)
        set_btn = Button(text="设置", size_hint=(None, 1), width=dp(60), font_size=sp(14))
        set_btn.bind(on_press=self._on_set_duration)
        top1.add_widget(set_btn)
        top1.add_widget(Widget())
        self.sound_btn = Button(text="音效已开", size_hint=(None, 1),
                                width=dp(100), font_size=sp(14))
        self.sound_btn.bind(on_press=self._on_toggle_sound)
        top1.add_widget(self.sound_btn)
        root.add_widget(top1)

        top2 = BoxLayout(orientation="horizontal", size_hint=(1, None),
                         height=dp(40), spacing=dp(4))
        self.color_btns = []
        for name, base, dark, light in SAND_PRESETS:
            r, g, b = hex_rgb(base)
            btn = Button(text=name, font_size=sp(13),
                         background_normal="", background_color=(r, g, b, 1),
                         color=fg_for(base))
            btn.bind(on_press=lambda inst, b=base, d=dark, l=light, n=name:
                     self._on_color(b, d, l, n))
            top2.add_widget(btn)
            self.color_btns.append((name, btn))
        root.add_widget(top2)

        self.time_label = Label(text="60.0s / 60s", font_size=sp(20), bold=True,
                                size_hint=(1, None), height=dp(36),
                                color=(0.2, 0.2, 0.2, 1))
        root.add_widget(self.time_label)

        self.hourglass = HourglassWidget(size_hint=(1, 1))
        root.add_widget(self.hourglass)

        bottom = BoxLayout(orientation="horizontal", size_hint=(1, None),
                           height=dp(56), spacing=dp(6))
        self.toggle_btn = Button(text="下落", font_size=sp(18), bold=True)
        self.toggle_btn.bind(on_press=self._on_toggle)
        bottom.add_widget(self.toggle_btn)
        reset_btn = Button(text="重置", font_size=sp(16))
        reset_btn.bind(on_press=self._on_reset)
        bottom.add_widget(reset_btn)
        root.add_widget(bottom)

        self._mark_selected("金沙")

        return root

    def _on_set_duration(self, *_):
        ok = self.hourglass.set_duration(self.duration_input.text)
        if not ok:
            self.duration_input.text = str(int(self.hourglass.duration))
        self.toggle_btn.text = "下落"

    def _on_toggle(self, *_):
        self.hourglass.toggle()
        self.toggle_btn.text = "停止" if self.hourglass.running else "下落"

    def _on_reset(self, *_):
        self.hourglass.reset()
        self.toggle_btn.text = "下落"

    def _on_toggle_sound(self, *_):
        on = self.hourglass.toggle_sound()
        self.sound_btn.text = "音效已开" if on else "音效已关"

    def _on_color(self, base, dark, light, name):
        self.hourglass.set_sand_color(base, dark, light)
        self._mark_selected(name)

    def _mark_selected(self, name):
        for n, btn in self.color_btns:
            btn.text = (("● " + n) if n == name else n)

    def update_time(self, remaining_sec, duration, running=False):
        self.time_label.text = f"{remaining_sec:.1f}s / {duration:.0f}s"
        if not running and remaining_sec <= 0.001 and self.toggle_btn.text == "停止":
            self.toggle_btn.text = "下落"

    def on_pause(self):
        return True

    def on_resume(self):
        return True


if __name__ == "__main__":
    HourglassApp().run()
