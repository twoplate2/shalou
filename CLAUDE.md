# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

桌面 tkinter 沙漏 (`..\hourglass.py`) 的 Android Kivy 移植版,本目录是**独立 git repo** (`https://github.com/twoplate2/shalou`),与父目录 `..\hourglass.py` 不在同一个仓库里——push 时只会推 `android/` 这一棵树。

入口文件: `main.py` (单文件 Kivy 应用,无 .kv 模板,~960 行)。

## 常用命令

```powershell
# 桌面预览(开发主用)
pip install kivy
python main.py                     # 默认窗口 420×760 模拟手机竖屏

# 重新生成 sand_loop.wav (15s seamless 循环)
python tools/generate_sand_loop.py

# 重新生成 icon.png / presplash.png (PIL 合成)
python tools/generate_icon.py
python tools/generate_presplash.py

# 构建 APK:push → GitHub Actions(Windows 原生不支持 buildozer)
git push origin main               # 触发 .github/workflows/build-apk.yml,~5-8 分钟

# 看构建结果与下载 APK
gh run list --limit 5              # 查最近 run
gh run view <id> --log-failed      # 失败时看日志
# 或网页:https://github.com/twoplate2/shalou/actions → Artifacts → hourglass-apk.zip
```

## ⚠️ 一定要知道的坑

### 1. p4a 必须锁 `v2024.01.21`,否则 100% 编译失败

2026 年起 python-for-android 默认下载 Python 3.14 alpha,`_PyLong_AsByteArray` 改了签名 (5→6 参数),Kivy 2.3 的 Cython 生成代码必失败。`buildozer.spec` 里 `p4a.branch = v2024.01.21` 这一行是命门——格式必须严格 `v + 年.月补零.日补零`,写成 `2024.1.21` 或 `V2024.01.21` 都会 `Remote branch not found`。完整踩坑过程见 `BUILD_APK.md` 的"Python 版本陷阱"小节(本项目第 6 次 push 才搞定)。

### 2. 不要用 `MediaPlayer.setLooping`,短循环必须 SoundPool

Kivy `SoundLoader.load(...).loop = True` 在 Android 底层是 `MediaPlayer.setLooping(True)`,**每次循环边界有 50-100ms 静音 gap**(MediaPlayer 是为长流式音频设计的,不是给短音效用的)。短 wav 循环必须用 `pyjnius` 直调 `android.media.SoundPool`(`_SoundProxy._init_soundpool`)。

写 SoundPool 代码时三个坑:
- `OnLoadCompleteListener` 实例**必须存到 `self._listener`**——`PythonJavaClass` 被 Java 端持有但 Python 端只在局部变量里 → GC 回收后 Java callback 崩溃
- `SoundPool.load()` 是**异步的**,必须等 listener 回调 `status==0` 才能 `play()`,否则静默失败
- WAV ≤ 1MB(SoundPool 单样本上限),> 30s 改用 MediaPlayer

### 3. SoundPool 边界仍可能有 click → wav 长度 + crossfade

即使用了 SoundPool,2s wav 量化到 int16 在 loop 边界仍可能有微小 click(用户实测每 ~10s 一次)。修复方法是**让 wav 更长 + 用 overlap-add crossfade** 让 `sample[0] = filtered[n]`(噪声序列的自然延续),而不是 `whites[0]` 的离散跳变。当前 `sand_loop.wav` 是 15s,生成逻辑在 `tools/generate_sand_loop.py`。**不要再退回 2s wav**——用户已经反馈过这个问题。

### 4. 中文必须注册字体覆盖默认 "Roboto"

Android 系统不带中文字体,Kivy 默认 `font_name="Roboto"` 是拉丁字母字体不含 CJK → APK 装手机后所有汉字显示成豆腐块。`main.py` 顶部 `LabelBase.register(name="Roboto", fn_regular=...)` 用同名注册全局覆盖,所有 Label/Button 自动生效——**不要给单个控件加 `font_name="zh"`,漏一个就乱码**。`buildozer.spec` 的 `source.include_patterns` 必须列 `fonts/*.otf`,否则字体不进 APK。

### 5. TextInput 没有 `text_align` 属性

