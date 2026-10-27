[app]

# ---------------------------------------------------------------- 基本信息
title = 识股
package.name = shigu
package.domain = cn.xiaoxiong

version = 1.0.0

# 源码根目录就是项目根（main.py 在这里）
source.dir = .
source.include_exts = py,html,css,js,json,md,txt,xml
source.exclude_dirs = .git,.github,docs,termux,__pycache__,bin,data/cache
source.exclude_patterns = *.pyc,*.pyo,*.bat,*.png,*.jpg,*.zip,boot_error.log

# ---------------------------------------------------------------- 依赖
# certifi 必须有：Android 上的 Python 没有系统 CA，访问 https 会证书校验失败
# charset-normalizer 必须钉到 2.x：
# kivy 依赖 requests，requests 依赖 charset-normalizer，
# 而 3.x 只发 wheel（没有 android_24_arm64_v8a 平台的），p4a 的 pip 会直接报
# "not a supported wheel on this platform"。2.1.1 有 sdist + setup.py，能装。
requirements = python3,kivy,android,certifi,charset-normalizer==2.1.1

orientation = portrait
fullscreen = 1

icon.filename = %(source.dir)s/docs/icon-512.png
presplash.filename = %(source.dir)s/docs/presplash.png

# ---------------------------------------------------------------- Android
android.permissions = INTERNET,ACCESS_NETWORK_STATE
# compileSdk 必须 33：p4a 的 SDL2 Java 代码（HIDDeviceManager）用了 API 28+ 的符号，
# 用 27 编译会直接 "cannot find symbol"。
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = shigu

android.meta_data =

# Android 9+ 对 targetSdk>=28 的应用默认禁明文 HTTP，而 APK 里的 WebView 要连
# 127.0.0.1:8765。p4a 的清单模板留了 {{ args.extra_manifest_application_arguments }} 插槽，
# buildozer 对应这个选项，把内容塞进 <application> 标签里。
# 必须绝对路径：p4a 会在 dist 目录（.buildozer/android/platform/.../dists/shigu）里
# 读这个文件，相对路径会 FileNotFoundError。GitHub runner 的工作目录是固定的。
android.extra_manifest_application_arguments = /home/runner/work/shigu/shigu/android/extra_manifest_app.xml

# ---------------------------------------------------------------- 打包
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
