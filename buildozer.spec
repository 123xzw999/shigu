[app]

# ---------------------------------------------------------------- 基本信息
title = 识股
package.name = shigu
package.domain = cn.xiaoxiong

version = 1.0.0

# 源码根目录就是项目根（main.py 在这里）
source.dir = .
source.include_exts = py,html,css,js,json,md,txt
source.exclude_dirs = .git,.github,docs,termux,__pycache__,bin,data/cache
source.exclude_patterns = *.pyc,*.pyo,*.bat,*.png,*.jpg,*.zip,boot_error.log

# ---------------------------------------------------------------- 依赖
# certifi 必须有：Android 上的 Python 没有系统 CA，访问 https 会证书校验失败
requirements = python3,kivy,android,certifi

orientation = portrait
fullscreen = 1

icon.filename = %(source.dir)s/docs/icon-512.png
presplash.filename = %(source.dir)s/docs/presplash.png

# ---------------------------------------------------------------- Android
android.permissions = INTERNET,ACCESS_NETWORK_STATE
# targetSdk 27：Android 9+ 对 targetSdk>=28 的应用默认禁止明文 HTTP，
# 而我们必须连 127.0.0.1:8765。降到 27 就不用改 manifest，最省事也最不容易出错。
# （不走 Google Play，只是自己装，targetSdk 老一点没影响）
android.api = 27
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = shigu

android.meta_data =

# ---------------------------------------------------------------- 打包
p4a.bootstrap = sdl2
p4a.branch = develop
p4a.source_dir = .

[buildozer]
log_level = 2
warn_on_root = 1
