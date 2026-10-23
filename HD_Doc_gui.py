#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# HD Doc —— GPL-3.0-or-later，完整文本见仓库根目录 LICENSE。
# 全部代码由 AI（WorkBuddy）完成；发布者仅提供提示词、需求与测试。
"""
HD_Doc_gui.py —— GUI 模式（PyQt5；只依赖 HD_Doc_core）

本模块只在 GUI 模式下被入口 HD_Doc.py 导入；
没有 PyQt5 的环境（如 --cli 命令行模式）永远不会加载本模块。

为什么用 PyQt5 而不是 ttkbootstrap（tkinter）：
  - 跨系统一致性：tkinter 在不同发行版上依赖系统 tk（Windows 的 tk8.6、
    Ubuntu/麒麟的 tk8.6 主题与渲染差异明显，HiDPI 下还会发虚）；PyQt5 的
    绘制完全由 Qt 自己完成，Windows / Ubuntu / 银河麒麟（UKUI）下界面
    像素级一致，且天然支持高分屏缩放；
  - 发行版支持：python3-pyqt5 在 Debian/Ubuntu/银河麒麟/openKylin 的
    软件源里都有（麒麟 V10 = Ubuntu 20.04 基座），无需 pip 编译；
  - 绘制性能：热力图 256 格用 QPainter 批量填充，逐格渲染的开销远低于
    逐个 create_rectangle/itemconfig 的 Tk 对象操作。

界面语言：默认英文，菜单 Language/语言 可切换到任何已安装语言
（菜单由 lang/*.json 自动发现生成，新增语言零代码改动），选择持久化在
用户配置目录（见 HD_Doc_core 的 i18n 小节；文案表在 lang/*.json，
独立于代码）。切换语言即保存偏好并原地重建界面（_rebuild_ui：
销毁全部控件后按新语言重建，扫描线程/结果/日志都不受影响），
不重启进程。扫描结果/错误提示以界面内横幅与日志展示，尽量不弹窗。

管理员权限：程序启动即申请（入口在创建窗口前调用
ensure_admin_at_startup，直接弹 UAC，不再先问"是否重启"），
UAC 确认后由提权后的新进程接管、本进程退出；取消则保持标准
权限继续运行（扫镜像文件不需要管理员）。扫描物理盘时若仍未
提权，同样直接弹 UAC，不再弹二次确认框。

界面主题：浅色/深色两套 QSS 样式表（默认浅色），选择持久化；
切换主题 = 保存偏好 + 整体换 stylesheet（QSS 作用于整个
QApplication，含消息框/下拉弹层等所有标准对话框），语义色
（热力图绿/黄/红/灰、横幅与状态级别色）与主题无关，两套通用。
"""

import os
import queue
import statistics
import sys
import threading
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDesktopWidget,
                             QDialog, QFileDialog, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QSizePolicy,
                             QTreeWidget, QTreeWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

import HD_Doc_core as core                      # 业务逻辑全部经 core
from HD_Doc_core import *                       # 常用名直接可用（调用点不变）
from HD_Doc_core import _pythonw_path           # 下划线名需显式导入

# 横幅级别 → (背景色, 文字色)。语义色与主题无关：浅/深两套 QSS 下都用
# 同一组饱和色 + 白字，与 ttkbootstrap 的 bootstyle 视觉一致。
BANNER_STYLE = {"info": ("#1565c0", "#ffffff"),
                "ok": ("#2e7d32", "#ffffff"),
                "warn": ("#ef6c00", "#ffffff"),
                "error": ("#c62828", "#ffffff")}

# 状态行语义键 → (背景色, 文字色)；neutral 色随主题取（见 _state_style）
STATE_ACCENT = {"gui.state_ready": "neutral",
                "gui.state_scanning": "#1565c0",
                "gui.state_stopping": "#ef6c00",
                "gui.state_stopped": "neutral",
                "gui.state_done": "#2e7d32",
                "gui.state_done_aborted": "#2e7d32",
                "gui.state_failed": "#c62828"}

# 热力图双模式（下拉选项顺序即下标语义，跨语言稳定）：
#   健康模式——只按"有没有读取错误"判定：绿=正常、红=读取错误
#     （HD Tune 错误扫描同语义；读得慢但不是错误，健康判定只有两色）；
#   速度模式——按读取延迟判定：绿=快、黄=偏慢、红=读取错误。
# 两种模式共用灰色表示"未扫描/未抽样"——无数据不是健康/速度判定，
# 不显示灰色会把未扫区域误读成"健康"。
MAP_MODE_HEALTH = 0
MAP_MODE_SPEED = 1

# 主题名沿用 core 的 THEMES（配置持久化兼容）：bootstrap-light/dark
# 只是名字，渲染完全由下面的 QSS + 色板决定。
THEME_COLORS = {
    "bootstrap-light": dict(
        bg="#f0f0f0", base="#ffffff", border="#c8c8c8", text="#1f1f1f",
        muted="#5f5f5f", selection_bg="#1976d2", selection_fg="#ffffff",
        neutral_bg="#e4e4e4", neutral_fg="#333333",
        tab_bg="#e8e8e8", tab_sel="#ffffff", input_bg="#ffffff",
        hover_bg="#eaf2fb", hover_border="#8bb3e8", chunk="#1976d2",
        menubar_bg="#f0f0f0"),
    "bootstrap-dark": dict(
        bg="#2b2d30", base="#2b2b2b", border="#5a5d5f", text="#dcdcdc",
        muted="#9a9da0", selection_bg="#3daee9", selection_fg="#101010",
        neutral_bg="#4a4d50", neutral_fg="#dddddd",
        tab_bg="#35373a", tab_sel="#3c3f41", input_bg="#2b2b2b",
        hover_bg="#45484b", hover_border="#7a7d7f", chunk="#3daee9",
        menubar_bg="#2b2d30"),
}

_QSS_TEMPLATE = """
QWidget {{ background: {bg}; color: {text}; font-size: 9pt; }}
QGroupBox {{ border: 1px solid {border}; border-radius: 4px;
             margin-top: 8px; padding: 4px 4px 8px 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; }}
QPushButton {{ background: {base}; border: 1px solid {border};
               border-radius: 3px; padding: 4px 10px; min-height: 18px; }}
QPushButton:hover {{ background: {hover_bg}; border-color: {hover_border}; }}
QPushButton:pressed {{ background: {chunk}; color: #ffffff; }}
QPushButton:disabled {{ color: {muted}; background: {bg};
                        border-color: {border}; }}
QPushButton#btn_start {{ background: {chunk}; color: #ffffff; border: none; }}
QPushButton#btn_start:hover {{ background: {hover_border}; }}
QPushButton#btn_start:pressed {{ background: {border}; }}
QPushButton#btn_start:disabled {{ background: {border}; color: {muted}; }}
QPushButton#btn_stop {{ color: #c62828; border: 1px solid #c62828;
                        background: {base}; }}
QPushButton#btn_stop:hover {{ background: #fdecea; }}
QPushButton#btn_stop:disabled {{ color: {muted}; border-color: {border};
                                  background: {bg}; }}
QComboBox {{ background: {input_bg}; border: 1px solid {border};
             border-radius: 3px; padding: 3px 6px; }}
QComboBox:disabled {{ color: {muted}; background: {bg}; }}
QComboBox QAbstractItemView {{ background: {input_bg}; color: {text};
    selection-background-color: {selection_bg};
    selection-color: {selection_fg}; }}
QComboBox QAbstractItemView:item {{ min-height: 20px; }}
QCheckBox {{ background: transparent; }}
QPlainTextEdit, QTreeWidget {{ background: {input_bg}; color: {text};
                               border: 1px solid {border}; }}
QTreeWidget::item:selected {{ background: {selection_bg};
                              color: {selection_fg}; }}
QTabWidget::pane {{ border: 1px solid {border}; }}
QTabBar::tab {{ background: {tab_bg}; border: 1px solid {border};
                padding: 5px 12px; }}
QTabBar::tab:selected {{ background: {tab_sel}; }}
QProgressBar {{ border: 1px solid {border}; border-radius: 3px;
                text-align: center; background: {input_bg}; }}
QProgressBar::chunk {{ background: {chunk}; }}
QMenuBar {{ background: {menubar_bg}; }}
QMenuBar::item:selected {{ background: {selection_bg};
                           color: {selection_fg}; }}
QMenu {{ background: {base}; border: 1px solid {border}; }}
QMenu::item:selected {{ background: {selection_bg}; color: {selection_fg}; }}
QToolTip {{ background: #ffffe1; color: #000000;
            border: 1px solid #767676; }}
"""

THEME_QSS = {name: _QSS_TEMPLATE.format(**colors)
             for name, colors in THEME_COLORS.items()}

# pkexec 授权等待宽限（秒）：输密码、找授权框都要时间，早期版本用 2.5 秒
# 固定超时猜测"授权进行中"，输密码超过 2.5 秒父进程先退出、授权框跟着
# 消失。现在靠就绪标记（core.elev_ready）精确判定，这里只是兜底上限。
ELEVATE_WAIT_DEFAULT = 90


def _elevate_wait_secs():
    """授权等待宽限（秒）：HDTUNE_ELEVATE_WAIT 可覆盖（测试/慢机器），
    非法值回退默认；夹在 [1, 600] 防呆。"""
    raw = os.environ.get("HDTUNE_ELEVATE_WAIT", "")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return ELEVATE_WAIT_DEFAULT
    return max(1.0, min(v, 600.0))


