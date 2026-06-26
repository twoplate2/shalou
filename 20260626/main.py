"""
沙漏 - Android Kivy 版本 (PC 完整球几何移植版)
基于 pc/hourglass_v2.py 的完整球 + 球体积微积分 + v2 布局 + 粒子通道修复

核心差异 vs 旧 Android 版:
- 几何: 完整球(R 公式)替代锥形(线性 w_at_y)
- 体积: v(t)=3t²-2t³ 数值积分替代线性高度
- 渲染: Kivy Ellipse + Stencil 裁剪替代 Mesh triangle_fan 锥形
- 布局: v2 色块上移+控件下移
- 粒子: 通道宽度自适应尺寸
"""
import math
import os
import random
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase, Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, Line, Ellipse
from kivy.graphics import StencilPush, StencilPop, StencilUse, StencilUnUse
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
GLASS_OUTLINE = (0.373, 0.420, 0.439, 1.0)  # #5f6b70
GLASS_OUTLINE_W_SCALE = 0.0158  # 6/380, 壁厚占 canvas_w 比例

# 沙子飞行到底时间 ≈ 1.0s
FALL_DELAY = 1.0
MOUND_APPEAR = 0.5
MOUND_FLOOR_MIN = 2.5
MOUND_FLOOR_MAX = 3.5
MOUND_FLOOR_EFF = 0.02

COLLAPSE_INTERVAL = (2.5, 4.0)
COLLAPSE_DURATION = 0.6
DUST_COUNT = 25
DUST_LIFETIME = 1.0

WAV_FILENAME = "sand_loop.wav"


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


# ---------- CenterTextInput (居中输入框) ----------

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


# ---------- 音效代理 (双 stream crossfade, 与旧版一致) ----------

class _SoundProxy:
    _WAV_DURATION = 15.0
    _FADE_OVERLAP = 0.1
    _FADE_STEPS = 10

    def __init__(self, wav_path):
        self._is_android = (platform == "android")
        self._sp = None
        self._sound_id = None
        self._loaded = False
        self._listener = None
        self._kivy_sound = None
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
        new_stream = self._sp.play(self._sound_id, 0.0, 0.0, 1, 0, 1.0)
        old_stream = self._current_stream
        for k in range(1, self._FADE_STEPS + 1):
            t = k / self._FADE_STEPS
            old_vol = math.cos(t * math.pi / 2)
            new_vol = math.sin(t * math.pi / 2)
            ev = Clock.schedule_once(
                lambda _dt, o=old_stream, n=new_stream, ov=old_vol, nv=new_vol:
                    self._apply_volumes(o, n, ov, nv),
                self._FADE_OVERLAP * t)
            self._fade_events.append(ev)
        ev = Clock.schedule_once(
            lambda _dt, sid=old_stream: self._safe_stop(sid),
            self._FADE_OVERLAP + 0.01)
        self._fade_events.append(ev)
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


# ---------- 沙漏画布 (完整球几何) ----------

