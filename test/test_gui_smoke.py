# -*- coding: utf-8 -*-
"""GUI 冒烟测试：用系统 Python（带 tkinter + ttkbootstrap）实例化应用并驱动
各事件处理器。覆盖：英文默认界面、浅色默认主题、语言切换（原地重建界面，
不重启进程）、主题切换（实时 theme_use 换色）、关于窗口、事件流、
完成/错误/快速汇总、横幅替代弹窗。"""
import os
import sys
import time
import types

# 阻止启动时的自动提权弹窗阻塞无人值守测试（见 _startup_admin_check）
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
# 固定英文，保证断言确定（语言切换行为单独验证）
os.environ["HDTUNE_LANG"] = "en"
# 固定浅色主题，保证断言确定（主题切换行为单独验证）
os.environ["HDTUNE_THEME"] = "bootstrap-light"
# 运行日志重定向到临时目录：避免污染真实配置目录；结束前断言内容后清理
import shutil
import tempfile
_LOG_DIR = tempfile.mkdtemp(prefix="HD_Doc_log_")
os.environ["HD_DOC_LOG_DIR"] = _LOG_DIR

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_gui as H
from HD_Doc_core import plan_grid, tr

# 本模块能导入就说明 ttkbootstrap 可用（HD_Doc_gui 顶层 import ttkbootstrap）
root = H.tk.Tk()
root.withdraw()
app = H.HDDocApp()
app.update()          # 等窗口映射/移动请求生效后再断言位置

# ---- 启动时窗口居中 ----
_sw, _sh = app.winfo_screenwidth(), app.winfo_screenheight()
_wx, _wy = app.winfo_x(), app.winfo_y()
assert 0 <= _wx <= _sw and 0 <= _wy <= _sh, (_wx, _wy, _sw, _sh)
assert abs(_wx + app.winfo_width() / 2 - _sw / 2) <= 2, \
    "window should be horizontally centered: x=%d w=%d screen=%d" % (
        _wx, app.winfo_width(), _sw)
assert abs(_wy + app.winfo_height() / 2 - _sh / 2) <= 2, \
    "window should be vertically centered: y=%d h=%d screen=%d" % (
        _wy, app.winfo_height(), _sh)
print("Window centered OK: +%d+%d on %dx%d" % (_wx, _wy, _sw, _sh))

app.withdraw()
app.geometry("1140x820")
app.update()
print("App instantiated OK | canvas %dx%d"
      % (app.canvas_map.winfo_width(), app.canvas_map.winfo_height()))

# ---- 默认英文界面 + 默认浅色主题 ----
assert "HD Doc" in app.title(), app.title()
assert app.style.theme_use() == "bootstrap-light", app.style.theme_use()
admin_txt = app.lbl_admin.cget("text")
assert "Permission" in admin_txt, admin_txt
print("Permission status: %s (is_admin=%s)" % (admin_txt, H.is_admin()))
assert app.btn_start.cget("text") == "Start scan"
assert app.combo_bs["values"][0] == "Auto", app.combo_bs["values"]
# 分段下拉已移除：默认按热力图格数分段（GUI 不再暴露分段大小选择）
assert not hasattr(app, "combo_seg"), "segment dropdown must be removed"

# ---- 热力图双模式（默认健康；可切速度）----
assert app.combo_map_mode["values"] == ("Disk health", "Read speed"), \
    app.combo_map_mode["values"]
assert app.var_map_mode.get() == "Disk health"
assert app.map_mode == H.MAP_MODE_HEALTH
assert "health" in app.map_frame.cget("text").lower(), app.map_frame.cget("text")
# 健康模式图例：正常/错误/未扫描可见，"偏慢"隐藏（winfo_manager 空=未 pack）
assert app._legend_labels[1][0].winfo_manager() == "", \
    "slow swatch must be hidden in health mode"
