#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HD_Doc.py —— 入口：解析命令行参数并分发到 CLI 或 GUI

代码结构（UI 与业务逻辑分离）：
  HD_Doc_core.py   业务逻辑：权限/提权、分段规划、磁盘枚举、fio 扫描引擎、
                   报告导出（零 GUI 依赖）
  HD_Doc_cli.py    命令行模式：只 import HD_Doc_core，不碰任何 UI
  HD_Doc_gui.py    GUI 模式：PyQt5 界面（浅色/深色主题），只 import HD_Doc_core
  HD_Doc.py   本文件：参数解析与分发（--cli 才会导入 cli 模块）

用法
  python HD_Doc.py                                          # GUI 模式
  python HD_Doc.py --cli --target test.img --bs 4M          # 命令行模式（无需 PyQt5）
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --segment-gb 4
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --quick          # 快速扫描（抽样）
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --limit-mb 64   # 只扫前 64MB（试扫）
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --no-elevate    # 禁止自动提权

  Linux（Ubuntu / 银河麒麟 / openKylin，同样支持 GUI）：
  sudo apt install python3-pyqt5 fio && pip install -r requirements.txt
  sudo python3 HD_Doc.py                                     # GUI（root 才能扫物理盘）
  python3 HD_Doc.py --cli --target /dev/sda --quick          # 扫 NVMe/ATA 盘
  python3 HD_Doc.py --cli --target ./test.img --bs 4M        # 扫镜像文件（无需 root）
  物理盘在 Linux 上形如 /dev/sda、/dev/nvme0n1；非 root 启动时界面会指引
  pkexec / sudo 路线（见 HD_Doc_core.request_elevation）。
  rpm 系（麒麟服务器 V10）：sudo dnf install fio python3-qt5

打包成 Windows 可执行文件
  python build_exe.py          # PyInstaller 单文件打包，一次产出两个变体：
   - dist/HD_Doc.exe       自带 fio.exe（6.5MB），拷到没装 fio 的电脑也能用
   - dist/HD_Doc_NoFio.exe 不含 fio（体积小），运行时用系统 fio 或 --fio 指定
  两个变体都内置 lang/ 语言文件，双击即用：
    HD_Doc.exe                                  # GUI（无控制台窗口）
    HD_Doc.exe --cli --target <目标>             # 命令行（输出自动绑回所在终端）
    HD_Doc.exe --version                        # 验证打包版可运行（含 fio 来源）
  只要单个变体：python build_exe.py --variant fio|nofio

注意
  - 扫描物理磁盘需要管理员权限（fio 才能打开 \\\\.\\PhysicalDriveN）：
    GUI 模式在程序启动时即申请提权（弹一次 UAC，不再等扫描时再问；
    取消则保持标准权限继续运行）；CLI 模式在扫描物理盘时申请
    （--no-elevate 或环境变量 HDTUNE_NO_AUTO_ELEVATE=1 可关闭该行为；
    扫描镜像文件无需管理员）。Linux 上对应 root 权限：GUI 非 root 启动
    时界面会提示，并可经 pkexec 图形授权重启（无 pkexec 则指引终端
    sudo python3 HD_Doc.py）。
  - 提权重启的子进程使用 pythonw.exe（GUI 子系统）启动，不会再伴随
    命令窗口；CLI 模式提权后输出会自动绑回原终端
  - 运行日志：关键事件（启动/扫描开始与结果/导出/偏好切换）与异常堆栈
    写入唯一一份日志 <配置目录>/HD_Doc.log（Windows: %APPDATA%\\HD_Doc\\），
    超过 512KB 整文件截断重写——不会按日期/次数产生多个日志文件；
    HD_DOC_LOG_DIR=<dir> 可改目录，HD_DOC_LOG=off 可关闭。
    排查问题时把这一个文件发出来即可
  - 本工具只读，不会向磁盘写入任何数据
