#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HD_Doc_gui.py —— GUI 模式（tkinter；只依赖 HD_Doc_core）

本模块只在 GUI 模式下被入口 HD_Doc.py 导入；
没有 tkinter 的环境（如 --cli 命令行模式）永远不会加载本模块。

界面语言：默认英文，菜单 Language/语言 可切换中文，选择持久化在
用户配置目录（见 HD_Doc_core 的 i18n 小节；文案表在 lang/*.json，
独立于代码）。切换语言即保存偏好并重启程序，以新语言重载整个
界面。扫描结果/错误提示以界面内横幅与日志展示，尽量不弹窗。
"""

import os
import queue
import statistics
import sys
import threading
import time
from bisect import bisect_right
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import HD_Doc_core as core                      # 业务逻辑全部经 core
from HD_Doc_core import *                       # 常用名直接可用（调用点不变）
from HD_Doc_core import _pythonw_path           # 下划线名需显式导入

# 横幅级别 → 前景色 / 背景色（tk.Label 才能设背景，做成浅色卡片式横幅）
BANNER_COLORS = {"info": "#185FA5", "ok": "#3B6D11",
                 "warn": "#B36A00", "error": "#A32D2D"}
BANNER_BG = {"info": "#EFF6FF", "ok": "#F0FDF4",
             "warn": "#FFFBEB", "error": "#FEF2F2"}

# 主题色（现代化 UI 的品牌色，与 Windows 11 的蓝色 accent 接近）
ACCENT = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
ACCENT_PRESS = "#1E40AF"
INK = "#0F172A"          # 主文字
INK_MUTED = "#64748B"    # 次要文字
BORDER = "#E2E8F0"       # 卡片描边
SURFACE = "#FFFFFF"      # 卡片底
CANVAS_BG = "#F1F5F9"    # 窗口底


def _resource_dir():
    """img/ 资源目录：打包版在 sys._MEIPASS，源码版在脚本同级"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "img")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")


def restart_app():
    """以当前解释器重启本程序（切换语言后重载界面用）。

    源码运行：python HD_Doc.py → python HD_Doc.py
    打包运行：HD_Doc.exe           → HD_Doc.exe
    """
    if getattr(sys, "frozen", False):
        os.execv(sys.executable, [sys.executable] + sys.argv[1:])
    os.execv(sys.executable, [sys.executable] + sys.argv)


class HDDocApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()               # 构建期不显示，避免默认位置闪一下
        self.title(tr("gui.title", ver=VERSION))
        self.geometry("1140x820")
        self.minsize(980, 700)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._target_paths = {}       # 下拉标签 → 裸设备路径（型号显示用）
        self._icon_img = None         # PhotoImage 引用，防止被 GC

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
        self.n_segments = 0
        self.seg_meta = []        # 每格的 (offset, size|None, span|None) 供悬停显示
        self.seg_block_base = []  # 每格起始全局块号（error_block → 格 映射）
        self.total_size = None
        self.planned_bytes = 0   # 快速扫描的计划读取量（进度/ETA 分母）
        self.thresholds = (0.0, 0.0)
        self.summary = None
        self.scan_start_ts = None
        self.scan_bs = 0
        self.scan_quick = False
        self.seg_base = []
        self._last_thresh_calc = 0.0
        self._last_flush = 0.0

        # 界面语言（切换后重启重载，见 _set_language / restart_app）
        self.var_lang = tk.StringVar(value=get_language())

        self._setup_theme()
        self._set_window_icon()
        self._build_ui()
        self._refresh_drives()
        self._center_on_screen()
        self._poll_after = self.after(100, self._poll_queue)
        self._admin_after = self.after(200, self._startup_admin_check)

    # ---------------------------------------------------------- 主题与图标
    def _setup_theme(self):
        """clam 主题 + 品牌色定制（Windows 默认 vista 主题可编程性太弱）"""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            return
        style.configure(".", font=("Segoe UI", 9), foreground=INK,
                        background=CANVAS_BG)
        style.configure("TFrame", background=CANVAS_BG)
        # 卡片式分区
        style.configure("TLabelframe", background=SURFACE, bordercolor=BORDER,
                        borderwidth=1, relief="solid", labeloutside=False)
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"),
                        foreground=INK, background=SURFACE)
        style.configure("Card.TFrame", background=SURFACE)
        # 文本
        style.configure("TLabel", foreground=INK, background=SURFACE)
        style.configure("Flat.TLabel", background=CANVAS_BG)
        style.configure("Muted.TLabel", foreground=INK_MUTED,
                        background=SURFACE)
        style.configure("Banner.TLabel", foreground=INK, background=SURFACE,
                        padding=(10, 6))
        # 按钮
        style.configure("TButton", padding=(10, 4), bordercolor=BORDER,
                        foreground=INK, background="#F8FAFC")
        style.map("TButton",
                  background=[("active", "#EFF6FF"), ("pressed", "#E2E8F0")],
                  bordercolor=[("active", ACCENT)])
        style.configure("Accent.TButton", padding=(12, 5),
                        background=ACCENT, foreground="#FFFFFF",
                        bordercolor=ACCENT, focuscolor=ACCENT,
                        font=("Segoe UI", 9, "bold"))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER),
                              ("pressed", ACCENT_PRESS)])
        style.configure("Danger.TButton", foreground="#B91C1C")
        # 输入控件
        style.configure("TCombobox", padding=(4, 2), bordercolor=BORDER,
                        fieldbackground=SURFACE, arrowcolor=INK_MUTED)
        style.configure("TEntry", padding=(4, 2), bordercolor=BORDER,
                        fieldbackground=SURFACE)
        style.configure("TCheckbutton", foreground=INK, background=SURFACE,
                        focuscolor=ACCENT)
        # 页签
        style.configure("TNotebook", background=CANVAS_BG, bordercolor=BORDER,
                        tabmargins=(2, 2, 2, 0))
        style.configure("TNotebook.Tab", padding=(14, 5),
                        background="#E2E8F0", foreground=INK_MUTED,
                        borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", SURFACE)],
                  foreground=[("selected", INK)],
                  font=[("selected", ("Segoe UI", 9, "bold"))])
        # 表格与进度条
        style.configure("Treeview", rowheight=26, background=SURFACE,
                        fieldbackground=SURFACE, foreground=INK,
                        bordercolor=BORDER)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                        background="#F1F5F9", foreground=INK,
                        padding=(6, 4), relief="flat")
        style.map("Treeview.Heading", background=[("active", "#E2E8F0")])
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor="#E2E8F0", thickness=8,
                        borderwidth=0)

    def _set_window_icon(self):
        """标题栏图标（.ico）+ 任务栏/Alt-Tab 图标（.png）；缺失时静默跳过"""
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
        except Exception:
            pass

    # ---------------------------------------------------------- 文案辅助
    # 语言在启动时确定（切换语言会重启程序），界面文案只需取一次
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

    def _set_language(self, lang):
        """切换语言：持久化偏好后重启程序，以新语言重载界面。
        扫描中禁止切换（重启会遗留 fio 子进程），只给界面内提示。"""
        if lang == get_language():
            return
        if self.worker and self.worker.is_alive():
            self._banner("gui.msg.lang_busy", "warn")
            return
        set_language(lang)      # 写入配置；重启后由 get_language 读回
        restart_app()           # 一般不返回（execv 替换当前进程）

    # ---------------------------------------------------------- UI 构建
    def _build_ui(self):
        pad = dict(padx=6, pady=3)

        self._build_menubar()

        # ---- 控制区（卡片式 LabelFrame）----
        outer = self._reg(ttk.LabelFrame(self, padding=(10, 6, 10, 8)),
                          "gui.settings")
        outer.pack(fill="x", padx=8, pady=(8, 4))
        bar = ttk.Frame(outer, style="Card.TFrame")
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
        self.var_bs = tk.StringVar(value="Auto")
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
        self._reg(ttk.Label(row1), "gui.segment").pack(side="left", padx=(14, 0))
        self.var_seg = tk.StringVar(value="4G")
        self.combo_seg = self._reg_values(
            ttk.Combobox(row1, textvariable=self.var_seg, width=22,
                         state="readonly"),
            "gui.seg_values")
        self.combo_seg.pack(side="left")
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

        self._reg(ttk.Label(bar), "gui.fio_path").grid(row=2, column=0,
                                                       sticky="w", pady=(4, 0))
        self.var_fio = tk.StringVar(value="fio")
        ttk.Entry(bar, textvariable=self.var_fio, width=52).grid(
            row=2, column=1, sticky="w", padx=(0, 4), pady=(4, 0))
        self._reg(ttk.Button(bar, command=self._browse_fio),
                  "gui.browse").grid(row=2, column=2, pady=(4, 0))

        btn_bar = ttk.Frame(bar)
        btn_bar.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.btn_start = self._reg(ttk.Button(btn_bar, style="Accent.TButton",
                                              command=self._start_scan),
                                   "gui.start")
        self.btn_start.pack(side="left")
        self.btn_stop = self._reg(ttk.Button(btn_bar, command=self._stop_scan,
                                             state="disabled"),
                                  "gui.stop")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_export = self._reg(ttk.Button(btn_bar, command=self._export_report,
                                               state="disabled"),
                                    "gui.export")
        self.btn_export.pack(side="left")
        self._reg(ttk.Label(btn_bar, style="Muted.TLabel"),
                  "gui.hint").pack(side="left", padx=12)
        self.lbl_admin = self._reg(ttk.Label(btn_bar), "gui.perm_checking")
        self.lbl_admin.pack(side="left", padx=(16, 0))
        self.btn_elevate = self._reg(ttk.Button(btn_bar,
                                                command=self._relaunch_elevated),
                                     "gui.relaunch")
        self.btn_elevate.pack(side="left", padx=6)
        self.btn_elevate.pack_forget()

        bar.columnconfigure(1, weight=1)

        # ---- 热力图 ----
        map_frame = self._reg(ttk.LabelFrame(self, padding=(8, 6, 8, 6)),
                              "gui.map_title")
        map_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas_map = tk.Canvas(map_frame, bg=SURFACE, highlightthickness=0)
        self.canvas_map.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas_map.bind("<Motion>", self._on_canvas_motion)
        self.canvas_map.bind("<Leave>", lambda e: self.lbl_hover.config(text=""))

        legend = ttk.Frame(map_frame, style="Card.TFrame")
        legend.pack(fill="x", padx=4)
        self.lbl_hover = ttk.Label(legend, text="", anchor="w",
                                   style="Muted.TLabel")
        self.lbl_hover.pack(side="left", fill="x", expand=True)
        self._legend_labels = []
        for color, key in ((COLOR_OK, "ok"), (COLOR_SLOW, "slow"),
                           (COLOR_BAD, "bad"), (COLOR_ERROR, "error"),
                           (COLOR_PENDING, "pending")):
            tk.Frame(legend, bg=color, width=12, height=12,
                     highlightbackground=BORDER, highlightthickness=1
                     ).pack(side="left", padx=(8, 2))
            lbl = ttk.Label(legend, text=status_text(key),
                            style="Muted.TLabel")
            lbl.pack(side="left")
            self._legend_labels.append((lbl, key))

        # ---- 状态行 ----
        st = ttk.Frame(self)
        st.pack(fill="x", padx=8, pady=4)
        self.progress = ttk.Progressbar(st, maximum=100)
        self.progress.pack(fill="x", side="top", pady=(0, 6))
        # 结果横幅：替代此前的 messagebox，扫描结果/错误在界面内展示
        self.lbl_banner = tk.Label(st, text="", anchor="w",
                                   foreground="#185FA5",
                                   bg=BANNER_BG["info"],
                                   font=("Segoe UI", 9, "bold"),
                                   padx=10, pady=6)
        self.lbl_banner.pack(fill="x", pady=(0, 6))
        row = ttk.Frame(st, style="Card.TFrame", padding=(10, 6))
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
        self.lbl_state = self._reg(ttk.Label(row, style="Muted.TLabel"),
                                   "gui.state_ready")
        self.lbl_state.pack(side="left", padx=10)

        # ---- 详情页 ----
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=False, padx=8, pady=(4, 8))
        self.txt_log = ScrolledText(self.nb, height=9, font=("Consolas", 9),
                                    wrap="word")
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
        self.txt_summary = ScrolledText(self.nb, height=9, font=("Consolas", 9),
                                        wrap="word")
        self._reg_tab(self.nb, self.txt_summary, "gui.tab_summary")

    def _lang_menu_state(self, enabled):
        """扫描期间禁用语言菜单（切换语言=重启，不能中断扫描）"""
        try:
            self._menubar.entryconfig(
                self._lang_cascade_idx,
                state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _build_menubar(self):
        menubar = tk.Menu(self)
        lang_menu = tk.Menu(menubar, tearoff=0)
        lang_menu.add_radiobutton(label="English", variable=self.var_lang,
                                  value="en", command=lambda: self._set_language("en"))
        lang_menu.add_radiobutton(label="中文", variable=self.var_lang,
                                  value="zh", command=lambda: self._set_language("zh"))
        menubar.add_cascade(label=tr("gui.menu.language"), menu=lang_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=tr("gui.menu.about"), command=self._show_about)
        menubar.add_cascade(label=tr("gui.menu.help"), menu=help_menu)
        self.config(menu=menubar)
        self._menubar = menubar
        self._lang_menu = lang_menu
        self._help_menu = help_menu
        self._lang_cascade_idx = 0    # Language 是第一个级联菜单

    # ---------------------------------------------------------- 关于窗口
    def _show_about(self):
        win = tk.Toplevel(self)
        win.title(tr("gui.about.title"))
        win.transient(self)
        win.resizable(False, False)
        try:
            win.iconbitmap(os.path.join(_resource_dir(), "HD_Doc.ico"))
        except Exception:
            pass
        frm = ttk.Frame(win, padding=24, style="Card.TFrame")
        frm.pack(fill="both", expand=True)
        head = ttk.Frame(frm, style="Card.TFrame")
        head.pack(fill="x")
        if self._icon_img is not None:
            ttk.Label(head, image=self._icon_img).pack(side="left",
                                                       padx=(0, 10))
        ttk.Label(head, text=tr("gui.title", ver=VERSION),
                  font=("Segoe UI", 12, "bold")).pack(side="left")
        tk.Label(frm, text=tr("gui.about.body"), wraplength=420,
                 justify="center", pady=12).pack()
        ttk.Button(frm, text="OK", command=win.destroy,
                   style="Accent.TButton").pack(pady=(8, 0))
        # 模态 + 居中于父窗口
        win.grab_set()
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_y() + (self.winfo_height() - win.winfo_reqheight()) // 2
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))

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
            name = model or tr("gui.disk_n", n=d["index"])
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
                                       filetypes=[("fio", "fio.exe fio"),
                                                  ("All", "*.*")])
        if p:
            self.var_fio.set(p)

    def _on_quick_toggle(self):
        # 仅在勾选快速扫描时允许选抽样大小
        self.combo_quick_sample.config(
            state="readonly" if self.var_quick.get() else "disabled")

    # ---------------------------------------------------------- 横幅/日志
    def _banner(self, key, level="info", **kw):
        """界面内结果横幅（替代弹窗）"""
        self.lbl_banner.config(text=tr(key, **kw),
                               foreground=BANNER_COLORS.get(level, "#185FA5"),
                               bg=BANNER_BG.get(level, BANNER_BG["info"]))

    def _log(self, stream, key, **kw):
        """写入一条日志（插入时定型；切换语言会重启重载）"""
        self._log_line(stream, tr(key, **kw))

    def _log_line(self, stream, line):
        self.txt_log.insert("end", "[%s] %s\n" % (stream, line))
        if int(self.txt_log.index("end-1c").split(".")[0]) > 600:
            self.txt_log.delete("1.0", "200.0")
        # 扫描过程中日志持续追加：固定滚动到最后一行
        self.txt_log.see("end")

    # ---------------------------------------------------------- 管理员权限
    def _update_admin_ui(self):
        if is_admin():
            self.lbl_admin.config(text=tr("gui.perm_admin"),
                                  foreground="#1E7B34")
            self.btn_elevate.pack_forget()
        else:
            self.lbl_admin.config(text=tr("gui.perm_standard"),
                                  foreground="#B36A00")
            self.btn_elevate.pack(side="left", padx=6)

    def _startup_admin_check(self):
        self._admin_checked = True
        self._update_admin_ui()
        if is_admin():
            self._log("info", "gui.log.admin_ok")
            return
        self._log("warn", "gui.log.not_admin")
        if not IS_WIN or not auto_elevate_enabled():
            return
        if messagebox.askyesno(
                tr("gui.msg.admin_needed_title"),
                tr("gui.msg.admin_needed", t="\\\\.\\PhysicalDriveN")):
            self._relaunch_elevated()

    def _relaunch_elevated(self):
        # gui=True：提权子进程用 pythonw.exe 启动，不再伴随命令窗口
        ok, _code, err = request_elevation(wait=False, gui=True)
        if not ok:
            self._banner("gui.msg.elevate_failed", "error", err=err or "?")
            self._log("error", "gui.msg.elevate_failed", err=err or "?")
            return
        if not _pythonw_path():
            self._log("warn", "gui.log.no_pythonw")
        self._log("info", "gui.log.elevate_requested")
        self.after(200, self._exit_now)

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
        for attr in ("_poll_after", "_admin_after"):
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
            if messagebox.askyesno(
                    tr("gui.msg.admin_needed_title"),
                    tr("gui.msg.admin_needed", t=target)):
                self._relaunch_elevated()
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
        seg_bytes = parse_segment_size(self.var_seg.get())
        seg_requested = seg_bytes is not None
        if not size and seg_requested:
            # 不弹窗：降级模式说明进日志与横幅，直接继续
            self._log("warn", "gui.log.no_size_degraded", t=target)
            self._banner("gui.log.no_size_degraded", "warn", t=target)
        quick_sample = 0
        if quick:
            if size:
                bs, segments, quick_sample = quick_scan_setup(
                    size, bs, seg_bytes, parse_bs(self.var_quick_sample.get()))
                self._log("info", "gui.log.quick_plan",
                          n=len(segments), sample=fmt_bytes(quick_sample),
                          total=fmt_bytes(sum(s for _o, s in segments if s)),
                          pct=sum(s for _o, s in segments if s) * 100.0 / size)
            else:
                self._log("warn", "gui.log.quick_no_size")
                quick = False
                segments = sanitize_segments(plan_segments(size, seg_bytes, bs), bs)
        else:
            segments = sanitize_segments(plan_segments(size, seg_bytes, bs), bs)
        if size:
            self._log("info", "gui.log.capacity_plan",
                      sz=fmt_bytes(size), n=len(segments), b=size // bs)

        # 热力图一格 = 一个段（快速扫描时为一个抽样区域）；容量未知时
        # segments=[(0, None)]，只有一格
        seg_meta = []
        seg_block_base = []
        blk_acc = 0
        for off, sz in segments:
            seg_meta.append((off, sz, None))
            seg_block_base.append(blk_acc)
            blk_acc += (sz // bs) if sz else 0
        # 快速扫描记录区域跨度，供悬停显示"抽样 X / 区域 Y"
        if quick:
            region = None
            for i, (off, sz) in enumerate(segments):
                nxt = segments[i + 1][0] if i + 1 < len(segments) else (
                    size if size else None)
                if nxt is not None and off is not None:
                    region = nxt - off
                seg_meta[i] = (off, sz, region)
        self._reset_map(len(segments), seg_meta)
        self.seg_block_base = seg_block_base
        if not size:
            self._log("warn", "gui.log.no_size_map")
        self.tree_err.delete(*self.tree_err.get_children())
        self.txt_summary.delete("1.0", "end")
        self.summary = None
        self.btn_export.config(state="disabled")
        self.lbl_banner.config(text="", bg=BANNER_BG["info"])
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
        self._lang_menu_state(False)
        self.lbl_state.config(text=tr("gui.state_scanning"),
                              foreground="#185FA5")
        self._log("info", "gui.log.start_scan",
                  t=target, bs=fmt_bytes(bs), n=len(segments),
                  kind=tr("gui.log.kind_region") if quick
                  else tr("gui.log.kind_segment"), fio=fio)

    def _run_worker(self, target, bs, segments, size, quick=False,
                    engine=None, direct=True):
        try:
            self.scanner.run(
                target, bs, segments,
                ioengine=engine,
                direct=direct,
                total_size=size,
                yellow_mult=3.0, red_mult=8.0,
                on_event=self._post,
                quick=quick)
        except Exception as e:
            self.q.put({"type": "failed", "message": "%s: %s" % (type(e).__name__, e)})
        finally:
            self.q.put({"type": "worker_done"})

    def _post(self, ev):
        self.q.put(ev)

    def _stop_scan(self):
        if self.scanner:
            self.scanner.stop()
            self.lbl_state.config(text=tr("gui.state_stopping"),
                                  foreground="#A32D2D")
            self._log("warn", "gui.log.stop_requested")

    def _on_close(self):
        if self.scanner and self.worker and self.worker.is_alive():
            if not messagebox.askyesno(tr("gui.msg.exit_title"),
                                       tr("gui.msg.exit_scanning")):
                return
            self.scanner.stop()
        self._cancel_timers()
        self.destroy()

    # ---------------------------------------------------------- 网格（横向 · 一格 = 一段）
    def _reset_map(self, n_segments, seg_meta=None):
        """按段数重建热力图：自适应平铺（格子大小随画布与段数动态计算），
        横向行优先排布（从左到右铺满一行再下一行），一格代表一个扫描段
        （快速扫描时代表一个抽样区域）。"""
        self.canvas_map.delete("all")
        self.canvas_map.update_idletasks()
        w = max(100, self.canvas_map.winfo_width())
        h = max(100, self.canvas_map.winfo_height())
        self.n_segments = n_segments or 0
        self.seg_meta = list(seg_meta) if seg_meta else []
        ncells = self.n_segments
        if ncells:
            pitch, cols, rows, ox, oy = plan_grid(w, h, ncells)
            self.cell_pitch = pitch
            self.grid_cols = cols
            self.grid_rows = rows
            self.grid_ox = ox
            self.grid_oy = oy
            cell = max(CELL_SIZE_MIN, int(pitch) - CELL_GAP)
            self.cells = [{"median": None, "max": None, "n": 0, "errors": 0}
                          for _ in range(ncells)]
            self.cell_items = []
            for i in range(ncells):
                r, c = divmod(i, cols)   # 行优先：铺满一行再下一行
                x = ox + c * pitch
                y = oy + r * pitch
                self.cell_items.append(self.canvas_map.create_rectangle(
                    x, y, x + cell, y + cell,
                    fill=COLOR_PENDING, outline=""))
        else:
            self.cell_pitch = CELL_SIZE_MIN + CELL_GAP
            self.grid_cols = self.grid_rows = 0
            self.grid_ox = self.grid_oy = 0.0
            self.cells = []
            self.cell_items = []
        self.dirty.clear()

    def _cell_color(self, idx, slow_thr, bad_thr):
        c = self.cells[idx]
        if c["errors"] > 0:
            return COLOR_ERROR
        if c["median"] is None:
            return COLOR_PENDING
        if c["median"] > bad_thr:
            return COLOR_BAD
        if c["median"] > slow_thr:
            return COLOR_SLOW
        return COLOR_OK

    def _flush_cells(self, force=False):
        now = time.time()
        if not force and now - self._last_flush < 0.12:
            return
        self._last_flush = now
        if not self.dirty:
            return
        # 周期性用全体格中位数重算 provisional 阈值
        if now - self._last_thresh_calc > 0.5:
            self._last_thresh_calc = now
            meds = [c["median"] for c in self.cells if c["median"] is not None]
            if meds:
                med = statistics.median(meds)
                self.thresholds = (max(med * 3.0, 10000.0), max(med * 8.0, 100000.0))
        slow_thr, bad_thr = self.thresholds
        items = self.canvas_map
        batch = list(self.dirty)[:4000]
        for idx in batch:
            if idx < len(self.cell_items) and self.cell_items[idx]:
                items.itemconfig(self.cell_items[idx],
                                 fill=self._cell_color(idx, slow_thr, bad_thr))
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

    def _block_to_segment(self, blk_idx):
        """全局块号 → 段格子下标（段起点块号列表二分查找）。
        容量未知时的 [(0, None)] 整盘段会吸收所有块号。"""
        if not self.seg_block_base:
            return 0
        return max(0, min(bisect_right(self.seg_block_base, blk_idx) - 1,
                          len(self.cells) - 1))

    def _handle_event(self, ev):
        et = ev.get("type")
        if et == "seg_stat":
            # 一段读完：段级统计直接决定格子颜色（一格 = 一段）
            idx = ev.get("index", 0)
            if 0 <= idx < len(self.cells):
                c = self.cells[idx]
                c["median"] = ev.get("median_us")
                c["max"] = ev.get("max_us")
                c["n"] = ev.get("n_blocks", 0)
                self.dirty.add(idx)
        elif et == "error_block":
            cell = self._block_to_segment(ev["index"])
            if 0 <= cell < len(self.cells):
                self.cells[cell]["errors"] += 1
                self.dirty.add(cell)
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
            self._lang_menu_state(True)
            self.worker = None
            if self.scan_start_ts and not self.summary:
                self.lbl_state.config(text=tr("gui.state_stopped"),
                                      foreground="#666")

    def _log_raw(self, stream, line):
        """fio 原始输出（英文技术文本，不过 i18n）"""
        self._log_line(stream, line)

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
                foreground="#A32D2D")
        elif ev.get("errors") == 0:
            self.lbl_errors.config(text=tr("gui.errors_none"),
                                   foreground="#3B6D11")

    def _on_finished(self, s):
        self.summary = s
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.progress["value"] = 100
        slow_thr, bad_thr = s["slow_thr_us"], s["bad_thr_us"]
        self.thresholds = (slow_thr, bad_thr)
        # 错误块计入热力图单元格（否则汇总里的错误块不显示颜色）
        for idx in s["error_blocks"]:
            cell = self._block_to_segment(idx)
            if 0 <= cell < len(self.cells):
                self.cells[cell]["errors"] += 1
        # 全量重绘（用最终阈值）
        for i in range(len(self.cells)):
            if i < len(self.cell_items) and self.cell_items[i]:
                self.canvas_map.itemconfig(self.cell_items[i],
                                           fill=self._cell_color(i, slow_thr, bad_thr))
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
                foreground="#A32D2D")
        else:
            self.lbl_errors.config(text=tr("gui.errors_none"),
                                   foreground="#3B6D11")
        self.lbl_state.config(
            text=tr("gui.state_done_aborted") if s["aborted"]
            else tr("gui.state_done"), foreground="#3B6D11")
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
                         bad=s["bad"], err=len(s["error_blocks"]))

    def _on_failed(self, msg):
        self.lbl_state.config(text=tr("gui.state_failed"),
                              foreground="#A32D2D")
        self._log_raw("error", msg)
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
        slow_thr, bad_thr = s["slow_thr_us"], s["bad_thr_us"]
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
        lines.append(tr("gui.sum.bad", n=s["bad"], thr=bad_thr / 1000.0))
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
        off, size, span = (self.seg_meta[idx]
                           if idx < len(self.seg_meta) else (None, None, None))
        blk_start = (self.seg_block_base[idx]
                     if idx < len(self.seg_block_base) else 0)
        key = "gui.hover_region" if self.scan_quick else "gui.hover_segment"
        txt = tr(key, i=idx + 1, n=self.n_segments,
                 off=fmt_bytes(off) if off is not None else "?")
        if size:
            txt += tr("gui.hover_sample" if self.scan_quick else "gui.hover_size",
                      sz=fmt_bytes(size))
            if self.scan_quick and span and span != size:
                txt += tr("gui.hover_region_span", sz=fmt_bytes(span))
        elif size is None and off is not None:
            txt += tr("gui.hover_to_end")
        txt += tr("gui.hover_blocks", b=blk_start, n=cell["n"], e=cell["errors"])
        if cell["median"] is not None:
            txt += tr("gui.hover_median", v=cell["median"] / 1000.0)
            if cell["max"] is not None:
                txt += tr("gui.hover_max", v=cell["max"] / 1000.0)
        self.lbl_hover.config(text=txt)
