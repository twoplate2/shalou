[app]

# 启动器中显示的可见名称
title = 沙漏

# 内部包名(小写,无空格,无中文)
package.name = hourglass
package.domain = org.shalou

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf,wav,mp3
source.include_patterns = sand_loop.wav

version = 0.1.0

requirements = python3,kivy==2.3.0

# 强制 Python 3.12（p4a 默认用 3.14 alpha，C API 变化导致 Kivy 编译失败）
p4a.python_version = 3.12

orientation = portrait
fullscreen = 0

android.permissions =

android.api = 31
android.minapi = 21
android.ndk = 25b

android.archs = arm64-v8a,armeabi-v7a

# Python 3.12 locked via P4A_PYTHON_VERSION env + p4a.python_version

android.allow_backup = True

icon.filename = %(source.dir)s/icon.png

android.presplash_color = #fdf6e3
presplash.filename = %(source.dir)s/presplash.png


[buildozer]

log_level = 2
warn_on_root = 1