"""

import argparse
import os
import sys
import time

import HD_Doc_core as core
from HD_Doc_core import VERSION, IS_WIN, auto_elevate_enabled, _ensure_console, \
    _fix_stdout_encoding


def build_parser():
    ap = argparse.ArgumentParser(
        prog="HD Doc",
        description="HD Doc: read-only disk error scanner (fio + PyQt5)")
    ap.add_argument("--cli", action="store_true",
                    help="command-line mode (no GUI toolkit needed)")
    ap.add_argument("--version", action="store_true",
                    help="show version and exit")
    ap.add_argument("--target",
                    help="scan target: \\\\.\\PhysicalDriveN, /dev/sda, "
                         "or an image file path")
    ap.add_argument("--bs", default="auto",
                    help="block size, e.g. 4M / 512K / auto (default: auto)")
    ap.add_argument("--segment-gb", type=float, default=None,
                    help="segment size in GB; 0/none = whole disk at once "
                         "(default: 4; quick scan uses the same setting: one "
                         "head sample per segment)")
    ap.add_argument("--quick", action="store_true",
                    help="quick scan (HD Tune Quick Scan style): read only the head "
                         "sample of each region and skip the rest")
    ap.add_argument("--quick-sample-mb", type=float, default=16.0,
                    help="quick scan sample size per region in MB (default: 16)")
    ap.add_argument("--ioengine", default=None,
                    help="fio ioengine (default: windowsaio/libaio)")
    ap.add_argument("--no-direct", action="store_true", help="disable direct=1")
    ap.add_argument("--no-elevate", action="store_true",
                    help="forbid automatic administrator elevation (default: auto "
                         "UAC elevation when scanning physical disks)")
    ap.add_argument("--fio", default=None, help="path to the fio executable")
    ap.add_argument("--limit-mb", type=float, default=0,
                    help="scan only the first N MB (with --offset-mb)")
    ap.add_argument("--offset-mb", type=float, default=0, help="start offset in MB")
    ap.add_argument("--export", nargs="?", const=".", default=None, metavar="DIR",
                    help="export the report (segments.csv / errors.csv / "
                         "summary.txt) into DIR/HD_Doc_report_<timestamp>/; "
                         "without this flag no files are written")
    ap.add_argument("--yellow-mult", type=float, default=3.0,
                    help="slow threshold = median x N")
    ap.add_argument("--yellow-floor-ms", type=float, default=10.0,
                    help="slow threshold floor in ms")
    return ap


def _dump_elev_env():
    """pkexec 提权实例的启动环境快照（仅在 HDTUNE_ELEV_LOG 存在时写）。

    为什么需要：root 实例连不上 X/Wayland 时，Qt 平台插件初始化失败是
    C++ 层 qFatal 直接 abort——Python 的 except / sys.excepthook /
    日志模块全部派不上用场，表现为"pkexec 授权框闪退、什么都不发生"。
    唯一的排查手段是让子进程在装配 Qt **之前**把现场环境写进文件。
    父进程由 core.pkexec_gui_spawn 通过 pkexec env 注入 HDTUNE_ELEV_LOG
    （默认 /tmp/hd-doc-elevated.log，root 可写、普通用户可读）。
    """
    path = os.environ.get("HDTUNE_ELEV_LOG")
    if not path:
        return
    try:
        try:
            uid, euid = os.getuid(), os.geteuid()
        except AttributeError:          # Windows 无 getuid（调试/移植路径）
            uid = euid = "n/a"
        lines = ["elevated instance snapshot",
                 "uid=%s euid=%s argv=%s" % (uid, euid, sys.argv)]
        for k in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY",
                  "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
                  "QT_QPA_PLATFORM", "HOME", "PATH"):
            lines.append("  %s=%s" % (k, os.environ.get(k)))
        # X 连接三要素的实际存在性（root 能否读到 authority 文件）
        xauth = os.environ.get("XAUTHORITY")
        if xauth:
            lines.append("  XAUTHORITY file exists: %s"
                         % os.path.isfile(xauth))
        disp = os.environ.get("DISPLAY") or ""
        if disp.startswith(":"):
            num = disp[1:].split(".")[0]
            if num.isdigit():
                lines.append("  X socket /tmp/.X11-unix/X%s exists: %s"
                             % (num, os.path.exists(
                                 "/tmp/.X11-unix/X%s" % num)))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass                     # 快照失败不能影响启动


def mark_elev_ready():
    """提权实例就绪标记：窗口已显示，向 HDTUNE_ELEV_LOG 追加 READY 行。

    父进程（ensure_admin_at_startup / GUI 的 _poll_pkexec）靠这一行区分
    "用户还在输密码"与"提权实例已起来、可以放心退出让位"——没有它，父
    进程只能靠超时猜测，输密码稍慢就会看到授权框闪退（详见
    core.elev_ready 的说明）。无 HDTUNE_ELEV_LOG（非提权启动）时是空操作。
    """
    path = os.environ.get("HDTUNE_ELEV_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("READY pid=%s t=%.3f\n" % (os.getpid(), time.time()))
    except Exception:
        pass                     # 标记失败不能影响启动


def main(argv=None):
    # 先修编码再解析参数：argparse 的 --help / 用法错误会直接打印后退出，
    # 必须在此之前保证标准流编码与终端匹配（打包版在 UTF-8 终端不乱码）
    _fix_stdout_encoding()
    _dump_elev_env()            # 提权实例现场快照（无 HDTUNE_ELEV_LOG 时是空操作）
    args = build_parser().parse_args(argv)

    if args.version:
        _ensure_console()   # 打包版在命令行里运行时校正输出编码
        # fio 来源如实报告：源码运行 / 打包内置 / 打包未内置（靠系统 fio）
        if getattr(sys, "frozen", False):
            fio_src = "bundled" if core.bundled_fio_path() \
                else "not bundled (use system fio or --fio PATH)"
        else:
            fio_src = "source"
        core.log_event("startup: --version (frozen=%s fio=%s)"
                       % (getattr(sys, "frozen", False), fio_src))
        print("HD Doc %s (fio: %s)" % (VERSION, fio_src))
        return 0
    core.log_event("startup: ver=%s mode=%s frozen=%s admin=%s argv=%s"
                   % (VERSION, "cli" if args.cli else "gui",
                      getattr(sys, "frozen", False), core.is_admin(),
                      " ".join(sys.argv[1:])))
    if args.cli:
        # 延迟导入：CLI 路径不加载 PyQt5 / GUI 代码
        from HD_Doc_cli import cli_main
        return cli_main(args)
    try:
        # 只有 GUI 模式才导入 PyQt5
        from HD_Doc_gui import HDDocApp, ensure_admin_at_startup
    except ImportError as e:
        core.log_event("startup: cannot import GUI (PyQt5?): %s" % e,
                       level="ERROR")
        print("Error: cannot start GUI (PyQt5 not installed? %s)" % e)
        print("Install it with:  python -m pip install PyQt5")
        print("Or use the CLI mode:")
        print("  python HD_Doc.py --cli --target <target> --bs 4M")
        return 2
    # 启动即提权：非管理员时先弹 UAC（不等扫到物理盘再问），确认后由
    # 提权进程接管、本进程直接退出；取消则保持标准权限继续启动
    if ensure_admin_at_startup():
        core.log_event("startup: relaunched elevated; this process exits")
        return 0
    # ---- Qt 应用装配（PyQt5 跨 Windows/Ubuntu/银河麒麟 一致）----
    # 高分屏缩放属性必须在 QApplication 构造前设置（Qt5 才有这两个开关；
    # Qt6 起默认开启，属性不存在时静默跳过）
    core.log_event("gui: assembling Qt application")
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    for _attr in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        if hasattr(Qt, _attr):
            QApplication.setAttribute(getattr(Qt, _attr))
    qt_app = QApplication(sys.argv)
    core.log_event("gui: QApplication created")
    qt_app.setApplicationName("HD_Doc")       # X11 WM_CLASS 的 res_class，
    qt_app.setDesktopFileName("hd-doc")       # 配合 StartupWMClass 匹配菜单图标
    win = HDDocApp()
    win.show()
    # 告诉父进程"提权实例窗口已就绪，可以退出让位了"（父进程的
    # ensure_admin_at_startup / GUI 轮询据此收尾，见 core.elev_ready）
    mark_elev_ready()
    # onefile 父进程（bootloader）被外部杀死时（任务管理器结束上面那个
    # 同名进程），本进程与 fio 不会跟着退、会变孤儿继续读盘：父进程监控
    # （Windows 版 PDEATHSIG）发现父死后同步杀 fio 并退出。Job Object
    # 只覆盖"本进程死"的连坐方向，这里是反向兜底。
    core.watch_parent_process(win._on_parent_died)
    rc = qt_app.exec_()
    core.log_event("gui: event loop returned")
    return rc


if __name__ == "__main__":
    try:
        _rc = main()
    except SystemExit:
        raise                       # argparse 等正常退出路径，不记日志
    except BaseException as _e:     # 含 KeyboardInterrupt：留痕后原样抛出
        core.log_exception("unhandled exception in main()", _e)
        raise
    sys.exit(_rc)