assert app._legend_labels[0][0].winfo_manager() == "pack"
assert app._legend_labels[2][0].winfo_manager() == "pack"
assert app._legend_labels[3][0].winfo_manager() == "pack"
# 切到速度模式：图例补回"偏慢"，标题换口径
# （注：测试环境的隐藏 root 与 app 是两个 Tcl 解释器，控件→StringVar
#  的回写不跨解释器；处理函数读控件下标、断言也按控件值，真实单窗口
#  应用里两者始终一致）
app.combo_map_mode.current(H.MAP_MODE_SPEED)
app._on_map_mode_toggle()
assert app.map_mode == H.MAP_MODE_SPEED
assert app.combo_map_mode.get() == "Read speed"
assert "read speed" in app.map_frame.cget("text").lower()
assert app._legend_labels[1][0].winfo_manager() == "pack"
# 切回健康模式（往返一致）
app.combo_map_mode.current(H.MAP_MODE_HEALTH)
app._on_map_mode_toggle()
assert app.map_mode == H.MAP_MODE_HEALTH
assert app.combo_map_mode.get() == "Disk health"
assert app._legend_labels[1][0].winfo_manager() == ""
# 无扫描数据时切换不报错（cells 空 → 只更新标题/图例）
assert app.cells == []

# ---- 目标下拉框禁止编辑 ----
assert str(app.combo_target.cget("state")) == "readonly", \
    "target dropdown must not be editable"

# ---- 快速扫描控件（复选框默认关、抽样下拉禁用） ----
assert hasattr(app, "var_quick") and app.var_quick.get() is False
assert str(app.combo_quick_sample.cget("state")) == "disabled"
app.var_quick.set(True)
app._on_quick_toggle()
assert str(app.combo_quick_sample.cget("state")) == "readonly"
app.var_quick.set(False)
app._on_quick_toggle()
assert str(app.combo_quick_sample.cget("state")) == "disabled"
print("Quick-scan controls OK (sample dropdown enabled only when checked)")

# ---- 热力图（固定格数：UI 一致性；withdrawn 窗口布局尺寸为 1x1，
#      monkeypatch 出真实画布尺寸） ----
app.canvas_map.winfo_width = lambda: 1100
app.canvas_map.winfo_height = lambda: 700
N_SEG = 19
BS = 4 << 20
SEG_SIZE = 4 << 20
TOTAL = N_SEG * SEG_SIZE
app.total_size = TOTAL            # 模拟 _start_scan 里查到的容量
app.scan_bs = BS                  # 模拟 _start_scan 里定下的块大小
seg_meta = [(i * SEG_SIZE, SEG_SIZE, None) for i in range(N_SEG)]
app._reset_map(seg_meta)
print("Heatmap %d cells (%d cols x %d rows, pitch=%.1fpx, fixed count) OK"
      % (len(app.cells), app.grid_cols, app.grid_rows, app.cell_pitch))
