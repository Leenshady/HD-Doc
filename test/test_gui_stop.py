# -*- coding: utf-8 -*-
"""GUI 停止扫描回归测试：停止后不得误报"磁盘错误"。

覆盖三种情形（新版行为：结果只进界面横幅，不弹窗）：
  A. 真实停止（扫描中点）→ 无弹窗、aborted=True、stop_requested=True、
     错误树为空（用户反馈"停止扫描就报磁盘错误"的直接回归）
  B. 停止信号落在扫描结束后（aborted=False 但 stop_requested=True，
     且停止前已发现真实错误）→ 不弹 warning，只出 warn 级横幅
     （这是误报警报的竞态路径：aborted 可能为 False）
  C. 完整扫描发现真实错误（未停止）→ error 级横幅（真实坏道必须警报）

运行：python test_gui_stop.py（需要带 tkinter 的 Python，如系统 Python 3.12）
"""
import os
import sys
import time

# 阻止启动时的自动提权弹窗阻塞无人值守测试
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
# 固定英文，保证断言确定
os.environ["HDTUNE_LANG"] = "en"
# 固定浅色主题，保证断言确定
os.environ["HDTUNE_THEME"] = "bootstrap-light"
os.environ["HD_DOC_LOG"] = "off"   # 运行日志隔离：不写真实配置目录

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_gui as H

FIO = "C:/Program Files/fio/fio.exe"
BIG = os.path.abspath(os.path.join("..", "fio_test", "it_big.img"))
assert os.path.isfile(BIG), "缺少 512MB 测试镜像，请先跑 test_integration.py"

FAILS = []


def check(name, got, want):
    ok = got == want
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("   got : %r\n   want: %r" % (got, want))
        FAILS.append(name)


def new_app():
    root = H.tk.Tk()
    root.withdraw()
    app = H.HDDocApp()
    app.withdraw()
    app.geometry("1140x820")
    app.canvas_map.winfo_width = lambda: 1100
    app.canvas_map.winfo_height = lambda: 700
    app.update()
    # 桩掉所有模态框，只记录不阻塞（新版下完成路径不应触发任何一个）
    # （ttkbootstrap Messagebox 替代 tkinter.messagebox）
    popups = []
    H.Messagebox.yesno = lambda *a, **k: True
    H.Messagebox.show_info = lambda *a, **k: popups.append(("info",) + a)
    H.Messagebox.show_warning = lambda *a, **k: popups.append(("warning",) + a)
    H.Messagebox.show_error = lambda *a, **k: popups.append(("error",) + a)
    return root, app, popups


def wait_done(app, limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.update()
        if app.summary is not None and app.worker is None:
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- 场景 A
print("== 场景 A：扫描中点停止（用户反馈的直接回归） ==")
root, app, popups = new_app()
app.var_target.set(BIG)
app.var_fio.set(FIO)
app.var_bs.set("4M")
app.var_seg.set("256M")          # 2 段，扫几秒
app.var_quick.set(False)
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
# 必须整段放弃——不进统计、不发 seg_stat、热力图该格保持未扫描
segs = s["segments"]
stopped_segs = [i for i, sg in enumerate(segs) if sg.get("stopped")]
check("A 至少一段被标记 stopped", len(stopped_segs) >= 1, True)
for i in stopped_segs:
    check("A 段%d 延迟统计已丢弃" % (i + 1), segs[i]["median_us"], None)
    check("A 段%d 最大延迟已丢弃" % (i + 1), segs[i]["max_us"], None)
    check("A 段%d 格子保持未扫描(无延迟)" % (i + 1), app.cells[i]["median"], None)
    check("A 段%d 格子无块数" % (i + 1), app.cells[i]["n"], 0)
# 反向：任何显示了延迟数据的格子都必须来自完整读完的段（无假慢格）
for i, c in enumerate(app.cells):
    if c["median"] is not None:
        check("A 有数据的段%d 必须完整读完" % (i + 1),
              not segs[i].get("stopped"), True)
check("A 状态标签=完成（中止）", app.lbl_state.cget("text"), "Done (aborted)")
check("A 错误标签=无", app.lbl_errors.cget("text"), "Errors: none")
check("A 错误树为空", len(app.tree_err.get_children()), 0)
check("A 无任何弹窗（不报磁盘错误）", popups, [])
check("A 横幅为正常完成口径（非错误警报）",
      "read errors" in app.lbl_banner.cget("text")
      and "physical damage" not in app.lbl_banner.cget("text"), True)
txt = app.txt_summary.get("1.0", "end")
check("A 汇总含停止状态行", "stopped by user" in txt, True)
app._cancel_timers()
app.destroy()
root.destroy()

# ---------------------------------------------------------------- 场景 B
print("\n== 场景 B：停止落在扫描结束后（竞态路径，aborted=False） ==")
root, app, popups = new_app()
# 直接以"停止前发现真实错误 + aborted=False + stop_requested=True"的汇总
# 驱动 _on_finished——这正是竞态下旧逻辑会误报的组合
app._reset_map(2, [(0, 4 << 20, None), (4 << 20, 4 << 20, None)])
app.seg_block_base = [0, 4]
fake = {
    "target": BIG, "bs": 4 << 20, "ioengine": "windowsaio", "direct": True,
    "total_size": 8 << 20, "segments": [], "n_blocks": 2, "ok": 1, "slow": 0,
    "bad": 0, "error_blocks": {5: "fio read failure EIO (offset 20971520)"},
    "unlocated_errors": 0, "median_us": 1000.0, "mean_us": 1000.0,
    "max_us": 2000.0, "p99_us": 2000.0, "slow_thr_us": 3000.0,
    "bad_thr_us": 8000.0, "elapsed_s": 3.0, "aborted": False,
    "stop_requested": True, "errno_segments": 1, "last_errno": 5,
    "last_errno_name": "EIO", "unscanned_bytes": 0,
    "stopped_unscanned_bytes": 0, "unread_tail_bytes": 0, "quick": False,
}
app._on_finished(fake)
check("B 无任何弹窗（含不弹 warning）", popups, [])
check("B 横幅为停止+错误提示口径",
      "stopped by user" in app.lbl_banner.cget("text"), True)
check("B 横幅不含'物理损伤'警报口径",
      "physical damage" in app.lbl_banner.cget("text"), False)
check("B 状态标签=完成", app.lbl_state.cget("text"), "Done")
check("B 汇总含停止状态行",
      "stopped by user" in app.txt_summary.get("1.0", "end"), True)
app._cancel_timers()
app.destroy()
root.destroy()

# ---------------------------------------------------------------- 场景 C
print("\n== 场景 C：完整扫描发现真实错误（未停止，必须警报） ==")
root, app, popups = new_app()
fake2 = dict(fake)
fake2["stop_requested"] = False
fake2["aborted"] = False
app._reset_map(2, [(0, 4 << 20, None), (4 << 20, 4 << 20, None)])
app.seg_block_base = [0, 4]
app._on_finished(fake2)
check("C 无弹窗（改为 error 级横幅）", popups, [])
check("C 横幅为错误警报口径",
      "physical damage" in app.lbl_banner.cget("text"), True)
check("C 横幅样式为错误级（danger bootstyle）",
      app.lbl_banner.cget("style"), H.BANNER_BOOTSTYLE["error"] + ".TLabel")
app._cancel_timers()
app.destroy()
root.destroy()

print()
if FAILS:
    print("失败 %d 项: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("GUI 停止扫描回归测试全部通过")
