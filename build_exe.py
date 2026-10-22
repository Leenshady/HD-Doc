#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_exe.py —— 把 HD_Doc.py 打包成单文件可执行程序（HD Doc）

Windows 产物为 .exe；在 Ubuntu/Linux 上运行同一脚本则产出无后缀的 Linux
可执行文件（PyInstaller 按运行平台交叉，不能在 Windows 上打出 Linux 包）。

用法（在装有 PyInstaller 的 Python 环境里运行，GUI 打包需要该 Python 带 tkinter）：
    python build_exe.py                # 一次打出两个变体 → dist/
    python build_exe.py --variant fio  # 只打 dist/HD_Doc（自带 fio）
    python build_exe.py --variant nofio# 只打 dist/HD_Doc_NoFio（不含 fio）
    python build_exe.py --onedir       # 目录模式（启动更快，分发整个文件夹）

两个变体的区别只在 fio 是否随包分发：
  dist/HD_Doc       自带 fio（Windows 约 +2.3MB），拷到没装 fio 的电脑
                    也能直接扫
  dist/HD_Doc_NoFio 不含 fio，运行时用系统 fio 或在 GUI/CLI 里 --fio
                    指定路径；--version 会如实报告 fio 来源
两者都内置 lang/ 语言文件与图标，运行时行为完全一致。
Linux 下自带 fio 的变体依赖系统已安装 fio（打包时 --add-binary 收入）。

其他说明：
  - --windowed（GUI 子系统）：双击运行不会出现黑色控制台窗口；在命令行里
    用 --cli 模式运行时，程序会自动把输出绑回所在终端（见 HD_Doc.py
    的 _ensure_console）
  - lang/ 语言文件一并打入（--add-data），界面文案在打包版同样可用
  - GUI 基于 ttkbootstrap：--collect-all ttkbootstrap 收齐其子模块与
    静态资源（复选框/进度条元素图、图标字体），否则打包版控件会缺图
  - --add-data/--add-binary 的路径分隔符按平台取 os.pathsep
    （Windows 为 ";"，Linux 为 ":"），本脚本在哪个系统上跑就打哪个平台的包
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
BASE_NAME = "HD_Doc"
NOFIO_NAME = "HD_Doc_NoFio"
IS_WIN = sys.platform.startswith("win")
EXE_SUFFIX = ".exe" if IS_WIN else ""
# PyInstaller --add-data/--add-binary 的 "src;dst" 分隔符随平台变化
SEP = os.pathsep

# 与 HD_Doc.resolve_fio 一致的候选列表（打包时用于 --add-binary）
FIO_CANDS = (
    r"C:\Program Files\fio\fio.exe",
    r"C:\Program Files (x86)\fio\fio.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\fio.exe"),
    r"C:\msys64\usr\bin\fio.exe",
    r"C:\msys32\usr\bin\fio.exe",
    "/usr/bin/fio",
    "/usr/local/bin/fio",
)


def find_fio():
    w = shutil.which("fio")
    if w:
        return w
    for c in FIO_CANDS:
        if c and os.path.isfile(c):
            return c
    return None


