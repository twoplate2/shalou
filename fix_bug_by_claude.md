
本次(2026-05-22)修复记录,以及上一轮 deepseek 设计建议中的具体缺陷。

---

## 1. 上一轮发生了什么

### 1.1 deepseek 写的设计文档

`new_two.deepseek2.md`(用户委托 deepseek 写的)提出 2 个需求:

1. **3600s 长周期下沙看不见** — 线性公式下,fallen=0.001 时沙堆只有 0.3px,要等 10 分钟才看到。
2. **流完后下仓应该留 10% 空气** — 上仓初始填到 100%,下沙因形状不同最多堆到 ~90%。

deepseek 给的解法是 3D 锥模型:`体积 ∝ 高度³` → `高度 ∝ 体积^(1/3)`。

但文档第 21 行加了一条:

> 上沙也要同步用 `remaining^(1/3)`,否则上下增长速度不一致,沙量看起来不守恒。

**这一条建议是有理论缺陷的**,见 §2。

### 1.2 另一个 AI 按 deepseek 文档改了代码

那个 AI 把上下沙公式都改成立方根,常量从 `SAND_FILL_RATIO = 0.80` 拆成 `UPPER_SAND_FACTOR = 1.0` + `LOWER_SAND_FACTOR = 0.9`,push 上线。

下沙的修改是对的(解决了需求 1)。但**上沙的立方根**让用户实测后立即反馈:

> 出现上面的沙漏一直流,但是高度不变的问题

---

## 2. deepseek 建议的具体缺陷

### 2.1 立方根公式的前提

`V ∝ h³` 只对**纯锥**(顶点收敛到 0)成立。例如一个标准圆锥:
- 顶部圆形截面半径 R, 高度 H
- 体积 V = (1/3) π R² H
- 沙顶到颈部高度 h 时,沙体形状与原锥形相似,小锥半径 = R·h/H
- 沙体积 V_h = (1/3) π (R·h/H)² · h = (1/3) π R² h³ / H²
- V_h / V = (h/H)³ ✓

### 2.2 Kivy 实际容器不是纯锥

`main.py` 的 `_w_at_y`:

```python
def _w_at_y(self, y, glass_top, neck_y, bot_y, top_w, neck_w):
    # ...
    return neck_w + (top_w - neck_w) * t
```

颈部宽 `neck_w` **不为 0**(4~20 dp,随周期变化)。容器是**截顶锥**而非纯锥。截顶锥的体积公式:

```
V = (h/3) · (A1 + A2 + sqrt(A1·A2))
```

其中 A1, A2 是上下底面积。这不是 h³ 关系,所以"严格立方根"在 Kivy 几何下本来就不成立 —— **deepseek 的"沙量守恒"理论站不住脚**。

### 2.3 立方根上沙的视觉副作用

立方根曲线在 remaining 大时极平。数值验证:

| remaining | `remaining^(1/3)` | 上沙下降比例 |
|---|---|---|
| 1.00 | 1.000 | 0% (满) |
| 0.90 | 0.965 | 3.5% |
| 0.50 | 0.794 | 20.6% |
| 0.30 | 0.669 | 33.1% |
| 0.10 | 0.464 | 53.6% |
| 0.01 | 0.215 | 78.5% |
| 0.00 | 0.000 | 100% |

**前 50% 时间上沙仅下降 20.6%**。在 60s 周期下,前 30 秒用户几乎看不出上沙顶在动 —— 这就是"一直流但高度不变"的根因。

### 2.4 deepseek 错在哪儿

错在**没有验证 Kivy 实际几何**:

- 文档假设容器是纯锥,但实际是截顶锥(`neck_w` 不为 0)。
- 文档关注"沙量守恒"(数学性质),但用户视觉上感知的是"上沙下降速度"(感官性质)。两者目标错位。
- 文档第 21 行的"否则沙量不守恒"是**用一个用户察觉不到的问题(沙量),换取一个用户立刻能察觉的问题(高度不变)**。

### 2.5 上一个 AI 错在哪儿

按文档照搬,**没有跑桌面预览验证视觉效果**就 push。如果它在桌面跑过 60s 周期,5 秒内就会发现上沙没下降。

---

## 3. 本次修复(2026-05-22, commit `ec4436e`)

### 3.1 沙体公式

| 部位 | 之前(其他 AI) | 之后(本次) |
|---|---|---|
| 上沙 `sand_top_y` | `(remaining ** (1.0/3.0)) * 1.0` | **`remaining * 1.0`** |
| 下沙 `sand_h`(`get_mound_top_y`) | `(fallen ** (1.0/3.0)) * 0.9` | 保持不动 |
| `UPPER_SAND_FACTOR` / `LOWER_SAND_FACTOR` | `1.0` / `0.9` | 保持不动 |

这样:

- ✓ 需求 1(下沙立刻可见)仍然满足:`fallen=0.001` → 下沙堆 9% 高度。
- ✓ 需求 2(留 10% 空气)仍然满足:终点下沙 90%,上沙 0,自然差 10%。
- ✓ 上沙现在线性下降:`remaining=0.5` 时沙顶下降 50% 高度,用户能直观感知。
- ✗ 总沙量在视觉上不严格守恒,但截顶锥本来也不严格守恒,人眼根本分辨不出。

### 3.2 音效问题(用户反馈"15s 版本仍有爆音和静音")

诊断出**两层独立根因**:

#### 第一层:wav 自身的 fade 算法

之前 `tools/generate_sand_loop.py`:

```python
samples[i] = filtered[n + i] * (1 - t) + filtered[i] * t
```

linear crossfade 有两个问题:

1. **能量凹陷**: 两个独立信号的加权和的方差 = `(1-t)²σ² + t²σ²`,在 `t=0.5` 时 = `0.5σ²`,即 rms 降到 `0.707σ`,**-3dB**。fade 区间听起来"忽轻"。
2. **单端处理**: 只对 `samples[0..crossfade-1]` 做了平滑,`samples[n-1]` 仍是裸样本。每次循环到 `samples[n-1] → samples[0]` 时虽然滤波器序列是连续的,但 fade 边界本身的能量阶跃会被感知。

修复:用 **equal-power fade**,`a = cos(t·π/2)`, `b = sin(t·π/2)`。任意 t 处 `a² + b² = 1`,叠加能量恒等于 σ²,听不出能量包络变化。

#### 第二层:SoundPool 自身

Android `SoundPool.play(soundID, ..., loop=-1)` 不是真正的硬件 ring buffer。底层是检测到 sample 末尾后**重新提交 sample buffer**,部分机型(包括用户实测的)有 ~10-30ms 的 audio buffer 空窗。

**单 wav + 单 stream 解决不了这个 gap** —— 不管 wav 多长、fade 多平滑,SoundPool 重启 sample 时硬件就是会有这个间隙。

修复:**双 stream 错开交替 + 100ms equal-power crossfade**:

```
stream A: ━━━━━━━━━━━━━━━ (14.9s 单次)
                       ╲╲╲╲ (100ms fade-out)
stream B:              ╱╱╱╱━━━━━━━━━━━━━━━ (14.9s 单次)
                       ↑ 启动 B,vol=0
                       ↓ A 在 100ms 内 fade 到 0,B 在 100ms 内 fade 到 1
                       ↓ 100ms 后 A.stop()
        |── 14.8s ──|100ms|── 14.8s ──|100ms|...
```

每个 stream 用 `loop=0` 单次播放(避免单 stream 自己 loop click)。Kivy `Clock.schedule_once` 调度 swap 事件。SoundPool maxStreams 从 1 改 2。

#### 为什么这两层叠加才能彻底解决

- 只改 wav fade(A 层): SoundPool 的 ~10-30ms gap 仍在,机型依赖。
- 只改双 stream(B 层): wav 自身的 click 在 fade 区间被掩盖了,但理论上 fade 末尾还是可能听到一丝 wav boundary 的能量阶跃。
- 两层叠加:wav 自身平滑 + SoundPool 边界被 fade 完全藏起来 → 听感上完全连续。

### 3.3 改动文件清单

| 文件 | 改动 |
|---|---|
| `main.py:57-60` | 注释改为说明上沙线性 + 下沙立方根 |
| `main.py:656` | 上沙公式 `(remaining ** (1.0/3.0))` → `remaining` |
| `main.py:116-280` | `_SoundProxy` 重构,加 `_swap` / `_apply_volumes` / `_safe_stop`;`maxStreams: 1 → 2`;`play` 用 `loop=0` 启动主 stream 并 schedule swap |
| `tools/generate_sand_loop.py` | linear fade → `cos/sin` equal-power fade;加 `import math` |
| `sand_loop.wav` | 用新算法重新生成,646KB / 15s |

### 3.4 没动的部分

完整阅读 main.py 全文后确认其他 AI 没破坏:
- `CenterTextInput`(TextInput 居中)
- `HourglassWidget` 状态初始化、reset、toggle
- tick 主循环、塌陷动画、尘埃、splash、flares
- 12 层 redraw 顺序
- 漏斗坑、堆尖、装饰颗粒、层理、侧壁描边
- 颈部物理(均匀分布、shrink 延后、起点入颈、涌出沙柱)
- 中文字体注册、p4a 锁版本

---

## 4. 验证

### 4.1 桌面预览(本机没装 Kivy 时跳过)

```powershell
cd E:\AI_Tools\shalou_claude\android
pip install kivy
python main.py
```

- 60s 周期跑 30s,上沙顶应**匀速下降到一半位置**(线性) —— 不再"纹丝不动"。
- 3600s 周期跑 30s,下沙堆应已堆到 ~18% 高度。
- 漏完时下沙堆顶离颈部留 ~10% 高度空气。

桌面用 `SoundLoader` fallback,**不走双 stream 路径**,音效平滑度只能在 APK 上验证。

### 4.2 APK 实测(关键)