Kivy 设计缺陷,没有 `halign` / `text_align`。`CenterTextInput` 子类用 `CoreLabel` 测真实文本宽度然后动态调 `padding=[(w-tw)/2, (h-th)/2, ...]`。必须 `Clock.schedule_once(self._refresh_pad, 0)` 等一帧 layout 完成后再算,否则 `__init__` 时 widget size 还是 0×0。

### 6. 不要再尝试上沙/下沙的立方根高度公式

项目踩过 **3 次**:`new_two.deepseek2.md` 提议 → commit `5d7ad6a` 实施 → commit `ec4436e` 部分回退保留下沙立方根 → commit `337d0fa` 彻底回到**线性恒等**:上沙 `H × remaining`、下沙 `H × fallen`、两者之和恒 = H、漏完时下沙顶刚好到颈部(0% 空气)。

立方根理论上对应 3D 锥体积守恒,但**人眼看高度不看体积**:6000s 周期跑 9s 时,立方根让下沙凭空冒 10% 高度而上沙几乎没动,视觉上"沙怎么跑过去的"。截顶锥(`neck_w` 不为 0)的几何下立方根理论上也不严格守恒,见 `volume_model.md`。完整决策与给后续 AI 的提示见 `fix_bug_by_claude.md` §2 + §6。

如果要解长周期"前期下沙不可见"问题,**用单调隐身的保底地板** `max(real, floor)`(见 `floor_simulation.md`),不要再改主公式。

## 核心设计原则:"假物理"

**沙漏的唯一真值是 `elapsed / duration`,所有可见效果都从这两个值派生**——塌陷动画、漏斗坑、喇叭口、尘埃、堆尖跟随都是观感装饰,**不反向影响计时**。粒子系统是纯视觉点缀,粒子撞击不会让 elapsed 加速,沙堆塌陷不会改沙顶位置。

不要引入真物理仿真(粒子互撞、沙粒休止角动力学等)。这是项目反复确认过的方向——用户说"做到近似模拟,别太假就行"。

## main.py 内部架构

3 个核心类的职责切分(读懂这 3 个就读懂了 80% 的代码):

| 类 | 职责 |
|---|---|
| `_SoundProxy` | 音频抽象层。Android 走 SoundPool(`pyjnius`),其它平台 fallback `SoundLoader`。`__init__` 里 `try _init_soundpool except → SoundLoader`,调用方完全不感知差异 |
| `CenterTextInput` | TextInput 居中子类,`bind(text/size/font_size, _refresh_pad)` 自动重算 padding |
| `HourglassWidget` | 主画布。`tick()` 每 16ms 一次:推 `elapsed` → `update_collapse` → `update_particles` → `redraw`。`redraw()` 是 `canvas.clear()` + immediate 重画整张图(每帧 ~1400 个 draw 指令,新机 60fps 无压力) |

### 渲染分层(redraw 顺序绝对不能调换)

```
1. 玻璃 Quad 填充
2. 玻璃左壁高光 / 右壁阴影 Line
3. 上沙体 Mesh (triangle_fan,含漏斗坑、曲线噪声、装饰颗粒、层理、侧壁描边)
4. 下沙堆 Mesh (含中央堆尖、塌陷下沉)
5. 颈部涌出沙柱 (沙流和颈部之间的视觉桥接)
6. 木盖 + 横纹
7. 玻璃外描边
8. 沙流粒子(渐变色 + 大小分布 + 喇叭口扩散)
9. splash 反弹粒子
10. flares 闪光
11. 完成尘埃
12. 暂停遮罩
```

### 颈部物理一致性(用户反复反馈过的点)

颈部缝隙宽 `2*neck_w` 必须看起来跟沙流一样宽,不能"缝隙 1cm 但沙流 0.3cm"。`update_particles` 里 4 个关键修复:

- **横向用 uniform 不用 gauss**:`x_off = random.uniform(-(neck_w-1), neck_w-1)` 撒满缝隙宽度,gauss 中央密集边缘几乎没粒子,看起来像"针"
- **shrink 延后 6px**:颈部下方 6px 内 `shrink = 1.0` 保持原宽,之后才按 `(v0/v_at)^0.5` 流量守恒收缩——给用户一个"先匀速带状再加速变细"的视觉
- **粒子起点入颈**:`y = neck_y + uniform(-2, 1)` 在颈部内 ±2px,看起来"涌出"而非凭空生成
- **颈部涌出沙柱**:`Rectangle(pos=(cx-neck_w, neck_y-5), size=(2*neck_w, 5))` 在颈下画 5px 高的实心沙带,消除颈部和粒子之间的视觉断层

