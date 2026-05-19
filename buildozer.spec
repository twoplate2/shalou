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

orientation = portrait
fullscreen = 0

android.permissions =

android.api = 31
android.minapi = 21
android.ndk = 25b

android.archs = arm64-v8a,armeabi-v7a

android.allow_backup = True

icon.filename = %(source.dir)s/icon.png

android.presplash_color = #fdf6e3
presplash.filename = %(source.dir)s/presplash.png


[buildozer]

log_level = 2
warn_on_root = 1
