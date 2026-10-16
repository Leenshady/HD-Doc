#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_exe.py —— 把 HD_Doc.py 打包成 Windows 单文件可执行程序（HD Doc）

用法（在装有 PyInstaller 的 Python 环境里运行，GUI 打包需要该 Python 带 tkinter）：
    python build_exe.py                # 单文件打包 → dist/HD_Doc.exe
    python build_exe.py --onedir       # 目录打包（启动更快，分发的是整个文件夹）

说明：
  - --windowed（GUI 子系统）：双击运行不会出现黑色控制台窗口；在命令行里
    用 --cli 模式运行时，程序会自动把输出绑回所在终端（见 HD_Doc.py
    的 _ensure_console）
  - 构建机上能找到 fio 时自动把它打进包（--add-binary），最终 exe 自带
    fio、拷到别的电脑也能用；找不到时也能打包，运行时再让用户指定 fio 路径
  - lang/ 语言文件一并打入（--add-data），界面文案在打包版同样可用
  - 本脚本只负责调用 PyInstaller，打包逻辑（隐藏导入等）都写在命令行参数里
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "HD_Doc.py")
LANG_DIR = os.path.join(HERE, "lang")
IMG_DIR = os.path.join(HERE, "img")
NAME = "HD_Doc"

# 与 HD_Doc.resolve_fio 一致的候选列表（打包时用于 --add-binary）
FIO_CANDS = (
    r"C:\Program Files\fio\fio.exe",
    r"C:\Program Files (x86)\fio\fio.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\fio.exe"),
    r"C:\msys64\usr\bin\fio.exe",
    r"C:\msys32\usr\bin\fio.exe",
)


def find_fio():
    w = shutil.which("fio")
    if w:
        return w
    for c in FIO_CANDS:
        if c and os.path.isfile(c):
            return c
    return None


def main():
    ap = argparse.ArgumentParser(description="打包 HD Doc 为 Windows 可执行文件")
    ap.add_argument("--onedir", action="store_true",
                    help="目录模式打包（默认单文件 onefile）")
    ap.add_argument("--no-fio", action="store_true",
                    help="不把 fio.exe 打进包（运行时依赖系统已安装 fio）")
    args = ap.parse_args()

    if not os.path.isfile(APP):
        print("[错误] 找不到 %s" % APP)
        return 2
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[错误] 未安装 PyInstaller。请先执行：")
        print("       python -m pip install pyinstaller")
        print("       （注意：打包含 tkinter 的 GUI 必须用带 tkinter 的 Python，")
        print("         例如 python.org 安装包自带的 python.exe）")
        return 2
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("[错误] 当前 Python 没有 tkinter，打不了的 GUI 版。")
        print("       请换用 python.org 安装包自带的 Python（默认包含 tkinter）。")
        return 2

    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean",
           "--name", NAME,
           "--windowed",            # GUI 子系统：双击无黑色控制台窗口
           "--collect-all", "tkinter",  # 兜底收齐 tkinter 数据文件
           ]
    if not args.onedir:
        cmd.append("--onefile")
    fio = None if args.no_fio else find_fio()
    if fio:
        # 目标名 ".: fio.exe" → 解压后位于 sys._MEIPASS/fio.exe
        # （HD_Doc.resolve_fio 在 frozen 时优先查这里）
        cmd += ["--add-binary", "%s;." % fio]
        print("[信息] 将内置 fio: %s（%.1f MB）"
              % (fio, os.path.getsize(fio) / 1048576.0))
    else:
        print("[警告] 未找到 fio.exe，打出的包不自带 fio；")
        print("        运行时需在 GUI 里指定 fio 路径，或系统已安装 fio。")
    if os.path.isdir(LANG_DIR):
        # lang/en.json、lang/zh.json → 解压后位于 sys._MEIPASS/lang/
        cmd += ["--add-data", "%s;lang" % LANG_DIR]
        print("[信息] 将内置语言文件: %s" % LANG_DIR)
    else:
        print("[警告] 未找到 %s，打包版将无界面文案" % LANG_DIR)
    icon = os.path.join(IMG_DIR, "HD_Doc.ico")
    if os.path.isfile(icon):
        # 程序图标（同时进入 exe 资源与运行时 img/ 数据）
        cmd += ["--icon", icon]
        print("[信息] 将使用程序图标: %s" % icon)
    else:
        print("[警告] 未找到 %s，exe 与窗口将使用默认图标" % icon)
    if os.path.isdir(IMG_DIR):
        # img/ → 解压后位于 sys._MEIPASS/img/（窗口标题栏/任务栏图标）
        cmd += ["--add-data", "%s;img" % IMG_DIR]
    cmd.append(APP)

    print("[信息] 执行: %s" % " ".join(cmd))
    r = subprocess.call(cmd, cwd=HERE)
    if r != 0:
        print("[错误] PyInstaller 退出码 %d" % r)
        return r

    out_dir = os.path.join(HERE, "dist")
    exe = os.path.join(out_dir, NAME + ".exe")
    if os.path.isfile(exe):
        print("\n[完成] 打包成功：%s（%.1f MB）"
              % (exe, os.path.getsize(exe) / 1048576.0))
        print("        双击运行 GUI；命令行用法：")
        print("          %s --version" % exe)
        print("          %s --cli --target \\\\.\\PhysicalDrive1 --quick" % exe)
    else:
        print("\n[完成] 打包成功，产物目录：%s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
