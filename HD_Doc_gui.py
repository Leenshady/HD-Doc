#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HD_Doc_gui.py —— GUI 模式（ttkbootstrap；只依赖 HD_Doc_core）

本模块只在 GUI 模式下被入口 HD_Doc.py 导入；
没有 ttkbootstrap 的环境（如 --cli 命令行模式）永远不会加载本模块。

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

界面主题：ttkbootstrap 主题（默认浅色 bootstrap-light，可切换深色
bootstrap-dark），选择同样持久化；切换主题 = 保存偏好 + 实时
theme_use() 换色（ttk 控件由主题引擎自动重绘，少数原生 tk 控件
手工同步），同样不重启进程。所有控件颜色取自当前主题
（style.colors），不写死十六进制色值，深浅两主题通用。
"""

import os
import queue
import statistics
import sys
import threading
import time
from datetime import datetime

import ttkbootstrap as ttk
from ttkbootstrap.dialogs import Messagebox
import tkinter as tk
from tkinter import filedialog

import HD_Doc_core as core                      # 业务逻辑全部经 core
from HD_Doc_core import *                       # 常用名直接可用（调用点不变）
from HD_Doc_core import _pythonw_path           # 下划线名需显式导入

# 横幅级别 → ttkbootstrap bootstyle（颜色随主题自动切换：浅色/深色通用）
BANNER_BOOTSTYLE = {"info": "info", "ok": "success",
                    "warn": "warning", "error": "danger"}

# 状态行语义键 → bootstyle（_set_state 用；切换语言重建界面时按键重放）
STATE_BOOTSTYLE = {"gui.state_ready": "secondary",
                   "gui.state_scanning": "info",
                   "gui.state_stopping": "warning",
                   "gui.state_stopped": "secondary",
                   "gui.state_done": "success",
                   "gui.state_done_aborted": "success",
                   "gui.state_failed": "danger"}

# 热力图双模式（下拉选项顺序即下标语义，跨语言稳定）：
#   健康模式——只按"有没有读取错误"判定：绿=正常、红=读取错误
#     （HD Tune 错误扫描同语义；读得慢但不是错误，健康判定只有两色）；
#   速度模式——按读取延迟判定：绿=快、黄=偏慢、红=读取错误。
# 两种模式共用灰色表示"未扫描/未抽样"——无数据不是健康/速度判定，
# 不显示灰色会把未扫区域误读成"健康"。
MAP_MODE_HEALTH = 0
MAP_MODE_SPEED = 1


def _resource_dir():
    """img/ 资源目录：打包版在 sys._MEIPASS，源码版在脚本同级"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "img")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")


# 弹窗内图标上限（原图可能是 1248px 的大图，直接放会把对话框撑爆）
ABOUT_ICON_PX = 48