# 固定格数：段多段少都是 MAP_CELLS 格、同一套布局（UI 一致性——
# 换盘/换分段方式不再改变热力图的格数与形状）
assert len(app.cells) == H.MAP_CELLS == 256, len(app.cells)
assert len(app.cell_items) == 256
assert app.grid_cols * app.grid_rows >= 256
assert app.grid_ox + app.grid_cols * app.cell_pitch <= 1100 + 1e-6
assert app.grid_oy + app.grid_rows * app.cell_pitch <= 700 + 1e-6
# 格按字节范围均分：首格 [0, TOTAL/256)，末格到 TOTAL
assert app.cell_span[0] == (0, TOTAL // 256), app.cell_span[0]
assert app.cell_span[-1][1] == TOTAL, app.cell_span[-1]
# 段 → 格映射：19 段铺满 256 格（每段约 13~14 格，边界格可被两段覆盖）
assert len(app.seg_cells) == N_SEG
assert app.seg_cells[0][0] == 0 and app.seg_cells[-1][-1] == 255
assert sum(len(s) for s in app.seg_cells) >= 256
# plan_grid 纯函数：固定 256 格在常见画布下都放得下且不超出
_g256 = plan_grid(1100, 350, 256)
assert _g256[1] * _g256[2] >= 256
assert _g256[4] + _g256[2] * _g256[0] <= 350 + 1e-6

# ---- 事件流（经 _handle_event 分发，与真实队列消费路径一致） ----
app._handle_event({"type": "segment", "index": 0, "total": N_SEG,
                   "offset": 0, "size": SEG_SIZE})
app._handle_event({"type": "tick", "segment": 0, "io_bytes": 40000000,
                   "bw_bytes": 1500000000, "errors": 0, "pct": None})
for i in range(N_SEG):
    app._handle_event({"type": "seg_stat", "index": i,
                       "median_us": 2200.0 + i * 10, "max_us": 2400.0 + i * 10,
                       "n_blocks": 1024})
app._handle_event({"type": "error_block", "index": 5})   # 块 5 → 偏移 20MB → 格 67
app._handle_event({"type": "log", "stream": "info", "line": "test log"})
app._handle_event({"type": "log", "stream": "warn", "line": "test warn"})
app._handle_event({"type": "log", "stream": "stderr", "line": "fio: test"})
app._update_status(50.0, 1500000000, 26, 0)
app.update()
print("Event flow OK | hover: %r" % app.lbl_hover.cget("text"))
# 块 5（偏移 20MB）→ 格 67；段 18 覆盖末尾诸格（格 255 拿到段 18 的中位数）
print("Cell 0: median=%.1f n=%d | cell67 errors=%d | cell255 median=%.1f"
      % (app.cells[0]["median"], app.cells[0]["n"],
         app.cells[67]["errors"], app.cells[255]["median"]))
assert app.cells[67]["errors"] == 1
assert app.cells[255]["median"] == 2200.0 + 18 * 10
# 聚合：边界格被两段覆盖时块数求和、中位数按块数加权（格 13 = 段0+段1）
assert app.cells[13]["n"] == 2048, app.cells[13]["n"]
assert app.cells[13]["median"] == 2200.0, app.cells[13]["median"]

# ---- 悬停（行优先：最后一个格子；坐标按 pitch 与居中偏移反算到格内） ----
last = len(app.cells) - 1
r, c = divmod(last, app.grid_cols)
ev = types.SimpleNamespace(
    x=int(app.grid_ox + c * app.cell_pitch + app.cell_pitch / 2),
    y=int(app.grid_oy + r * app.cell_pitch + app.cell_pitch / 2))
app._on_canvas_motion(ev)
hover = app.lbl_hover.cget("text")
print("Hover info: %r" % hover)
assert hover, "hover info should not be empty"
assert "Cell #256/256" in hover and "offset" in hover, \
    "hover should contain cell number and byte range"
_a, _b = app.cell_span[last]
assert H.fmt_bytes(_a) in hover and H.fmt_bytes(_b) in hover, hover
assert "median latency" in hover, "hover should contain median latency"
assert "start block %d" % (_a // BS) in hover, hover

# ---- 完成事件（合成汇总） ----
summary = {
    "target": "C:/x/test.img", "bs": BS, "ioengine": "windowsaio", "direct": True,
    "total_size": N_SEG * SEG_SIZE, "quick": False, "segments": [{
        "index": 0, "offset": 0, "size": N_SEG * SEG_SIZE, "blocks": N_SEG * 1024,
        "errno": 0,
        "errno_name": "", "actual_ios": N_SEG * 1024,
        "expected_ios": N_SEG * 1024,
        "median_us": 2200.0, "max_us": 2400.0, "runtime_ms": 55,
        "bw_bytes": 1400000000}],
    "n_blocks": N_SEG * 1024, "ok": N_SEG * 1024, "slow": 0,
    "error_blocks": {},
    "unlocated_errors": 0, "median_us": 2250.0, "mean_us": 2255.0, "max_us": 2400.0,
    "p99_us": 2400.0, "slow_thr_us": 30000.0,
    "elapsed_s": 3.0, "aborted": False, "errno_segments": 0, "last_errno": 0,
    "last_errno_name": "", "unscanned_bytes": 0, "json_errors": 0,
    "first_error_offset": None, "tmpdir": "", "fio": "fio",
}
# 桩掉所有弹窗：完成路径不应弹任何窗（结果只进横幅/汇总页）
popped = []
H.Messagebox.show_warning = lambda *a, **k: popped.append(("warning", a))
H.Messagebox.show_info = lambda *a, **k: popped.append(("info", a))
H.Messagebox.show_error = lambda *a, **k: popped.append(("error", a))
H.Messagebox.yesno = lambda *a, **k: popped.append(("yesno", a))
app._on_finished(summary)
app.update()
print("Finish event OK | summary %d chars" % len(app.txt_summary.get("1.0", "end")))
print("Export button state: %s" % app.btn_export.cget("state"))
assert not popped, "clean scan must not pop any dialog: %r" % (popped,)
assert "Scan complete" in app.lbl_banner.cget("text"), app.lbl_banner.cget("text")
assert "Block size" in app.txt_summary.get("1.0", "end")

# ---- 错误场景汇总（错误展示路径 + 错误块按字节偏移映射到格 + error 级横幅） ----
summary2 = dict(summary)
summary2["error_blocks"] = {5: "fio read failure EIO (offset 20971520)"}
summary2["errno_segments"] = 1
summary2["last_errno"] = 5
summary2["last_errno_name"] = H.errno_name(5)
summary2["unscanned_bytes"] = 8388608
app._on_finished(summary2)
app.update()
print("Error scenario OK | error tree rows: %d | cell67 errors=%d"
      % (len(app.tree_err.get_children()), app.cells[67]["errors"]))
assert len(app.tree_err.get_children()) == 1
assert "error blocks" in app.lbl_banner.cget("text")
assert not popped, "error result must use the in-app banner, not dialogs: %r" % (popped,)

# ---- 快速扫描汇总（覆盖率行） ----
summary3 = dict(summary)
summary3["quick"] = True
summary3["segments"] = [{
    "index": i, "offset": i * (8 << 30), "size": 16 << 20, "blocks": 4,
    "errno": 0, "errno_name": "", "actual_ios": 4, "expected_ios": 4,
    "median_us": 2200.0, "max_us": 2400.0, "runtime_ms": 55,
    "bw_bytes": 1400000000} for i in range(4)]
summary3["error_blocks"] = {}
app._on_finished(summary3)
app.update()
txt = app.txt_summary.get("1.0", "end")
assert "quick scan" in txt and "% of capacity" in txt, \
    "quick-scan summary should contain the coverage line"
print("Quick-scan summary OK (with coverage line)")

# ---- 语言切换：原地重建界面（不重启进程）----
import HD_Doc_core as core

# 先 seed 一条可翻译日志：切换后应按新语言重放
# （旧实现靠 execv 重启重载，本条验证结构化日志机制）
app._log("info", "gui.log.admin_ok")

class _LiveWorker:
    def is_alive(self):
        return True

# 扫描中切换：不再禁止——重建只换控件，不动扫描线程/fio 子进程
live = _LiveWorker()
app.summary = None                      # 模拟"扫描进行中、尚无结果"
app._set_state("gui.state_scanning")    # 与 _start_scan 同一入口
app.worker = live
app.combo_map_mode.current(H.MAP_MODE_SPEED)   # 重建前切到速度模式
app._on_map_mode_toggle()
app._set_language("zh")
app.update()
assert core.get_language() == "zh"
assert core.load_config().get("language") == "zh", \
    "choice must persist to config"
assert app.btn_start.cget("text") == "▶ 开始扫描", app.btn_start.cget("text")
# 扫描状态跨重建保留（旧实现重启后全丢，才被迫禁止扫描中切换）
assert str(app.btn_start.cget("state")) == "disabled", "start stays disabled"
assert str(app.btn_stop.cget("state")) == "normal", "stop stays enabled"
assert app.worker is live, "rebuild must not touch the scan thread"
assert app.lbl_state.cget("text") == "扫描中…", app.lbl_state.cget("text")
# 热力图模式跨重建保留（快照下标恢复；格子颜色由地图块按新模式重绘）
assert app.map_mode == H.MAP_MODE_SPEED, "heatmap mode must survive rebuild"
assert app.combo_map_mode.get() == "磁盘读取速度热力图", \
    app.combo_map_mode.get()
# 热力图数据跨重建保留（格数固定 256；错误块经 live 事件与汇总去重后
# cell67 errors=1，不重复计数）
assert len(app.cells) == H.MAP_CELLS, len(app.cells)
assert app.cells[67]["errors"] == 1
assert app.cells[255]["median"] == 2200.0 + 18 * 10
# 日志：可翻译条目按新语言重放；fio 原始输出原样保留（不过 i18n）
log_zh = app.txt_log.get("1.0", "end")
assert "管理员" in log_zh, log_zh
assert "fio: test" in log_zh, "raw fio output must survive verbatim"
app.worker = None
print("Language switch during scan OK (in-place rebuild; scan state kept)")

# 正常切换（带回已完成的结果）：结果区按新语言重放，选择持久化
app.summary = summary                   # 还原一轮已完成扫描
app._set_language("en")                 # zh → en 反向切换
app.update()
assert core.get_language() == "en"
assert app.btn_start.cget("text") == "Start scan"
assert app.map_mode == H.MAP_MODE_SPEED, "mode survives zh→en rebuild too"
assert app.combo_map_mode.get() == "Read speed"
assert "Block size" in app.txt_summary.get("1.0", "end"), \
    "summary page must be re-rendered in the new language"
assert "Scan complete" in app.lbl_banner.cget("text"), \
    "banner must be replayed in the new language"
assert app.nb.select() == str(app.txt_summary), "selected tab must be kept"
assert len(app.cells) == H.MAP_CELLS and app.cells[67]["errors"] == 1
app._set_language("en")
assert app.btn_start.cget("text") == "Start scan", "same language is a no-op"
# 还原空闲态与默认模式（后续用例不关心，保持界面自洽）
app.combo_map_mode.current(H.MAP_MODE_HEALTH)
app._on_map_mode_toggle()
app.btn_start.config(state="normal")
app.btn_stop.config(state="disabled")
print("Language switch OK (in-place rebuild; results/log/banner replayed)")

# ---- 主题切换：实时 theme_use（不重启进程，UI 不重建）----
app.worker = _LiveWorker()              # 扫描中同样允许切换
app._set_theme("bootstrap-dark")
app.update()
assert core.get_theme() == "bootstrap-dark"
assert core.load_config().get("theme") == "bootstrap-dark", \
    "theme choice must persist to config"
assert app.style.theme_use() == "bootstrap-dark"
# 原生 tk 控件同步到新主题色板（ttk 控件由主题引擎自动换色）
assert str(app.canvas_map.cget("bg")).lower() == app.style.colors.bg.lower()
for swatch in app._legend_swatches:
    assert str(swatch.cget("highlightbackground")).lower() \
        == app.style.colors.border.lower()
# 主题切换不重建界面：控件原样（英文文案还在即证明未重建）
assert app.btn_start.cget("text") == "Start scan"
assert app.worker is not None
app.worker = None
app._set_theme("bootstrap-dark")        # 同主题不重复动作
assert app.style.theme_use() == "bootstrap-dark"
# 切回浅色，避免影响后续用例
app._set_theme("bootstrap-light")
app.update()
assert app.style.theme_use() == "bootstrap-light"
assert str(app.canvas_map.cget("bg")).lower() == app.style.colors.bg.lower()
print("Theme switch OK (live theme_use; native widgets follow)")

# ---- 关于窗口（一行简介，无作者行，图标限制大小，标题栏图标走 iconphoto） ----
# 记录 _show_about 对 iconphoto 的调用：标题栏图标必须走 iconphoto 且用
# 缩放版（iconbitmap 渲染不了 PNG 压缩的 .ico → 标题栏图标空白）
_iconphoto_calls = []
_orig_iconphoto = H.tk.Wm.iconphoto


def _spy_iconphoto(self, default=False, *args):
    _iconphoto_calls.append((default, args))
    return _orig_iconphoto(self, default, *args)


H.tk.Wm.iconphoto = _spy_iconphoto
try:
    app._show_about()
    app.update()
finally:
    H.tk.Wm.iconphoto = _orig_iconphoto
about_win = [w for w in app.winfo_children() if w.winfo_class() == "Toplevel"]
assert about_win, "About window should open"
about_labels = [w for w in about_win[0].winfo_children()[0].winfo_children()
                if w.winfo_class() in ("Label", "TLabel")]
assert about_labels, "About should show a one-line label"
about_txt = about_labels[0].cget("text")
assert "HD Doc" in about_txt, about_txt
assert "Author" not in about_txt and "作者" not in about_txt, about_txt
assert "\n" not in about_txt, "About must be a single line: %r" % about_txt
# 弹窗内图标必须被 _bounded_photo 限制大小（原图 1248px 会撑爆对话框）
def _descendants(w):
    for c in w.winfo_children():
        yield c
        yield from _descendants(c)
about_imgs = []
for w in _descendants(about_win[0]):
    if w.winfo_class() not in ("Label", "TLabel"):
        continue
    v = w.cget("image")          # 带图的标签返回 ('pyimageN',)，无图返回 ''
    if isinstance(v, (tuple, list)):
        v = v[0] if v else ""
    if v:
        about_imgs.append(v)
assert about_imgs, "About dialog should show the app icon"
assert about_imgs[0] == str(app._about_icon), \
    "about dialog must show the bounded icon copy, not the full-size one: %r" % (
        about_imgs,)
assert max(app._about_icon.width(), app._about_icon.height()) <= H.ABOUT_ICON_PX, \
    "about icon must be bounded to %dpx: got %dx%d" % (
        H.ABOUT_ICON_PX, app._about_icon.width(), app._about_icon.height())
# 标题栏图标：必须通过 iconphoto 设置（iconbitmap 对 PNG 压缩的 .ico 静默
# 无效果，标题栏图标就是空白），且必须用 48px 缩放版而非 1248px 原图
assert any(a and a[0] is app._about_icon for _d, a in _iconphoto_calls), \
    "About dialog must set its title-bar icon via iconphoto (bounded copy): %r" % (
        _iconphoto_calls,)
print("About window OK (one-line intro, no author line, icon %dx%d <= %dpx, "
      "title-bar icon via iconphoto)"
      % (app._about_icon.width(), app._about_icon.height(), H.ABOUT_ICON_PX))
# 弹窗按钮必须 i18n（本测试固定英文 → "OK"）；弹窗必须真正获焦：
# 模态 grab 落在弹窗上、键盘焦点落在"确定"按钮（回车即关）、Escape 也能关
about_btns = [w for w in _descendants(about_win[0])
              if w.winfo_class() == "TButton"]
assert about_btns, "About dialog should have an OK button"
assert about_btns[0].cget("text") == tr("gui.about.ok"), \
    "OK button must be localized: %r" % (about_btns[0].cget("text"),)
assert about_win[0].grab_current() is about_win[0], \
    "About dialog must take the modal grab"
assert app.focus_get() is about_btns[0], \
    "About dialog must focus its OK button: focus=%r" % (app.focus_get(),)
about_win[0].event_generate("<Escape>")
app.update()
assert not [w for w in app.winfo_children() if w.winfo_class() == "Toplevel"], \
    "Escape must close the About dialog"
print("About focus/i18n OK (grab on dialog, focus on OK button, Escape closes)")

# ---- 目标下拉框：只显示 型号+容量，路径走 _target_paths 映射 ----
app._refresh_drives()
app.update()
vals = list(app.combo_target["values"])
if vals:   # 本机枚举到物理盘时才断言（无盘/权限受限时空列表也合法）
    for v in vals:
        assert "PhysicalDrive" not in v, \
            "target dropdown must show model+capacity only: %r" % v
    assert app._target_paths, "label→path mapping must be populated"
    assert all(p.startswith("\\\\.\\PhysicalDrive") or p.lower().startswith("//./")
               for p in app._target_paths.values()), app._target_paths
    assert app.var_target.get() in app._target_paths or not app.var_target.get()
print("Drive labels OK (model + capacity only, %d drives, mapping=%d)"
      % (len(vals), len(app._target_paths)))

# ---- Linux 适配：目标下拉无型号时显示内核名（sda/nvme0n1）而非 Disk N ----
import unittest.mock as _mock


class _FakePopen:
    """假 Popen：模拟 pkexec 子进程（rc=None 表示仍存活）"""
    def __init__(self, rc=None):
        self.returncode = rc
        self.pid = 4242

    def poll(self):
        return self.returncode


_saved_iswin = H.IS_WIN
H.IS_WIN = False
try:
    with _mock.patch.object(H, "list_drives", return_value=[
            {"index": 0, "path": "/dev/sda", "size": 1000204886016,
             "model": "WDC WD10EZEX-22MFCA0", "bus": "sata"},
            {"index": 1, "path": "/dev/nvme0n1", "size": 500107862016,
             "model": "", "bus": "nvme"}]):
        app._refresh_drives()
        app.update()
        vals = list(app.combo_target["values"])
    assert len(vals) == 2, vals
    assert vals[0].startswith("WDC WD10EZEX"), vals
    assert vals[1].startswith("nvme0n1") and "Disk" not in vals[1], vals
    assert app._target_paths.get(vals[0]) == "/dev/sda", app._target_paths
    print("Linux drive labels OK (model, or kernel name fallback): %r" % (vals,))

    # ---- Linux 提权场景 1：pkexec 很快退出（授权取消/失败）→ 窗口保留 ----
    # 旧版 after(200) 无条件退出：授权被取消时窗口直接消失且无提示=闪退
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(126), None)):
        app._relaunch_elevated()
    time.sleep(0.25)          # 等 after(150, _poll_pkexec) 到期
    app.update()
    assert app.winfo_exists(), "pkexec 失败时窗口必须保留（不能闪退）"
    assert app._pkexec_popen is None
    banner = app.lbl_banner.cget("text")
    assert "126" in banner and "Elevation" in banner, banner
    print("Elevation cancelled OK (window kept, banner shows exit 126)")

    # ---- 场景 2：pkexec 存活（授权进行中）→ 轮询期满退出本窗口 ----
    # ttkbootstrap 只允许单根窗口，不能新建第二个 App：用记录器替换
    # _exit_now（验证"会退出"而不真销毁）
    exited = []
    _real_exit_now = app._exit_now
    app._exit_now = lambda: exited.append(True)
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(None), None)):
        app._relaunch_elevated()
    app._pkexec_polls = 1     # 只轮一次即移交（不必真等 3 秒）
    time.sleep(0.25)
    app.update()
    assert exited, "授权进行中应在轮询期满后退出本窗口（移交提权实例）"
    assert "Waiting for authorization" in app.lbl_banner.cget("text")
    app._exit_now = _real_exit_now
    print("Elevation handover OK (window exits once authorization is up)")

    # ---- 场景 3：无 pkexec → 横幅报错，窗口保留 ----
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(None, "pkexec not found")):
        app._relaunch_elevated()
    app.update()
    assert app.winfo_exists()
    assert "pkexec not found" in app.lbl_banner.cget("text")
    print("No-pkexec OK (banner error, window kept)")

    # ---- 场景 4：ensure_admin_at_startup 在 Linux 也发起提权 ----
    with _mock.patch.object(H, "is_admin", return_value=False), \
         _mock.patch.object(H, "auto_elevate_enabled", return_value=True), \
         _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(126), None)):
        assert H.ensure_admin_at_startup() is False, \
            "授权失败应返回 False（标准权限继续启动）"
    _clock = [0.0]

    def _fake_monotonic():
        _clock[0] += 1.0
        return _clock[0]

    with _mock.patch.object(H, "is_admin", return_value=False), \
         _mock.patch.object(H, "auto_elevate_enabled", return_value=True), \
         _mock.patch.object(H.time, "sleep", lambda s: None), \
         _mock.patch.object(H.time, "monotonic", _fake_monotonic), \
         _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(None), None)):
        assert H.ensure_admin_at_startup() is True, \
            "授权进行中应返回 True（提权实例接管，本进程退出）"
    print("ensure_admin_at_startup(Linux) OK (cancel→False, auth→True)")