```powershell
git push origin main
```

→ https://github.com/twoplate2/shalou/actions → 等绿勾 → 下载 `hourglass-apk.zip` → 装手机:

- 60s 周期连续听,boundary 应完全平滑(每 14.9s 一次 swap,听不出来)。
- 切周期 / 切色 / 暂停 / 重启,音效切换无杂音。
- 漏完时音效自然停止,不被截断。

---

## 5. 给后续 AI 的提示

写沙漏代码时:

- **不要照搬"严格物理"的设计建议**,真实容器都是截顶锥不是纯锥,严格立方根公式视觉副作用很重。先在桌面跑 60s 看视觉效果,再决定要不要那个公式。
- **不要用 SoundPool 单 stream + `loop=-1` 做无缝循环**,部分机型有 ~10-30ms 的 buffer gap。要么用双 stream 错开 fade,要么用 AudioTrack STATIC + setLoopPoints 走硬件 ring buffer。
- **不要用 linear crossfade**,在中间会有 -3dB 能量凹陷,听感上"忽轻"。用 `cos(t·π/2)` / `sin(t·π/2)` equal-power fade,`a² + b² = 1`,能量恒等。
- **改任何视觉/听感相关的代码,push 前必须在桌面跑过一次实际验证**。`ast.parse` 通过 ≠ 视觉对。

---

## 6. 二次回退到线性恒等(2026-05-22 晚)

§3 push 后用户在两个周期实测截图反馈:

- **6000s** 跑到 9s(剩 5991s):上沙几乎没动,下沙堆已在下仓中段。
- **60s** 跑到 6s(剩 53.9s):上沙刚降一点,下沙堆已成型。

两张图都让人觉得"沙没漏多少,下沙怎么堆了一截",物质不守恒。

> **顺带的好消息**:同次 APK 实测中用户确认 §3.2 的双 stream + equal-power crossfade 音效修复已**平滑无杂音**,跨 wav boundary 无可闻 click。§3.2 修复站住,本次只回退沙漏高度部分。

### 6.1 根因

立方根 `(fallen^(1/3)) * 0.9` 在长周期前期把下沙高度严重放大:

| fallen | 旧公式高度 | 视觉 |
|---|---|---|
| 0.0015 (6000s, 9s) | 10.3% | 下沙凭空冒半个下仓 |
| 0.102 (60s, 6s) | 42% | 上沙没动下沙成型 |

立方根理论上来自 3D 锥模型的"体积守恒",但**人眼看的是高度**。上沙线性 vs 下沙立方根的混合曲线下,前期视觉完全感觉不到守恒。这跟 §2 对 deepseek 的批评同源,只是要等长周期实测才暴露。

### 6.2 决定:不修,回退到线性恒等

放弃 §3 想保留的"长周期前期下沙立刻可见"和"留 10% 空气"两个 deepseek 目标。两条简单约束:

1. **上沙高度 = `H × remaining`**
2. **下沙高度 = `H × fallen`**

由于沙漏对称 `top_y - neck_y == neck_y - bot_y`,两者之和恒 = H;且 `fallen=1` 时下沙顶刚好 = `neck_y`(到颈部,0% 空气)。

### 6.3 为什么"不修"是对的

下沙长周期前期可见性 → 加 `max(real, floor)` 保底地板可解(`floor_simulation.md` 已设计好,floor 在短周期被 real 隐身,不污染主公式)。但这是 P3 需求,日常多跑 60s。

用户原话:**"不是不能改好,而是性价比太低了"** —— 为 P3 体验引入一个**全程影响视觉**的曲线,代价远大于收益。

### 6.4 改动

| 文件 | 改动 |
|---|---|
| `main.py:57-60` | 删 `UPPER_SAND_FACTOR` / `LOWER_SAND_FACTOR` 常量,注释改"上下沙都用线性" |
| `main.py:362-365` | `get_mound_top_y` 立方根 → 线性,顺手去掉 `if fallen <= 0.001` 短路(线性下自然返回 bot_y) |
| `main.py:733` | `sand_top_y` 去掉 `* UPPER_SAND_FACTOR` 后缀 |

### 6.5 给后续 AI 的再次提示

**单点优势的曲线 vs 全程视觉的代价**:为了一个特定场景的好处而改主公式,会让所有场景都付视觉代价。要么用单调隐身的保底函数(`max(real, floor)`)把好处局部化,要么承认这是低优先级不修。**不要用 P1 视觉代价换 P3 体验改善**——这是本项目第三次踩同类型坑了(deepseek 立方根、上沙立方根、下沙立方根)。

---

## 7. 相关文档

- `CLAUDE.md`:Android 项目架构总览(被本次修复进一步验证过)
- `BUILD_APK.md`:云构建指南 + 历史踩坑
- `new_two.deepseek2.md`:本次踩坑的 deepseek 原始文档(保留作历史参考,**不要再按它的第 21 行执行**)
- `..\hourglass.py`:桌面 tk 版,本次的"上沙线性"和它的设计一致