def build_variant(name, with_fio, onedir):
    """打一个变体；返回产物 exe 路径（失败返回 None）"""
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean",
           "--name", name,
           "--windowed",            # GUI 子系统：双击无黑色控制台窗口
           "--collect-all", "tkinter",  # 兜底收齐 tkinter 数据文件
           "--collect-all", "ttkbootstrap",  # ttkbootstrap 子模块 + 静态资源
           ]
    if not onedir:
        cmd.append("--onefile")
    if with_fio:
        fio = find_fio()
        if fio:
            # 目标名 ".: fio(.exe)" → 解压后位于 sys._MEIPASS/fio(.exe)
            # （HD_Doc.resolve_fio 在 frozen 时优先查这里）
            cmd += ["--add-binary", "%s%s." % (fio, SEP)]
            print("[信息] 将内置 fio: %s（%.1f MB）"
                  % (fio, os.path.getsize(fio) / 1048576.0))
        else:
            print("[警告] 未找到 fio，%s 变体将不自带 fio；" % name)
            print("        运行时需在 GUI 里指定 fio 路径，或系统已安装 fio。")
    if os.path.isdir(LANG_DIR):
        # lang/en.json、lang/zh.json → 解压后位于 sys._MEIPASS/lang/
        cmd += ["--add-data", "%s%slang" % (LANG_DIR, SEP)]
        print("[信息] 将内置语言文件: %s" % LANG_DIR)
    else:
        print("[警告] 未找到 %s，打包版将无界面文案" % LANG_DIR)
    icon = os.path.join(IMG_DIR, "HD_Doc.ico")
    if os.path.isfile(icon):
        # 程序图标（同时进入 exe 资源与运行时 img/ 数据）
        cmd += ["--icon", icon]
        print("[信息] 将使用程序图标: %s" % icon)
    else:
        print("[警告] 未找到 %s，程序与窗口将使用默认图标" % icon)
    if os.path.isdir(IMG_DIR):
        # img/ → 解压后位于 sys._MEIPASS/img/（窗口标题栏/任务栏图标）
        cmd += ["--add-data", "%s%simg" % (IMG_DIR, SEP)]
    cmd.append(APP)

    print("[信息] 执行: %s\n" % " ".join(cmd))
    r = subprocess.call(cmd, cwd=HERE)
    if r != 0:
        print("[错误] PyInstaller 对 %s 退出码 %d" % (name, r))
        return None
    exe = os.path.join(HERE, "dist", name + EXE_SUFFIX)
    if os.path.isfile(exe):
        print("\n[完成] %s（%.1f MB）"
              % (exe, os.path.getsize(exe) / 1048576.0))
        print("        %s --version" % exe)
        if IS_WIN:
            print("        %s --cli --target \\\\.\\PhysicalDrive1 --quick\n" % exe)
        else:
            print("        sudo %s --cli --target /dev/sda --quick\n" % exe)
        return exe
    print("[错误] 未找到产物 %s" % exe)
    return None


def main():
    ap = argparse.ArgumentParser(
        description="打包 HD Doc 为单文件可执行程序"
                    "（Windows 产物 .exe；Linux 产物无后缀）")
    ap.add_argument("--variant", choices=("fio", "nofio", "all"), default="all",
                    help="fio=自带 fio 的 HD_Doc；nofio=不含 fio 的 "
                         "HD_Doc_NoFio；all=两个都打（默认）")
    ap.add_argument("--onedir", action="store_true",
                    help="目录模式打包（默认单文件 onefile）")
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
        print("       Windows: 换用 python.org 安装包自带的 Python（自带 tkinter）")
        print("       Ubuntu/麒麟(apt 系):  sudo apt install python3-tk")
        print("       麒麟服务器/openEuler(rpm 系):  sudo dnf install python3-tkinter")
        return 2
    try:
        import ttkbootstrap  # noqa: F401
    except ImportError:
        print("[错误] 未安装 ttkbootstrap（GUI 框架）。请先执行：")
        print("       python -m pip install ttkbootstrap")
        return 2

    # 变体清单：(exe 名, 是否内置 fio)
    variants = {"fio": [(BASE_NAME, True)],
                "nofio": [(NOFIO_NAME, False)],
                "all": [(BASE_NAME, True), (NOFIO_NAME, False)]}[args.variant]

    out = []
    for name, with_fio in variants:
        print("=" * 66)
        print("打包变体：%s（%s）" % (name, "自带 fio" if with_fio else "不含 fio"))
        print("=" * 66)
        exe = build_variant(name, with_fio, args.onedir)
        if exe:
            out.append(exe)

    if not out:
        print("\n[错误] 没有成功产出任何 exe")
        return 1
    print("\n%s\n本次产物：" % ("=" * 66))
    for exe in out:
        print("  %s（%.1f MB）" % (exe, os.path.getsize(exe) / 1048576.0))
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