finally:
    H.IS_WIN = _saved_iswin
    app._refresh_drives()
    app.update()

# ---- 日志自动滚动到底部 ----
app.txt_log.delete("1.0", "end")
for i in range(120):
    app._log_line("info", "scroll probe line %d" % i)
app.update()
_y0, _y1 = app.txt_log.yview()
assert _y1 >= 0.999, "log should stay scrolled to the last line: yview=%r" % ((_y0, _y1),)
print("Log auto-scroll OK (120 lines, yview bottom=%.3f)" % _y1)

# ---- 程序图标（标题栏 ico + 任务栏 png） ----
assert app._icon_img is not None, "window icon (img/HD_Doc.png) should be loaded"
print("Window icon OK (iconphoto set)")

# ---- 失败路径（不弹窗，走横幅） ----
popped.clear()
app._on_failed("test failure message")
app.update()
assert not popped, "failure must use the in-app banner, not dialogs: %r" % (popped,)
assert "test failure message" in app.lbl_banner.cget("text")

# ---- Tk 回调异常必须落运行日志（默认只打印 stderr，打包版不可见） ----
app.after(5, lambda: 1 / 0)
time.sleep(0.15)          # 等定时器到期：update() 只处理已就绪的事件
app.update()
app.update()

# ---- 运行日志：单文件，含启动/扫描结果/失败/回调异常 ----
_log_file = os.path.join(_LOG_DIR, "HD_Doc.log")
assert os.path.isfile(_log_file), "run log should exist at %s" % _log_file
_log_txt = open(_log_file, encoding="utf-8").read()
for _needle in ("gui: start", "scan: finished", "scan: failed",
                "tk callback exception", "ZeroDivisionError"):
    assert _needle in _log_txt, "run log should contain %r:\n%s" % (
        _needle, _log_txt[-800:])
assert os.listdir(_LOG_DIR) == ["HD_Doc.log"], \
    "exactly one log file: %r" % (os.listdir(_LOG_DIR),)
print("Run log OK (single file %s, %d bytes)"
      % (_log_file, os.path.getsize(_log_file)))

app.destroy()
root.destroy()
shutil.rmtree(_LOG_DIR, ignore_errors=True)
print("\nGUI smoke test: all passed")