def _resource_dir():
    """img/ 资源目录：打包版在 sys._MEIPASS，源码版在脚本同级"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "img")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")


# 弹窗内图标上限（原图可能是 1248px 的大图，直接放会把对话框撑爆）
ABOUT_ICON_PX = 48


def _bounded_pixmap(path, max_px=ABOUT_ICON_PX):
    """QPixmap 等比缩到 max_px 以内（SmoothTransformation，模糊但不会
    出现 Tk subsample 的点采样噪点；原图任一边已不超上限时原样返回）。"""
    pm = QPixmap(path)
    if pm.isNull() or max(pm.width(), pm.height()) <= max_px:
        return pm
    return pm.scaled(max_px, max_px, Qt.KeepAspectRatio,
                     Qt.SmoothTransformation)


def _mono_font():
    """等宽字体（日志/汇总页）：优先 Consolas（Windows），缺失时按
    Monospace 风格提示由 Qt 在各平台选系统等宽字体（麒麟/Ubuntu 的
    DejaVu Sans Mono 等），不写死单一字体名。"""
    f = QFont("Consolas")
    f.setStyleHint(QFont.Monospace)
    f.setFixedPitch(True)
    return f


def _qt_excepthook(exc_type, exc_value, exc_tb):
    """Qt 槽/事件回调未捕获异常 → 运行日志。

    PyQt5 对槽里逃出的异常默认走 sys.excepthook（打印到 stderr 后继续，
    打包版 --windowed 没有控制台 → 用户什么都看不到）。这里连同堆栈
    落盘，便于事后排查；同时保留 stderr 打印（源码调试用）。
    """
    import traceback
    try:
        traceback.print_exception(exc_type, exc_value, exc_tb)
    except Exception:
        pass
    core.log_exception("qt callback exception", exc_value)


def ensure_admin_at_startup():
    """GUI 启动即申请管理员权限（入口 HD_Doc.py 在创建窗口前调用）。

    设计取舍：不在程序跑起来以后再弹"是否重启为管理员"的对话框——
    UAC/pkexec 确认本身就是那个询问。非管理员且允许自动提权时直接发起
    提权重启：
      - 授权确认 → 提权进程已启动，返回 True，调用方应退出本进程
        （窗口都不会创建，不存在"先闪一下再提权"）；
      - 授权取消 → 返回 False，以标准权限继续运行（扫镜像文件、
        刷新磁盘列表都不需要管理员；物理盘扫描入口还会再提权）。
    --no-elevate / HDTUNE_NO_AUTO_ELEVATE=1 关闭自动提权时直接返回
    False（照常启动，界面保留"以管理员重启"按钮）。

    平台差异：Windows 用 ShellExecuteEx("runas")，取消时同步返回错误、
    立刻可知；Linux 没有 UAC，用 pkexec 异步启动（授权期间 pkexec 一直
    存活）。此时"存活"有两种含义——用户还在输密码，或授权已通过、提权
    实例正在起窗口——必须用就绪标记区分（core.elev_ready）：提权实例
    窗口起来后会向 HDTUNE_ELEV_LOG 快照文件追加 READY 行。因此这里：
      - 出现 READY → 提权实例已接管 → 返回 True，调用方退出本进程
        （窗口都不会创建，不存在"先闪一下再提权"）；
      - pkexec 退出 → 授权被取消(126)/目标实例崩溃(其他非 0) → 返回
        False，以标准权限继续运行（扫镜像文件、刷新磁盘列表都不需要
        管理员；物理盘扫描入口还会再提权）；
      - 超时（默认 90s，HDTUNE_ELEVATE_WAIT 可调）仍未就绪 → 终止
        pkexec 关掉授权框，返回 False 照常启动。
    早期版本用固定 2.5 秒超时猜测"授权进行中"：输密码超过 2.5 秒时
    父进程先退出、授权框跟着消失——用户看到"密码没输完窗口就没了"。
    """
    if is_admin() or not auto_elevate_enabled():
        return False
    if IS_WIN:
        print("[Elevate] Not running as administrator; requesting elevation (UAC)...")
        ok, _code, err = request_elevation(wait=False, gui=True)
        if ok:
            print("[Elevate] Elevated instance started; exiting this process.")
            return True
        # UAC 被取消或启动失败：不退出程序，继续标准权限运行
        print("[Elevate] Elevation not granted (%s); continuing unelevated."
              % (err or "unknown"))
        return False
    # ---- Linux / 其他平台：pkexec 图形授权 ----
    # 预检显示环境：DISPLAY/WAYLAND_DISPLAY 全无（含探测）时，root 实例
    # 注定连不上 X/Wayland（Qt 平台插件失败会 C++ qFatal 秒退，授权框
    # 跟着闪退）——不弹这个注定失败的框，保持标准权限启动并提示。
    if not (core._probe_display()
            or os.environ.get("WAYLAND_DISPLAY")):
        print("[Elevate] No DISPLAY / WAYLAND_DISPLAY detected;"
              " skipping pkexec elevation (would fail to connect).")
        core.log_event("startup: no display env; skip pkexec elevation")
        return False
    popen, err = core.pkexec_gui_spawn()
    if popen is None:
        # 已是 root（err=None）或 pkexec 不可用：不阻塞启动
        print("[Elevate] pkexec unavailable (%s); starting unelevated."
              % (err or "already root"))
        core.log_event("startup: pkexec unavailable (%s)" % (err or "root"))
        return False
    core.log_event("startup: pkexec elevation requested (pid=%s)" % popen.pid)
    # 就绪标记协议（替代早期的固定 2.5 秒超时猜测，见函数文档）：
    # pkexec 存活 ≠ 授权成功——用户可能还在输密码。只有提权实例窗口
    # 起来写入 READY 行（core.elev_ready）才判定"已接管"，父进程退出。
    marker = core.elev_log_path()
    wait_secs = _elevate_wait_secs()
    deadline = time.monotonic() + wait_secs
    while True:
        code = popen.poll()
        if code is not None:
            print("[Elevate] pkexec exited with %s (authorization cancelled"
                  " or failed); continuing unelevated." % code)
            core.log_event("startup: pkexec exited rc=%s; continuing"
                           " unelevated" % code)
            # pkexec 在授权前/后很快退出：排除"用户主动取消"后，最常见的
            # 是提权实例启动即崩溃（root 连不上 X/Wayland → Qt qFatal，
            # Python 层无痕）。子进程已把环境快照写进 HDTUNE_ELEV_LOG，
            # 指给用户/排查者。
            if code:
                core.log_event("startup: elevated instance may have crashed"
                               " on startup; see env snapshot in %s" % marker)
            return False
        if core.elev_ready(marker):
            # 提权实例窗口已显示：本进程退出，让提权实例接管
            print("[Elevate] Elevated instance is up (marker %s); exiting"
                  " this process." % marker)
            core.log_event("startup: elevated instance READY (%s); exiting"
                           % marker)
            return True
        if time.monotonic() >= deadline:
            # 超时：授权框关了（终止 pkexec），本进程以标准权限继续启动，
            # 窗口随后会出现；用户可改用"以 root 重启"或终端 sudo。
            print("[Elevate] Authorization wait timed out after %.0fs;"
                  " continuing unelevated." % wait_secs)
            core.log_event("startup: elevation wait timed out after %.0fs;"
                           " pkexec terminated" % wait_secs)
            try:
                popen.terminate()
            except Exception:
                pass
            return False
        time.sleep(0.1)


class MapWidget(QWidget):
    """热力图绘制部件：256 格平铺（布局由 core.plan_grid 计算，数据与
    颜色判定全部在 app 侧，本类只负责画）。

    与 ttk Canvas 的对应关系：
      - itemconfig(fill=...) → app 改 cells 数据后调用本部件 update()
        （Qt 重绘由 paintEvent 统一按当前模式/阈值重新取色，不需要
        像 Tk 那样逐个 item 改色）；
      - <Motion> → mouseMoveEvent（setMouseTracking 无按键也收移动事件）；
      - <Leave> → leaveEvent；
      - <Configure> → resizeEvent（app 侧 50ms 防抖后重排）。
    """

    def __init__(self, app):
        super().__init__(app.map_frame)
        self.app = app
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, ev):
        app = self.app
        try:
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(THEME_COLORS[get_theme()]["base"]))
            if not app.cells:
                return
            cols = max(1, app.grid_cols)
            pitch = app.cell_pitch
            size = max(CELL_SIZE_MIN, int(pitch) - CELL_GAP)
            ox, oy = app.grid_ox, app.grid_oy
            for i in range(len(app.cells)):
                color = app._cell_color(i)
                x = ox + (i % cols) * pitch
                y = oy + (i // cols) * pitch
                p.fillRect(int(x), int(y), size, size, QColor(color))
        except Exception as e:            # 绝不让异常逃进 Qt 事件循环
            core.log_exception("heatmap paint failed", e)

    def mouseMoveEvent(self, ev):
        self.app._on_map_hover(ev.x(), ev.y())

    def leaveEvent(self, ev):
        self.app._on_map_hover(None, None)

    def resizeEvent(self, ev):
        # 尺寸变化（窗口缩放/最大化/DPI 变化/语言重建后重映射）：
        # 交 app 侧 50ms 防抖合并成一次重排（拖拽缩放会连续触发）
        super().resizeEvent(ev)
        self.app._on_map_resize()


class AboutDialog(QDialog):
    """关于对话框（模态）：图标 + 标题 + 说明 + 确定。

    对应 ttk 版的 _show_about：Esc/关闭 = 取消；确定按钮默认聚焦；
    居中于父窗口。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("gui.about.title"))
        self.setModal(True)
        self.setSizeGripEnabled(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 18)
        head = QHBoxLayout()
        icon_path = os.path.join(_resource_dir(), "HD_Doc.png")
        if os.path.isfile(icon_path):
            pm = _bounded_pixmap(icon_path)
            if not pm.isNull():
                lbl_icon = QLabel()
                lbl_icon.setPixmap(pm)
                head.addWidget(lbl_icon)
        lbl_title = QLabel(tr("gui.title", ver=VERSION))
        f = lbl_title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 3)
        lbl_title.setFont(f)
        head.addWidget(lbl_title)
        head.addStretch(1)
        lay.addLayout(head)
        lbl_body = QLabel(tr("gui.about.body"))
        lbl_body.setWordWrap(True)
        lbl_body.setMaximumWidth(440)
        lbl_body.setMinimumWidth(360)
        lbl_body.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl_body)
        lay.addSpacing(8)
        btn = QPushButton(tr("gui.about.ok"))
        btn.setObjectName("btn_ok_about")
        btn.clicked.connect(self.accept)
        lay.addWidget(btn, 0, Qt.AlignHCenter)
        # 居中于父窗口（show 后父窗口几何才稳定）
        self._center(parent)
        btn.setFocus()

    def _center(self, parent):
        try:
            pg = parent.geometry()
            self.adjustSize()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + (pg.height() - self.height()) // 2
            self.move(max(0, x), max(0, y))
        except Exception:
            pass

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(ev)


class HDDocApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # 异常落日志（PyQt5 槽异常默认走 sys.excepthook；打包版无控制台）
        sys.excepthook = _qt_excepthook
        self.setObjectName("HD_Doc")
        # QApplication.setApplicationName/setDesktopFileName 在入口设置；
        # 这里再确保一次（测试直接实例化本类时）
        QApplication.setApplicationName("HD_Doc")
        QApplication.setDesktopFileName("hd-doc")
        self.setWindowTitle(tr("gui.title", ver=VERSION))
        self.resize(1140, 820)
        self.setMinimumSize(980, 700)
        self._target_paths = {}       # 下拉标签 → 裸设备路径（型号显示用）
        self._about_icon = None       # 弹窗内小图标（_bounded_pixmap 缩放版）
        # pkexec 提权轮询（Linux）：_relaunch_elevated 发起后用定时器
        # 观察子进程存活——授权取消/失败时 pkexec 很快退出，此时必须保留
        # 本窗口并提示，不能像旧版那样 200ms 后无条件退出（表现为"闪退"）
        self._pkexec_popen = None
        self._pkexec_marker = ""       # 就绪标记文件（core.elev_log_path）
        self._pkexec_deadline = 0.0    # 授权等待宽限截止（monotonic）

        self.q = queue.Queue()
        self.scanner = None
        self.worker = None
        self.cells = []
        self.dirty = set()
        self.grid_cols = 1
        self.grid_rows = 1
        self.cell_pitch = CELL_SIZE_MIN + CELL_GAP
        self.grid_ox = self.grid_oy = 0.0
        self.n_cells = 0            # 热力图格数（固定 MAP_CELLS，UI 一致性）
        self.seg_meta = []          # 扫描计划每段 (offset, size|None, span|None)
        self.cell_span = []         # 每格字节范围 (start, end|None)，悬停显示
        self.seg_cells = []         # 每段覆盖的格下标列表（聚合映射）
        self.cell_region = []       # 每格由哪个段/区域供数（悬停显示抽样上下文）
        self._map_wh = None         # 上次布局采用的画布尺寸（缩放事件去重）
        self._err_seen = set()      # 已计入热力图的错误块（事件/汇总去重）
        self._painted = []          # 每格上次渲染的颜色（_queue_recolor 比对）
        self.total_size = None
        self.planned_bytes = 0   # 快速扫描的计划读取量（进度/ETA 分母）
        self.thresholds = 0.0
        self.summary = None
        self.scan_start_ts = None
        self.scan_bs = 0
        self.scan_quick = False
        self.seg_base = []
        self._last_thresh_calc = 0.0
        self._last_flush = 0.0
        self._progress_indeterminate = False
        # 结构化日志/横幅：切换语言重建界面时按新语言重放（_render_log /
        # _render_banner）。日志条目 ("i18n", stream, key, kw) 可重翻译，
        # ("raw", stream, line) 为 fio 原始输出，原样保留。
        self._log_entries = []
        self._banner_key = None
        # 状态行语义键（_set_state 记录；重建界面时按新语言重放——
        # 状态行没有 tick 刷新，不能像进度/速度那样等它自愈）
        self._state_key = "gui.state_ready"

        # 界面语言与主题（切换即原地重建/换色，不重启进程，
        # 见 _set_language / _set_theme / _rebuild_ui）
        self._lang = get_language()
        self._theme = get_theme()

        # 热力图模式（健康/读取速度）：_build_ui 建下拉前就绪，
        # 切换语言重建界面时按快照下标恢复（见 _rebuild_ui）
        self.map_mode = MAP_MODE_HEALTH

        # ---- 定时器（重建/退出时统一管理）----
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_queue)
        self._pkexec_timer = QTimer(self)
        self._pkexec_timer.timeout.connect(self._poll_pkexec)
        self._pkexec_timer.setInterval(150)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._flush_map_configure)

        self._setup_theme()
        self._set_window_icon()
        # central widget 必须先建：_build_ui 的所有控件都以它为父
        # （与 ttk 版"窗口本身就是控件容器"对应；_rebuild_ui 换 central
        #  即等效"销毁全部子控件后重建"）
        self._central = QWidget(self)
        self.setCentralWidget(self._central)
        self._build_ui(self._central)
        self._refresh_drives()
        self._center_on_screen()
        self._poll_timer.start(100)
        QTimer.singleShot(200, self._startup_admin_check)
        core.log_event("gui: start ver=%s frozen=%s admin=%s lang=%s theme=%s"
                       % (VERSION, getattr(sys, "frozen", False), is_admin(),
                          get_language(), get_theme()))

    # ---------------------------------------------------------- 主题与图标
    def _setup_theme(self):
        """应用当前主题的 QSS（浅色/深色）+ 全局 UI 字体。

        QSS 挂在 QApplication 上：整个进程的标准控件（含下拉弹层、
        QMessageBox、QFileDialog）一起换肤，不需要像 ttk 那样逐个
        style.configure；语义色（横幅/状态/热力图）不走 QSS，由代码
        直接给 stylesheet，两套主题通用。
        """
        QApplication.instance().setStyleSheet(THEME_QSS[get_theme()])

    def _set_window_icon(self):
        """标题栏 + 任务栏/Alt-Tab 图标（.png，经 setWindowIcon）。

        Qt 在 Windows/X11/Wayland 上都直接渲染 PNG，不存在 Tk 端口
        "渲染不了 PNG 压缩的 .ico"的问题——一条路即可，.ico 仅作打包
        版 exe 资源用（build_exe.py --icon）。资源缺失时静默跳过。"""
        path = os.path.join(_resource_dir(), "HD_Doc.png")
        if os.path.isfile(path):
            self.setWindowIcon(QIcon(path))
            self._about_icon = _bounded_pixmap(path)
        else:
            ico = os.path.join(_resource_dir(), "HD_Doc.ico")
            if os.path.isfile(ico):
                self.setWindowIcon(QIcon(ico))

    # ---------------------------------------------------------- 文案辅助
    # 文案全部经 tr() 取当前语言：切换语言会重建界面（_rebuild_ui），
    # 各构建函数重新执行即拿到新语言文案
    def _center_on_screen(self):
        """启动时把窗口居中放到屏幕中间（构建期 resize 请求会被窗口
        管理器改写，show 前一次性指定尺寸与位置；offscreen 测试环境
        屏幕几何为默认值，逻辑同样成立）。"""
        self.adjustSize()
        self.resize(1140, 820)          # 设计尺寸（与 __init__ 一致）
        try:
            geo = QDesktopWidget().availableGeometry(self)
            self.move(max(0, (geo.width() - self.width()) // 2),
                      max(0, (geo.height() - self.height()) // 2))
        except Exception:
            pass

    def _reg(self, widget, key, **kw):
        """设置静态文本控件（按钮/标签）的文案"""
        widget.setText(tr(key, **kw))
        return widget

    def _reg_values(self, combo, key):
        """设置下拉列表控件的选项文案"""
        combo.clear()
        combo.addItems(tr_list(key))
        return combo

    def _reg_tab(self, nb, child, key):
        nb.addTab(child, tr(key))

    def _reg_heading(self, tree, column, key):
        """表头文案（列序固定：block/offset/desc）"""
        heads = [tree.headerItem().text(i) for i in range(3)]
        heads[column] = tr(key)
        tree.setHeaderLabels(heads)

    def _state_style(self, key):
        """状态行 (bg, fg)：accent 语义色 + neutral 随主题"""
        accent = STATE_ACCENT.get(key, "neutral")
        if accent == "neutral":
            c = THEME_COLORS[get_theme()]
            return c["neutral_bg"], c["neutral_fg"]
        return accent, "#ffffff"

    def _set_state(self, key):
        """状态行文案（记录语义键：切换语言重建界面时按新语言重放）"""
        self._state_key = key
        bg, fg = self._state_style(key)
        self.lbl_state.setText(tr(key))
        self.lbl_state.setStyleSheet(
            "background: %s; color: %s; border-radius: 3px; padding: 2px 8px;"
            % (bg, fg))
        return self.lbl_state

    def _ask_yes(self, title, message):
        """是/否确认框（关闭扫描时用）。

        按钮文案走 lang/*.json（gui.btn.yes / gui.btn.no）；返回 False
        表示"否/取消"（默认按钮为否，防误触继续扫描）。"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Question)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        yes_btn = box.button(QMessageBox.Yes)
        no_btn = box.button(QMessageBox.No)
        if yes_btn:
            yes_btn.setText(tr("gui.btn.yes"))
        if no_btn:
            no_btn.setText(tr("gui.btn.no"))
        return box.exec_() == QMessageBox.Yes

    def _set_language(self, lang):
        """切换语言：保存偏好并原地重建界面（不重启进程）。

        旧实现靠 execv 重启重载界面，扫描中只能禁止切换（重启会遗留
        fio 子进程）；现在 _rebuild_ui 只换控件与文案，扫描线程、
        fio 子进程、扫描结果都不受影响，因此扫描中也能切换。
        """
        if lang == get_language():
            self._lang = lang
            return
        if set_language(lang):          # 写入配置 + 进程内切换
            core.log_event("pref: language -> %s" % lang)
            self._lang = lang
            self._rebuild_ui()

    def _set_theme(self, theme):
        """切换主题（浅色/深色）：保存偏好 + 整体换 QSS，不重启进程。

        QSS 作用于整个 QApplication（所有标准控件与对话框）；不走 QSS
        的自绘部分（热力图背景）与语义色无关，只需重画一次；图例色块
        边框色随主题手工同步（_apply_theme_to_legend）。
        """
        if theme == get_theme():
            self._theme = theme
            return
        if set_theme(theme):            # 写入配置 + 进程内切换
            core.log_event("pref: theme -> %s" % theme)
            self._theme = theme
            QApplication.instance().setStyleSheet(THEME_QSS[theme])
            self._apply_theme_to_legend()
            if self.map_widget:
                self.map_widget.update()

    def _apply_theme_to_legend(self):
        """图例色块边框色随主题同步（色块填充是语义色，不随主题切换）"""
        border = THEME_COLORS[get_theme()]["border"]
        for swatch in getattr(self, "_legend_swatches", []):
            swatch.setStyleSheet(
                "background: %s; border: 1px solid %s;"
                % (swatch.property("cell_color"), border))

    # ---------------------------------------------------------- 界面重建
    def _rebuild_ui(self):
        """原地重建整个界面（切换语言用；不重启进程）。

        流程：快照当前可见状态 → 停掉碰控件的定时器 → 换新的 central
        widget（旧的由 setCentralWidget 删除，等效于 ttk 版"销毁全部
        子控件"）→ 重建 → 恢复。
        跨重建保留的：
          - 各下拉/输入框的当前选择（本地化列表如块大小按
            下标恢复，避免"自动"↔"Auto"对不上）；
          - 结构化日志（按新语言重放）与横幅（按键+参数重放）；
          - 已完成的扫描结果（热力图数据 + 汇总页 + 错误树）；
          - 进行中扫描的 UI 状态（按钮禁用、状态行文案、进度值），
            保证切换后扫描继续、界面不回到"就绪"的误导状态。
        普通属性（scanner/worker/summary/cells 阈值等）本就活着，
        无需快照；只有被销毁的控件持有的值需要在这里搬运。
        """
        scanning = bool(self.worker and self.worker.is_alive())
        # ---- 快照（控件里的值，重建后会丢）----
        state_key = self._state_key    # _build_ui 会把它重置为 ready，先存
        snap = {
            "target": self.combo_target.currentText(),
            "bs_idx": self.combo_bs.currentIndex(),
            "engine": self.combo_engine.currentText(),
            "direct": self.chk_direct.isChecked(),
            "seg_idx": self.combo_seg.currentIndex(),
            "quick": self.chk_quick.isChecked(),
            "sample_idx": self.combo_quick_sample.currentIndex(),
            "map_mode_idx": self.combo_map_mode.currentIndex(),
            "fio": self.entry_fio.currentText(),
            "tab": self.nb.currentIndex(),
            "progress": (self.progress.value()
                         if not self._progress_indeterminate else 0),
            "progress_indeterminate": self._progress_indeterminate,
            "status": {
                "lbl_progress": self.lbl_progress.text(),
                "lbl_speed": self.lbl_speed.text(),
                "lbl_elapsed": self.lbl_elapsed.text(),
                "lbl_eta": self.lbl_eta.text(),
                "lbl_errors": self.lbl_errors.text(),
                # lbl_state 不进快照：语义键 _state_key 是普通属性，
                # 重建后直接 _set_state 重放（按新语言）
            },
            # 热力图：_reset_map 会新建 cells，先备份数据
            # （格数固定 MAP_CELLS，重建后按段计划重算段→格映射）
            "map": (list(self.seg_meta), [dict(c) for c in self.cells],
                    self.thresholds) if self.cells else None,
        }
        # ---- 停定时器（它们持控件引用；重建后重启轮询）----
        self._poll_timer.stop()
        self._pkexec_timer.stop()
        self._resize_timer.stop()
        # ---- 销毁 + 重建（setCentralWidget 删除旧 central 及其子控件）----
        self.menuBar().clear()
        new_central = QWidget(self)
        self.setCentralWidget(new_central)
        self._build_ui(new_central)
        self.setWindowTitle(tr("gui.title", ver=VERSION))
        self._set_state(state_key)     # 状态行按键重放（按新语言）
        # ---- 恢复 ----
        self._refresh_drives()
        if snap["target"]:
            idx = self.combo_target.findText(snap["target"])
            if idx >= 0:
                self.combo_target.setCurrentIndex(idx)
            else:
                # 浏览文件/手动路径不在磁盘列表：加入后选中（快照值不丢）
                self._set_target_text(snap["target"])
        if snap["bs_idx"] >= 0:
            self.combo_bs.setCurrentIndex(snap["bs_idx"])
        if snap["engine"]:
            idx = self.combo_engine.findText(snap["engine"])
            if idx < 0:
                self.combo_engine.addItem(snap["engine"])
                idx = self.combo_engine.findText(snap["engine"])
            self.combo_engine.setCurrentIndex(idx)
        self.chk_direct.setChecked(snap["direct"])
        if snap["seg_idx"] >= 0:
            self.combo_seg.setCurrentIndex(snap["seg_idx"])
        self.chk_quick.setChecked(snap["quick"])
        self._on_quick_toggle()
        if snap["sample_idx"] >= 0:
            self.combo_quick_sample.setCurrentIndex(snap["sample_idx"])
        # 热力图模式：先恢复下标与 self.map_mode（后面的热力图数据重载
        # _redraw 要按新模式上色），此时不重绘（map_widget 是新的，
        # 随后地图块数据恢复会正确上色）
        if snap["map_mode_idx"] >= 0:
            self.combo_map_mode.setCurrentIndex(snap["map_mode_idx"])
        self._on_map_mode_toggle(redraw=False)
        self.entry_fio.setCurrentText(snap["fio"])
        self._render_log()
        self._render_banner()
        self._update_admin_ui()
        if snap["map"] is not None:
            seg_meta, cells, thresholds = snap["map"]
            self._reset_map(seg_meta)             # 固定格数 + 段→格映射重算
            self.cells = [dict(c) for c in cells]   # 数据搬回新格子
            self.thresholds = thresholds
            # 界面重建（切语言/主题）不是扫描渲染：整幅按当前模式与阈值
            # 即刻恢复，不走逐格队列（否则地图要重新"扫"一遍才填满）
            self._redraw_cells()
        if self.summary is not None:
            self._set_progress_determinate()
            self.progress.setValue(100)
            self.btn_export.setEnabled(True)
            self._render_result_ui(self.summary)
        else:
            if snap["progress_indeterminate"]:
                self._set_progress_indeterminate()
            else:
                self._set_progress_determinate()
                self.progress.setValue(int(snap["progress"]))
            st = snap["status"]
            self.lbl_progress.setText(st["lbl_progress"])
            self.lbl_speed.setText(st["lbl_speed"])
            self.lbl_elapsed.setText(st["lbl_elapsed"])
            self.lbl_eta.setText(st["lbl_eta"])
            self.lbl_errors.setText(st["lbl_errors"])
            # 注：lbl_state 已在重建后由 _set_state 按 _state_key 重放
            # （进度/速度等动态值没有语义键可循，按快照原样恢复，
            #  扫描中下一个 tick（≤100ms）即按新语言刷新）
        if scanning:
            # 扫描进行中：恢复按钮禁用态（状态行文案上面已按快照恢复）
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
        self.nb.setCurrentIndex(snap["tab"])
        self._poll_timer.start(25 if len(self.dirty) > 2 else 100)

    # ---------------------------------------------------------- UI 构建
    def _build_ui(self, central=None):
        central = central if central is not None else self.centralWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._build_menubar()

        # ---- 控制区（卡片式 GroupBox，对应 ttk LabelFrame）----
        outer = QGroupBox(central)
        outer.setTitle(tr("gui.settings"))
        root.addWidget(outer)
        bar = QGridLayout(outer)
        bar.setContentsMargins(10, 6, 10, 8)
        bar.setHorizontalSpacing(6)
        bar.setVerticalSpacing(4)

        bar.addWidget(self._reg(QLabel(outer), "gui.target"), 0, 0)
        self.combo_target = QComboBox(outer)
        self.combo_target.setSizePolicy(QSizePolicy.Expanding,
                                        QSizePolicy.Fixed)
        self.combo_target.setMinimumWidth(360)
        bar.addWidget(self.combo_target, 0, 1)

        # ---- 目标行：下拉 + 刷新 + 浏览文件 ----
        bar.addWidget(self.combo_target, 0, 1)
        self.btn_refresh = self._reg(QPushButton(outer), "gui.refresh")
        self.btn_refresh.clicked.connect(self._refresh_drives)
        bar.addWidget(self.btn_refresh, 0, 2)
        self.btn_browse = self._reg(QPushButton(outer), "gui.browse_file")
        self.btn_browse.clicked.connect(self._browse_file)
        bar.addWidget(self.btn_browse, 0, 3)

        # ---- 参数行：块大小/引擎/direct/分段/快速扫描/抽样/热力图模式 ----
        row1 = QHBoxLayout()
        bar.addLayout(row1, 1, 0, 1, 4)
        row1.setSpacing(6)
        row1.addWidget(self._reg(QLabel(outer), "gui.bs"))
        # 默认值取当前语言列表的首项（"自动"/"Auto"），不写死英文
        self.combo_bs = self._reg_values(QComboBox(outer), "gui.bs_values")
        self.combo_bs.setMinimumWidth(90)
        self.combo_bs.setCurrentIndex(0)
        row1.addWidget(self.combo_bs)
        row1.addSpacing(14)
        row1.addWidget(self._reg(QLabel(outer), "gui.engine"))
        self.combo_engine = QComboBox(outer)
        engines = platform_engines()
        self.combo_engine.addItems(engines)
        default_engine = "windowsaio" if IS_WIN else "libaio"
        idx = self.combo_engine.findText(default_engine)
        if idx < 0:
            self.combo_engine.addItem(default_engine)
            idx = self.combo_engine.findText(default_engine)
        self.combo_engine.setCurrentIndex(max(0, idx))
        row1.addWidget(self.combo_engine)
        row1.addSpacing(14)
        self.chk_direct = self._reg(QCheckBox(outer), "gui.direct")
        self.chk_direct.setChecked(True)
        row1.addWidget(self.chk_direct)
        # 分段大小可选（默认 4G）：一段可跨多格，热力图按格索引顺序
        # 逐格点亮（一次只亮一格，见 _flush_cells）
        row1.addSpacing(14)
        row1.addWidget(self._reg(QLabel(outer), "gui.segment"))
        self.combo_seg = self._reg_values(QComboBox(outer), "gui.seg_values")
        idx = self.combo_seg.findText("4G")
        self.combo_seg.setCurrentIndex(idx if idx >= 0 else 0)
        row1.addWidget(self.combo_seg)
        row1.addSpacing(14)
        self.chk_quick = self._reg(QCheckBox(outer), "gui.quick")
        self.chk_quick.stateChanged.connect(self._on_quick_toggle)
        row1.addWidget(self.chk_quick)
        row1.addWidget(self._reg(QLabel(outer), "gui.sample"))
        self.combo_quick_sample = QComboBox(outer)
        self.combo_quick_sample.addItems(tr_list("gui.sample_values"))
        idx = self.combo_quick_sample.findText("16M")
        self.combo_quick_sample.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_quick_sample.setEnabled(False)
        row1.addWidget(self.combo_quick_sample)
        # 热力图模式（健康/读取速度）：显示选项，与扫描参数同行排放
        row1.addSpacing(14)
        row1.addWidget(self._reg(QLabel(outer), "gui.map_mode"))
        self.combo_map_mode = self._reg_values(QComboBox(outer),
                                               "gui.map_mode_values")
        self.combo_map_mode.setMinimumWidth(160)
        self.combo_map_mode.setCurrentIndex(MAP_MODE_HEALTH)
        self.combo_map_mode.currentIndexChanged.connect(
            self._on_map_mode_toggle)
        row1.addWidget(self.combo_map_mode)
        row1.addStretch(1)

        # ---- fio 路径行 ----
        bar.addWidget(self._reg(QLabel(outer), "gui.fio_path"), 2, 0)
        self.entry_fio = QComboBox(outer)     # 可编辑：既是输入框又留历史
        self.entry_fio.setEditable(True)
        self.entry_fio.setMinimumWidth(360)
        self.entry_fio.setCurrentText("fio")
        bar.addWidget(self.entry_fio, 2, 1)
        self.btn_fio = self._reg(QPushButton(outer), "gui.browse")
        self.btn_fio.clicked.connect(self._browse_fio)
        bar.addWidget(self.btn_fio, 2, 2)

        # ---- 按钮行 ----
        btn_bar = QHBoxLayout()
        bar.addLayout(btn_bar, 3, 0, 1, 4)
        btn_bar.setSpacing(6)
        self.btn_start = self._reg(QPushButton(outer), "gui.start")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self._start_scan)
        btn_bar.addWidget(self.btn_start)
        self.btn_stop = self._reg(QPushButton(outer), "gui.stop")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        btn_bar.addWidget(self.btn_stop)
        self.btn_export = self._reg(QPushButton(outer), "gui.export")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_report)
        btn_bar.addWidget(self.btn_export)
        lbl_hint = self._reg(QLabel(outer), "gui.hint")
        lbl_hint.setStyleSheet("color: %s;" % THEME_COLORS[get_theme()]["muted"])
        self.lbl_hint = lbl_hint
        btn_bar.addWidget(lbl_hint)
        btn_bar.addSpacing(16)
        # 权限状态：初值"检测中"，_startup_admin_check（200ms 后）刷新为
        # 管理员/标准权限（与 ttk 版 lbl_admin 初值一致）
        self.lbl_admin = self._reg(QLabel(outer), "gui.perm_checking")
        btn_bar.addWidget(self.lbl_admin)
        self.btn_elevate = self._reg(QPushButton(outer), "gui.relaunch")
        self.btn_elevate.clicked.connect(self._relaunch_elevated)
        self.btn_elevate.setVisible(False)
        btn_bar.addWidget(self.btn_elevate)
        btn_bar.addStretch(1)

        bar.setColumnStretch(1, 1)

        # ---- 热力图 ----
        # 标题文案随模式切换（_update_map_title），不占 _reg 的静态键
        self.map_frame = QGroupBox(central)
        self._update_map_title()
        root.addWidget(self.map_frame, 1)
        map_lay = QVBoxLayout(self.map_frame)
        map_lay.setContentsMargins(6, 4, 6, 4)
        self.map_widget = MapWidget(self)
        map_lay.addWidget(self.map_widget, 1)

        legend = QWidget(central)
        legend_lay = QHBoxLayout(legend)
        legend_lay.setContentsMargins(4, 0, 4, 0)
        legend_lay.setSpacing(4)
        self.lbl_hover = QLabel(legend)
        self.lbl_hover.setStyleSheet(
            "color: %s;" % THEME_COLORS[get_theme()]["muted"])
        legend_lay.addWidget(self.lbl_hover, 1)
        self._legend_labels = []
        self._legend_swatches = []   # 色块标签：切主题时同步边框色
        # 四个语义色全部建好，按模式显隐（_layout_legend）：健康模式只留
        # 绿/红/灰，速度模式 绿/黄/红/灰
        for color, key in ((COLOR_OK, "ok"), (COLOR_SLOW, "slow"),
                           (COLOR_ERROR, "error"),
                           (COLOR_PENDING, "pending")):
            swatch = QLabel(legend)
            swatch.setProperty("cell_color", color)
            swatch.setFixedSize(12, 12)
            legend_lay.addWidget(swatch)
            self._legend_swatches.append(swatch)
            lbl = QLabel(legend, text=status_text(key))
            lbl.setStyleSheet(
                "color: %s;" % THEME_COLORS[get_theme()]["muted"])
            legend_lay.addWidget(lbl)
            self._legend_labels.append((lbl, key))
        self._apply_theme_to_legend()
        self._layout_legend()

        # ---- 状态行 ----
        st = QWidget(central)
        root.addWidget(st)
        st_lay = QVBoxLayout(st)
        st_lay.setContentsMargins(8, 4, 8, 4)
        st_lay.setSpacing(4)
        self.progress = QProgressBar(st)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        st_lay.addWidget(self.progress)
        # 结果横幅：替代此前的 messagebox，扫描结果/错误在界面内展示
        # （背景色随级别动态切换：info/success/warning/danger）
        self.lbl_banner = QLabel(st, text="")
        self.lbl_banner.setWordWrap(True)
        self.lbl_banner.setStyleSheet(
            "background: %s; color: %s; border-radius: 3px; padding: 6px 10px;"
            % BANNER_STYLE["info"])
        st_lay.addWidget(self.lbl_banner)
        row = QWidget(st)
        st_lay.addWidget(row)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(10)
        self.lbl_progress = self._reg(QLabel(row), "gui.progress")
        row_lay.addWidget(self.lbl_progress)
        self.lbl_speed = self._reg(QLabel(row), "gui.speed")
        row_lay.addWidget(self.lbl_speed)
        self.lbl_elapsed = self._reg(QLabel(row), "gui.elapsed")
        row_lay.addWidget(self.lbl_elapsed)
        self.lbl_eta = self._reg(QLabel(row), "gui.eta")
        row_lay.addWidget(self.lbl_eta)
        self.lbl_errors = self._reg(QLabel(row), "gui.errors")
        row_lay.addWidget(self.lbl_errors)
        self.lbl_state = QLabel(row)
        row_lay.addWidget(self.lbl_state)
        row_lay.addStretch(1)
        self._set_state("gui.state_ready")

        # ---- 详情页 ----
        self.nb = QTabWidget(central)
        root.addWidget(self.nb, 2)
        self.txt_log = QPlainTextEdit(self.nb)
        self.txt_log.setFont(_mono_font())
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(600)
        self.txt_log.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._reg_tab(self.nb, self.txt_log, "gui.tab_log")
        err_frame = QWidget(self.nb)
        err_lay = QHBoxLayout(err_frame)
        err_lay.setContentsMargins(0, 0, 0, 0)
        cols = ("block", "offset", "desc")
        self.tree_err = QTreeWidget(err_frame)
        self.tree_err.setHeaderLabels(["", "", ""])
        self.tree_err.setRootIsDecorated(False)
        self.tree_err.setUniformRowHeights(True)
        for c, w, key in zip(cols, (90, 160, 420),
                             ("gui.col_block", "gui.col_offset",
                              "gui.col_desc")):
            self._reg_heading(self.tree_err, cols.index(c), key)
            self.tree_err.setColumnWidth(cols.index(c), w)
        err_lay.addWidget(self.tree_err)
        self._reg_tab(self.nb, err_frame, "gui.tab_errors")
        self.txt_summary = QPlainTextEdit(self.nb)
        self.txt_summary.setFont(_mono_font())
        self.txt_summary.setReadOnly(True)
        self.txt_summary.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._reg_tab(self.nb, self.txt_summary, "gui.tab_summary")

        # 图例放进地图卡片底部（与 ttk 版一致：hover 提示 + 色块横条）
        map_lay.addWidget(legend, 0)

    def _build_menubar(self):
        mb = self.menuBar()
        # 语言菜单由 lang/*.json 自动发现生成（core.available_languages：
        # 文件名即语言码、_meta.name 即菜单标签）。新增语言只需往 lang/
        # 放一个 JSON，不用改这里；切换后 _rebuild_ui 会用新表重建菜单。
        lang_menu = mb.addMenu(tr("gui.menu.language"))
        self._lang_actions = []
        for code, name in available_languages():
            act = lang_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == get_language())
            act.triggered.connect(
                lambda checked=False, c=code: self._set_language(c))
            self._lang_actions.append((act, code))
        view_menu = mb.addMenu(tr("gui.menu.view"))
        self._theme_actions = []
        for label_key, value in (("gui.menu.theme_light", "bootstrap-light"),
                                 ("gui.menu.theme_dark", "bootstrap-dark")):
            act = view_menu.addAction(tr(label_key))
            act.setCheckable(True)
            act.setChecked(value == get_theme())
            act.triggered.connect(
                lambda checked=False, v=value: self._set_theme(v))
            self._theme_actions.append((act, value))
        help_menu = mb.addMenu(tr("gui.menu.help"))
        act = help_menu.addAction(tr("gui.menu.about"))
        act.triggered.connect(self._show_about)

    # ---------------------------------------------------------- 关于窗口
    def _show_about(self):
        win = AboutDialog(self)
        win.exec_()
        # 关闭后把焦点还给主窗口（模态对话框的基本礼仪）
        self.raise_()
        self.activateWindow()

    def _on_tk_exception(self, exc_type, exc_value, exc_tb):
        """兼容旧名的异常入口（实际由 sys.excepthook 全局捕获）"""
        _qt_excepthook(exc_type, exc_value, exc_tb)

    # ---------------------------------------------------------- 交互
    def _refresh_drives(self):
        r"""刷新目标下拉框：只显示 硬盘型号 + 容量（不显示 \\.\PhysicalDriveN）。

        选中项的真实设备路径存放在 self._target_paths（label → path），
        _start_scan 解析时先查映射，查不到再按普通文件路径规范化
        （兼容 _browse_file 直接设置的路径）。
        """
        self._target_paths = {}
        values, seen = [], {}
        for d in list_drives():
            model = (d["model"] or "").strip()
            if model:
                name = model
            elif not IS_WIN and d.get("path"):
                # Linux 无型号信息时显示内核设备名（sda/nvme0n1），
                # 比"Disk N"更可识别；Windows 侧保持 Disk N 兜底
                name = os.path.basename(d["path"])
            else:
                name = tr("gui.disk_n", n=d["index"])
            size = fmt_bytes(d["size"]) if d["size"] else ""
            label = "%s  —  %s" % (name, size) if size else name
            if label in seen:   # 同型号同容量（双盘）时加序号区分
                seen[label] += 1
                label = "%s  (#%d)" % (label, seen[label])
            else:
                seen[label] = 1
            self._target_paths[label] = d["path"]
            values.append(label)
        self.combo_target.clear()
        self.combo_target.addItems(values)
        if values and not self.combo_target.currentText():
            self.combo_target.setCurrentIndex(0)

    def _set_target_text(self, text):
        """把任意文本设为目标下拉的当前值。

        下拉保持只读（防误输入），但 _browse_file 选中的文件路径 /
        测试注入的镜像路径可能不在磁盘列表里——与 ttk 版 textvariable
        可显示任意文本的行为对应：路径不在列表时先加入再选中。
        _start_scan 解析时先查 _target_paths 映射，查不到按普通文件
        路径规范化（见 _start_scan 首行）。
        """
        idx = self.combo_target.findText(text)
        if idx < 0:
            self.combo_target.addItem(text)
            idx = self.combo_target.count() - 1
        self.combo_target.setCurrentIndex(idx)

    def _browse_file(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("gui.browse_file"))
        if p:
            self._set_target_text(p)

    def _browse_fio(self):
        p, _ = QFileDialog.getOpenFileName(
            self, tr("gui.fio_path"), "",
            "fio (fio);;%s (*)" % tr("gui.browse"))
        if p:
            self.entry_fio.setCurrentText(p)

    def _on_quick_toggle(self):
        # 仅在勾选快速扫描时允许选抽样大小
        self.combo_quick_sample.setEnabled(self.chk_quick.isChecked())

    # ---------------------------------------------------------- 横幅/日志
    def _banner(self, key, level="info", **kw):
        """界面内结果横幅（替代弹窗）；级别 → (bg, fg) 语义色。
        键与参数记入 _banner_key：切换语言重建界面时按新语言重放。"""
        self._banner_key = (key, level, kw)
        self._render_banner()

    def _render_banner(self):
        """按当前语言渲染横幅（界面重建后调用；无横幅时不动）"""
        if self._banner_key is None:
            return
        key, level, kw = self._banner_key
        bg, fg = BANNER_STYLE.get(level, BANNER_STYLE["info"])
        self.lbl_banner.setText(tr(key, **kw))
        self.lbl_banner.setStyleSheet(
            "background: %s; color: %s; border-radius: 3px; padding: 6px 10px;"
            % (bg, fg))

    def _log(self, stream, key, **kw):
        """写入一条可翻译日志（结构化记录；切换语言后随界面重建，
        由 _render_log 按新语言重放，不再靠重启进程）"""
        self._log_entries.append(("i18n", stream, key, kw))
        if len(self._log_entries) > 600:
            del self._log_entries[:200]
        self._log_line(stream, tr(key, **kw))

    def _log_raw(self, stream, line):
        """fio 原始输出（英文技术文本，不过 i18n；原样记录/重放）"""
        self._log_entries.append(("raw", stream, line))
        if len(self._log_entries) > 600:
            del self._log_entries[:200]
        self._log_line(stream, line)

    def _log_line(self, stream, line):
        self.txt_log.appendPlainText("[%s] %s" % (stream, line))
        # 扫描过程中日志持续追加：固定滚动到最后一行
        # （与 ttk 版 see("end") 对应；Qt 里 appendPlainText 不自动滚动）
        bar = self.txt_log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _render_log(self):
        """按当前语言重放全部日志（界面重建后调用）"""
        self.txt_log.clear()
        for entry in self._log_entries:
            if entry[0] == "raw":
                _kind, stream, line = entry
            else:
                _kind, stream, key, kw = entry
                line = tr(key, **kw)
            self.txt_log.appendPlainText("[%s] %s" % (stream, line))
        bar = self.txt_log.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ---------------------------------------------------------- 管理员权限
    def _update_admin_ui(self):
        if is_admin():
            self.lbl_admin.setText(tr("gui.perm_admin"))
            self.lbl_admin.setStyleSheet(
                "background: %s; color: %s; border-radius: 3px; padding: 2px 8px;"
                % BANNER_STYLE["ok"])
            self.btn_elevate.setVisible(False)
        else:
            self.lbl_admin.setText(tr("gui.perm_standard"))
            self.lbl_admin.setStyleSheet(
                "background: %s; color: %s; border-radius: 3px; padding: 2px 8px;"
                % BANNER_STYLE["warn"])
            self.btn_elevate.setVisible(True)
            self.btn_elevate.setText(
                tr("gui.relaunch" if IS_WIN else "gui.relaunch_linux"))

    def _startup_admin_check(self):
        self._update_admin_ui()
        if is_admin():
            self._log("info", "gui.log.admin_ok")
            return
        self._log("warn", "gui.log.not_admin" if IS_WIN
                  else "gui.log.not_admin_linux")
        # 提权已在启动时由入口 ensure_admin_at_startup 处理：Windows 弹
        # UAC、Linux 弹 pkexec 授权框（都在窗口出现前）。能运行到这里只有
        # 三种情况：授权被取消、--no-elevate / HDTUNE_NO_AUTO_ELEVATE=1
        # 关闭了自动提权、或 pkexec 不可用。都保持标准权限继续运行，需要
        # 时点界面上的"以管理员/root 重启"按钮（Linux 见 pkexec_gui_spawn）。
        if not IS_WIN:
            self._banner("gui.log.not_admin_linux", "warn")

    def _relaunch_elevated(self):
        # gui=True：Windows 提权子进程用 pythonw.exe 启动，不再伴随命令窗口
        # （ShellExecuteEx 同步返回，UAC 取消时 ok=False，窗口保留）；
        # Linux 走 pkexec 异步启动，必须轮询子进程存活来判断授权成败——
        # 旧版无条件 after(200, 退出)，授权被取消时窗口直接消失且没有任何
        # 提示，用户看到的就是"点扫描闪退"
        if not IS_WIN:
            self._relaunch_elevated_linux()
            return
        ok, _code, err = request_elevation(wait=False, gui=True)
        if not ok:
            self._banner("gui.msg.elevate_failed", "error", err=err or "?")
            self._log("error", "gui.msg.elevate_failed", err=err or "?")
            return
        if IS_WIN and not _pythonw_path():
            self._log("warn", "gui.log.no_pythonw")
        self._log("info", "gui.log.elevate_requested")
        core.log_event("elevate: requesting administrator relaunch (gui=True)")
        QTimer.singleShot(200, self._exit_now)

    def _relaunch_elevated_linux(self):
        """Linux pkexec 提权：发起 → 横幅告知等待授权 → 轮询子进程。

        判定规则（就绪标记协议，与入口 ensure_admin_at_startup 一致）：
        pkexec 存活有两种含义——用户还在输密码 / 授权已通过实例正起窗口，
        只看存活无法区分（早期固定 3 秒轮询即因此误判）。因此：
          - 快照文件出现 READY 行 → 提权实例已接管：退出本窗口
          - pkexec 退出 → 授权被取消(126)/目标实例崩溃(其他非 0)：
            保留本窗口，横幅说明（不闪退）
          - 超时（_elevate_wait_secs，默认 90s）仍未就绪 → 终止 pkexec，
            保留窗口并提示可重试/终端 sudo
        """
        # 无显示环境时 root 实例必然连不上 X/Wayland（Qt 平台插件失败 →
        # C++ qFatal 秒退，授权框跟着闪退）：直接提示，不发起注定失败的
        # 提权（与启动入口 ensure_admin_at_startup 的预检同一逻辑）。
        if not (core._probe_display()
                or os.environ.get("WAYLAND_DISPLAY")):
            self._banner("gui.msg.elevate_no_display", "warn")
            self._log("warn", "gui.msg.elevate_no_display")
            core.log_event("elevate: no display env; pkexec not spawned")
            return
        popen, err = core.pkexec_gui_spawn()
        if popen is None:
            # 已是 root（err=None，理论上按钮此时已隐藏）或 pkexec 不可用
            self._banner("gui.msg.elevate_failed", "error",
                         err=err or tr("gui.msg.already_root"))
            self._log("error", "gui.msg.elevate_failed",
                      err=err or "already root")
            return
        self._pkexec_popen = popen
        self._pkexec_marker = core.elev_log_path()
        self._pkexec_deadline = time.monotonic() + _elevate_wait_secs()
        self._banner("gui.msg.elevate_waiting", "info")
        self._log("info", "gui.log.elevate_requested")
        core.log_event("elevate: pkexec requested (pid=%s, marker=%s)"
                       % (popen.pid, self._pkexec_marker))
        self._pkexec_timer.start()

    def _poll_pkexec(self):
        popen = self._pkexec_popen
        if popen is None:
            self._pkexec_timer.stop()
            return
        try:
            if popen.poll() is None:
                # pkexec 仍存活：授权框还在（用户可能正在输密码）。只有
                # 出现就绪标记才认定"提权实例已接管"——不能像早期版本那样
                # 轮询几秒没退出就替用户决定（输密码慢一点都会闪退）。
                if core.elev_ready(getattr(self, "_pkexec_marker", "")
                                   or core.elev_log_path()):
                    self._pkexec_popen = None
                    self._pkexec_timer.stop()
                    self._log("info", "gui.log.elevate_handover")
                    core.log_event("elevate: elevated instance READY;"
                                   " handover (this window exits)")
                    self._exit_now()
                    return
                if time.monotonic() >= self._pkexec_deadline:
                    # 超时：保留窗口（用户看得见），关掉授权框并提示
                    self._pkexec_popen = None
                    self._pkexec_timer.stop()
                    try:
                        popen.terminate()
                    except Exception:
                        pass
                    secs = int(_elevate_wait_secs())
                    self._banner("gui.msg.elevate_timeout", "warn", secs=secs)
                    self._log("warn", "gui.msg.elevate_timeout", secs=secs)
                    core.log_event("elevate: wait timed out after %ss;"
                                   " pkexec terminated" % secs)
                    return
                return
        except Exception:
            # 窗口已销毁等：放弃轮询
            self._pkexec_popen = None
            self._pkexec_timer.stop()
            return
        # pkexec 已退出 = 授权被取消/失败：保留窗口并说明原因。
        # 退出码语义（polkit/pkexec 约定）：126 = 认证失败/授权被取消或
        # polkit 拒绝；127 = 目标程序找不到/无法执行；其他非 0 = 授权后
        # 目标实例自身退出（root 连不上 X/Wayland → Qt qFatal 秒退是该
        # 场景最常见原因）。子进程已把环境快照写进 HDTUNE_ELEV_LOG
        # （core.pkexec_gui_spawn 注入），指给用户/排查者。
        self._pkexec_timer.stop()
        code = popen.returncode
        self._pkexec_popen = None
        if code != 126:
            elev_log = getattr(self, "_pkexec_marker", "") \
                or core.elev_log_path()
            self._banner("gui.msg.elevate_log_hint", "warn", path=elev_log)
            self._log("warn", "gui.msg.elevate_log_hint", path=elev_log)
            core.log_event("elevate: pkexec exited rc=%s (instance may have"
                           " crashed on startup); env snapshot: %s"
                           % (code, elev_log))
            return
        self._banner("gui.msg.elevate_cancelled", "warn", code=code)
        self._log("warn", "gui.msg.elevate_cancelled", code=code)
        core.log_event("elevate: pkexec exited rc=%s; staying unelevated"
                       % code)

    def _exit_now(self):
        self._cancel_timers()
        try:
            if self.scanner and self.worker and self.worker.is_alive():
                self.scanner.stop()
        except Exception:
            pass
        self.close()
        QApplication.instance().quit()

    def _cancel_timers(self):
        """停掉全部挂起的定时器，避免销毁后回调打到已删除的控件
        （提权重启/关闭路径的退出噪声）"""
        for t in (self._poll_timer, self._pkexec_timer, self._resize_timer):
            try:
                t.stop()
            except Exception:
                pass

    # ---------------------------------------------------------- 扫描控制
    def _start_scan(self):
        # 下拉标签（型号+容量）→ 设备路径；手动输入的路径走规范化
        target = (self._target_paths.get(self.combo_target.currentText())
                  or normalize_target_path(self.combo_target.currentText()))
        if not target:
            self._banner("gui.msg.no_target", "warn")
            self._log("warn", "gui.msg.no_target")
            return
        if is_physical_target(target) and not is_admin():
            if auto_elevate_enabled():
                # 与启动提权一致：直接弹 UAC，不再先问"是否重启"
                # （UAC 本身就是确认；取消则 _relaunch_elevated 出横幅）
                self._relaunch_elevated()
            else:
                # 明确关闭了自动提权（--no-elevate）：只提示不弹窗，
                # 由用户点"以管理员重启"或去掉该参数重试
                self._banner("gui.msg.admin_needed" if IS_WIN
                             else "gui.msg.admin_needed_linux", "warn", t=target)
                self._log("warn", "gui.msg.admin_needed" if IS_WIN
                          else "gui.msg.admin_needed_linux", t=target)
            return
        fio = resolve_fio(self.entry_fio.currentText().strip())
        if not os.path.isfile(fio):
            # 不弹窗：日志 + 横幅提示后继续（用户可能稍后补齐路径）
            self._log("warn", "gui.log.fio_missing", f=fio)
            self._banner("gui.log.fio_missing", "warn", f=fio)
        engine = (self.combo_engine.currentText() or "").strip()
        engines = list_fio_engines(fio)
        if engines is not None and engine and engine not in engines:
            # 引擎不可用是确定性错误：界面内展示，不弹窗
            self._banner("gui.msg.engine_bad", "error", e=engine,
                         list="\n".join(sorted(engines)),
                         win="、".join(ENGINES_WIN))
            self._log("error", "gui.msg.engine_bad", e=engine,
                      list="\n".join(sorted(engines)),
                      win="、".join(ENGINES_WIN))
            return
        if engines is None:
            self._log("warn", "gui.log.no_engine_probe")
        if DRIVE_PATH_RE.match(target) or target.lower().startswith("//./"):
            self._log("info", "gui.log.readonly_note", t=target)

        size = query_target_size(target)
        self.total_size = size
        try:
            bs = parse_bs(self.combo_bs.currentText(), size)
        except ValueError as e:
            self._banner("gui.msg.param_error_title", "error")
            self._log_raw("error", "%s: %s" % (tr("gui.msg.param_error_title"), e))
            return
        if size and bs > size:
            bs = clamp_bs(bs, size)
            self._log("warn", "gui.log.bs_clamped", sz=fmt_bytes(bs))
        quick = self.chk_quick.isChecked()
        # 分段大小可选（默认 4G）："整盘一次"（parse 返回 None）→ 单段
        # 整盘；容量未知时同样降级整盘一次（横幅提示，不弹窗）。
        # 快速扫描与全段扫描共用同一套分段设置：按分段大小把磁盘切成
        # 若干区域，每区只读开头样本（用户反馈"取消固定 256 段，按照
        # 分段设置分段"——旧版快速扫描固定按格数布 256 区，与分段下拉
        # 脱节）；分段超过容量时合成单区（只读区头样本）。
        seg_bytes = parse_segment_size(self.combo_seg.currentText())
        if not size and seg_bytes is not None:
            # 不弹窗：降级模式说明进日志与横幅，直接继续
            self._log("warn", "gui.log.no_size_degraded", t=target)
            self._banner("gui.log.no_size_degraded", "warn", t=target)
        quick_sample = 0
        if quick:
            if size:
                bs, segments, quick_sample = quick_scan_setup(
                    size, bs, seg_bytes,
                    parse_bs(self.combo_quick_sample.currentText()))
                if (seg_bytes and len(segments) > 1
                        and segments[1][0] - segments[0][0] > seg_bytes):
                    # 段数超硬上限被翻倍兜底：告知用户实际区域跨度，
                    # 避免"设了 512M 怎么变成 16G 一区"的困惑
                    self._log("warn", "gui.log.quick_region_enlarged",
                              set=fmt_bytes(seg_bytes),
                              actual=fmt_bytes(segments[1][0]
                                               - segments[0][0]))
                self._log("info", "gui.log.quick_plan",
                          n=len(segments), sample=fmt_bytes(quick_sample),
                          total=fmt_bytes(sum(s for _o, s in segments if s)),
                          pct=sum(s for _o, s in segments if s) * 100.0 / size)
            else:
                self._log("warn", "gui.log.quick_no_size")
                quick = False
                segments = sanitize_segments(
                    plan_segments(size, seg_bytes, bs), bs)
        else:
            segments = sanitize_segments(plan_segments(size, seg_bytes, bs), bs)
        if size:
            self._log("info", "gui.log.capacity_plan",
                      sz=fmt_bytes(size), n=len(segments), b=size // bs)

        # 热力图固定 MAP_CELLS 格（UI 一致性）：格按全盘字节范围均分，段
        # 统计按覆盖范围聚合进格；容量未知时 segments=[(0, None)]，单段
        # 广播到所有格（无位置信息，只显示整盘聚合，见 _reset_map）
        seg_meta = [(off, sz, None) for off, sz in segments]
        # 快速扫描记录区域跨度：既供悬停显示"抽样 X / 区域 Y"，也是热力图
        # 的点亮范围（区头抽样结果覆盖整区，见 _reset_map）
        if quick:
            region = None
            for i, (off, sz) in enumerate(segments):
                nxt = segments[i + 1][0] if i + 1 < len(segments) else (
                    size if size else None)
                if nxt is not None and off is not None:
                    region = nxt - off
                seg_meta[i] = (off, sz, region)
        self._reset_map(seg_meta)
        self._err_seen = set()      # 新一轮扫描：错误块去重集清零
        if not size:
            self._log("warn", "gui.log.no_size_map")
        self.tree_err.clear()
        self.txt_summary.clear()
        self.summary = None
        self.btn_export.setEnabled(False)
        self._banner_key = None      # 清横幅（重放时不再显示上一轮结果）
        self.lbl_banner.setText("")
        self.lbl_banner.setStyleSheet(
            "background: %s; color: %s; border-radius: 3px; padding: 6px 10px;"
            % BANNER_STYLE["info"])
        self.scan_start_ts = time.time()
        self.scan_bs = bs
        self.scan_quick = quick
        # 快速扫描：进度/ETA 按抽样总量计算，否则 1TB 盘抽 1.8GB
        # 也会显示"剩余十几分钟"（按整盘容量算的误导值）
        self.planned_bytes = (sum(sz for _off, sz in segments if sz)
                              if quick else 0)
        acc = 0
        self.seg_base = []
        for _off, sz in segments:
            self.seg_base.append(acc)
            acc += sz if sz else 0
        self._update_status(0, None, None, 0)

        self.scanner = FioScanner(fio)
        # UI 变量只能在主线程读：工作线程里访问 Qt 控件会炸（Qt 非线程
        # 安全），故 engine/direct 在此读出后当参数传进 worker
        engine_val = (self.combo_engine.currentText() or "").strip() or None
        direct_val = self.chk_direct.isChecked()
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(target, bs, segments, size, quick,
                  engine_val, direct_val), daemon=True)
        self.worker.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_state("gui.state_scanning")
        self._log("info", "gui.log.start_scan",
                  t=target, bs=fmt_bytes(bs), n=len(segments),
                  kind=tr("gui.log.kind_region") if quick
                  else tr("gui.log.kind_segment"), fio=fio)
        core.log_event("scan: start target=%s bs=%s segments=%d quick=%s "
                       "engine=%s direct=%s fio=%s"
                       % (target, fmt_bytes(bs), len(segments), quick,
                          engine_val or "auto", direct_val, fio))

    def _run_worker(self, target, bs, segments, size, quick=False,
                    engine=None, direct=True):
        try:
            self.scanner.run(
                target, bs, segments,
                ioengine=engine,
                direct=direct,
                total_size=size,
                yellow_mult=3.0,
                on_event=self._post,
                quick=quick)
        except Exception as e:
            core.log_exception("scan: worker thread crashed", e)
            self.q.put({"type": "failed", "message": "%s: %s" % (type(e).__name__, e)})
        finally:
            self.q.put({"type": "worker_done"})

    def _post(self, ev):
        self.q.put(ev)

    def _stop_scan(self):
        if self.scanner:
            self.scanner.stop()
            self._set_state("gui.state_stopping")
            self._log("warn", "gui.log.stop_requested")
            core.log_event("scan: stop requested by user")

    def closeEvent(self, ev):
        if self.scanner and self.worker and self.worker.is_alive():
            if not self._ask_yes(tr("gui.msg.exit_title"),
                                 tr("gui.msg.exit_scanning")):
                ev.ignore()
                return
            self.scanner.stop()
            core.log_event("scan: stopped because the app window is closing")
        self._cancel_timers()
        core.log_event("gui: exit")
        ev.accept()

    def _on_close(self):
        """兼容旧名的关闭入口（closeEvent 调用同名逻辑）"""
        if self.scanner and self.worker and self.worker.is_alive():
            if not self._ask_yes(tr("gui.msg.exit_title"),
                                 tr("gui.msg.exit_scanning")):
                return
            self.scanner.stop()
            core.log_event("scan: stopped because the app window is closing")
        self._cancel_timers()
        core.log_event("gui: exit")
        self.close()

    def _on_parent_died(self):
        """父进程（onefile bootloader）被外部杀死时的退出路径。

        任务管理器结束上面那个同名进程（bootloader）时，本进程与 fio
        不会跟着退（Job Object 只覆盖"本进程死"的方向），会变孤儿继续
        把整盘读完。父进程句柄等待发现父死后：同步终止 fio 并立即退出。
        配置均为即时保存，无需走优雅退出；退出码 3 仅供日志辨识。
        """
        core.log_event("gui: parent bootloader died; killing fio and exiting",
                       level="WARN")
        try:
            if self.scanner:
                self.scanner.kill_fio_now()
        except Exception:
            pass
        os._exit(3)

    # ---------------------------------------------------------- 网格（固定格数 · 按字节范围聚合）
    def _reset_map(self, seg_meta, total_size=None):
        """按固定格数重建热力图（UI 一致性：任何扫描都是 MAP_CELLS 格、
        同一套平铺布局，不随容量/分段方式变化）。

        格按全盘字节范围均分（第 i 格覆盖 [total*i/N, total*(i+1)/N)），
        段统计按覆盖的字节范围聚合进格：
          - 段少格多（如 8MB 盘 2 段）：一段覆盖多格，每格都计入该段；
          - 段多格少（如 1TB 盘 4G 分段 233 段）：一格含多段，按块数
            加权求中位数（weighted_median），max 取各段最大值。
        容量未知时无位置信息：单段 [(0, None)] 广播到所有格，悬停显示
        "容量未知"——此时热力图只表达整盘聚合，不代表盘内分布。
        快速扫描按区域跨度点亮（seg_meta 第三元素）：区头 16MB 抽样的
        结果覆盖整个区域，否则未抽样格会永久灰色（见下方 seg_cells）。
        """
        self.seg_meta = list(seg_meta) if seg_meta else []
        self.n_cells = MAP_CELLS
        w = max(100, self.map_widget.width())
        h = max(100, self.map_widget.height())
        total = total_size if total_size else self.total_size
        pitch, cols, rows, ox, oy = plan_grid(w, h, self.n_cells)
        self._map_wh = (w, h)       # 记录本次布局的画布尺寸（resizeEvent 去重）
        self.cell_pitch = pitch
        self.grid_cols = cols
        self.grid_rows = rows
        self.grid_ox = ox
        self.grid_oy = oy
        cell = max(CELL_SIZE_MIN, int(pitch) - CELL_GAP)
        self.cells = []
        self.cell_span = []
        for i in range(self.n_cells):
            self.cells.append({"median": None, "max": None, "n": 0,
                               "errors": 0, "parts": []})
            a = total * i // self.n_cells if total else None
            b = total * (i + 1) // self.n_cells if total else None
            self.cell_span.append((a, b))
        # 段 → 覆盖的格（字节重叠）；容量未知（total 为空）→ 广播到所有格。
        # 快速扫描按"区域跨度"点亮而非抽样大小：抽样只有 16MB，若只点亮
        # 样本覆盖的格，931GB 盘 117 个区域只有约 117/256 格有数据、其余
        # 永久灰（用户反馈"有的块保持灰色"）。区域才是快速扫描的取样单位
        # （旧版一格=一区域即此语义）：整区用区头抽样结果上色，悬停注明
        # 抽样量与区域跨度。全段扫描第三元素为 None，按段大小点亮。
        self.seg_cells = []
        self.cell_region = [None] * self.n_cells
        for i, (off, sz, span) in enumerate(self.seg_meta):
            eff = span if span else sz
            rng = seg_cell_span(off, eff, total, self.n_cells)
            cells = (list(range(self.n_cells)) if rng is None
                     else list(range(rng[0], rng[1] + 1)))
            self.seg_cells.append(cells)
            for c in cells:      # 格 → 供数段（边界格被多段覆盖时取最先的）
                if self.cell_region[c] is None:
                    self.cell_region[c] = i
        self.dirty.clear()
        self._painted = [None] * self.n_cells
        self.map_widget.update()

    def _on_map_resize(self):
        """地图部件尺寸变化（窗口缩放/最大化/DPI 变化/语言重建后重映射）：
        拖拽缩放会连续触发，用 50ms 防抖合并成一次重排。"""
        self._resize_timer.start()

    def _flush_map_configure(self):
        self._relayout_map()

    def _relayout_map(self):
        """按当前地图部件尺寸重排热力图格子（窗口缩放自适应）。

        只更新网格参数（cell_pitch/grid_cols/grid_rows/grid_ox/grid_oy），
        格子的统计数据、颜色、错误数全部不动——缩放是纯几何变化。
        无格子（未扫描）或尺寸没变时直接返回。
        """
        if not self.cells:
            return
        w = max(100, self.map_widget.width())
        h = max(100, self.map_widget.height())
        if self._map_wh == (w, h):
            return
        self._map_wh = (w, h)
        pitch, cols, rows, ox, oy = plan_grid(w, h, self.n_cells or MAP_CELLS)
        self.cell_pitch = pitch
        self.grid_cols = cols
        self.grid_rows = rows
        self.grid_ox = ox
        self.grid_oy = oy
        self.map_widget.update()

    def _update_map_title(self):
        """热力图标题随模式切换（GroupBox 文本）"""
        key = ("gui.map_title_health" if self.map_mode == MAP_MODE_HEALTH
               else "gui.map_title_speed")
        self.map_frame.setTitle(tr(key, n=MAP_CELLS))

    def _layout_legend(self):
        """图例按模式显隐重排：健康模式只留 绿(正常)/红(错误)/灰(未扫描)，
        速度模式 绿(快)/黄(偏慢)/红(错误)/灰(未扫描)。

        灰色两种模式都保留：未扫描/未抽样不是健康或速度判定，藏掉灰色
        会把"还没扫到"误读成"正常"。下标对应创建顺序
        0=ok 1=slow 2=error 3=pending（_legend_swatches/_legend_labels）。
        先全部收起再按需显示——否则从速度模式切回健康时"偏慢"会残留。
        """
        for swatch, lbl in zip(self._legend_swatches,
                               (l for l, _k in self._legend_labels)):
            swatch.hide()
            lbl.hide()
        order = ((0, 2, 3) if self.map_mode == MAP_MODE_HEALTH
                 else (0, 1, 2, 3))
        for i in order:
            self._legend_swatches[i].show()
            self._legend_labels[i][0].show()

    def _on_map_mode_toggle(self, _ev=None, redraw=True):
        """切换热力图模式（健康 ↔ 读取速度）：标题与图例即时更新，
        格子按新模式重新逐格上色（_queue_recolor → _flush_cells，
        一次只亮一格，与扫描推进的渲染方式一致）。

        redraw=False 供界面重建（_rebuild_ui）用：彼时地图还是新部件、
        数据未恢复，重排无意义；随后的地图数据恢复会按新模式即刻整幅
        上色（界面重建不是扫描渲染，不走逐格队列）。
        """
        idx = self.combo_map_mode.currentIndex()
        self.map_mode = idx if idx >= 0 else MAP_MODE_HEALTH
        if self.map_mode < 0:      # 防御：选择被清空时回到健康模式
            self.map_mode = MAP_MODE_HEALTH
            self.combo_map_mode.setCurrentIndex(MAP_MODE_HEALTH)
        self._update_map_title()
        self._layout_legend()
        if not redraw or not self.cells:
            return
        self._queue_recolor()

    def _queue_recolor(self):
        """把"当前模式/阈值下颜色会变"的格入待渲染队列（逐格上色）。

        用于扫描完成（最终阈值就位）与模式切换：不变色的格不进队列，
        避免无谓的重排延迟；入队后由 _flush_cells 逐格渲染。
        """
        for i in range(len(self.cells)):
            if i >= len(self._painted):
                continue
            want = self._cell_color(i)
            if self._painted[i] != want:
                self.dirty.add(i)

    def _add_seg_stat(self, cell_idx, ev):
        """把一段的统计聚合进格：parts 累积 (median, max, n_blocks)，格中位数
        按块数加权、max 取最大、块数求和。一段跨多格时每格都计入该段。"""
        if not (0 <= cell_idx < len(self.cells)):
            return
        med, mx = ev.get("median_us"), ev.get("max_us")
        n = ev.get("n_blocks") or 0
        if med is None or n <= 0:
            return
        c = self.cells[cell_idx]
        c["parts"].append((med, mx, n))
        c["n"] = sum(p[2] for p in c["parts"])
        c["median"] = weighted_median([(p[0], p[2]) for p in c["parts"]])
        maxes = [p[1] for p in c["parts"] if p[1] is not None]
        c["max"] = max(maxes) if maxes else None
        self.dirty.add(cell_idx)

    def _cell_color(self, idx):
        """格子填充色（双模式，见 MAP_MODE_* 注释）：
        - 读取错误：两种模式都是红（最高优先级，盖过延迟颜色）；
        - 健康模式：无错误即绿——读得慢但不是错误，健康判定只有绿/红；
        - 速度模式：延迟超当前阈值→黄，否则→绿；
        - 无数据（未扫描/未抽样）：两种模式都是灰——不是判定结果。
        """
        c = self.cells[idx]
        if c["errors"] > 0:
            return COLOR_ERROR
        if c["median"] is None:
            return COLOR_PENDING
        if self.map_mode == MAP_MODE_HEALTH:
            return COLOR_OK
        return COLOR_SLOW if c["median"] > self.thresholds else COLOR_OK

    def _flush_cells(self, force=False):
        """逐格渲染热力图：每次调用最多上色一格。

        用户要求"一个一个渲染，不要一次渲染多个"：一段跨多格（如 4G 段在
        1TB 盘上覆盖 1-2 格）或多段在同一拍完成时，格子按索引顺序
        （左→右、上→下，即扫描推进方向）逐格点亮，形成随扫描前进的填充
        效果，而不是整批同时变色。

        节流随待渲染数量自适应：段间自然节奏（积压 ≤2 格）约 120ms 一格，
        肉眼就是逐格点亮；大批积压（快速扫描/整盘一次/小盘大段）时约
        25ms 一格追赶扫描进度（256 格约 6.4s 排干），避免扫描结束了地图
        还在慢慢填。轮询周期同步自适应，见 _poll_queue。
        """
        now = time.time()
        interval = 0.12 if len(self.dirty) <= 2 else 0.025
        if not force and now - self._last_flush < interval:
            return
        self._last_flush = now
        if not self.dirty:
            return
        # 周期性用全体格中位数重算 provisional 阈值（速度模式用；
        # 健康模式不按延迟判定，算了也不用，无害且模式随时可切）
        if now - self._last_thresh_calc > 0.5:
            self._last_thresh_calc = now
            meds = [c["median"] for c in self.cells if c["median"] is not None]
            if meds:
                med = statistics.median(meds)
                self.thresholds = max(med * 3.0, 10000.0)
        idx = min(self.dirty)      # 索引顺序：铺格顺序即扫描推进方向
        self.dirty.discard(idx)
        if idx < len(self._painted):
            self._painted[idx] = self._cell_color(idx)
        # Qt 侧只发一次重绘请求（paintEvent 按当前数据统一取色），
        # 等价于 ttk 版的 itemconfig(fill=...)
        self.map_widget.update()

    # ---------------------------------------------------------- 事件处理
    def _poll_queue(self):
        # 窗口已销毁（如提权重启路径 _exit_now）时定时器已停
        # （closeEvent/_cancel_timers），不会再有回调进来
        n = 0
        try:
            while n < 4000:
                ev = self.q.get_nowait()
                n += 1
                self._handle_event(ev)
        except queue.Empty:
            pass
        self._flush_cells()
        # 逐格渲染的速率上限由轮询周期决定：待渲染格子多时加快轮询
        # （25ms → 40 格/s，256 格约 6.4s 排干），没有积压时回到 100ms
        self._poll_timer.start(25 if len(self.dirty) > 2 else 100)

    def _mark_error_block(self, blk_idx, bs=None, total=None):
        """错误块计入热力图：按块起始字节精确落到格（格按字节范围均分，
        比旧实现按段二分更准——段边界与格边界不再重合）。同一块只计一次：
        扫描中 live error_block 事件与 finished 汇总会各带一遍（旧实现重复
        计数只是碰巧不影响颜色；现在悬停要显示错误数，必须去重）。
        容量未知时无位置信息：广播到所有格（与统计广播一致，整盘聚合显示）。
        """
        if not self.cells or blk_idx in self._err_seen:
            return
        self._err_seen.add(blk_idx)
        bs = bs or self.scan_bs
        total = total if total else self.total_size
        cell = block_cell_index(blk_idx, bs, total, self.n_cells)
        if cell is None:                      # 容量未知：广播到所有格
            for c in self.cells:
                c["errors"] += 1
            self.dirty.update(range(len(self.cells)))
            return
        self.cells[cell]["errors"] += 1
        self.dirty.add(cell)

    def _handle_event(self, ev):
        et = ev.get("type")
        if et == "seg_stat":
            # 一段读完：段级统计按覆盖范围聚合进各格（一格可含多段，
            # 加权中位数见 _add_seg_stat；一段也可覆盖多格）
            idx = ev.get("index", 0)
            if 0 <= idx < len(self.seg_cells):
                for c in self.seg_cells[idx]:
                    self._add_seg_stat(c, ev)
        elif et == "error_block":
            self._mark_error_block(ev["index"])
        elif et == "tick":
            self._on_tick(ev)
        elif et == "segment":
            sz_txt = ""
            if ev["size"]:
                sz_txt = tr("gui.log.segment_size", sz=fmt_bytes(ev["size"]))
                if self.scan_quick:
                    sz_txt += tr("gui.log.segment_sampled")
            else:
                sz_txt = tr("gui.log.segment_to_end")
            self._log("info", "gui.log.segment",
                      i=ev["index"] + 1, n=ev["total"],
                      off=fmt_bytes(ev["offset"]), extra=sz_txt)
        elif et == "log":
            if ev.get("stream") in ("stderr", "cmd"):
                # fio 原始输出（英文技术文本）不过 i18n，直接插入
                self._log_raw(ev["stream"], ev["line"])
        elif et == "finished":
            self._on_finished(ev["summary"])
        elif et == "failed":
            self._on_failed(ev["message"])
        elif et == "worker_done":
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.worker = None
            if self.scan_start_ts and not self.summary:
                self._set_state("gui.state_stopped")

    def _set_progress_indeterminate(self):
        """Qt 的不确定进度：量程设为 0（0-0）即进入忙碌动画"""
        self._progress_indeterminate = True
        self.progress.setRange(0, 0)
        self.progress.reset()

    def _set_progress_determinate(self):
        self._progress_indeterminate = False
        self.progress.setRange(0, 100)

    def _on_tick(self, ev):
        seg = ev.get("segment") or 0
        base = self.seg_base[seg] if seg < len(self.seg_base) else 0
        done = base + (ev.get("io_bytes") or 0)
        bw = ev.get("bw_bytes")
        # 快速扫描按计划读取量（抽样总量）算进度/ETA，避免按整盘容量
        # 显示误导性的"剩余十几分钟"
        total = (self.planned_bytes
                 if (self.scan_quick and self.planned_bytes) else self.total_size)
        if total:
            pct = min(100.0, done * 100.0 / total)
            self._set_progress_determinate()
            self.progress.setValue(int(pct))
            self.lbl_progress.setText(tr("gui.progress_pct", pct=pct))
            if bw and done < total:
                self.lbl_eta.setText(tr("gui.eta_fmt", v=fmt_duration(
                    (total - done) / float(bw))))
        elif ev.get("pct") is not None:
            self._set_progress_determinate()
            self.progress.setValue(int(ev["pct"]))
            self.lbl_progress.setText(tr("gui.progress_pct", pct=ev["pct"]))
        else:
            self._set_progress_indeterminate()
            self.lbl_progress.setText(tr("gui.progress_read",
                                         sz=fmt_bytes(done)))
        self.lbl_speed.setText(tr("gui.speed_fmt", v=fmt_speed(bw)))
        if self.scan_start_ts:
            self.lbl_elapsed.setText(tr("gui.elapsed_fmt", v=fmt_duration(
                time.time() - self.scan_start_ts)))
        if ev.get("errors"):
            # fio 的 error 字段是 errno 码而非计数
            code = int(ev["errors"])
            self.lbl_errors.setText(
                tr("gui.errors_code", name=errno_name(code), code=code))
            self._set_label_level(self.lbl_errors, "error")
        elif ev.get("errors") == 0:
            self.lbl_errors.setText(tr("gui.errors_none"))
            self._set_label_level(self.lbl_errors, "ok")

    def _set_label_level(self, label, level):
        """给标签上"语义级别色"（ok/error/warn/info）：与主题无关的
        饱和底色 + 白字，两套 QSS 下通用。"""
        bg, fg = BANNER_STYLE.get(level, BANNER_STYLE["info"])
        label.setStyleSheet(
            "background: %s; color: %s; border-radius: 3px; padding: 2px 8px;"
            % (bg, fg))

    def _on_finished(self, s):
        self.summary = s
        self._set_progress_determinate()
        self.progress.setValue(100)
        self.thresholds = s["slow_thr_us"]
        # 错误块计入热力图单元格（按字节偏移精确到格；live 事件已计过
        # 的块在这里去重，不重复计数）
        total = s.get("total_size") or self.total_size
        for idx in s["error_blocks"]:
            self._mark_error_block(idx, s.get("bs"), total)
        # 最终阈值就位：只把颜色会变的格入队，逐格渲染（一次一格）
        self._queue_recolor()
        self._render_result_ui(s)
        core.log_event(
            "scan: finished target=%s blocks=%d ok=%d slow=%d "
            "errors=%d aborted=%s stopped=%s elapsed=%.1fs"
            % (s["target"], s["n_blocks"], s["ok"], s["slow"],
               len(s["error_blocks"]), s["aborted"],
               bool(s.get("stop_requested")), s["elapsed_s"]))

    def _redraw_cells(self):
        """用当前模式与阈值全量重绘热力图（界面重建/主题切换等非扫描
        渲染路径。扫描推进、扫描完成与模式切换走逐格队列，见
        _flush_cells 与 _queue_recolor）"""
        for i in range(len(self.cells)):
            if i < len(self._painted):
                self._painted[i] = self._cell_color(i)
        self.map_widget.update()

    def _render_result_ui(self, s):
        """渲染已完成扫描的结果区（状态行/导出按钮/错误树/汇总页/横幅）。

        只写文案与控件状态、不改 cells 数据——切换语言重建界面时用
        同一份 summary 重放（错误块已计入格子，不能重复加）。
        """
        self.lbl_progress.setText(tr("gui.progress_pct", pct=100.0))
        self.lbl_speed.setText(tr("gui.speed"))
        self.lbl_elapsed.setText(tr("gui.elapsed_fmt",
                                    v=fmt_duration(s["elapsed_s"])))
        self.lbl_eta.setText(tr("gui.eta_fmt", v="00:00"))
        if s["last_errno"]:
            self.lbl_errors.setText(
                tr("gui.errors_code",
                   name=s["last_errno_name"] or tr("unknown"),
                   code=s["last_errno"]))
            self._set_label_level(self.lbl_errors, "error")
        else:
            self.lbl_errors.setText(tr("gui.errors_none"))
            self._set_label_level(self.lbl_errors, "ok")
        self._set_state("gui.state_done_aborted" if s["aborted"]
                        else "gui.state_done")
        self.btn_export.setEnabled(True)

        self._render_error_tree()
        self._render_summary()
        self.nb.setCurrentWidget(self.txt_summary)

        # 结果以界面横幅展示，不弹窗：
        # - 主动停止造成的不完整绝不是坏道；停止前发现的错误只提示
        # - 完整扫描的真实错误才升级为 error 级横幅
        stopped = bool(s["aborted"] or s.get("stop_requested"))
        has_err = bool(s["error_blocks"] or s["errno_segments"])
        if has_err and not stopped:
            self._banner("gui.banner.errors", "error",
                         n=len(s["error_blocks"]), es=s["errno_segments"])
        elif has_err and stopped:
            self._banner("gui.banner.stopped_with_errors", "warn",
                         n=len(s["error_blocks"]), es=s["errno_segments"])
        else:
            self._banner("gui.banner.clean", "ok",
                         ok=s["ok"], n=s["n_blocks"], slow=s["slow"],
                         err=len(s["error_blocks"]))

    def _on_failed(self, msg):
        self._set_state("gui.state_failed")
        self._log_raw("error", msg)
        core.log_event("scan: failed: %s" % msg, level="ERROR")
        self._banner("gui.banner.failed", "error", msg=msg)

    def _render_error_tree(self):
        self.tree_err.clear()
        if not self.summary:
            return
        s = self.summary
        for idx in sorted(s["error_blocks"]):
            QTreeWidgetItem(self.tree_err,
                            [str(idx), fmt_bytes(idx * s["bs"]),
                             s["error_blocks"][idx][:120]])

    def _render_summary(self):
        self.txt_summary.clear()
        if not self.summary:
            return
        s = self.summary
        slow_thr = s["slow_thr_us"]
        lines = []
        lines.append(tr("gui.sum.target", t=s["target"]))
        lines.append(tr("gui.sum.bs", bs=fmt_bytes(s["bs"]), n=s["n_blocks"]))
        lines.append(tr("gui.sum.ioengine", e=s["ioengine"], d=s["direct"]))
        lines.append(tr("gui.sum.capacity", sz=fmt_bytes(s["total_size"])))
        if s.get("quick"):
            covered = sum((seg["size"] or 0) for seg in s["segments"])
            cov_pct = covered * 100.0 / s["total_size"] if s["total_size"] else 0.0
            lines.append(tr("gui.sum.mode_quick", n=len(s["segments"]),
                            cov=fmt_bytes(covered), pct=cov_pct))
        if s.get("stop_requested"):
            lines.append(tr("gui.sum.state_stopped"))
        lines.append(tr("gui.sum.elapsed", d=fmt_duration(s["elapsed_s"])))
        lines.append("")
        lines.append(tr("gui.sum.ok", n=s["ok"]))
        lines.append(tr("gui.sum.slow", n=s["slow"], thr=slow_thr / 1000.0))
        lines.append(tr("gui.sum.read_errors", n=len(s["error_blocks"]),
                        es=s["errno_segments"], ul=s["unlocated_errors"]))
        if s["last_errno"]:
            lines.append(tr("gui.sum.fio_errno", code=s["last_errno"],
                            name=s["last_errno_name"]))
        if s["unscanned_bytes"]:
            if s["aborted"]:
                lines.append(tr("gui.sum.unscanned_stopped",
                                sz=fmt_bytes(s["unscanned_bytes"])))
            else:
                lines.append(tr("gui.sum.uncovered",
                                sz=fmt_bytes(s["unscanned_bytes"])))
        if s.get("unread_tail_bytes"):
            lines.append(tr("gui.sum.unread_tail",
                            sz=fmt_bytes(s["unread_tail_bytes"])))
        lines.append("")
        lines.append(tr("gui.sum.median", v=s["median_us"] / 1000.0))
        lines.append(tr("gui.sum.mean", v=s["mean_us"] / 1000.0))
        lines.append(tr("gui.sum.p99", v=s["p99_us"] / 1000.0))
        lines.append(tr("gui.sum.max", v=s["max_us"] / 1000.0))
        if s["aborted"]:
            lines.append("")
            lines.append(tr("gui.sum.aborted_note"))
        lines.append("")
        lines.append(tr("gui.sum.threshold_note"))
        self.txt_summary.setPlainText("\n".join(lines))

    def _export_report(self):
        if not self.summary:
            return
        d = QFileDialog.getExistingDirectory(self, tr("gui.export"))
        if not d:
            return
        outdir = os.path.join(d, "HD_Doc_report_%s"
                              % datetime.now().strftime("%Y%m%d_%H%M%S"))
        files = write_reports(outdir, self.summary)
        self._log("info", "gui.log.exported", d=outdir)
        core.log_event("report: exported to %s (%d file(s))"
                       % (outdir, len(files)))
        self._banner("gui.log.exported", "ok", d=outdir)

    def _update_status(self, pct, bw, eta_s, errors):
        self.lbl_progress.setText(tr("gui.progress_pct", pct=pct))
        self.lbl_speed.setText(tr("gui.speed_fmt", v=fmt_speed(bw)))
        self.lbl_eta.setText(tr("gui.eta_fmt", v=fmt_duration(eta_s)))
        self.lbl_errors.setText(tr("gui.errors", n=errors))

    # ---------------------------------------------------------- 悬停提示
    def _on_map_hover(self, x, y):
        """鼠标在地图上的悬停信息（None, None = 离开地图）"""
        if x is None or not self.cells:
            self.lbl_hover.setText("")
            return
        c = int((x - self.grid_ox) // self.cell_pitch)
        r = int((y - self.grid_oy) // self.cell_pitch)
        if c < 0 or r < 0 or c >= self.grid_cols or r >= self.grid_rows:
            self.lbl_hover.setText("")
            return
        idx = r * self.grid_cols + c
        if idx >= len(self.cells):
            self.lbl_hover.setText("")
            return
        cell = self.cells[idx]
        a, b = (self.cell_span[idx]
                if idx < len(self.cell_span) else (None, None))
        if a is None or b is None:
            # 容量未知：无位置信息，热力图只显示整盘聚合
            txt = tr("gui.hover_cell_unknown", i=idx + 1, n=self.n_cells)
        else:
            txt = tr("gui.hover_cell", i=idx + 1, n=self.n_cells,
                     a=fmt_bytes(a), b=fmt_bytes(b))
        bs = self.scan_bs or (self.summary or {}).get("bs") or 0
        if self.scan_quick:
            # 快速扫描：格子颜色来自所在区域开头的抽样（整区点亮，见
            # _reset_map）——悬停注明抽样量与区域跨度，避免误以为
            # 整区都逐块读过；区域未抽样（停止过早/无数据）时明确标注
            if cell["median"] is not None:
                src = (self.cell_region[idx]
                       if idx < len(self.cell_region) else None)
                if src is not None and src < len(self.seg_meta):
                    _off, sample, region = self.seg_meta[src]
                    txt += tr("gui.hover_region_src",
                              sz=fmt_bytes(sample or 0),
                              rg=fmt_bytes(region) if region else "?")
                else:
                    txt += tr("gui.hover_sampled", sz=fmt_bytes(cell["n"] * bs))
            else:
                txt += tr("gui.hover_not_sampled")
        blk_start = (a // bs) if (a is not None and bs) else 0
        txt += tr("gui.hover_blocks", b=blk_start, n=cell["n"], e=cell["errors"])
        if cell["median"] is not None:
            txt += tr("gui.hover_median", v=cell["median"] / 1000.0)
            if cell["max"] is not None:
                txt += tr("gui.hover_max", v=cell["max"] / 1000.0)
        self.lbl_hover.setText(txt)


def _app_font():
    """全局 UI 字体：跟随系统默认（Qt 在各平台选本平台 UI 字体：
    Windows Segoe UI、Linux/麒麟 Noto Sans CJK 等），只统一点阵大小，
    不写死字体名——不同系统都有本平台原生观感（与 ttkbootstrap 的
    set_global_family("Segoe UI") 效果等价但不强制字体存在）。"""
    f = QApplication.instance().font()
    f.setPointSize(9)
    return f


def run():
    """GUI 运行入口（供入口/测试共用）：创建 QApplication 与主窗口并
    进入事件循环。单实例保护：QApplication 只允许一个，重复调用返回
    已有实例。"""
    app = QApplication.instance()
    created = False
    if app is None:
        # 高分屏：Qt5 需要在 QApplication 构造前打开缩放属性
        for attr in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
            if hasattr(Qt, attr):
                QApplication.setAttribute(getattr(Qt, attr))
        app = QApplication(sys.argv)
        created = True
    app.setApplicationName("HD_Doc")
    app.setApplicationDisplayName(tr("gui.title", ver=VERSION))
    # X11/Wayland 下把运行中的窗口匹配到 hd-doc.desktop（图标归属）
    app.setDesktopFileName("hd-doc")
    win = HDDocApp()
    win.show()
    if created:
        return app.exec_()
    return 0
