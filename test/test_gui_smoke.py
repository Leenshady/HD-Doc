# -*- coding: utf-8 -*-
"""GUI 冒烟测试：用系统 Python（带 PyQt5）实例化应用并驱动各事件处理器。
覆盖：英文默认界面、浅色默认主题、语言切换（原地重建界面，不重启进程）、
主题切换（实时换 QSS）、关于窗口、事件流、完成/错误/快速汇总、横幅替代
弹窗、逐格渲染。

offscreen 平台：QT_QPA_PLATFORM=offscreen，无显示环境（CI/远程）也能跑；
逻辑与真实窗口完全一致（布局/绘制/定时器都走同一套代码）。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
import HD_Doc_gui as H
from HD_Doc_core import plan_grid, tr

# 本模块能导入就说明 PyQt5 可用（HD_Doc_gui 顶层 import PyQt5）
qt_app = QApplication.instance() or QApplication(sys.argv)
app = H.HDDocApp()
app.show()
QApplication.processEvents()   # 等布局/几何请求生效后再断言


def _pe():
    QApplication.processEvents()


# ---- 启动时窗口居中 ----
from PyQt5.QtWidgets import QDesktopWidget
_geo = QDesktopWidget().availableGeometry(app)
_g = app.geometry()
assert _g.x() >= 0 and _g.y() >= 0, (_g.x(), _g.y())
# offscreen 虚拟屏幕可能小于设计尺寸（800x600）：窗口放不下时无居中可言
# （_center_on_screen 里 max(0, ...) 夹到 0），只校验"不出界"
if _geo.width() >= _g.width() and _geo.height() >= _g.height():
    assert _g.x() <= max(0, _geo.width() - _g.width()), (_g.x(), _geo.width())
    assert _g.y() <= max(0, _geo.height() - _g.height()), (_g.y(), _geo.height())
    assert abs(_g.x() + _g.width() / 2 - _geo.width() / 2) <= 2, \
        "window should be horizontally centered: %r geo=%r" % (_g, _geo)
    assert abs(_g.y() + _g.height() / 2 - _geo.height() / 2) <= 2, \
        "window should be vertically centered: %r geo=%r" % (_g, _geo)
    print("Window centered OK: %r on %dx%d" % (_g, _geo.width(), _geo.height()))
else:
    print("Window position OK (offscreen screen %dx%d smaller than window %dx%d)"
          % (_geo.width(), _geo.height(), _g.width(), _g.height()))

app.resize(1140, 820)
_pe()
print("App instantiated OK | map %dx%d"
      % (app.map_widget.width(), app.map_widget.height()))

# ---- 默认英文界面 + 默认浅色主题 ----
assert "HD Doc" in app.windowTitle(), app.windowTitle()
_qss = QApplication.instance().styleSheet()
assert "#f0f0f0" in _qss and "#1f1f1f" in _qss, \
    "light theme QSS should be applied: %r" % _qss[:120]
admin_txt = app.lbl_admin.text()
assert "Permission" in admin_txt, admin_txt
print("Permission status: %s (is_admin=%s)" % (admin_txt, H.is_admin()))
assert app.btn_start.text() == "Start scan"
assert app.combo_bs.itemText(0) == "Auto", \
    [app.combo_bs.itemText(i) for i in range(app.combo_bs.count())]
# 分段下拉恢复：默认 4G，可选整盘一次/512M/1G/2G/4G/8G/16G/32G/64G
_vals = [app.combo_seg.itemText(i) for i in range(app.combo_seg.count())]
assert "Whole disk at once" in _vals[0], _vals
assert app.combo_seg.currentText() == "4G", app.combo_seg.currentText()

# ---- 热力图双模式（默认健康；可切速度）----
assert [app.combo_map_mode.itemText(i)
        for i in range(app.combo_map_mode.count())] == \
    ["Disk health", "Read speed"], app.combo_map_mode.count()
assert app.combo_map_mode.currentText() == "Disk health"
assert app.map_mode == H.MAP_MODE_HEALTH
assert "health" in app.map_frame.title().lower(), app.map_frame.title()
# 健康模式图例：正常/错误/未扫描可见，"偏慢"隐藏
assert app._legend_labels[1][0].isVisible() is False, \
    "slow swatch must be hidden in health mode"
assert app._legend_labels[0][0].isVisible() is True
assert app._legend_labels[2][0].isVisible() is True
assert app._legend_labels[3][0].isVisible() is True
# 切到速度模式：图例补回"偏慢"，标题换口径
app.combo_map_mode.setCurrentIndex(H.MAP_MODE_SPEED)
app._on_map_mode_toggle()
assert app.map_mode == H.MAP_MODE_SPEED
assert app.combo_map_mode.currentText() == "Read speed"
assert "read speed" in app.map_frame.title().lower()
assert app._legend_labels[1][0].isVisible() is True
# 切回健康模式（往返一致）
app.combo_map_mode.setCurrentIndex(H.MAP_MODE_HEALTH)
app._on_map_mode_toggle()
assert app.map_mode == H.MAP_MODE_HEALTH
assert app.combo_map_mode.currentText() == "Disk health"
assert app._legend_labels[1][0].isVisible() is False
# 无扫描数据时切换不报错（cells 空 → 只更新标题/图例）
assert app.cells == []

# ---- 目标下拉框禁止编辑 ----
assert not app.combo_target.isEditable(), \
    "target dropdown must not be editable"

# ---- 快速扫描控件（复选框默认关、抽样下拉禁用） ----
assert app.chk_quick.isChecked() is False
assert app.combo_quick_sample.isEnabled() is False
app.chk_quick.setChecked(True)
app._on_quick_toggle()
assert app.combo_quick_sample.isEnabled() is True
app.chk_quick.setChecked(False)
app._on_quick_toggle()
assert app.combo_quick_sample.isEnabled() is False
print("Quick-scan controls OK (sample dropdown enabled only when checked)")

# ---- 热力图（固定格数：UI 一致性）----
app.map_widget.resize(1100, 700)     # offscreen 下显式给地图部件尺寸
_pe()
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
_pe()
print("Event flow OK | hover: %r" % app.lbl_hover.text())
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
app._on_map_hover(int(app.grid_ox + c * app.cell_pitch + app.cell_pitch / 2),
                  int(app.grid_oy + r * app.cell_pitch + app.cell_pitch / 2))
hover = app.lbl_hover.text()
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
H.QMessageBox.warning = lambda *a, **k: popped.append(("warning", a))
H.QMessageBox.information = lambda *a, **k: popped.append(("info", a))
H.QMessageBox.critical = lambda *a, **k: popped.append(("error", a))
H.QMessageBox.question = lambda *a, **k: popped.append(("yesno", a))
app._on_finished(summary)
_pe()
print("Finish event OK | summary %d chars" % len(app.txt_summary.toPlainText()))
print("Export button enabled: %s" % app.btn_export.isEnabled())
assert not popped, "clean scan must not pop any dialog: %r" % (popped,)
assert "Scan complete" in app.lbl_banner.text(), app.lbl_banner.text()
assert "Block size" in app.txt_summary.toPlainText()

# ---- 错误场景汇总（错误展示路径 + 错误块按字节偏移映射到格 + error 级横幅） ----
summary2 = dict(summary)
summary2["error_blocks"] = {5: "fio read failure EIO (offset 20971520)"}
summary2["errno_segments"] = 1
summary2["last_errno"] = 5
summary2["last_errno_name"] = H.errno_name(5)
summary2["unscanned_bytes"] = 8388608
app._on_finished(summary2)
_pe()
print("Error scenario OK | error tree rows: %d | cell67 errors=%d"
      % (app.tree_err.topLevelItemCount(), app.cells[67]["errors"]))
assert app.tree_err.topLevelItemCount() == 1
assert "error blocks" in app.lbl_banner.text()
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
_pe()
txt = app.txt_summary.toPlainText()
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
app.combo_map_mode.setCurrentIndex(H.MAP_MODE_SPEED)   # 重建前切到速度模式
app._on_map_mode_toggle()
app._set_language("zh")
_pe()
assert core.get_language() == "zh"
assert core.load_config().get("language") == "zh", \
    "choice must persist to config"
assert app.btn_start.text() == "▶ 开始扫描", app.btn_start.text()
# 扫描状态跨重建保留（旧实现重启后全丢，才被迫禁止扫描中切换）
assert app.btn_start.isEnabled() is False, "start stays disabled"
assert app.btn_stop.isEnabled() is True, "stop stays enabled"
assert app.worker is live, "rebuild must not touch the scan thread"
assert app.lbl_state.text() == "扫描中…", app.lbl_state.text()
# 热力图模式跨重建保留（快照下标恢复；格子颜色由地图块按新模式重绘）
assert app.map_mode == H.MAP_MODE_SPEED, "heatmap mode must survive rebuild"
assert app.combo_map_mode.currentText() == "磁盘读取速度热力图", \
    app.combo_map_mode.currentText()
# 热力图数据跨重建保留（格数固定 256；错误块经 live 事件与汇总去重后
# cell67 errors=1，不重复计数）
assert len(app.cells) == H.MAP_CELLS, len(app.cells)
assert app.cells[67]["errors"] == 1
assert app.cells[255]["median"] == 2200.0 + 18 * 10
# 日志：可翻译条目按新语言重放；fio 原始输出原样保留（不过 i18n）
log_zh = app.txt_log.toPlainText()
assert "管理员" in log_zh, log_zh
assert "fio: test" in log_zh, "raw fio output must survive verbatim"
app.worker = None
print("Language switch during scan OK (in-place rebuild; scan state kept)")

# 正常切换（带回已完成的结果）：结果区按新语言重放，选择持久化
app.summary = summary                   # 还原一轮已完成扫描
app._set_language("en")                 # zh → en 反向切换
_pe()
assert core.get_language() == "en"
assert app.btn_start.text() == "Start scan"
assert app.map_mode == H.MAP_MODE_SPEED, "mode survives zh→en rebuild too"
assert app.combo_map_mode.currentText() == "Read speed"
assert "Block size" in app.txt_summary.toPlainText(), \
    "summary page must be re-rendered in the new language"
assert "Scan complete" in app.lbl_banner.text(), \
    "banner must be replayed in the new language"
assert app.nb.currentWidget() is app.txt_summary, "selected tab must be kept"
assert len(app.cells) == H.MAP_CELLS and app.cells[67]["errors"] == 1
app._set_language("en")
assert app.btn_start.text() == "Start scan", "same language is a no-op"
# 还原空闲态与默认模式（后续用例不关心，保持界面自洽）
app.combo_map_mode.setCurrentIndex(H.MAP_MODE_HEALTH)
app._on_map_mode_toggle()
app.btn_start.setEnabled(True)
app.btn_stop.setEnabled(False)
print("Language switch OK (in-place rebuild; results/log/banner replayed)")

# ---- 主题切换：实时换 QSS（不重启进程，UI 不重建）----
app.worker = _LiveWorker()              # 扫描中同样允许切换
app._set_theme("bootstrap-dark")
_pe()
assert core.get_theme() == "bootstrap-dark"
assert core.load_config().get("theme") == "bootstrap-dark", \
    "theme choice must persist to config"
assert "#2b2d30" in QApplication.instance().styleSheet(), \
    "dark theme QSS should be applied"
# 图例色块边框同步到新主题色板（填充是语义色，不随主题切换）
for swatch in app._legend_swatches:
    assert "#5a5d5f" in swatch.styleSheet(), swatch.styleSheet()
# 主题切换不重建界面：控件原样（英文文案还在即证明未重建）
assert app.btn_start.text() == "Start scan"
assert app.worker is not None
app.worker = None
app._set_theme("bootstrap-dark")        # 同主题不重复动作
assert "#2b2d30" in QApplication.instance().styleSheet()
# 切回浅色，避免影响后续用例
app._set_theme("bootstrap-light")
_pe()
assert "#f0f0f0" in QApplication.instance().styleSheet()
for swatch in app._legend_swatches:
    assert "#c8c8c8" in swatch.styleSheet(), swatch.styleSheet()
print("Theme switch OK (live QSS swap; legend borders follow)")

# ---- 关于窗口（一行简介，无作者行，图标限制大小，模态+聚焦+Esc 关闭） ----
# exec_ 会阻塞：用记录器替换，验证"会以模态打开"而不真的阻塞
_about_dialogs = []
_real_exec = H.AboutDialog.exec_
H.AboutDialog.exec_ = lambda self: (_about_dialogs.append(self),
                                    QMessageBox.Yes)[1]
try:
    app._show_about()
    _pe()
finally:
    H.AboutDialog.exec_ = _real_exec
assert _about_dialogs, "About dialog should open"
dlg = _about_dialogs[0]
labels = dlg.findChildren(QLabel)
txts = [l.text() for l in labels if l.text()]
assert any("HD Doc" in t for t in txts), txts
one_line = [t for t in txts if "HD Doc" in t][0]
assert "Author" not in one_line and "作者" not in one_line, one_line
assert "\n" not in one_line, "About must be a single line: %r" % one_line
# 弹窗内图标必须被 _bounded_pixmap 限制大小（原图 1248px 会撑爆对话框）
# （PyQt5 的 QLabel.pixmap() 无图时返回 None，不是 null QPixmap）
_icon_labels = [l for l in labels
                if l.pixmap() is not None and not l.pixmap().isNull()]
assert _icon_labels, "About dialog should show the app icon"
_pm = _icon_labels[0].pixmap()
assert max(_pm.width(), _pm.height()) <= H.ABOUT_ICON_PX, \
    "about icon must be bounded to %dpx: got %dx%d" % (
        H.ABOUT_ICON_PX, _pm.width(), _pm.height())
# 主窗口图标同样来自 PNG（Qt 直接渲染，标题栏/任务栏都归它管）
assert not app.windowIcon().isNull(), "window icon should be set"
# 弹窗按钮必须 i18n（本测试固定英文 → "OK"）
btns = dlg.findChildren(QPushButton)
assert btns, "About dialog should have an OK button"
assert btns[0].text() == tr("gui.about.ok"), \
    "OK button must be localized: %r" % (btns[0].text(),)
assert dlg.isModal(), "About dialog must be modal"
# Escape 关闭（keyPressEvent 映射到 reject）
dlg.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
assert dlg.result() == H.AboutDialog.Rejected, "Escape must close the dialog"
print("About window OK (one-line intro, no author line, icon %dx%d <= %dpx, "
      "modal + Escape closes)"
      % (_pm.width(), _pm.height(), H.ABOUT_ICON_PX))

# ---- 目标下拉框：只显示 型号+容量，路径走 _target_paths 映射 ----
app._refresh_drives()
_pe()
vals = [app.combo_target.itemText(i)
        for i in range(app.combo_target.count())]
if vals:   # 本机枚举到物理盘时才断言（无盘/权限受限时空列表也合法）
    for v in vals:
        assert "PhysicalDrive" not in v, \
            "target dropdown must show model+capacity only: %r" % v
    assert app._target_paths, "label→path mapping must be populated"
    assert all(p.startswith("\\\\.\\PhysicalDrive") or p.lower().startswith("//./")
               for p in app._target_paths.values()), app._target_paths
print("Drive labels OK (model + capacity only, %d drives, mapping=%d)"
      % (len(vals), len(app._target_paths)))

# ---- Linux 适配：目标下拉无型号时显示内核名（sda/nvme0n1）而非 Disk N ----
import unittest.mock as _mock


class _FakePopen:
    """假 Popen：模拟 pkexec 子进程（rc=None 表示仍存活）"""
    def __init__(self, rc=None):
        self.returncode = rc
        self.pid = 4242
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True


_saved_iswin = H.IS_WIN
H.IS_WIN = False
# 模拟"桌面会话"：offscreen 环境无 DISPLAY，预检（_probe_display）会
# 拦截提权——测试提权流程本身，故统一打桩成有显示环境。
_display_patch = _mock.patch.object(H.core, "_probe_display",
                                    return_value=":0")
_display_patch.start()
try:
    with _mock.patch.object(H, "list_drives", return_value=[
            {"index": 0, "path": "/dev/sda", "size": 1000204886016,
             "model": "WDC WD10EZEX-22MFCA0", "bus": "sata"},
            {"index": 1, "path": "/dev/nvme0n1", "size": 500107862016,
             "model": "", "bus": "nvme"}]):
        app._refresh_drives()
        _pe()
        vals = [app.combo_target.itemText(i)
                for i in range(app.combo_target.count())]
    assert len(vals) == 2, vals
    assert vals[0].startswith("WDC WD10EZEX"), vals
    assert vals[1].startswith("nvme0n1") and "Disk" not in vals[1], vals
    assert app._target_paths.get(vals[0]) == "/dev/sda", app._target_paths
    print("Linux drive labels OK (model, or kernel name fallback): %r" % (vals,))

    # ---- Linux 提权场景 1：pkexec 很快退出（授权取消/失败）→ 窗口保留 ----
    # 旧版无条件 200ms 后退出：授权被取消时窗口直接消失且无提示=闪退
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(126), None)):
        app._relaunch_elevated()
    time.sleep(0.25)          # 等 150ms 轮询定时器到期
    _pe()
    assert app.isVisible(), "pkexec 失败时窗口必须保留（不能闪退）"
    assert app._pkexec_popen is None
    banner = app.lbl_banner.text()
    assert "126" in banner and "Elevation" in banner, banner
    print("Elevation cancelled OK (window kept, banner shows exit 126)")

    # ---- 场景 2：pkexec 存活但无就绪标记 → 继续等，绝不退出 ----
    # 回归（Ubuntu 实测："密码还没输完提权窗口就消失了"）：pkexec 存活
    # 有两种含义——用户还在输密码 / 授权已通过实例正起窗口。只看存活无法
    # 区分，早期版本轮询 3 秒没退出就替用户移交，输密码慢一点授权框跟着
    # 闪退。现在只有快照文件出现 READY 行（core.elev_ready）才移交。
    exited = []
    _real_exit_now = app._exit_now
    app._exit_now = lambda: exited.append(True)
    _mk_dir = tempfile.mkdtemp(prefix="HD_Doc_smoke_elev_")
    _marker = os.path.join(_mk_dir, "marker.log")
    os.environ["HDTUNE_ELEV_LOG"] = _marker
    _fake = _FakePopen(None)
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_fake, None)):
        app._relaunch_elevated()
    time.sleep(0.4)          # 轮询定时器转两三次，无标记 → 不退
    _pe()
    assert not exited, "无就绪标记时不得退出（用户可能还在输密码）"
    assert app.isVisible(), "等待授权期间窗口必须保留"
    assert "Waiting for authorization" in app.lbl_banner.text()
    print("Elevation wait OK (no READY marker → window kept waiting)")

    # ---- 场景 2b：超时仍未就绪 → 保留窗口 + 超时提示，pkexec 被终止 ----
    os.environ["HDTUNE_ELEVATE_WAIT"] = "0.5"
    exited.clear()
    _fake2 = _FakePopen(None)
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_fake2, None)):
        app._relaunch_elevated()
    time.sleep(1.2)          # 0.5s 宽限 + 150ms 轮询粒度
    _pe()
    assert not exited, "超时是保留窗口提示，不是闪退"
    assert app.isVisible()
    assert _fake2.terminated, "超时应终止 pkexec（关掉授权框）"
    assert "timed out" in app.lbl_banner.text(), app.lbl_banner.text()
    os.environ.pop("HDTUNE_ELEVATE_WAIT", None)
    print("Elevation timeout OK (window kept, banner hints, pkexec killed)")

    # ---- 场景 2c：就绪标记出现 → 移交，退出本窗口 ----
    exited.clear()
    with open(_marker, "a", encoding="utf-8") as _f:
        _f.write("READY pid=1 t=0\n")
    _fake3 = _FakePopen(None)
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_fake3, None)):
        app._relaunch_elevated()
    time.sleep(0.4)          # 标记已在，下一轮轮询即移交
    _pe()
    assert exited, "出现就绪标记后应移交提权实例（退出本窗口）"
    assert not _fake3.terminated, "已移交不得再终止 pkexec"
    app._exit_now = _real_exit_now
    shutil.rmtree(_mk_dir, ignore_errors=True)
    os.environ.pop("HDTUNE_ELEV_LOG", None)
    print("Elevation handover OK (READY marker → this window exits)")

    # ---- 场景 3：无 pkexec → 横幅报错，窗口保留 ----
    with _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(None, "pkexec not found")):
        app._relaunch_elevated()
    _pe()
    assert app.isVisible()
    assert "pkexec not found" in app.lbl_banner.text()
    print("No-pkexec OK (banner error, window kept)")

    # ---- 场景 3b：无显示环境 → 预检拦截，pkexec 都不发起 ----
    # 回归：Kylin/无 X 会话下 root 实例必然连不上显示服务（Qt qFatal
    # 秒退 → 授权框闪退），预检直接跳过并提示，不弹注定失败的框
    with _mock.patch.object(H.core, "_probe_display", return_value=None), \
         _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(None, "should not be called")) as _sp:
        app._relaunch_elevated()
    _pe()
    assert app.isVisible()
    assert "No graphical display" in app.lbl_banner.text(), \
        app.lbl_banner.text()
    assert not _sp.called, "无显示环境时不应发起 pkexec"
    print("No-display precheck OK (pkexec not spawned, window kept)")

    # ---- 场景 4：ensure_admin_at_startup 在 Linux 也发起提权 ----
    # 4a 授权取消（pkexec 126）→ False（标准权限继续启动）
    with _mock.patch.object(H, "is_admin", return_value=False), \
         _mock.patch.object(H, "auto_elevate_enabled", return_value=True), \
         _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(126), None)):
        assert H.ensure_admin_at_startup() is False, \
            "授权失败应返回 False（标准权限继续启动）"

    # 4b 提权实例已就绪（READY 标记）→ True（本进程退出让位）。
    # 回归：早期版本用 2.5 秒固定超时猜"授权进行中"，输密码超过 2.5 秒
    # 父进程先退出、授权框跟着消失（"密码没输完窗口就没了"）；现在以
    # 就绪标记为准，输密码再慢也不会误退。
    _mk_dir2 = tempfile.mkdtemp(prefix="HD_Doc_smoke_elev2_")
    _mk2 = os.path.join(_mk_dir2, "startup.log")
    with open(_mk2, "w", encoding="utf-8") as _f:
        _f.write("READY pid=7 t=0\n")
    os.environ["HDTUNE_ELEV_LOG"] = _mk2
    with _mock.patch.object(H, "is_admin", return_value=False), \
         _mock.patch.object(H, "auto_elevate_enabled", return_value=True), \
         _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_FakePopen(None), None)):
        assert H.ensure_admin_at_startup() is True, \
            "出现就绪标记应返回 True（提权实例接管，本进程退出）"

    # 4c 超时仍未就绪 → False（终止 pkexec，标准权限继续启动）
    _clock = [0.0]

    def _fake_monotonic():
        _clock[0] += 1.0
        return _clock[0]

    os.remove(_mk2)                      # 清掉 4b 的标记，模拟"还没就绪"
    os.environ["HDTUNE_ELEVATE_WAIT"] = "0.5"
    _fake4 = _FakePopen(None)
    with _mock.patch.object(H, "is_admin", return_value=False), \
         _mock.patch.object(H, "auto_elevate_enabled", return_value=True), \
         _mock.patch.object(H.time, "sleep", lambda s: None), \
         _mock.patch.object(H.time, "monotonic", _fake_monotonic), \
         _mock.patch.object(H.core, "pkexec_gui_spawn",
                            return_value=(_fake4, None)):
        assert H.ensure_admin_at_startup() is False, \
            "超时未就绪应返回 False（照常启动，不干等）"
    assert _fake4.terminated, "超时应终止 pkexec"
    os.environ.pop("HDTUNE_ELEVATE_WAIT", None)
    shutil.rmtree(_mk_dir2, ignore_errors=True)
    print("ensure_admin_at_startup(Linux) OK "
          "(cancel→False, READY→True, timeout→False)")
finally:
    H.IS_WIN = _saved_iswin
    _display_patch.stop()
    os.environ.pop("HDTUNE_ELEV_LOG", None)
    os.environ.pop("HDTUNE_ELEVATE_WAIT", None)
    app._refresh_drives()
    _pe()

# ---- 日志自动滚动到底部 ----
app.txt_log.clear()
for i in range(120):
    app._log_line("info", "scroll probe line %d" % i)
_pe()
_bar = app.txt_log.verticalScrollBar()
assert _bar.maximum() > 0, "120 lines should overflow the log view"
assert _bar.value() == _bar.maximum(), \
    "log should stay scrolled to the last line: %r/%r" % (
        _bar.value(), _bar.maximum())
print("Log auto-scroll OK (120 lines, scrollbar %d/%d)"
      % (_bar.value(), _bar.maximum()))

# ---- 程序图标（标题栏 + 任务栏，PNG 经 setWindowIcon） ----
assert not app.windowIcon().isNull(), \
    "window icon (img/HD_Doc.png) should be loaded"
print("Window icon OK (setWindowIcon)")

# ---- 失败路径（不弹窗，走横幅） ----
popped.clear()
app._on_failed("test failure message")
_pe()
assert not popped, "failure must use the in-app banner, not dialogs: %r" % (popped,)
assert "test failure message" in app.lbl_banner.text()

# ---- Qt 回调异常必须落运行日志（默认只打印 stderr，打包版不可见） ----
from PyQt5.QtCore import QTimer
QTimer.singleShot(5, lambda: 1 / 0)
time.sleep(0.15)          # 等定时器到期
_pe()

# ---- 运行日志：单文件，含启动/扫描结果/失败/回调异常 ----
_log_file = os.path.join(_LOG_DIR, "HD_Doc.log")
assert os.path.isfile(_log_file), "run log should exist at %s" % _log_file
_log_txt = open(_log_file, encoding="utf-8").read()
for _needle in ("gui: start", "scan: finished", "scan: failed",
                "qt callback exception", "ZeroDivisionError"):
    assert _needle in _log_txt, "run log should contain %r:\n%s" % (
        _needle, _log_txt[-800:])
assert os.listdir(_LOG_DIR) == ["HD_Doc.log"], \
    "exactly one log file: %r" % (os.listdir(_LOG_DIR),)
print("Run log OK (single file %s, %d bytes)"
      % (_log_file, os.path.getsize(_log_file)))

# ---- 逐格渲染：一次只上色一格（用户要求"一个一个渲染，不要一次渲染
#      多个"——4G 段跨 1-2 格时也不能两格同时亮） ----
app._reset_map([(0, 4 << 20, None), (4 << 20, 4 << 20, None)])
for i in range(5):
    app.cells[i]["median"] = 1000.0
    app.cells[i]["n"] = 1
app.dirty.update(range(5))
app._flush_cells(force=True)          # 第一拍：只点亮第 1 格
assert [i for i in range(5) if app._painted[i]] == [0], app._painted[:5]
app._flush_cells(force=True)          # 第二拍：才点亮第 2 格（索引顺序）
assert [i for i in range(5) if app._painted[i]] == [0, 1], app._painted[:5]
for _ in range(3):                    # 剩余格子逐拍排干
    app._flush_cells(force=True)
assert not app.dirty, "待渲染格子应已排干"
assert all(f == H.COLOR_OK for f in app._painted[:5]), app._painted[:5]
print("逐格渲染 OK：每次只亮一格，按索引顺序逐拍点亮")

app.close()
shutil.rmtree(_LOG_DIR, ignore_errors=True)
print("\nGUI smoke test: all passed")