### 静态装饰 vs 动态粒子

`_gen_static_decor()` 在 `__init__` 用 seeded `random.Random(7/13/23/31)` 一次性生成相对参数:
- `top_surface` / `mound_surface`: `(tt, dx, dy, is_dark)` 35+50 颗装饰颗粒
- `top_curve_noise` / `mound_curve_noise`: 沙顶/堆顶曲线的静态锯齿偏移

每帧渲染时把相对参数 `tt ∈ [0,1]` 映射到当前沙体边界 → 沙顶下移时颗粒平滑跟随。**不能每帧 re-seed**——会闪烁。

### 切沙色后立即生效的设计

`top_surface` / `mound_surface` 项**不存色字符串,存 `is_dark` bool**;粒子 dict 不存色,而是 `is_light` bool 或按 y 从 `_color_table[0..10]` 取。`set_sand_color` 切换三元组 + `_rebuild_color_table()`,下一帧所有元素自动反映新颜色,不需要重建任何粒子或装饰。

### 沙体高度公式:线性恒等(commit `337d0fa` 定型)

上下沙都用线性,公式应用到 2 处:

- `get_mound_top_y` (`main.py:362`): `bot_y + (neck_y - bot_y) × fallen`
- `_draw_top_sand` 的 `sand_top_y` (`main.py:733`): `neck_y + (top_y - neck_y) × remaining`

由于沙漏对称(`top_y - neck_y == neck_y - bot_y`),上下沙高度之和恒等于半仓高 H,fallen=1 时下沙顶刚好到颈部(0% 空气)。**这是反复迭代后定型的方案,不要再"优化"为立方根/任何非线性曲线**——见上节"⚠️ 坑 6"。`SAND_FILL_RATIO = 0.80` / `UPPER_SAND_FACTOR` / `LOWER_SAND_FACTOR` 都是历史常量,grep 不到任何一个都是正常的。

## 桌面版 vs Android 版差异

桌面版 `..\hourglass.py` 是 tkinter,**y 向下**;Android 是 Kivy,**y 向上**。从桌面版搬代码时所有 y 坐标计算都要翻转,重力 `g = -700` 而不是 `+450`。其它差异(几何坐标自适配 size 而非硬编码、Mesh 替代 polygon、SoundPool 替代 winsound、CoreLabel 替代 tk.font)都是平台不同必然的。

## 不要做的事

- 不要在沙漏物理里引入"真撞击"——elapsed 仍由墙钟驱动,粒子只是装饰
- 不要给单个 Label/Button 加 `font_name="zh"`,顶部 `LabelBase.register(name="Roboto", ...)` 已经全局覆盖
- 不要把 `sand_loop.wav` 退回 2s——15s + crossfade 是用户反馈定型的方案
- 不要解锁 `p4a.branch`——任何 build 报 `_PyLong_AsByteArray too few arguments` 都是这个原因
- 不要每帧 re-seed 装饰颗粒——会闪烁,装饰参数必须一次性生成
- 不要再改沙体高度公式为立方根/任何非线性曲线——见"⚠️ 坑 6",已踩 3 次,长周期保底要走 `floor_simulation.md` 设计的保底地板而非改主公式

## 相关文档

- `BUILD_APK.md`: 完整云构建指南,含 Python 3.14 陷阱、中文字体、SoundPool 三大坑的来龙去脉
- `fix_bug_by_claude.md`: 沙体高度公式踩坑全记录(§2 deepseek 立方根理论缺陷,§3 上沙线性回归 + 音效双 stream 修复,§6 下沙也回退线性);**改沙体公式 / 改音效前必读**
- `floor_simulation.md`: 长周期保底地板公式 `max(real, floor)` 的模拟分析,**未实施**——若要解决"3600s 周期前期下沙不可见",应走这条路而非改主公式
- `volume_model.md`: 3D 锥/截顶锥体积模型推导,确认实际容器是截顶锥(`neck_w` 不为 0),纯立方根公式理论上也不严格守恒
- `new_two.deepseek2.md`: 失败的 deepseek 设计文档,保留作教训(**勿照搬其第 21 行**)
- `..\CLAUDE.md`: 父项目(包含桌面版的)架构总览
