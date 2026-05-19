# 沙漏 Android (Kivy) — MVP

桌面 tkinter 沙漏 (`E:\AI_Tools\shalou_claude\hourglass.py`) 的 Android 移植版。这一版是 **MVP**:保留外形 + 沙下落 + 颈部粒子流(流量守恒收缩) + 6 色块切换 + 沙沙循环音效 + 计时,**未移植**装饰颗粒/玻璃高光/木纹/底部喇叭口/触底闪光/EMA 沙堆顶。

## 桌面预览

```
pip install kivy
python main.py
```

非 Android 平台默认窗口 420×760(模拟手机竖屏)。

## 云端构建 APK

推送到 `main` 自动触发 GitHub Actions(`.github/workflows/build-apk.yml`),约 15-20 分钟产出 debug APK(后续构建命中缓存约 5-8 分钟)。

也可以在 GitHub 仓库的 Actions 页面手动 `workflow_dispatch` 触发。

构建完成后:
1. 进 GitHub Actions → 选最近一次成功的 run
2. 下方 **Artifacts** 处下载 `hourglass-apk.zip`
3. 解压得到 `hourglass-0.1.0-arm64-v8a_armeabi-v7a-debug.apk`(类似名字)
4. 传到手机安装(需要"未知来源"权限)

## 本地构建 APK(可选)

需要 Linux/WSL + Buildozer。Windows 原生不支持 Buildozer。

```
pip install "cython<3.0" buildozer
buildozer android debug
# 产物在 bin/
```

## 文件结构

```
android/
├── main.py              # Kivy 应用入口
├── buildozer.spec       # Buildozer 配置 (api 31, ndk 25b, arm64+armv7)
├── sand_loop.wav        # 沙沙声循环音效 (从 desktop 版复用,88KB)
├── icon.png             # 1024×1024 启动器图标
├── presplash.png        # 1080×1920 启动画面
├── tools/
│   ├── generate_icon.py       # 用 PIL 生成 icon.png
│   └── generate_presplash.py  # 用 PIL 生成 presplash.png
├── .github/workflows/
│   └── build-apk.yml    # GitHub Actions CI
└── README.md
```

## 后续可加(从桌面版搬过来)

- 装饰颗粒(沙体表面亮暗颗粒)
- 玻璃左壁高光线 + 右壁阴影线
- 木盖横木纹
- 沙体两侧斜壁 SAND_DARK 描边
- 流量守恒粒子的颜色梯度(`_color_table` 11 档)
- 触底 flares(4×4 半透明,0.08s)
- EMA 沙堆顶 `mound_peak_offset`
- 暂停遮罩 + 完成闪烁层

桌面版完整实现见 `..\hourglass.py`,关键架构见 `..\CLAUDE.md`。
