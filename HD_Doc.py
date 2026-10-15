#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HD_Doc.py —— 入口：解析命令行参数并分发到 CLI 或 GUI

代码结构（UI 与业务逻辑分离）：
  HD_Doc_core.py   业务逻辑：权限/提权、分段规划、磁盘枚举、fio 扫描引擎、
                   报告导出（零 tkinter 依赖）
  HD_Doc_cli.py    命令行模式：只 import HD_Doc_core，不碰任何 UI
  HD_Doc_gui.py    GUI 模式：tkinter 界面，只 import HD_Doc_core
  HD_Doc.py   本文件：参数解析与分发（--cli 才会导入 cli 模块）

用法
  python HD_Doc.py                                          # GUI 模式
  python HD_Doc.py --cli --target test.img --bs 4M          # 命令行模式（无需 tkinter）
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --segment-gb 4
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --quick          # 快速扫描（抽样）
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --limit-mb 64   # 只扫前 64MB（试扫）
  python HD_Doc.py --cli --target "\\\\.\\PhysicalDrive1" --no-elevate    # 禁止自动提权

打包成 Windows 可执行文件
  python build_exe.py          # PyInstaller 单文件打包（输出 dist/HD_Doc.exe）
  打包版自带 fio.exe 与 lang/ 语言文件，双击即用：
    HD_Doc.exe                                  # GUI（无控制台窗口）
    HD_Doc.exe --cli --target <目标>             # 命令行（输出自动绑回所在终端）
    HD_Doc.exe --version                        # 验证打包版可运行

注意
  - 扫描物理磁盘需要管理员权限（fio 才能打开 \\\\.\\PhysicalDriveN）；
    未提权时程序会自动弹出 UAC 申请提权重启（--no-elevate 或环境变量
    HDTUNE_NO_AUTO_ELEVATE=1 可关闭该行为；扫描镜像文件无需管理员）
  - 提权重启的子进程使用 pythonw.exe（GUI 子系统）启动，不会再伴随
    命令窗口；CLI 模式提权后输出会自动绑回原终端
  - 本工具只读，不会向磁盘写入任何数据
"""

import argparse
import os
import sys

import HD_Doc_core as core
from HD_Doc_core import VERSION, IS_WIN, auto_elevate_enabled, _ensure_console, \
    _fix_stdout_encoding


def build_parser():
    ap = argparse.ArgumentParser(
        prog="HD Doc",
        description="HD Doc: read-only disk error scanner (fio + tkinter)")
    ap.add_argument("--cli", action="store_true",
                    help="command-line mode (no tkinter needed)")
    ap.add_argument("--version", action="store_true",
                    help="show version and exit")
    ap.add_argument("--target",
                    help="scan target: \\\\.\\PhysicalDriveN or an image file path")
    ap.add_argument("--bs", default="auto",
                    help="block size, e.g. 4M / 512K / auto (default: auto)")
    ap.add_argument("--segment-gb", type=float, default=4.0,
                    help="segment size in GB; 0 = whole disk at once (default: 4)")
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
    ap.add_argument("--red-mult", type=float, default=8.0,
                    help="very slow threshold = median x N")
    ap.add_argument("--yellow-floor-ms", type=float, default=10.0,
                    help="slow threshold floor in ms")
    ap.add_argument("--red-floor-ms", type=float, default=100.0,
                    help="very slow threshold floor in ms")
    return ap


def main(argv=None):
    # 先修编码再解析参数：argparse 的 --help / 用法错误会直接打印后退出，
    # 必须在此之前保证标准流编码与终端匹配（打包版在 UTF-8 终端不乱码）
    _fix_stdout_encoding()
    args = build_parser().parse_args(argv)

    if args.version:
        _ensure_console()   # 打包版在命令行里运行时校正输出编码
        print("HD Doc %s (fio: %s)"
              % (VERSION, "bundled" if getattr(sys, "frozen", False) else "source"))
        return 0
    if args.cli:
        # 延迟导入：CLI 路径不加载 tkinter / GUI 代码
        from HD_Doc_cli import cli_main
        return cli_main(args)
    try:
        # 只有 GUI 模式才导入 tkinter
        from HD_Doc_gui import HDDocApp
    except ImportError as e:
        print("Error: cannot start GUI (no tkinter in this Python? %s)" % e)
        print("Use the python.org installer (bundles tkinter), or the CLI mode:")
        print("  python HD_Doc.py --cli --target <target> --bs 4M")
        return 2
    app = HDDocApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
