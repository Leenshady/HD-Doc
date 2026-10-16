# -*- coding: utf-8 -*-
"""GUI 冒烟测试：用系统 Python（带 tkinter + ttkbootstrap）实例化应用并驱动
各事件处理器。覆盖：英文默认界面、浅色默认主题、语言切换（原地重建界面，
不重启进程）、主题切换（实时 theme_use 换色）、关于窗口、事件流、
完成/错误/快速汇总、横幅替代弹窗。"""
import os
import sys
import types

# 阻止启动时的自动提权弹窗阻塞无人值守测试（见 _startup_admin_check）
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
# 固定英文，保证断言确定（语言切换行为单独验证）
os.environ["HDTUNE_LANG"] = "en"
# 固定浅色主题，保证断言确定（主题切换行为单独验证）
os.environ["HDTUNE_THEME"] = "bootstrap-light"

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
assert "Whole disk at once" in app.combo_seg["values"][0]

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

# ---- 热力图（withdrawn 窗口布局尺寸为 1x1，monkeypatch 出真实画布尺寸） ----
app.canvas_map.winfo_width = lambda: 1100
app.canvas_map.winfo_height = lambda: 700
N_SEG = 19
BS = 4 << 20
SEG_SIZE = 4 << 20
seg_meta = [(i * SEG_SIZE, SEG_SIZE, None) for i in range(N_SEG)]
app._reset_map(N_SEG, seg_meta)
# 段起点块号表（每段 1024 块）——error_block → 格子 的映射依据
app.seg_block_base = [i * 1024 for i in range(N_SEG)]
print("Heatmap %d cells (%d cols x %d rows, pitch=%.1fpx, adaptive tiling) OK"
      % (len(app.cells), app.grid_cols, app.grid_rows, app.cell_pitch))
assert len(app.cells) == N_SEG
# 自适应平铺：格子远大于旧的固定 6px；cols*rows 覆盖全部段；网格不超出画布
assert app.cell_pitch > 20, app.cell_pitch
assert app.grid_cols * app.grid_rows >= N_SEG
assert app.grid_ox + app.grid_cols * app.cell_pitch <= 1100 + 1e-6
assert app.grid_oy + app.grid_rows * app.cell_pitch <= 700 + 1e-6
# plan_grid 纯函数：段数少→格子封顶；段数多(1862)→格子更小；极端段数全可见
p_few = plan_grid(1100, 700, 4)[0]
p_many = plan_grid(1100, 700, 1862)[0]
assert p_few <= H.CELL_SIZE_MAX and p_many < p_few, (p_few, p_many)
assert plan_grid(1100, 700, 5000)[1] * plan_grid(1100, 700, 5000)[2] >= 5000

# ---- 事件流（经 _handle_event 分发，与真实队列消费路径一致） ----
app._handle_event({"type": "segment", "index": 0, "total": N_SEG,
                   "offset": 0, "size": SEG_SIZE})
app._handle_event({"type": "tick", "segment": 0, "io_bytes": 40000000,
                   "bw_bytes": 1500000000, "errors": 0, "pct": None})
for i in range(N_SEG):
    app._handle_event({"type": "seg_stat", "index": i,
                       "median_us": 2200.0 + i * 10, "max_us": 2400.0 + i * 10,
                       "n_blocks": 1024})
app._handle_event({"type": "error_block", "index": 5})   # 块 5 → 段 0
app._handle_event({"type": "log", "stream": "info", "line": "test log"})
app._handle_event({"type": "log", "stream": "warn", "line": "test warn"})
app._handle_event({"type": "log", "stream": "stderr", "line": "fio: test"})
app._update_status(50.0, 1500000000, 26, 0)
app.update()
print("Event flow OK | hover: %r" % app.lbl_hover.cget("text"))
print("Cell 0: median=%.1f n=%d errors=%d"
      % (app.cells[0]["median"], app.cells[0]["n"], app.cells[0]["errors"]))
assert app.cells[0]["errors"] == 1
assert app.cells[18]["median"] == 2200.0 + 18 * 10

# ---- 悬停（横向行优先：最后一个格子 → 第 r 行第 c 列，坐标按自适应 pitch 反算） ----
last = len(app.cells) - 1
r, c = divmod(last, app.grid_cols)
ev = types.SimpleNamespace(
    x=int(app.grid_ox + c * app.cell_pitch + app.cell_pitch / 2),
    y=int(app.grid_oy + r * app.cell_pitch + app.cell_pitch / 2))
app._on_canvas_motion(ev)
hover = app.lbl_hover.cget("text")
print("Hover info: %r" % hover)
assert hover, "hover info should not be empty"
assert ("Segment #%d/%d" % (last + 1, N_SEG)) in hover and "offset" in hover, \
    "hover should contain segment number and offset"
assert "median latency" in hover and "block 18432 on" in hover, \
    "hover should contain median latency and start block"

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
    "n_blocks": N_SEG * 1024, "ok": N_SEG * 1024, "slow": 0, "bad": 0,
    "error_blocks": {},
    "unlocated_errors": 0, "median_us": 2250.0, "mean_us": 2255.0, "max_us": 2400.0,
    "p99_us": 2400.0, "slow_thr_us": 30000.0, "bad_thr_us": 100000.0,
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

# ---- 错误场景汇总（错误展示路径 + 错误块映射到段格子 + error 级横幅） ----
summary2 = dict(summary)
summary2["error_blocks"] = {5: "fio read failure EIO (offset 20971520)"}
summary2["errno_segments"] = 1
summary2["last_errno"] = 5
summary2["last_errno_name"] = H.errno_name(5)
summary2["unscanned_bytes"] = 8388608
app._on_finished(summary2)
app.update()
print("Error scenario OK | error tree rows: %d | cell0 errors=%d"
      % (len(app.tree_err.get_children()), app.cells[0]["errors"]))
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
# 热力图数据跨重建保留（errors=2：事件流 1 次 + 错误场景汇总 1 次）
assert len(app.cells) == N_SEG, len(app.cells)
assert app.cells[0]["errors"] == 2
assert app.cells[18]["median"] == 2200.0 + 18 * 10
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
assert "Block size" in app.txt_summary.get("1.0", "end"), \
    "summary page must be re-rendered in the new language"
assert "Scan complete" in app.lbl_banner.cget("text"), \
    "banner must be replayed in the new language"
assert app.nb.select() == str(app.txt_summary), "selected tab must be kept"
assert len(app.cells) == N_SEG and app.cells[0]["errors"] == 2
app._set_language("en")
assert app.btn_start.cget("text") == "Start scan", "same language is a no-op"
# 还原空闲态按钮（后续用例不关心，保持界面自洽）
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

# ---- 关于窗口（一行简介，无作者行） ----
app._show_about()
app.update()
about_win = [w for w in app.winfo_children() if w.winfo_class() == "Toplevel"]
assert about_win, "About window should open"
about_labels = [w for w in about_win[0].winfo_children()[0].winfo_children()
                if w.winfo_class() in ("Label", "TLabel")]
assert about_labels, "About should show a one-line label"
about_txt = about_labels[0].cget("text")
assert "HD Doc" in about_txt, about_txt
assert "Author" not in about_txt and "作者" not in about_txt, about_txt
assert "\n" not in about_txt, "About must be a single line: %r" % about_txt
print("About window OK (one-line intro, no author line)")

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

app.destroy()
root.destroy()
print("\nGUI smoke test: all passed")
