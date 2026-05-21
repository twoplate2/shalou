# 用 GitHub Actions 云构建 Python → Android APK

把 Python GUI 应用(Kivy)打成 Android APK,**全程不需要本地装 Android SDK / NDK / Buildozer**。所有编译在 GitHub Actions 的 Ubuntu runner 上完成,Windows 开发者也能用。

适用场景:Windows 开发(Buildozer 不支持 Windows 原生)、不想折腾 Linux/WSL/Docker。

---

## 技术栈

| 组件 | 作用 |
|---|---|
| **Kivy 2.3.0** | 跨平台 Python GUI,支持打包 Android。tkinter 不能直接转 Android,要重写 |
| **Buildozer** | Kivy 官方打包工具,用 python-for-android 把 Python + 依赖编译进 APK |
| **GitHub Actions** | 云端 Ubuntu 22.04 runner,跑 Buildozer + 上传 APK 产物 |
| **Git Credential Manager** | Windows 下 push 自动用缓存的 GitHub 凭证(不用每次输密码) |

---

## 项目骨架

```
project/
├── main.py                       # Kivy 应用入口(必须叫这个名)
├── buildozer.spec                # 构建配置
├── icon.png                      # 1024×1024 启动器图标
├── presplash.png                 # 1080×1920 启动屏
├── <你的资源>.wav/png/...         # 音频/图片等
├── .github/workflows/
│   └── build-apk.yml             # CI 配置
├── .gitignore
└── README.md
```

---

## 关键文件模板

### `main.py` — Kivy app 必备约定

```python
from kivy.app import App
from kivy.utils import platform
from kivy.core.window import Window

class MyApp(App):
    def build(self):
        # 桌面预览模拟手机窗口;Android 上让系统决定
        if platform != "android":
            Window.size = (420, 760)
        return ...root_widget...

    # Android 生命周期 — on_pause 必须返回 True 保持 GL 上下文
    def on_pause(self):
        return True

    def on_resume(self):
        return True

if __name__ == "__main__":
    MyApp().run()
```

**资源路径**用 `os.path.join(os.path.dirname(os.path.abspath(__file__)), name)`,桌面和 Android 上都正确(buildozer 把资源解压到 `main.py` 同级目录)。

### `buildozer.spec` — 最小可工作版

```ini
[app]
title = 沙漏
package.name = hourglass              # 小写/无空格/无中文
package.domain = org.shalou
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf,wav,mp3
source.include_patterns = sand_loop.wav   # 显式列非 .py 资源,否则不会进 APK
version = 0.1.0
requirements = python3,kivy==2.3.0
orientation = portrait
fullscreen = 0
android.api = 31
android.minapi = 21
android.ndk = 25b                     # 25c+/26 当前有兼容性问题
android.archs = arm64-v8a,armeabi-v7a
icon.filename = %(source.dir)s/icon.png
android.presplash_color = #fdf6e3     # 必须和 app 背景同色,避免闪屏黑闪
presplash.filename = %(source.dir)s/presplash.png

[buildozer]
log_level = 2
warn_on_root = 1
```

### `.github/workflows/build-apk.yml` — CI 模板

```yaml
name: Build APK
on:
  push:
    branches: [ main, master ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-22.04          # 不要用 24.04, buildozer 还没适配
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.10'   # 不要用 3.11+, Kivy 2.3 兼容性最好
      - uses: actions/setup-java@v5
        with:
          distribution: 'temurin'
          java-version: '17'       # Android Gradle 要求 Java 17

      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends \
            build-essential git zip unzip openjdk-17-jdk \
            python3-pip autoconf libtool pkg-config zlib1g-dev \
            libncurses-dev libncursesw5-dev libtinfo6 cmake \
            libffi-dev libssl-dev automake

      - name: Install buildozer & Cython
        run: |
          python -m pip install --upgrade pip wheel
          pip install "cython<3.0" buildozer    # cython 必须 < 3.0

      - uses: actions/cache@v5
        with:
          path: |
            ~/.buildozer
            .buildozer
          key: buildozer-${{ runner.os }}-${{ hashFiles('buildozer.spec') }}

      - name: Build APK (debug)
        run: yes | buildozer android debug

      - uses: actions/upload-artifact@v7
        with:
          name: app-apk
          path: bin/*.apk
          if-no-files-found: error
          retention-days: 30
```