class HourglassWidget(Widget):
    """沙漏画布。Kivy 坐标 y 向上 (top > bot)。完整球 + 颈部圆柱管。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.duration = 60.0
        self.elapsed = 0.0
        self.running = False
        self.last_tick = None
        self.last_frame = time.time()

        self.sand_base = hex_rgb(SAND_PRESETS[0][1])
        self.sand_dark = hex_rgb(SAND_PRESETS[0][2])
        self.sand_light = hex_rgb(SAND_PRESETS[0][3])
        self._color_table = []
        self._rebuild_color_table()

        # 球几何(延迟到 size 确定后重建)
        self._geom_ready = False
        self._R = 0.0
        self._R_inner = 0.0
        self._upper_y_c = 0.0
        self._lower_y_c = 0.0
        self._vol_to_height = []

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

        self.bind(size=self._on_size, pos=self._on_size)
        Clock.schedule_once(self._on_size, 0)
        Clock.schedule_interval(self.tick, 1 / 60)

    # ---------- 球几何 ----------

    def _on_size(self, *_):
        self._rebuild_height_table()

    @property
    def neck_w(self):
        """颈部半宽, 随 duration 缩放"""
        base = max(dp(2.5), self.width * 0.0316)  # 12/380
        factor = (60.0 / max(1.0, self.duration)) ** 0.4
        return max(dp(2), min(dp(14), base * factor))

    @property
    def speed_factor(self):
        return max(0.5, min(2.5, 60.0 / max(0.1, self.duration)))

    def _rebuild_height_table(self):
        """完整球体积查找表(两球 + 颈部圆柱管)"""
        w, h = self.width, self.height
        if w <= 0 or h <= 0:
            return

        glass_outline_w = max(dp(2), w * GLASS_OUTLINE_W_SCALE)
        tube_h = max(dp(10), h * 0.0315)  # 23/730

        # 玻璃区域
        cap_h = max(dp(6), h * 0.022)  # 木盖
        glass_top = self.y + h - cap_h
        glass_bot = self.y + cap_h
        neck_y = (glass_top + glass_bot) / 2

        ball_h = (glass_top - glass_bot - tube_h) / 2
        nw = self.neck_w
        R = (ball_h**2 + nw**2) / (2 * ball_h) if ball_h > 0 else ball_h

        self._R = R
        self._R_inner = R - glass_outline_w
        self._glass_outline_w = glass_outline_w
        self._tube_h = tube_h
        self._cx = self.x + w / 2
        self._glass_top = glass_top
        self._glass_bot = glass_bot
        self._neck_y = neck_y
        self._ball_h = ball_h
        self._upper_y_c = glass_top - R
        self._lower_y_c = glass_bot + R

        Ri = self._R_inner
        self._upper_sand_top = self._upper_y_c + Ri   # 上球内壁顶
        self._upper_sand_bot = self._upper_y_c - Ri   # 上球内壁底(接管)
        self._lower_sand_top = self._lower_y_c + Ri   # 下球内壁顶(接管)
        self._lower_sand_bot = self._lower_y_c - Ri   # 下球内壁底

        # 数值积分 v(t), t∈[0,1], t=0 球顶→t=1 截口
        n = 101
        dy = ball_h / (n - 1)
        prev_w2 = self._w2_at_ball_ratio(0.0)
        V_total = 0.0
        for i in range(1, n):
            w2 = self._w2_at_ball_ratio(i / (n - 1))
            V_total += (prev_w2 + w2) / 2 * dy
            prev_w2 = w2
        table = [(0.0, 0.0)]
        cum = 0.0
        prev_w2 = self._w2_at_ball_ratio(0.0)
        for i in range(1, n):
            w2 = self._w2_at_ball_ratio(i / (n - 1))
            cum += (prev_w2 + w2) / 2 * dy
            table.append((cum / V_total if V_total > 0 else 0.0, i / (n - 1)))
            prev_w2 = w2
        self._vol_to_height = table
        self._geom_ready = True

    def _w2_at_ball_ratio(self, t):
        """球在高度比例 t 处的半宽平方(t=0 球顶, t=1 截口)"""
        y = self._glass_top - t * self._ball_h
        return max(0.0, self._R**2 - (y - self._upper_y_c)**2)

    def _raw_height_ratio(self, vol_ratio):
        """体积比例 → 高度比例(raw), 二分查找表"""
        if vol_ratio <= 0:
            return 0.0
        if vol_ratio >= 1:
            return 1.0
        table = self._vol_to_height
        lo, hi = 0, len(table) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if table[mid][0] < vol_ratio:
                lo = mid
            else:
                hi = mid
        v0, x0 = table[lo]
        v1, x1 = table[hi]
        if v1 == v0:
            return x0
        t = (vol_ratio - v0) / (v1 - v0)
        return x0 + (x1 - x0) * t

    def get_remaining(self):
        return max(0.0, 1 - self.elapsed / self.duration) if self.duration > 0 else 0

    # ---------- 下落延迟 ----------

    @property
    def _fall_delay(self):
        return min(FALL_DELAY, self.duration * 0.5)

    def _effective_fallen(self):
        if self.duration <= 0:
            return 0.0
        if not self.running and self.elapsed >= self.duration:
            return 1.0
        return max(0.0, (self.elapsed - self._fall_delay) / self.duration)

    def _mound_floor(self, eff):
        if eff <= 0:
            return MOUND_FLOOR_MIN
        t = min(1.0, (eff / MOUND_FLOOR_EFF) ** 0.5)
        return MOUND_FLOOR_MIN + (MOUND_FLOOR_MAX - MOUND_FLOOR_MIN) * t

    def _mound_height_px(self):
        """下沙堆高度(像素)"""
        eff = self._effective_fallen()
        ball_h_px = 2 * self._R_inner
        delay = self._fall_delay
        if self.elapsed < delay:
            return 0.0
        target = max(self._raw_height_ratio(eff) * ball_h_px, self._mound_floor(eff))
        appear_window = max(0.01, min(MOUND_APPEAR, self.duration - delay))
        appear = min(1.0, (self.elapsed - delay) / appear_window)
        return appear * target

    def get_mound_top_y(self):
        """下沙堆顶 y(Kivy y 向上)"""
        h = self._mound_height_px()
        if h <= 0:
            return self._lower_sand_bot
        return self._lower_sand_bot + h

    def _sand_half_w(self, y, yc):
        """球内壁(yc 为球心)在 y 处的半宽"""
        return math.sqrt(max(0.0, self._R_inner**2 - (y - yc)**2))

    # ---------- 控制 ----------

    def toggle(self):
        if self.running:
            self.running = False
            self._stop_sound()
        else:
            if self.elapsed >= self.duration:
                self.elapsed = 0
                self._reset_run_state()
            self.running = True
            self.last_tick = time.time()
            if self.sound_on:
                self._play_sound()

    def reset(self):
        self.elapsed = 0
        self.running = False
        self.last_tick = None
        self._reset_run_state()
        self._stop_sound()

    def _reset_run_state(self):
        self.particles = []
        self.particle_acc = 0.0
        self.splashes = []
        self.flares = []
        self.dusts = []
        self.mound_peak_offset = 0.0
        self._collapse = None
        self._next_collapse = time.time() + random.uniform(*COLLAPSE_INTERVAL)
        self._completion_triggered = False

    def set_duration(self, d):
        try:
            d = float(d)
        except (TypeError, ValueError):
            return False
        if d <= 0:
            return False
        d = min(d, 100000)
        if d == self.duration:
            return False
        self.duration = d
        self._rebuild_height_table()
        self.reset()
        return True

    def set_sand_color(self, base, dark, light):
        self.sand_base = hex_rgb(base)
        self.sand_dark = hex_rgb(dark)
        self.sand_light = hex_rgb(light)
        self._rebuild_color_table()

    def _rebuild_color_table(self):
        self._color_table = [
            lerp_rgb(self.sand_base, self.sand_light, i / 10.0)
            for i in range(11)
        ]

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
        if not self._geom_ready:
            return
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
            app.update_time(max(0.0, self.duration - self.elapsed), self.duration)

    def update_collapse(self, now):
        if self._collapse is not None:
            if now >= self._collapse["end"]:
                self._collapse = None
                self._next_collapse = now + random.uniform(*COLLAPSE_INTERVAL)
        elif self.running:
            eff_fallen = self._effective_fallen()
            if 0.05 < eff_fallen < 0.95 and now >= self._next_collapse:
                self._collapse = {
                    "tt": random.uniform(0.25, 0.75),
                    "magnitude": random.uniform(1.2, 2.4),
                    "start": now,
                    "end": now + COLLAPSE_DURATION,
                }

    def _spawn_dust(self):
        mound_top = self.get_mound_top_y()
        cx = self._cx
        w_at_top = self._sand_half_w(mound_top, self._lower_y_c)
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
        if not self._geom_ready:
            return
        cx = self._cx
        mound_top = self.get_mound_top_y()
        remaining = self.get_remaining()
        now = time.time()
        neck_w = self.neck_w
        glass_ow = self._glass_outline_w

        # 主流粒子生成
        if self.running and remaining > 0:
            rate = 600 * self.speed_factor
            if remaining < 0.08:
                rate *= max(0.1, (remaining / 0.08) ** 0.5)
            self.particle_acc += dt * rate
            x_clip = max(1.0, neck_w - glass_ow / 2)
            while self.particle_acc >= 1:
                self.particle_acc -= 1
                x_off = random.uniform(-x_clip, x_clip)
                # 粒子尺寸自适应通道宽: 窄通道全用 size=1
                p_size = (2 if random.random() < 0.85 else 1) if x_clip >= 3.0 else 1
                self.particles.append({
                    "x": cx + x_off,
                    "x_offset": x_off,
                    "y": self._upper_sand_bot + random.uniform(-2, 1),
                    "vy": -random.uniform(60, 90),
                    "is_light": random.random() < 0.10,
                    "size": p_size,
                })

        gforce = -700.0
        v0_abs = 75.0
        new_list = []
        for p in self.particles:
            p["vy"] += gforce * dt
            p["y"] += p["vy"] * dt
            fallen_dist = max(0.0, self._upper_sand_bot - p["y"])

            if fallen_dist < 6:
                shrink = 1.0
            else:
                eff_fallen = fallen_dist - 6
                v_at = (v0_abs**2 + 2 * 700.0 * eff_fallen) ** 0.5
                shrink = max(0.12, (v0_abs / v_at) ** 0.5)
                dist_to_floor = p["y"] - mound_top
                if 0 < dist_to_floor < 30:
                    shrink *= 1 + (1 - dist_to_floor / 30) * 0.4

            p["x"] = cx + p["x_offset"] * shrink

            # 横向 clamp(扣除线宽视觉延伸)
            tube_lim = max(1.0, neck_w - glass_ow / 2)
            if p["y"] > self._lower_sand_top:
                lim = tube_lim
            else:
                lim = max(tube_lim, self._sand_half_w(p["y"], self._lower_y_c))
            lim = max(0.2, lim - p["size"] / 2.0)
            off = p["x"] - cx
            p["x"] = cx + max(-lim, min(lim, off))

            if p["y"] <= mound_top + 1:
                if mound_top > self._lower_sand_bot + 1:
                    self.mound_peak_offset = (
                        self.mound_peak_offset * 0.97 + (p["x"] - cx) * 0.03
                    )
                if random.random() < 0.25:
                    self.flares.append({
                        "x": p["x"], "y": mound_top, "end": now + 0.08,
                    })
                if random.random() < 0.50:
                    self.splashes.append({
                        "x": p["x"], "y": mound_top,
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
            half_w = self._sand_half_w(s["y"], self._lower_y_c)
            if abs(s["x"] - cx) > half_w - 1:
                continue
            if s["vy"] < 0 and s["y"] <= mound_top + 1:
                continue
            if s["y"] < self._lower_sand_bot or s["y"] > self._lower_sand_top - 5:
                continue
            new_splashes.append(s)
        self.splashes = new_splashes

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
        if not self._geom_ready:
            return

        cx = self._cx
        R = self._R
        Ri = self._R_inner
        ow = self._glass_outline_w
        upper_y_c = self._upper_y_c
        lower_y_c = self._lower_y_c
        u_sand_bot = self._upper_sand_bot
        l_sand_top = self._lower_sand_top
        remaining = self.get_remaining()
        now = time.time()
        nw = self.neck_w

        with self.canvas:
            # === 1. 玻璃外壳 (Ellipse + Rectangle) ===
            # 上球外壁
            Color(*GLASS_OUTLINE)
            Ellipse(pos=(cx - R, upper_y_c - R), size=(2 * R, 2 * R))
            # 上球内壁(填充色)
            Color(*hex_rgb(GLASS_FILL))
            Ellipse(pos=(cx - R + ow, upper_y_c - R + ow),
                    size=(2 * (R - ow), 2 * (R - ow)))
            # 下球外壁
            Color(*GLASS_OUTLINE)
            Ellipse(pos=(cx - R, lower_y_c - R), size=(2 * R, 2 * R))
            # 下球内壁
            Color(*hex_rgb(GLASS_FILL))
            Ellipse(pos=(cx - R + ow, lower_y_c - R + ow),
                    size=(2 * (R - ow), 2 * (R - ow)))
            # 颈部管子 fill + 管壁线
            tube_w = nw
            tube_top = upper_y_c - R + ow  # 上球内壁底
            tube_bot = lower_y_c + R - ow  # 下球内壁顶
            Color(*hex_rgb(GLASS_FILL))
            Rectangle(pos=(cx - tube_w, tube_bot),
                      size=(2 * tube_w, tube_top - tube_bot))
            Color(*GLASS_OUTLINE)
            Rectangle(pos=(cx - tube_w, tube_bot),
                      size=(ow, tube_top - tube_bot))
            Rectangle(pos=(cx + tube_w - ow, tube_bot),
                      size=(ow, tube_top - tube_bot))

            # === 2. 木盖 ===
            cap_h = max(dp(6), self.height * 0.022)
            cap_w = R + dp(4)
            wood_rgb = hex_rgb("#8b6f47")
            Color(*wood_rgb)
            Rectangle(pos=(cx - cap_w, self._glass_top),
                      size=(2 * cap_w, cap_h))
            Rectangle(pos=(cx - cap_w, self._glass_bot - cap_h),
                      size=(2 * cap_w, cap_h))
            grain_rgb = (0.435, 0.349, 0.22, 1.0)
            Color(*grain_rgb)
            for base_y in (self._glass_top, self._glass_bot - cap_h):
                Line(points=[cx - cap_w, base_y + cap_h * 0.32,
                             cx + cap_w, base_y + cap_h * 0.32], width=0.8)
                Line(points=[cx - cap_w, base_y + cap_h * 0.65,
                             cx + cap_w, base_y + cap_h * 0.65], width=0.8)

            # === 3. 上沙体 (Stencil 裁剪弓形) ===
            if remaining > 0.001:
                eff = self._effective_fallen()
                cut_y = u_sand_bot + (self._upper_sand_top - u_sand_bot) * (1 - self._raw_height_ratio(eff))
                self._draw_sand_chord(upper_y_c, Ri, cut_y, above=False)

            # === 4. 下沙堆 ===
            h_mound = self._mound_height_px()
            if h_mound > 0.5:
                cut_y = self._lower_sand_bot + h_mound
                self._draw_sand_chord(lower_y_c, Ri, cut_y, above=True)

            # === 5. 颈部沙柱 ===
            if self.elapsed > 0 and remaining > 0.001:
                tsw = max(1.0, nw - ow / 2)
                Color(*self.sand_base)
                Rectangle(pos=(cx - tsw, u_sand_bot),
                          size=(2 * tsw, l_sand_top - u_sand_bot))

            # === 6. 沙流粒子 ===
            for p in self.particles:
                if p["is_light"]:
                    Color(*self.sand_light)
                else:
                    h_total = max(1.0, self._neck_y - self._glass_bot)
                    idx = int((self._neck_y - p["y"]) / h_total * 10)
                    idx = max(0, min(10, idx))
                    Color(*self._color_table[idx])
                trail = max(2.0, abs(p["vy"]) * 0.05)
                Rectangle(pos=(p["x"] - p["size"] / 2, p["y"]),
                          size=(p["size"], trail))

            # === 7. splash 粒子 ===
            Color(*self.sand_light)
            for s in self.splashes:
                Rectangle(pos=(s["x"] - 0.75, s["y"] - 0.75), size=(1.5, 1.5))

            # === 8. flares 闪光 ===
            for f in self.flares:
                rem_life = max(0.0, f["end"] - now) / 0.08
                Color(self.sand_light[0], self.sand_light[1],
                      self.sand_light[2], 0.45 * rem_life)
                size = 4 + rem_life * 2
                Rectangle(pos=(f["x"] - size / 2, f["y"] - size / 2),
                          size=(size, size))

            # === 9. 完成尘埃 ===
            Color(*self.sand_light)
            for d in self.dusts:
                Rectangle(pos=(d["x"], d["y"]), size=(1, 1))

            # === 10. 暂停遮罩 ===
            if not self.running and 0 < self.elapsed < self.duration:
                Color(0.99, 0.96, 0.89, 0.55)
                Rectangle(pos=self.pos, size=self.size)

    def _draw_sand_chord(self, yc, Ri, cut_y, above):
        """用 Stencil 裁剪画出球内壁被 cut_y 截出的弓形。
        above=True: 画 cut_y 以上部分(Kivy y 向上, 下沙)
        above=False: 画 cut_y 以下部分(上沙)"""
        x0, y0 = self.pos
        w, h = self.size
        cx = self._cx

        StencilPush()
        if above:
            # 保留 cut_y 以上(下沙堆, 从 cut_y 往上)
            Color(1, 1, 1, 1)
            Rectangle(pos=(x0, cut_y), size=(w, y0 + h - cut_y))
        else:
            # 保留 cut_y 以下(上沙, 从底部到 cut_y)
            Color(1, 1, 1, 1)
            Rectangle(pos=(x0, y0), size=(w, cut_y - y0))
        StencilUse()
        Color(*self.sand_base)
        Ellipse(pos=(cx - Ri, yc - Ri), size=(2 * Ri, 2 * Ri))
        StencilUnUse()
        StencilPop()


# ---------- App ----------

class HourglassApp(App):
    title = "跳跳的沙漏"

    def build(self):
        if platform != "android":
            try:
                Window.size = (420, 760)
            except Exception:
                pass
        Window.clearcolor = (*hex_rgb(BG_COLOR), 1)

        root = BoxLayout(orientation="vertical", spacing=dp(2),
                         padding=[dp(6), dp(4), dp(6), dp(4)])

        # === v2 布局: 顶部色块 ===
        top_colors = BoxLayout(orientation="horizontal", size_hint=(1, None),
                               height=dp(42), spacing=dp(3))
        self.color_btns = []
        for name, base, dark, light in SAND_PRESETS:
            r, g, b = hex_rgb(base)
            btn = Button(text=name, font_size=sp(13),
                         background_normal="", background_color=(r, g, b, 1),
                         color=fg_for(base))
            btn.bind(on_press=lambda inst, b=base, d=dark, l=light, n=name:
                     self._on_color(b, d, l, n))
            top_colors.add_widget(btn)
            self.color_btns.append((name, btn))
        root.add_widget(top_colors)

        # === 倒计时(位置不变) ===
        self.time_label = Label(text="60s / 60s", font_size=sp(20), bold=True,
                                size_hint=(1, None), height=dp(32),
                                color=(0.2, 0.2, 0.2, 1))
        root.add_widget(self.time_label)

        # === 沙漏画布 ===
        self.hourglass = HourglassWidget(size_hint=(1, 1))
        root.add_widget(self.hourglass)

        # === v2 布局: 底部控件 ===
        bottom_ctrl = BoxLayout(orientation="horizontal", size_hint=(1, None),
                                height=dp(48), spacing=dp(4))
        bottom_ctrl.add_widget(Label(text="周期:", size_hint=(None, 1),
                                     width=dp(52), color=(0.2, 0.2, 0.2, 1),
                                     font_size=sp(14)))
        self.duration_input = CenterTextInput(text="60", multiline=False,
                                              size_hint=(None, 1), width=dp(70),
                                              font_size=sp(20),
                                              input_filter="float")
        self.duration_input.bind(on_text_validate=self._on_set_duration)
        bottom_ctrl.add_widget(self.duration_input)
        self.sound_btn = Button(text="音效:开", size_hint=(None, 1),
                                width=dp(64), font_size=sp(12))
        self.sound_btn.bind(on_press=self._on_toggle_sound)
        bottom_ctrl.add_widget(self.sound_btn)
        bottom_ctrl.add_widget(Widget())
        self.start_btn = Button(text="开始", size_hint=(None, 1),
                                width=dp(64), font_size=sp(14), bold=True,
                                background_color=(0.353, 0.620, 0.243, 1),
                                color=(1, 1, 1, 1))
        self.start_btn.bind(on_press=self._on_toggle)
        bottom_ctrl.add_widget(self.start_btn)
        reset_btn = Button(text="重置", size_hint=(None, 1),
                           width=dp(64), font_size=sp(14))
        reset_btn.bind(on_press=self._on_reset)
        bottom_ctrl.add_widget(reset_btn)
        root.add_widget(bottom_ctrl)

        self._mark_selected("金沙")
        return root

    def _on_set_duration(self, *_):
        changed = self.hourglass.set_duration(self.duration_input.text)
        if not changed:
            self.duration_input.text = str(int(self.hourglass.duration))
        self._update_start_btn()

    def _on_toggle(self, *_):
        # 先应用周期(幂等), 再 toggle
        self.hourglass.set_duration(self.duration_input.text)
        self.duration_input.text = str(int(self.hourglass.duration))
        self.hourglass.toggle()
        self._update_start_btn()

    def _on_reset(self, *_):
        self.hourglass.set_duration(self.duration_input.text)
        self.duration_input.text = str(int(self.hourglass.duration))
        self.hourglass.reset()
        self._update_start_btn()

    def _update_start_btn(self):
        if self.hourglass.running:
            self.start_btn.text = "暂停"
            self.start_btn.background_color = (0.851, 0.557, 0.243, 1)
        else:
            self.start_btn.text = "开始"
            self.start_btn.background_color = (0.353, 0.620, 0.243, 1)

    def _on_toggle_sound(self, *_):
        on = self.hourglass.toggle_sound()
        self.sound_btn.text = "音效:开" if on else "音效:关"

    def _on_color(self, base, dark, light, name):
        self.hourglass.set_sand_color(base, dark, light)
        self._mark_selected(name)

    def _mark_selected(self, name):
        for n, btn in self.color_btns:
            btn.text = (("● " + n) if n == name else n)

    def update_time(self, remaining_sec, duration):
        self.time_label.text = f"{remaining_sec:.0f}s / {duration:.0f}s"

    def on_pause(self):
        return True

    def on_resume(self):
        return True


if __name__ == "__main__":
    HourglassApp().run()