def _bounded_photo(img, max_px=ABOUT_ICON_PX):
    """PhotoImage 等比缩到 max_px 以内。

    PhotoImage 只有 subsample（整数倍点采样）可用、且运行时无 PIL 依赖。
    subsample 的结果尺寸是向上取整（如 1024/21→49），所以因子必须按
    向上取整算：factor = ceil(长边/max_px)，否则原图边长不是 max_px
    整数倍时会超出上限（1024 主图按 // 算得 21 → 49px > 48）。
    原图任一边已不超上限时原样返回（避免多余拷贝）。
    """
    long_edge = max(img.width(), img.height())
    if long_edge <= max_px:
        return img
    factor = -(-long_edge // max_px)          # ceil 除法
    return img.subsample(factor, factor)


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
    存活），因此这里轮询约 2.5 秒：pkexec 很快退出 = 授权被取消或
    pkexec 不可用 → 保持标准权限继续启动（Ubuntu 桌面图标点击时同样
    会弹 polkit 密码框，与 Windows 的 UAC 体验一致）。
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
    popen, err = core.pkexec_gui_spawn()
    if popen is None:
        # 已是 root（err=None）或 pkexec 不可用：不阻塞启动
        print("[Elevate] pkexec unavailable (%s); starting unelevated."
              % (err or "already root"))
        core.log_event("startup: pkexec unavailable (%s)" % (err or "root"))
        return False
    core.log_event("startup: pkexec elevation requested (pid=%s)" % popen.pid)
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline and popen.poll() is None:
        time.sleep(0.1)
    if popen.poll() is None:
        # 授权进行中或提权实例已启动：本进程退出，让提权实例接管
        print("[Elevate] Authorization in progress / elevated instance started;"
              " exiting this process.")
        return True
    code = popen.returncode
    print("[Elevate] pkexec exited with %s (authorization cancelled or failed);"
          " continuing unelevated." % code)
    core.log_event("startup: pkexec exited rc=%s; continuing unelevated" % code)
    return False


class HDDocApp(ttk.Window):
    def __init__(self):
        # 主题来自持久化偏好（见 HD_Doc_core 的 get_theme/set_theme）
        # className="HD_Doc"：设置 WM_CLASS 的 res_class，GNOME/KDE 据此把
        # 运行中的窗口匹配到 .desktop 文件（配合 StartupWMClass），否则程序
        # 坞里会显示默认的齿轮状兜底图标而不是应用图标（用户反馈）
        super().__init__(themename=get_theme(), className="HD_Doc")
        self.withdraw()               # 构建期不显示，避免默认位置闪一下
        self.title(tr("gui.title", ver=VERSION))
        self.geometry("1140x820")
        self.minsize(980, 700)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._target_paths = {}       # 下拉标签 → 裸设备路径（型号显示用）
        self._icon_img = None         # PhotoImage 引用，防止被 GC
        self._about_icon = None       # 弹窗内小图标（_bounded_photo 缩放版）
        # pkexec 提权轮询（Linux）：_relaunch_elevated 发起后用 after 链
        # 观察子进程存活——授权取消/失败时 pkexec 很快退出，此时必须保留
        # 本窗口并提示，不能像旧版那样 200ms 后无条件退出（表现为"闪退"）
        self._pkexec_popen = None
        self._pkexec_polls = 0

        self.q = queue.Queue()
        self.scanner = None
        self.worker = None
        self.cells = []
        self.cell_items = []
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
        self._map_cfg_after = None  # 挂起的 <Configure> 防抖回调（退出时取消）
        self._err_seen = set()      # 已计入热力图的错误块（事件/汇总去重）
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
        self.var_lang = tk.StringVar(value=get_language())
        self.var_theme = tk.StringVar(value=get_theme())

        # 热力图模式（健康/读取速度）：_build_ui 建下拉前就绪，
        # 切换语言重建界面时按快照下标恢复（见 _rebuild_ui）
        self.map_mode = MAP_MODE_HEALTH

        self._setup_theme()
        self._set_window_icon()
        self._build_ui()
        self._refresh_drives()
        self._center_on_screen()
        self._poll_after = self.after(100, self._poll_queue)
        self._admin_after = self.after(200, self._startup_admin_check)
        # Tk 回调里未捕获的异常默认只打印到 stderr（打包版没有控制台 →
        # 用户什么都看不到）：统一落到运行日志，便于事后排查
        self.report_callback_exception = self._on_tk_exception
        core.log_event("gui: start ver=%s frozen=%s admin=%s lang=%s theme=%s"
                       % (VERSION, getattr(sys, "frozen", False), is_admin(),
                          get_language(), get_theme()))

    # ---------------------------------------------------------- 主题与图标
    def _setup_theme(self):
        """ttkbootstrap 主题定制（主题本身在 Window 构造时按 get_theme()
        选定；切换主题走 theme_use() 实时换色，这里只做一次性微调，
        颜色不写死）。

        - set_global_family：全局字体走系统 UI 字体（Windows 即 Segoe UI，
          非 Windows 自动回退），与 clam 时代的硬编码效果一致；
        - Treeview 行高/表头内边距：主题默认偏挤，错误块表格需要呼吸感。
        （幂等：切换主题后也会再调一次，保证定制不被主题默认值覆盖。）
        """
        try:
            ttk.set_global_family("Segoe UI")
        except Exception:
            pass
        style = self.style
        style.configure("Treeview", rowheight=26)
        style.configure("Treeview.Heading", padding=(6, 4))

    def _set_window_icon(self):
        """标题栏 + 任务栏/Alt-Tab 图标（.png，经 iconphoto）。

        注意：iconbitmap(.ico) 只是兜底——Tk 的 Windows 端口渲染不了 PNG
        压缩的 .ico（静默无效果，表现为标题栏图标空白），真正生效的是
        随后 iconphoto 设置的那个 PNG（标题栏与任务栏都归它管）。
        资源缺失时两者都静默跳过。"""
        d = _resource_dir()
        try:
            self.iconbitmap(os.path.join(d, "HD_Doc.ico"))
        except Exception:
            pass
        try:
            # master=self 必须显式指定：默认 photo 会挂到第一个 Tk 实例上，
            # 而 iconphoto 在本窗口调用时拒绝跨实例的 photo（TclError）
            img = tk.PhotoImage(master=self, file=os.path.join(d, "HD_Doc.png"))
            self.iconphoto(False, img)
            self._icon_img = img      # 持有引用，防止被垃圾回收
            # 弹窗里另存一份缩放版：原图 1248px，直接显示会撑爆对话框
            try:
                self._about_icon = _bounded_photo(img)
            except Exception:
                self._about_icon = img
        except Exception:
            pass

    # ---------------------------------------------------------- 文案辅助
    # 文案全部经 tr() 取当前语言：切换语言会重建界面（_rebuild_ui），
    # 各构建函数重新执行即拿到新语言文案
    def _center_on_screen(self):
        """启动时把窗口居中放到屏幕中间，并一次性显示（无位置闪烁）。

        要点：未映射时发出的几何请求会被窗口管理器丢弃（实测位置/尺寸
        都被改写），所以先 update() 让布局就绪，再用一个请求同时指定
        尺寸与位置；构建期窗口是 withdraw 状态，deiconify 时按请求位置
        直接出现，不会先在默认位置闪一下。
        """
        self.update_idletasks()
        self.update()
        w, h = 1140, 820              # 设计尺寸（与 __init__ 首行一致）
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.deiconify()

    def _reg(self, widget, key, **kw):
        """设置静态文本控件（按钮/标签）的文案"""
        widget.config(text=tr(key, **kw))
        return widget

    def _reg_values(self, widget, key):
        """设置下拉列表控件的选项文案"""
        widget.config(values=tr_list(key))
        return widget

    def _reg_tab(self, nb, child, key):
        nb.add(child, text=tr(key))

    def _reg_heading(self, tree, column, key):
        tree.heading(column, text=tr(key))

    def _set_state(self, key):
        """状态行文案（记录语义键：切换语言重建界面时按新语言重放）"""
        self._state_key = key
        self.lbl_state.config(text=tr(key),
                              bootstyle=STATE_BOOTSTYLE.get(key, "secondary"))
        return self.lbl_state

    def _ask_yes(self, title, message):
        """主题化的是/否确认框（替代 tkinter.messagebox）。

        按钮文案走 lang/*.json（gui.btn.yes / gui.btn.no），localize=False
        关闭 ttkbootstrap 自带的按钮本地化，返回值与当前语言解耦，
        中英文界面都能确定判断。用户关掉对话框时结果为 None → 视为否。
        """
        return Messagebox.yesno(
            message, title, parent=self,
            buttons=["%s:primary" % tr("gui.btn.yes"), tr("gui.btn.no")],
            localize=False) == tr("gui.btn.yes")

    def _set_language(self, lang):
        """切换语言：保存偏好并原地重建界面（不重启进程）。

        旧实现靠 execv 重启重载界面，扫描中只能禁止切换（重启会遗留
        fio 子进程）；现在 _rebuild_ui 只换控件与文案，扫描线程、
        fio 子进程、扫描结果都不受影响，因此扫描中也能切换。
        """
        if lang == get_language():
            self.var_lang.set(lang)
            return
        if set_language(lang):          # 写入配置 + 进程内切换
            core.log_event("pref: language -> %s" % lang)
            self.var_lang.set(lang)
            self._rebuild_ui()

    def _set_theme(self, theme):
        """切换主题（浅色/深色）：保存偏好 + 实时 theme_use()，不重启进程。

        ttk 控件由 ttkbootstrap 主题引擎自动换色；少数不走主题引擎的
        原生 tk 控件（热力图 Canvas 背景、图例色块边框）手工同步到
        新主题色板（_apply_theme_to_tk_widgets）。同样不中断扫描。
        """
        if theme == get_theme():
            self.var_theme.set(theme)
            return
        if set_theme(theme):            # 写入配置 + 进程内切换
            core.log_event("pref: theme -> %s" % theme)
            self.var_theme.set(theme)
            self.style.theme_use(theme)
            self._setup_theme()         # 行高等定制跨主题保留（幂等）
            self._apply_theme_to_tk_widgets()

    def _apply_theme_to_tk_widgets(self):
        """原生 tk 控件（不走 ttk 主题引擎）手工同步到当前主题色板：
        热力图 Canvas 背景、图例色块边框（格子填充色是语义色，与主题
        无关，不随主题切换）。"""
        colors = self.style.colors
        self.canvas_map.configure(bg=colors.bg)
        for swatch in self._legend_swatches:
            swatch.configure(highlightbackground=colors.border)

    @staticmethod
    def _bootstyle_of(widget):
        """从 ttk 样式名反推 bootstyle（'danger.TLabel' → 'danger'）；
        默认样式返回 None（ttkbootstrap 的 bootstyle 不是 Tcl 选项，
        cget('bootstyle') 会抛 unknown option，但它落实在样式名上）。

        只用于状态行标签的快照/恢复，它们只设朴素 bootstyle
        （info/success/warning/danger/secondary），前缀即完整值；
        outline 等复合样式的样式名含 'Outline' 段，不在本方法适用范围内。
        """
        name = str(widget.cget("style"))
        prefix = name.split(".")[0]
        return prefix if prefix and prefix != widget.winfo_class() else None

    # ---------------------------------------------------------- 界面重建
    def _rebuild_ui(self):
        """原地重建整个界面（切换语言用；不重启进程）。

        流程：快照当前可见状态 → 销毁全部子控件与菜单 → 重建 → 恢复。
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
            "target": self.var_target.get(),
            "bs_idx": self.combo_bs.current(),
            "engine": self.var_engine.get(),
            "direct": bool(self.var_direct.get()),
            "quick": bool(self.var_quick.get()),
            "sample_idx": self.combo_quick_sample.current(),
            "map_mode_idx": self.combo_map_mode.current(),
            "fio": self.var_fio.get(),
            "tab": self.nb.index("current"),
            "progress": self.progress["value"],
            "progress_mode": self.progress.cget("mode"),
            "status": {
                "lbl_progress": self.lbl_progress.cget("text"),
                "lbl_speed": self.lbl_speed.cget("text"),
                "lbl_elapsed": self.lbl_elapsed.cget("text"),
                "lbl_eta": self.lbl_eta.cget("text"),
                "lbl_errors": (self.lbl_errors.cget("text"),
                               self._bootstyle_of(self.lbl_errors)),
                # lbl_state 不进快照：语义键 _state_key 是普通属性，
                # 重建后直接 _set_state 重放（按新语言）
            },
            # 热力图：_reset_map 会新建 cells/cell_items，先备份数据
            # （格数固定 MAP_CELLS，重建后按段计划重算段→格映射）
            "map": (list(self.seg_meta), [dict(c) for c in self.cells],
                    self.thresholds) if self.cells else None,
        }
        # ---- 销毁（子控件 + 旧菜单；窗口本身与 after 回调不动）----
        for w in self.winfo_children():
            w.destroy()
        if getattr(self, "_menubar", None) is not None:
            try:
                self._menubar.destroy()
            except Exception:
                pass
        # ---- 重建 ----
        self._build_ui()
        self.title(tr("gui.title", ver=VERSION))   # 标题也是 i18n 文案
        self._set_state(state_key)     # 状态行按键重放（按新语言）
        # ---- 恢复 ----
        self._refresh_drives()
        self.var_target.set(snap["target"])
        if snap["bs_idx"] >= 0:
            self.combo_bs.current(snap["bs_idx"])
        self.var_engine.set(snap["engine"])
        self.var_direct.set(snap["direct"])
        self.var_quick.set(snap["quick"])
        self._on_quick_toggle()
        if snap["sample_idx"] >= 0:
            self.combo_quick_sample.current(snap["sample_idx"])
        # 热力图模式：先恢复下标与 self.map_mode（后面的热力图数据重载
        # _redraw_cells 要按新模式上色），此时不重绘（cell_items 还是旧
        # 画布的 id，地图块随后会以新 items 正确上色）
        if snap["map_mode_idx"] >= 0:
            self.combo_map_mode.current(snap["map_mode_idx"])
        self._on_map_mode_toggle(redraw=False)
        self.var_fio.set(snap["fio"])
        self._render_log()
        self._render_banner()
        self._update_admin_ui()
        if snap["map"] is not None:
            seg_meta, cells, thresholds = snap["map"]
            self._reset_map(seg_meta)             # 固定格数 + 段→格映射重算
            self.cells = [dict(c) for c in cells]   # 数据搬回新格子
            self.thresholds = thresholds
            if self.summary is not None:
                self._redraw_cells()      # 已完成：按最终阈值画
            else:
                # 扫描中：等下一次 _flush_cells 统一上色
                self.dirty = set(range(len(self.cells)))
        if self.summary is not None:
            self.progress.stop()
            self.progress.config(mode="determinate")
            self.progress["value"] = 100
            self.btn_export.config(state="normal")
            self._render_result_ui(self.summary)
        else:
            self.progress.config(mode=snap["progress_mode"])
            self.progress["value"] = snap["progress"]
            st = snap["status"]
            self.lbl_progress.config(text=st["lbl_progress"])
            self.lbl_speed.config(text=st["lbl_speed"])
            self.lbl_elapsed.config(text=st["lbl_elapsed"])
            self.lbl_eta.config(text=st["lbl_eta"])
            self.lbl_errors.config(text=st["lbl_errors"][0])
            if st["lbl_errors"][1]:
                self.lbl_errors.config(bootstyle=st["lbl_errors"][1])
            # 注：lbl_state 已在重建后由 _set_state 按 _state_key 重放
            # （进度/速度等动态值没有语义键可循，按快照原样恢复，
            #  扫描中下一个 tick（≤100ms）即按新语言刷新）
        if scanning:
            # 扫描进行中：恢复按钮禁用态（状态行文案上面已按快照恢复）
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
        self.nb.select(snap["tab"])

    # ---------------------------------------------------------- UI 构建
    def _build_ui(self):
        colors = self.style.colors   # 主题色板：浅/深两套，构建期取一次

        self._build_menubar()

        # ---- 控制区（卡片式 LabelFrame）----
        outer = self._reg(ttk.LabelFrame(self, padding=(10, 6, 10, 8)),
                          "gui.settings")
        outer.pack(fill="x", padx=8, pady=(8, 4))
        bar = ttk.Frame(outer)
        bar.pack(fill="x")

        self._reg(ttk.Label(bar), "gui.target").grid(row=0, column=0, sticky="w")
        self.var_target = tk.StringVar()
        self.combo_target = ttk.Combobox(bar, textvariable=self.var_target, width=52,
                                       state="readonly")
        self.combo_target.grid(row=0, column=1, sticky="we", padx=(0, 4))
        self._reg(ttk.Button(bar, command=self._refresh_drives),
                  "gui.refresh").grid(row=0, column=2)
        self._reg(ttk.Button(bar, command=self._browse_file),
                  "gui.browse_file").grid(row=0, column=3)

        row1 = ttk.Frame(bar)
        row1.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self._reg(ttk.Label(row1), "gui.bs").pack(side="left")
        # 默认值取当前语言列表的首项（"自动"/"Auto"），不写死英文
        self.var_bs = tk.StringVar(value=tr_list("gui.bs_values")[0])
        self.combo_bs = self._reg_values(
            ttk.Combobox(row1, textvariable=self.var_bs, width=10,
                         state="readonly"),
            "gui.bs_values")
        self.combo_bs.pack(side="left", padx=(0, 14))
        self._reg(ttk.Label(row1), "gui.engine").pack(side="left")
        self.var_engine = tk.StringVar(value="windowsaio" if IS_WIN else "libaio")
        self.combo_engine = ttk.Combobox(row1, textvariable=self.var_engine,
                                         width=13, state="readonly",
                                         values=platform_engines())
        self.combo_engine.pack(side="left", padx=(0, 14))
        self.var_direct = tk.BooleanVar(value=True)
        self._reg(ttk.Checkbutton(row1, variable=self.var_direct),
                  "gui.direct").pack(side="left")
        # 分段大小不再提供选择：全段扫描默认按热力图格数（MAP_CELLS）
        # 固定切段（一段对应一格），见 _start_scan 的 plan_cell_segments
        self.var_quick = tk.BooleanVar(value=False)
        self._reg(ttk.Checkbutton(row1, variable=self.var_quick,
                                  command=self._on_quick_toggle),
                  "gui.quick").pack(side="left", padx=(14, 0))
        self._reg(ttk.Label(row1), "gui.sample").pack(side="left", padx=(6, 0))
        self.var_quick_sample = tk.StringVar(value="16M")
        self.combo_quick_sample = ttk.Combobox(
            row1, textvariable=self.var_quick_sample, width=8, state="readonly",
            values=tr_list("gui.sample_values"))
        self.combo_quick_sample.pack(side="left")
        self.combo_quick_sample.config(state="disabled")
        # 热力图模式（健康/读取速度）：显示选项，与扫描参数同行排放
        self._reg(ttk.Label(row1), "gui.map_mode").pack(side="left",
                                                        padx=(14, 0))
        self.var_map_mode = tk.StringVar(value=tr_list("gui.map_mode_values")[0])
        self.combo_map_mode = self._reg_values(
            ttk.Combobox(row1, textvariable=self.var_map_mode, width=20,
                         state="readonly"),
            "gui.map_mode_values")
        self.combo_map_mode.pack(side="left")
        self.combo_map_mode.bind("<<ComboboxSelected>>",
                                 self._on_map_mode_toggle)

        self._reg(ttk.Label(bar), "gui.fio_path").grid(row=2, column=0,
                                                       sticky="w", pady=(4, 0))
        self.var_fio = tk.StringVar(value="fio")
        ttk.Entry(bar, textvariable=self.var_fio, width=52).grid(
            row=2, column=1, sticky="w", padx=(0, 4), pady=(4, 0))
        self._reg(ttk.Button(bar, command=self._browse_fio),
                  "gui.browse").grid(row=2, column=2, pady=(4, 0))

        btn_bar = ttk.Frame(bar)
        btn_bar.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.btn_start = self._reg(ttk.Button(btn_bar, bootstyle="primary",
                                              command=self._start_scan),
                                   "gui.start")
        self.btn_start.pack(side="left")
        self.btn_stop = self._reg(ttk.Button(btn_bar, bootstyle="danger outline",
                                             command=self._stop_scan,
                                             state="disabled"),
                                  "gui.stop")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_export = self._reg(ttk.Button(btn_bar, command=self._export_report,
                                               state="disabled"),
                                    "gui.export")
        self.btn_export.pack(side="left")
        self._reg(ttk.Label(btn_bar, bootstyle="secondary"),
                  "gui.hint").pack(side="left", padx=12)
        self.lbl_admin = self._reg(ttk.Label(btn_bar), "gui.perm_checking")
        self.lbl_admin.pack(side="left", padx=(16, 0))
        self.btn_elevate = self._reg(ttk.Button(btn_bar,
                                                command=self._relaunch_elevated),
                                     "gui.relaunch" if IS_WIN
                                     else "gui.relaunch_linux")
        self.btn_elevate.pack(side="left", padx=6)
        self.btn_elevate.pack_forget()

        bar.columnconfigure(1, weight=1)

        # ---- 热力图 ----
        # 标题文案随模式切换（_update_map_title），不占 _reg 的静态键
        self.map_frame = ttk.LabelFrame(self, padding=(8, 6, 8, 6))
        self._update_map_title()
        self.map_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas_map = tk.Canvas(self.map_frame, bg=colors.bg,
                                    highlightthickness=0)
        self.canvas_map.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas_map.bind("<Motion>", self._on_canvas_motion)
        self.canvas_map.bind("<Leave>", lambda e: self.lbl_hover.config(text=""))
        # 窗口缩放/DPI 变化：格子按新画布尺寸重排（只挪坐标，不动数据）
        self.canvas_map.bind("<Configure>", self._on_canvas_configure)

        legend = ttk.Frame(self.map_frame)
        legend.pack(fill="x", padx=4)
        self.lbl_hover = ttk.Label(legend, text="", anchor="w",
                                   bootstyle="secondary")
        self.lbl_hover.pack(side="left", fill="x", expand=True)
        self._legend_labels = []
        self._legend_swatches = []   # 原生 tk 色块：切主题时手工同步边框色
        # 四个语义色全部建好，按模式显隐（_layout_legend）：健康模式只留
        # 绿/红/灰，速度模式 绿/黄/红/灰
        for color, key in ((COLOR_OK, "ok"), (COLOR_SLOW, "slow"),
                           (COLOR_ERROR, "error"),
                           (COLOR_PENDING, "pending")):
            swatch = tk.Frame(legend, bg=color, width=12, height=12,
                              highlightbackground=colors.border,
                              highlightthickness=1)
            self._legend_swatches.append(swatch)
            lbl = ttk.Label(legend, text=status_text(key),
                            bootstyle="secondary")
            self._legend_labels.append((lbl, key))
        self._layout_legend()

        # ---- 状态行 ----
        st = ttk.Frame(self)
        st.pack(fill="x", padx=8, pady=4)
        self.progress = ttk.Progressbar(st, maximum=100, bootstyle="primary")
        self.progress.pack(fill="x", side="top", pady=(0, 6))
        # 结果横幅：替代此前的 messagebox，扫描结果/错误在界面内展示
        # （bootstyle 随级别动态切换：info/success/warning/danger）
        self.lbl_banner = ttk.Label(st, text="", anchor="w", bootstyle="info",
                                    font=("Segoe UI", 9, "bold"),
                                    padding=(10, 6))
        self.lbl_banner.pack(fill="x", pady=(0, 6))
        row = ttk.Frame(st, padding=(10, 6))
        row.pack(fill="x")
        self.lbl_progress = self._reg(ttk.Label(row, width=16), "gui.progress")
        self.lbl_progress.pack(side="left")
        self.lbl_speed = self._reg(ttk.Label(row, width=18), "gui.speed")
        self.lbl_speed.pack(side="left")
        self.lbl_elapsed = self._reg(ttk.Label(row, width=14), "gui.elapsed")
        self.lbl_elapsed.pack(side="left")
        self.lbl_eta = self._reg(ttk.Label(row, width=14), "gui.eta")
        self.lbl_eta.pack(side="left")
        self.lbl_errors = self._reg(ttk.Label(row, width=12), "gui.errors")
        self.lbl_errors.pack(side="left")
        self.lbl_state = ttk.Label(row)
        self.lbl_state.pack(side="left", padx=10)
        self._set_state("gui.state_ready")

        # ---- 详情页 ----
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=False, padx=8, pady=(4, 8))
        self.txt_log = ttk.ScrolledText(self.nb, height=9,
                                        font=("Consolas", 9), wrap="word")
        self._reg_tab(self.nb, self.txt_log, "gui.tab_log")
        err_frame = ttk.Frame(self.nb)
        self._reg_tab(self.nb, err_frame, "gui.tab_errors")
        cols = ("block", "offset", "desc")
        self.tree_err = ttk.Treeview(err_frame, columns=cols, show="headings",
                                     height=7)
        for c, w, key in zip(cols, (90, 160, 420),
                             ("gui.col_block", "gui.col_offset", "gui.col_desc")):
            self._reg_heading(self.tree_err, c, key)
            self.tree_err.column(c, width=w, anchor="w")
        self.tree_err.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(err_frame, command=self.tree_err.yview)
        sb.pack(side="right", fill="y")
        self.tree_err.configure(yscrollcommand=sb.set)
        self.txt_summary = ttk.ScrolledText(self.nb, height=9,
                                            font=("Consolas", 9), wrap="word")
        self._reg_tab(self.nb, self.txt_summary, "gui.tab_summary")

    def _build_menubar(self):
        menubar = tk.Menu(self)
        lang_menu = tk.Menu(menubar, tearoff=0)
        # 语言菜单由 lang/*.json 自动发现生成（core.available_languages：
        # 文件名即语言码、_meta.name 即菜单标签）。新增语言只需往 lang/
        # 放一个 JSON，不用改这里；切换后 _rebuild_ui 会用新表重建菜单。
        for code, name in available_languages():
            lang_menu.add_radiobutton(
                label=name, variable=self.var_lang, value=code,
                command=lambda c=code: self._set_language(c))
        menubar.add_cascade(label=tr("gui.menu.language"), menu=lang_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_radiobutton(label=tr("gui.menu.theme_light"),
                                  variable=self.var_theme,
                                  value="bootstrap-light",
                                  command=lambda: self._set_theme("bootstrap-light"))
        view_menu.add_radiobutton(label=tr("gui.menu.theme_dark"),
                                  variable=self.var_theme,
                                  value="bootstrap-dark",
                                  command=lambda: self._set_theme("bootstrap-dark"))
        menubar.add_cascade(label=tr("gui.menu.view"), menu=view_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=tr("gui.menu.about"), command=self._show_about)
        menubar.add_cascade(label=tr("gui.menu.help"), menu=help_menu)
        self.config(menu=menubar)
        self._menubar = menubar
        self._lang_menu = lang_menu
        self._view_menu = view_menu
        self._help_menu = help_menu

    # ---------------------------------------------------------- 关于窗口
    def _show_about(self):
        # ttkbootstrap.Toplevel 的第一个位置参数是 title 而非 master，
        # 必须用关键字传 master；iconphoto='' 默认继承主窗口图标
        win = ttk.Toplevel(master=self)
        win.title(tr("gui.about.title"))
        win.transient(self)
        win.resizable(False, False)
        # 标题栏图标必须走 iconphoto：Tk 的 Windows 端口渲染不了 PNG 压缩的
        # .ico（iconbitmap 静默无效果 → 标题栏图标空白；主窗口同样因此改用
        # iconphoto 设置标题栏/任务栏图标）。用 48px 缩放版即可，Windows 会
        # 按标题栏尺寸自行缩放；两条路都失败才回退 iconbitmap。
        try:
            win.iconphoto(False, self._about_icon or self._icon_img)
        except Exception:
            try:
                win.iconbitmap(os.path.join(_resource_dir(), "HD_Doc.ico"))
            except Exception:
                pass
        frm = ttk.Frame(win, padding=24)
        frm.pack(fill="both", expand=True)
        head = ttk.Frame(frm)
        head.pack(fill="x")
        if self._about_icon is not None:
            ttk.Label(head, image=self._about_icon).pack(side="left",
                                                        padx=(0, 10))
        ttk.Label(head, text=tr("gui.title", ver=VERSION),
                  font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Label(frm, text=tr("gui.about.body"), wraplength=420,
                  justify="center", padding=(0, 12)).pack()
        btn = ttk.Button(frm, text=tr("gui.about.ok"),
                         command=lambda: self._close_about(win),
                         bootstyle="primary")
        btn.pack(pady=(8, 0))
        win.bind("<Escape>", lambda e: self._close_about(win))
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_about(win))
        # 模态 + 居中于父窗口
        win.grab_set()
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_y() + (self.winfo_height() - win.winfo_reqheight()) // 2
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        # grab_set 只拦截输入，不保证窗口置前/获焦（Windows 上弹窗常留在
        # 父窗口后面）：先 lift + 强抢窗口焦点使其激活，再把键盘焦点交给
        # "确定"按钮（聚焦后回车/空格即关闭）。取焦失败不影响功能，静默继续。
        win.lift()
        try:
            win.focus_force()
            btn.focus_set()
        except Exception:
            pass

    def _close_about(self, win):
        """关闭关于窗口并把焦点/置前状态还给主窗口（模态对话框的基本礼仪）"""
        win.destroy()
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _on_tk_exception(self, exc_type, exc_value, exc_tb):
        """Tk 回调未捕获异常 → 运行日志（默认行为是打印到 stderr，
        打包版无控制台用户不可见；这里连同堆栈落盘便于排查）"""
        core.log_exception("tk callback exception", exc_value)

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
        self.combo_target["values"] = values
        if values and not self.var_target.get():
            self.var_target.set(values[0])

    def _browse_file(self):
        p = filedialog.askopenfilename(title=tr("gui.browse_file"))
        if p:
            self.var_target.set(p)

    def _browse_fio(self):
        p = filedialog.askopenfilename(title=tr("gui.fio_path"),
                                       filetypes=[("fio", "fio"),
                                                  ("All", "*.*")])
        if p:
            self.var_fio.set(p)

    def _on_quick_toggle(self):
        # 仅在勾选快速扫描时允许选抽样大小
        self.combo_quick_sample.config(
            state="readonly" if self.var_quick.get() else "disabled")

    # ---------------------------------------------------------- 横幅/日志
    def _banner(self, key, level="info", **kw):
        """界面内结果横幅（替代弹窗）；级别 → ttkbootstrap bootstyle。
        键与参数记入 _banner_key：切换语言重建界面时按新语言重放。"""
        self._banner_key = (key, level, kw)
        self._render_banner()

    def _render_banner(self):
        """按当前语言渲染横幅（界面重建后调用；无横幅时不动）"""
        if self._banner_key is None:
            return
        key, level, kw = self._banner_key
        self.lbl_banner.config(text=tr(key, **kw),
                               bootstyle=BANNER_BOOTSTYLE.get(level, "info"))

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
        # ScrolledText 的文本方法委托给内部 Text（见 ttkbootstrap 文档）
        self.txt_log.insert("end", "[%s] %s\n" % (stream, line))
        if int(self.txt_log.index("end-1c").split(".")[0]) > 600:
            self.txt_log.delete("1.0", "200.0")
        # 扫描过程中日志持续追加：固定滚动到最后一行
        self.txt_log.see("end")

    def _render_log(self):
        """按当前语言重放全部日志（界面重建后调用）"""
        self.txt_log.delete("1.0", "end")
        for entry in self._log_entries:
            if entry[0] == "raw":
                _kind, stream, line = entry
            else:
                _kind, stream, key, kw = entry
                line = tr(key, **kw)
            self.txt_log.insert("end", "[%s] %s\n" % (stream, line))
        self.txt_log.see("end")

    # ---------------------------------------------------------- 管理员权限
    def _update_admin_ui(self):
        if is_admin():
            self.lbl_admin.config(text=tr("gui.perm_admin"),
                                  bootstyle="success")
            self.btn_elevate.pack_forget()
        else:
            self.lbl_admin.config(text=tr("gui.perm_standard"),
                                  bootstyle="warning")
            self.btn_elevate.pack(side="left", padx=6)

    def _startup_admin_check(self):
        self._admin_checked = True
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
        self.after(200, self._exit_now)

    def _relaunch_elevated_linux(self):
        """Linux pkexec 提权：发起 → 横幅告知等待授权 → 轮询子进程。

        判定规则（pkexec 语义）：授权期间 pkexec 一直存活；授权被取消 /
        polkit 拒绝 / 启动失败时 pkexec 立刻退出。因此：
          - 轮询期内退出 → 授权失败：保留本窗口，横幅说明（不闪退）
          - 轮询期满仍存活 → 授权进行中/提权实例已启动：退出本窗口
        """
        popen, err = core.pkexec_gui_spawn()
        if popen is None:
            # 已是 root（err=None，理论上按钮此时已隐藏）或 pkexec 不可用
            self._banner("gui.msg.elevate_failed", "error",
                         err=err or tr("gui.msg.already_root"))
            self._log("error", "gui.msg.elevate_failed",
                      err=err or "already root")
            return
        self._pkexec_popen = popen
        self._pkexec_polls = 20               # 150ms × 20 ≈ 3s
        self._banner("gui.msg.elevate_waiting", "info")
        self._log("info", "gui.log.elevate_requested")
        core.log_event("elevate: pkexec requested (pid=%s)" % popen.pid)
        self._pkexec_after = self.after(150, self._poll_pkexec)

    def _poll_pkexec(self):
        popen = self._pkexec_popen
        if popen is None:
            return
        try:
            if popen.poll() is None:
                self._pkexec_polls -= 1
                if self._pkexec_polls > 0:
                    self._pkexec_after = self.after(150, self._poll_pkexec)
                else:
                    # 3 秒仍存活：授权进行中或提权实例已启动，退出本窗口，
                    # 避免两个实例并存（授权框关掉后新窗口会出现）
                    self._pkexec_popen = None
                    self._log("info", "gui.log.elevate_handover")
                    self._exit_now()
                return
        except Exception:
            # 窗口已销毁等：放弃轮询
            self._pkexec_popen = None
            return
        # pkexec 已退出 = 授权被取消/失败：保留窗口并说明原因
        code = popen.returncode
        self._pkexec_popen = None
        key = ("gui.msg.elevate_cancelled" if code
               else "gui.msg.elevate_failed")
        self._banner(key, "warn", code=code)
        self._log("warn", key, code=code)
        core.log_event("elevate: pkexec exited rc=%s; staying unelevated"
                       % code)

    def _exit_now(self):
        self._cancel_timers()
        try:
            if self.scanner and self.worker and self.worker.is_alive():
                self.scanner.stop()
        except Exception:
            pass
        self.destroy()

    def _cancel_timers(self):
        """取消挂起的 after 回调，避免销毁后 Tcl 报
        “invalid command name …”（提权重启/关闭路径的退出噪声）"""
        for attr in ("_poll_after", "_admin_after", "_pkexec_after",
                     "_map_cfg_after"):
            try:
                after_id = getattr(self, attr, None)
                if after_id:
                    self.after_cancel(after_id)
                    setattr(self, attr, None)
            except Exception:
                pass

    # ---------------------------------------------------------- 扫描控制
    def _start_scan(self):
        # 下拉标签（型号+容量）→ 设备路径；手动输入的路径走规范化
        target = (self._target_paths.get(self.var_target.get())
                  or normalize_target_path(self.var_target.get()))
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
        fio = resolve_fio(self.var_fio.get().strip())
        if not os.path.isfile(fio):
            # 不弹窗：日志 + 横幅提示后继续（用户可能稍后补齐路径）
            self._log("warn", "gui.log.fio_missing", f=fio)
            self._banner("gui.log.fio_missing", "warn", f=fio)
        engine = (self.var_engine.get() or "").strip()
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
            bs = parse_bs(self.var_bs.get(), size)
        except ValueError as e:
            self._banner("gui.msg.param_error_title", "error")
            self._log_raw("error", "%s: %s" % (tr("gui.msg.param_error_title"), e))
            return
        if size and bs > size:
            bs = clamp_bs(bs, size)
            self._log("warn", "gui.log.bs_clamped", sz=fmt_bytes(bs))
        quick = bool(self.var_quick.get())
        # 分段大小不再手工可选：全段扫描默认按热力图格数**固定**切 256 段
        # （段与格一一对应，段统计直接就是格的统计）；容量未知/极小盘时
        # plan_cell_segments 退化为"整盘一次"。
        # 快速扫描同样按格数固定布点（区域数不随容量漂移——1TB 盘固定
        # 256 区而非 4G 区域翻倍后的 117 区），每区只读开头样本。
        if not size:
            # 不弹窗：降级模式说明进日志与横幅，直接继续
            self._log("warn", "gui.log.no_size_degraded", t=target)
            self._banner("gui.log.no_size_degraded", "warn", t=target)
        quick_sample = 0
        if quick:
            if size:
                bs, segments, quick_sample = quick_scan_setup(
                    size, bs, None,
                    parse_bs(self.var_quick_sample.get()))
                self._log("info", "gui.log.quick_plan",
                          n=len(segments), sample=fmt_bytes(quick_sample),
                          total=fmt_bytes(sum(s for _o, s in segments if s)),
                          pct=sum(s for _o, s in segments if s) * 100.0 / size)
            else:
                self._log("warn", "gui.log.quick_no_size")
                quick = False
                segments = sanitize_segments(
                    plan_cell_segments(size, MAP_CELLS, bs), bs)
        else:
            segments = sanitize_segments(
                plan_cell_segments(size, MAP_CELLS, bs), bs)
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
        self.tree_err.delete(*self.tree_err.get_children())
        self.txt_summary.delete("1.0", "end")
        self.summary = None
        self.btn_export.config(state="disabled")
        self._banner_key = None      # 清横幅（重放时不再显示上一轮结果）
        self.lbl_banner.config(text="", bootstyle="info")
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
        # UI 变量只能在主线程读：工作线程里访问 Tk 变量会抛
        # "main thread is not in main loop"（tkinter 解释器非线程安全），
        # 故 engine/direct 在此读出后当参数传进 worker
        engine_val = (self.var_engine.get() or "").strip() or None
        direct_val = bool(self.var_direct.get())
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(target, bs, segments, size, quick,
                  engine_val, direct_val), daemon=True)
        self.worker.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
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

    def _on_close(self):
        if self.scanner and self.worker and self.worker.is_alive():
            if not self._ask_yes(tr("gui.msg.exit_title"),
                                 tr("gui.msg.exit_scanning")):
                return
            self.scanner.stop()
            core.log_event("scan: stopped because the app window is closing")
        self._cancel_timers()
        core.log_event("gui: exit")
        self.destroy()

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
        self.canvas_map.delete("all")
        self.canvas_map.update_idletasks()
        w = max(100, self.canvas_map.winfo_width())
        h = max(100, self.canvas_map.winfo_height())
        total = total_size if total_size else self.total_size
        self.seg_meta = list(seg_meta) if seg_meta else []
        self.n_cells = MAP_CELLS
        pitch, cols, rows, ox, oy = plan_grid(w, h, self.n_cells)
        self._map_wh = (w, h)       # 记录本次布局的画布尺寸（<Configure> 去重）
        self.cell_pitch = pitch
        self.grid_cols = cols
        self.grid_rows = rows
        self.grid_ox = ox
        self.grid_oy = oy
        cell = max(CELL_SIZE_MIN, int(pitch) - CELL_GAP)
        self.cells = []
        self.cell_items = []
        self.cell_span = []
        for i in range(self.n_cells):
            r, c = divmod(i, cols)   # 行优先：铺满一行再下一行
            x = ox + c * pitch
            y = oy + r * pitch
            self.cell_items.append(self.canvas_map.create_rectangle(
                x, y, x + cell, y + cell,
                fill=COLOR_PENDING, outline=""))
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

    def _on_canvas_configure(self, ev=None):
        """画布尺寸变化（窗口缩放/最大化/DPI 变化/语言重建后重映射）：
        拖拽缩放会连续触发 Configure，用 50ms 防抖合并成一次重排。"""
        if self._map_cfg_after is not None:
            return                  # 已挂起：等它跑（顺带覆盖最新尺寸）
        self._map_cfg_after = self.after(50, self._flush_canvas_configure)

    def _flush_canvas_configure(self):
        self._map_cfg_after = None
        # 窗口已销毁（提权重启/关闭路径）时安静退出，避免 Tcl 报
        # “invalid command name”（与 _poll_queue 同款防御）
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._relayout_map()

    def _relayout_map(self):
        """按当前画布尺寸重排热力图格子（窗口缩放自适应）。

        只更新格子矩形的坐标与网格参数（cell_pitch/grid_cols/grid_rows/
        grid_ox/grid_oy），格子的统计数据、颜色、错误数全部不动——缩放
        是纯几何变化。无格子（未扫描）或尺寸没变时直接返回。
        """
        if not self.cell_items:
            return
        w = max(100, self.canvas_map.winfo_width())
        h = max(100, self.canvas_map.winfo_height())
        if self._map_wh == (w, h):
            return
        self._map_wh = (w, h)
        pitch, cols, rows, ox, oy = plan_grid(w, h, self.n_cells or MAP_CELLS)
        self.cell_pitch = pitch
        self.grid_cols = cols
        self.grid_rows = rows
        self.grid_ox = ox
        self.grid_oy = oy
        cell = max(CELL_SIZE_MIN, int(pitch) - CELL_GAP)
        for i, item in enumerate(self.cell_items):
            r, c = divmod(i, cols)   # 行优先：与 _reset_map 一致
            x = ox + c * pitch
            y = oy + r * pitch
            self.canvas_map.coords(item, x, y, x + cell, y + cell)

    def _update_map_title(self):
        """热力图标题随模式切换（LabelFrame 文本）"""
        key = ("gui.map_title_health" if self.map_mode == MAP_MODE_HEALTH
               else "gui.map_title_speed")
        self.map_frame.config(text=tr(key, n=MAP_CELLS))

    def _layout_legend(self):
        """图例按模式显隐重排：健康模式只留 绿(正常)/红(错误)/灰(未扫描)，
        速度模式 绿(快)/黄(偏慢)/红(错误)/灰(未扫描)。

        灰色两种模式都保留：未扫描/未抽样不是健康或速度判定，藏掉灰色
        会把"还没扫到"误读成"正常"。下标对应创建顺序
        0=ok 1=slow 2=error 3=pending（_legend_swatches/_legend_labels）。
        先全部收起再按需 pack——否则从速度模式切回健康时"偏慢"会残留。
        """
        for swatch, lbl in zip(self._legend_swatches,
                               (l for l, _k in self._legend_labels)):
            swatch.pack_forget()
            lbl.pack_forget()
        order = ((0, 2, 3) if self.map_mode == MAP_MODE_HEALTH
                 else (0, 1, 2, 3))
        for i in order:
            self._legend_swatches[i].pack(side="left", padx=(8, 2))
            self._legend_labels[i][0].pack(side="left")

    def _on_map_mode_toggle(self, _ev=None, redraw=True):
        """切换热力图模式（健康 ↔ 读取速度）：标题与图例即时更新，
        格子按新模式重上色——已完成→立即全量重绘；扫描中→全部标记脏，
        下一拍 _flush_cells 随 provisional 阈值统一上色（避免用过程阈值
        把中间态定格）。数据（中位数/错误数/块数）与模式无关，不重算。

        redraw=False 供界面重建（_rebuild_ui）用：彼时 cell_items 还是
        已销毁画布的旧 id，重绘无意义；随后的地图数据重载会以新 items
        按新模式上色。
        """
        self.map_mode = self.combo_map_mode.current()
        if self.map_mode < 0:      # 防御：选择被清空时回到健康模式
            self.map_mode = MAP_MODE_HEALTH
            self.combo_map_mode.current(MAP_MODE_HEALTH)
        self._update_map_title()
        self._layout_legend()
        if not redraw or not self.cells:
            return
        if self.summary is not None:
            self._redraw_cells()
        else:
            self.dirty = set(range(len(self.cells)))

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
        now = time.time()
        if not force and now - self._last_flush < 0.12:
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
        items = self.canvas_map
        batch = list(self.dirty)[:4000]
        for idx in batch:
            if idx < len(self.cell_items) and self.cell_items[idx]:
                items.itemconfig(self.cell_items[idx],
                                 fill=self._cell_color(idx))
        self.dirty.clear()

    # ---------------------------------------------------------- 事件处理
    def _poll_queue(self):
        # 窗口已销毁（如提权重启路径 _exit_now）时安静退出，
        # 避免 Tcl 报 “invalid command name …_poll_queue”
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        n = 0
        try:
            while n < 4000:
                ev = self.q.get_nowait()
                n += 1
                self._handle_event(ev)
        except queue.Empty:
            pass
        self._flush_cells()
        self._poll_after = self.after(100, self._poll_queue)

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
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.worker = None
            if self.scan_start_ts and not self.summary:
                self._set_state("gui.state_stopped")

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
            self.progress["value"] = pct
            self.lbl_progress.config(text=tr("gui.progress_pct", pct=pct))
            if bw and done < total:
                self.lbl_eta.config(text=tr("gui.eta_fmt", v=fmt_duration(
                    (total - done) / float(bw))))
        elif ev.get("pct") is not None:
            self.progress["value"] = ev["pct"]
            self.lbl_progress.config(text=tr("gui.progress_pct", pct=ev["pct"]))
        else:
            self.progress.config(mode="indeterminate")
            self.progress.start(60)
            self.lbl_progress.config(text=tr("gui.progress_read",
                                             sz=fmt_bytes(done)))
        self.lbl_speed.config(text=tr("gui.speed_fmt", v=fmt_speed(bw)))
        if self.scan_start_ts:
            self.lbl_elapsed.config(text=tr("gui.elapsed_fmt", v=fmt_duration(
                time.time() - self.scan_start_ts)))
        if ev.get("errors"):
            # fio 的 error 字段是 errno 码而非计数
            code = int(ev["errors"])
            self.lbl_errors.config(
                text=tr("gui.errors_code", name=errno_name(code), code=code),
                bootstyle="danger")
        elif ev.get("errors") == 0:
            self.lbl_errors.config(text=tr("gui.errors_none"),
                                   bootstyle="success")

    def _on_finished(self, s):
        self.summary = s
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.progress["value"] = 100
        self.thresholds = s["slow_thr_us"]
        # 错误块计入热力图单元格（按字节偏移精确到格；live 事件已计过
        # 的块在这里去重，不重复计数）
        total = s.get("total_size") or self.total_size
        for idx in s["error_blocks"]:
            self._mark_error_block(idx, s.get("bs"), total)
        self._redraw_cells()
        self._render_result_ui(s)
        core.log_event(
            "scan: finished target=%s blocks=%d ok=%d slow=%d "
            "errors=%d aborted=%s stopped=%s elapsed=%.1fs"
            % (s["target"], s["n_blocks"], s["ok"], s["slow"],
               len(s["error_blocks"]), s["aborted"],
               bool(s.get("stop_requested")), s["elapsed_s"]))

    def _redraw_cells(self):
        """用当前模式与阈值全量重绘热力图（最终阈值/重建界面/切换模式后调用）"""
        for i in range(len(self.cells)):
            if i < len(self.cell_items) and self.cell_items[i]:
                self.canvas_map.itemconfig(self.cell_items[i],
                                           fill=self._cell_color(i))

    def _render_result_ui(self, s):
        """渲染已完成扫描的结果区（状态行/导出按钮/错误树/汇总页/横幅）。

        只写文案与控件状态、不改 cells 数据——切换语言重建界面时用
        同一份 summary 重放（错误块已计入格子，不能重复加）。
        """
        self.lbl_progress.config(text=tr("gui.progress_pct", pct=100.0))
        self.lbl_speed.config(text=tr("gui.speed"))
        self.lbl_elapsed.config(text=tr("gui.elapsed_fmt",
                                        v=fmt_duration(s["elapsed_s"])))
        self.lbl_eta.config(text=tr("gui.eta_fmt", v="00:00"))
        if s["last_errno"]:
            self.lbl_errors.config(
                text=tr("gui.errors_code",
                        name=s["last_errno_name"] or tr("unknown"),
                        code=s["last_errno"]),
                bootstyle="danger")
        else:
            self.lbl_errors.config(text=tr("gui.errors_none"),
                                   bootstyle="success")
        self._set_state("gui.state_done_aborted" if s["aborted"]
                        else "gui.state_done")
        self.btn_export.config(state="normal")

        self._render_error_tree()
        self._render_summary()
        self.nb.select(self.txt_summary)

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
        self.tree_err.delete(*self.tree_err.get_children())
        if not self.summary:
            return
        s = self.summary
        for idx in sorted(s["error_blocks"]):
            self.tree_err.insert(
                "", "end",
                values=[idx, fmt_bytes(idx * s["bs"]),
                        s["error_blocks"][idx][:120]])

    def _render_summary(self):
        self.txt_summary.delete("1.0", "end")
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
        self.txt_summary.insert("1.0", "\n".join(lines))

    def _export_report(self):
        if not self.summary:
            return
        d = filedialog.askdirectory(title=tr("gui.export"))
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
        self.lbl_progress.config(text=tr("gui.progress_pct", pct=pct))
        self.lbl_speed.config(text=tr("gui.speed_fmt", v=fmt_speed(bw)))
        self.lbl_eta.config(text=tr("gui.eta_fmt", v=fmt_duration(eta_s)))
        self.lbl_errors.config(text=tr("gui.errors", n=errors))

    def _on_canvas_motion(self, ev):
        if not self.cells or not self.cell_items:
            return
        c = int((ev.x - self.grid_ox) // self.cell_pitch)
        r = int((ev.y - self.grid_oy) // self.cell_pitch)
        if c < 0 or r < 0 or c >= self.grid_cols or r >= self.grid_rows:
            self.lbl_hover.config(text="")
            return
        idx = r * self.grid_cols + c
        if idx >= len(self.cells):
            self.lbl_hover.config(text="")
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
        self.lbl_hover.config(text=txt)