### `.gitignore` — 至少这几条

```
.buildozer/
bin/
*.apk
__pycache__/
*.pyc
```

---

## 完整流程(顺序操作)

1. **写代码**: 完成 `main.py` + `buildozer.spec` + workflow.yml + 资源文件
2. **本地 commit**:
   ```
   git init -b main
   git add .
   git commit -m "Initial commit"
   ```
3. **网页建空 repo**: https://github.com/new — **不勾任何** README/.gitignore/license(否则要 merge),Public 方便下载 Artifacts
4. **关联远端 + push**:
   ```
   git remote add origin https://github.com/<owner>/<repo>.git
   git push -u origin main
   ```
   如果 Windows GCM 之前登录过 GitHub 账号,无需输密码
5. **等 Actions**: 进 repo Actions 标签页 — 黄圆点(跑中) → 绿勾(成功) → 红叉(失败,点进看 log)
6. **下载 APK**: run 详情页底部 **Artifacts** → `app-apk.zip` → 解压得 `.apk` → 传手机安装(需开"未知来源"权限)

**首次构建 15-20 分钟**(下载 Android SDK/NDK + 编译 Python/Kivy)。**后续命中 `~/.buildozer` 缓存 5-8 分钟**。

---

## 常见错误与解法

| 错误 | 原因 | 解法 |
|---|---|---|
| `Cython compilation failed` | Cython 3.x 不兼容 p4a | spec 锁 `pip install "cython<3.0"` |
| `JAVA_HOME not set` | runner 没配 Java | `actions/setup-java@v5` + `java-version: '17'` |
| `NDK download timeout` | Google CDN 偶发 | retry workflow,通常二次能过 |
| `KeyError: 'AndroidManifest.xml'` | api/minapi/ndk 版本不匹配 | 锁 api=31, minapi=21, ndk=25b |
| Resource not found at runtime | wav/png 没进 APK | spec 加 `source.include_patterns = xxx.wav` |
| 闪屏后黑屏 | `presplash_color` ≠ app 背景 | spec 改 `android.presplash_color = #你的BG色` |
| App 切后台回来 GL 黑屏 | 没实现生命周期 | `on_pause` 返 True, `on_resume` 重载音频/纹理 |
| Windows 双击 .py 闪退 | tk.Frame 的 padx/pady 不接受 tuple | 把 padx/pady 移到 `pack()` 调用,或换 ttk.Frame.padding |

---

## 进阶

- **Release 签名**: debug APK 用默认 debug key,Google Play 上架要 release key。spec 加 `android.release_artifact = aab`,workflow 加 keystore secret。
- **自动发布**: tag push 触发 `actions/create-release` + 上传 APK 作为 release asset。
- **多架构并行**: `strategy.matrix.arch: [arm64-v8a, armeabi-v7a]` 拆两个 job 并行。

---

## 本项目验证案例

- 桌面版: `..\hourglass.py` (tkinter,~700 行)
- Android 版: 本目录 (Kivy MVP,~330 行)
- GitHub: https://github.com/twoplate2/shalou
- 首次 push 到 Actions 完成 APK 产出 ~17 分钟

---

## 参考

- Buildozer: https://buildozer.readthedocs.io
- python-for-android: https://python-for-android.readthedocs.io
- Kivy 2.3: https://kivy.org/doc/stable/
- 模板灵感来源: `E:\AI_Tools\Clac\android\` (twoplate2/clac_ChinaStyle)
