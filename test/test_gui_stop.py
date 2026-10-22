# -*- coding: utf-8 -*-
"""GUI 停止扫描回归测试：停止后不得误报"磁盘错误"。

覆盖三种情形（新版行为：结果只进界面横幅，不弹窗）：
  A. 真实停止（扫描中点）→ 无弹窗、aborted=True、stop_requested=True、
     错误树为空（用户反馈"停止扫描就报磁盘错误"的直接回归）
  B. 停止信号落在扫描结束后（aborted=False 但 stop_requested=True，
     且停止前已发现真实错误）→ 不弹 warning，只出 warn 级横幅
     （这是误报警报的竞态路径：aborted 可能为 False）
  C. 完整扫描发现真实错误（未停止）→ error 级横幅（真实坏道必须警报）

运行：python test_gui_stop.py（需要带 PyQt5 的 Python；offscreen 平台）
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 阻止启动时的自动提权弹窗阻塞无人值守测试
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
# 固定英文，保证断言确定
os.environ["HDTUNE_LANG"] = "en"
# 固定浅色主题，保证断言确定
os.environ["HDTUNE_THEME"] = "bootstrap-light"
os.environ["HD_DOC_LOG"] = "off"   # 运行日志隔离：不写真实配置目录

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtWidgets import QApplication, QMessageBox
import HD_Doc_gui as H

FIO = "C:/Program Files/fio/fio.exe"
BIG = os.path.abspath(os.path.join("..", "fio_test", "it_big.img"))
assert os.path.isfile(BIG), "缺少 512MB 测试镜像，请先跑 test_integration.py"

# QApplication 必须先于任何 QWidget 构造（否则 Qt 直接 qFatal abort）
qt_app = QApplication.instance() or QApplication(sys.argv)

FAILS = []


def check(name, got, want):
    ok = got == want
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("   got : %r\n   want: %r" % (got, want))
        FAILS.append(name)


def new_app():
    app = H.HDDocApp()
    app.show()
    app.map_widget.resize(1100, 700)
    QApplication.processEvents()
    # 桩掉所有模态框，只记录不阻塞（新版下完成路径不应触发任何一个）
    popups = []
    QMessageBox.question = lambda *a, **k: popups.append(("yesno",) + a) or QMessageBox.Yes
    QMessageBox.information = lambda *a, **k: popups.append(("info",) + a)
    QMessageBox.warning = lambda *a, **k: popups.append(("warning",) + a)
    QMessageBox.critical = lambda *a, **k: popups.append(("error",) + a)
    return app, popups


def wait_done(app, limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        QApplication.processEvents()
        if app.summary is not None and app.worker is None:
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- 场景 A
print("== 场景 A：扫描中点停止（用户反馈的直接回归） ==")
app, popups = new_app()
app._set_target_text(BIG)
app.entry_fio.setCurrentText(FIO)
app.combo_bs.setCurrentIndex(app.combo_bs.findText("4M"))
app.combo_seg.setCurrentIndex(app.combo_seg.findText("256M"))  # 512MB/256M = 2 段
app.chk_quick.setChecked(False)
app._start_scan()
check("A 扫描线程已启动", app.worker is not None, True)
time.sleep(1.2)                  # 扫到一半
app._stop_scan()                 # 用户点停止
check("A 等待扫描收敛", wait_done(app), True)
s = app.summary
check("A aborted=True", s["aborted"], True)
check("A stop_requested=True", s.get("stop_requested"), True)
check("A 无错误块", len(s["error_blocks"]), 0)
check("A errno_segments=0", s["errno_segments"], 0)
# 停止时正在扫的段：lat 是截断样本（SSD 短段启动瞬态放大中位数），
# 必须整段放弃——不发 seg_stat，该段覆盖的所有格保持未扫描
segs = s["segments"]
stopped_segs = [i for i, sg in enumerate(segs) if sg.get("stopped")]
check("A 至少一段被标记 stopped", len(stopped_segs) >= 1, True)
for i in stopped_segs:
    check("A 段%d 延迟统计已丢弃" % (i + 1), segs[i]["median_us"], None)
    check("A 段%d 最大延迟已丢弃" % (i + 1), segs[i]["max_us"], None)
    covered = app.seg_cells[i]
    check("A 段%d 覆盖的格保持未扫描(无延迟)" % (i + 1),
          all(app.cells[c]["median"] is None for c in covered), True)
    check("A 段%d 覆盖的格无块数" % (i + 1),
          all(app.cells[c]["n"] == 0 for c in covered), True)
# 反向：有延迟数据的格，必须被至少一个完整读完的段覆盖（无假慢格）
bad = []
for ci, c in enumerate(app.cells):
    if c["median"] is None:
        continue
    if not any((not segs[j].get("stopped")) and ci in app.seg_cells[j]
               for j in range(len(segs))):
        bad.append(ci)
check("A 有数据的格必须被完整段覆盖", bad, [])
check("A 热力图格数固定", len(app.cells), H.MAP_CELLS)
check("A 状态标签=完成（中止）", app.lbl_state.text(), "Done (aborted)")
check("A 错误标签=无", app.lbl_errors.text(), "Errors: none")
check("A 错误树为空", app.tree_err.topLevelItemCount(), 0)
check("A 无任何弹窗（不报磁盘错误）", popups, [])
check("A 横幅为正常完成口径（非错误警报）",
      "read errors" in app.lbl_banner.text()
      and "physical damage" not in app.lbl_banner.text(), True)
txt = app.txt_summary.toPlainText()
check("A 汇总含停止状态行", "stopped by user" in txt, True)
app._cancel_timers()
app.close()

# ---------------------------------------------------------------- 场景 B
print("\n== 场景 B：停止落在扫描结束后（竞态路径，aborted=False） ==")
app, popups = new_app()
# 直接以"停止前发现真实错误 + aborted=False + stop_requested=True"的汇总
# 驱动 _on_finished——这正是竞态下旧逻辑会误报的组合
app.total_size = 8 << 20
app._reset_map([(0, 4 << 20, None), (4 << 20, 4 << 20, None)])
fake = {
    "target": BIG, "bs": 4 << 20, "ioengine": "windowsaio", "direct": True,
    "total_size": 8 << 20, "segments": [], "n_blocks": 2, "ok": 1, "slow": 0,
    "error_blocks": {5: "fio read failure EIO (offset 20971520)"},
    "unlocated_errors": 0, "median_us": 1000.0, "mean_us": 1000.0,
    "max_us": 2000.0, "p99_us": 2000.0, "slow_thr_us": 3000.0,
    "elapsed_s": 3.0, "aborted": False,
    "stop_requested": True, "errno_segments": 1, "last_errno": 5,
    "last_errno_name": "EIO", "unscanned_bytes": 0,
    "stopped_unscanned_bytes": 0, "unread_tail_bytes": 0, "quick": False,
}
app._on_finished(fake)
check("B 无任何弹窗（含不弹 warning）", popups, [])
check("B 横幅为停止+错误提示口径",
      "stopped by user" in app.lbl_banner.text(), True)
check("B 横幅不含'物理损伤'警报口径",
      "physical damage" in app.lbl_banner.text(), False)
check("B 状态标签=完成", app.lbl_state.text(), "Done")
check("B 汇总含停止状态行",
      "stopped by user" in app.txt_summary.toPlainText(), True)
check("B 错误块计入热力图（块5 偏移 20MB 越界 → 钳制到末格）",
      app.cells[H.MAP_CELLS - 1]["errors"], 1)
app._cancel_timers()
app.close()

# ---------------------------------------------------------------- 场景 C
print("\n== 场景 C：完整扫描发现真实错误（未停止，必须警报） ==")
app, popups = new_app()
fake2 = dict(fake)
fake2["stop_requested"] = False
fake2["aborted"] = False
app.total_size = 8 << 20
app._reset_map([(0, 4 << 20, None), (4 << 20, 4 << 20, None)])
app._on_finished(fake2)
check("C 无弹窗（改为 error 级横幅）", popups, [])
check("C 横幅为错误警报口径",
      "physical damage" in app.lbl_banner.text(), True)
check("C 横幅样式为错误级（BANNER_STYLE 的 error 底色）",
      "#c62828" in app.lbl_banner.styleSheet(), True)
app._cancel_timers()
app.close()

print()
if FAILS:
    print("失败 %d 项: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("GUI 停止扫描回归测试全部通过")
