"""
沙漏 - Android Kivy 版本 (MVP)
保留:外形/上下沙体/粒子流量守恒/计时/6 色块/音效循环
简化:无装饰颗粒/无玻璃高光木纹/无 flares/无底部喇叭/无 EMA 沙堆顶
"""
import math
import os
import random
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.core.text import LabelBase, Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, Line, Quad
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform


# 注册中文字体并覆盖 Kivy 默认 "Roboto" 名,使所有 Label/Button 自动渲染汉字
# Android 系统不带中文字体,不注册的话所有汉字会显示为豆腐块
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
WOOD_FILL = "#8b6f47"

MOUND_MAX_FILL = 1.0
WAV_FILENAME = "sand_loop.wav"


def hex_rgb(h):
    return (int(h[1:3], 16) / 255.0,
            int(h[3:5], 16) / 255.0,
            int(h[5:7], 16) / 255.0)


def resource_path(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def fg_for(hex_color):
    r, g, b = hex_rgb(hex_color)
    luma = r * 0.299 + g * 0.587 + b * 0.114
    return (0, 0, 0, 1) if luma > 0.59 else (1, 1, 1, 1)


class CenterTextInput(TextInput):
    """让 TextInput 文字水平+垂直居中(Kivy 原生 TextInput 默认左对齐顶对齐,无 align 属性)"""

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
    """统一音效接口:Android 用 SoundPool 实现无 gap 循环,桌面 fallback 到 Kivy SoundLoader.

    Android 默认 SoundLoader 底层走 Java MediaPlayer.setLooping(True),循环短音频每次切换
    有 50-100ms 静音 gap → 用户听到沙沙声断续。SoundPool 是 Android 官方为短音效设计的
    API,内存预解码 + 硬件循环,做到无缝重复。
    """

    def __init__(self, wav_path):
        self._is_android = (platform == "android")
        self._sp = None
        self._sound_id = None
        self._stream_id = 0
        self._loaded = False
        self._listener = None  # 防 PythonJavaClass 被 GC
        self._kivy_sound = None

        if self._is_android:
            try:
                self._init_soundpool(wav_path)
                return
            except Exception:
                self._sp = None  # 任何失败 → fallback

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
                    .setMaxStreams(1)
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
            if self._stream_id:
                return  # 已经在播
            if self._loaded:
                # play(soundID, leftVol, rightVol, priority, loop=-1 永久循环, rate)
                self._stream_id = self._sp.play(self._sound_id, 1.0, 1.0, 1, -1, 1.0)
            return
        if self._kivy_sound is not None:
            try:
                if self._kivy_sound.state != "play":
                    self._kivy_sound.play()
            except Exception:
                pass

    def stop(self):
        if self._sp is not None:
            if self._stream_id:
                try:
                    self._sp.stop(self._stream_id)
                except Exception:
                    pass
                self._stream_id = 0
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

        self.particles = []
        self.particle_acc = 0.0

        self.sound_on = True
        try:
            self._sound = _SoundProxy(resource_path(WAV_FILENAME))
        except Exception:
            self._sound = None

        Clock.schedule_interval(self.tick, 1 / 60)

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
        sand_h = (g["neck_y"] - g["bot_y"]) * fallen * MOUND_MAX_FILL
        return g["bot_y"] + sand_h

    # ---------- 控制 ----------
    def toggle(self):
        if self.running:
            self.running = False
            self._stop_sound()
        else:
            if self.elapsed >= self.duration:
                self.elapsed = 0
                self.particles = []
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

    # ---------- tick / 粒子 ----------
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
        self.update_particles(dt)
        self.redraw()
        app = App.get_running_app()
        if app is not None:
            app.update_time(max(0.0, self.duration - self.elapsed), self.duration,
                            running=self.running)

    def update_particles(self, dt):
        g = self.get_geom()
        mound_top = self.get_mound_top_y()
        remaining = self.get_remaining()

        # Kivy y 向上,粒子从颈部 y=neck_y 向下(y 减小)
        if self.running and remaining > 0:
            speed_factor = max(0.5, min(2.5, 60.0 / self.duration))
            rate = 250 * speed_factor
            if remaining < 0.08:
                rate *= max(0.1, (remaining / 0.08) ** 0.5)
            self.particle_acc += dt * rate
            sigma = max(1.0, g["neck_w"] * 0.5)
            x_clip = g["neck_w"] - 1
            while self.particle_acc >= 1:
                self.particle_acc -= 1
                x_off = random.gauss(0, sigma)
                x_off = max(-x_clip, min(x_clip, x_off))
                self.particles.append({
                    "x": g["cx"] + x_off,
                    "x_offset": x_off,
                    "y": g["neck_y"] - random.uniform(0, 1.5),
                    "vy": -random.uniform(40, 65),
                })

        gforce = -700.0
        v0_abs = 50.0
        new_list = []
        for p in self.particles:
            p["vy"] += gforce * dt
            p["y"] += p["vy"] * dt
            fallen = max(0.0, g["neck_y"] - p["y"])
            v_at = (v0_abs ** 2 + 2 * 700.0 * fallen) ** 0.5
            shrink = max(0.12, (v0_abs / v_at) ** 0.5)
            p["x"] = g["cx"] + p["x_offset"] * shrink
            if p["y"] <= mound_top + 1:
                continue
            new_list.append(p)
        self.particles = new_list

    # ---------- 渲染 ----------
    def redraw(self):
        self.canvas.clear()
        g = self.get_geom()
        cx = g["cx"]
        top_y, neck_y, bot_y = g["top_y"], g["neck_y"], g["bot_y"]
        top_w, neck_w, cap_h = g["top_w"], g["neck_w"], g["cap_h"]

        with self.canvas:
            # 玻璃填充(上半倒梯 + 下半正梯)
            Color(*hex_rgb(GLASS_FILL))
            Quad(points=[cx - top_w, top_y, cx + top_w, top_y,
                         cx + neck_w, neck_y, cx - neck_w, neck_y])
            Quad(points=[cx - neck_w, neck_y, cx + neck_w, neck_y,
                         cx + top_w, bot_y, cx - top_w, bot_y])

            # 玻璃描边
            Color(0.4, 0.4, 0.4, 1)
            Line(points=[cx - top_w, top_y, cx + top_w, top_y, cx + neck_w, neck_y,
                         cx + top_w, bot_y, cx - top_w, bot_y, cx - neck_w, neck_y,
                         cx - top_w, top_y], width=1.2)

            # 上沙体(沙顶随 remaining 从 top_y 向 neck_y 下降)
            remaining = self.get_remaining()
            if remaining > 0.001:
                sand_top_y = neck_y + (top_y - neck_y) * remaining
                t = (top_y - sand_top_y) / max(1.0, top_y - neck_y)
                w = top_w * (1 - t) + neck_w * t
                Color(*self.sand_base)
                Quad(points=[cx - w, sand_top_y, cx + w, sand_top_y,
                             cx + neck_w, neck_y, cx - neck_w, neck_y])

            # 下沙堆(底部 top_w,顶部 w2 收窄到 neck_w 方向)
            fallen = 1 - remaining
            if fallen > 0.001:
                sand_h_lo = (neck_y - bot_y) * fallen * MOUND_MAX_FILL
                sand_top_y2 = bot_y + sand_h_lo
                tt = (sand_top_y2 - bot_y) / max(1.0, neck_y - bot_y)
                w2 = top_w * (1 - tt) + neck_w * tt
                Color(*self.sand_base)
                Quad(points=[cx - top_w, bot_y, cx + top_w, bot_y,
                             cx + w2, sand_top_y2, cx - w2, sand_top_y2])

            # 木盖
            Color(*hex_rgb(WOOD_FILL))
            cap_w = top_w + dp(8)
            Rectangle(pos=(cx - cap_w, top_y), size=(2 * cap_w, cap_h))
            Rectangle(pos=(cx - cap_w, bot_y - cap_h), size=(2 * cap_w, cap_h))

            # 粒子(单色,Rectangle 拖尾长度 = |vy|*0.05)
            Color(*self.sand_base)
            for p in self.particles:
                trail = max(2.0, abs(p["vy"]) * 0.05)
                Rectangle(pos=(p["x"] - 1, p["y"]), size=(2, trail))


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

        # 第 1 行
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
        top1.add_widget(Widget())  # spacer
        self.sound_btn = Button(text="音效已开", size_hint=(None, 1), width=dp(100), font_size=sp(14))
        self.sound_btn.bind(on_press=self._on_toggle_sound)
        top1.add_widget(self.sound_btn)
        root.add_widget(top1)

        # 第 2 行: 6 色块
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

        # 时间
        self.time_label = Label(text="60.0s / 60s", font_size=sp(20), bold=True,
                                size_hint=(1, None), height=dp(36),
                                color=(0.2, 0.2, 0.2, 1))
        root.add_widget(self.time_label)

        # 沙漏画布
        self.hourglass = HourglassWidget(size_hint=(1, 1))
        root.add_widget(self.hourglass)

        # 底部
        bottom = BoxLayout(orientation="horizontal", size_hint=(1, None),
                           height=dp(56), spacing=dp(6))
        self.toggle_btn = Button(text="下落", font_size=sp(18), bold=True)
        self.toggle_btn.bind(on_press=self._on_toggle)
        bottom.add_widget(self.toggle_btn)
        reset_btn = Button(text="重置", font_size=sp(16))
        reset_btn.bind(on_press=self._on_reset)
        bottom.add_widget(reset_btn)
        root.add_widget(bottom)

        # 默认选中金沙(第一项)
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
        # 漏完瞬间统一恢复按钮
        if not running and remaining_sec <= 0.001 and self.toggle_btn.text == "停止":
            self.toggle_btn.text = "下落"

    # Android 生命周期
    def on_pause(self):
        return True

    def on_resume(self):
        return True


if __name__ == "__main__":
    HourglassApp().run()
