# -*- coding: utf-8 -*-
"""GUI 扫描全链路：快速扫描（512MB 镜像抽样区域）+ 全段扫描（8MB 镜像），
验证段级热力图填充、悬停信息与 _run_worker 主线程变量读取（回归）。

界面固定英文（HDTUNE_LANG=en），断言按英文口径。"""
import os, sys, time, types
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
os.environ["HDTUNE_LANG"] = "en"
sys.path.insert(0, ".")
import hdtune_gui as H

FIO = "C:/Program Files/fio/fio.exe"
BIG = os.path.abspath(os.path.join("..", "fio_test", "it_big.img"))
assert os.path.isfile(BIG), "缺少 512MB 测试镜像，请先跑 test_integration.py"

root = H.tk.Tk(); root.withdraw()
app = H.HDTuneScanApp(); app.withdraw()
app.geometry("1140x820")
app.canvas_map.winfo_width = lambda: 1100
app.canvas_map.winfo_height = lambda: 700
app.update()

# 镜像文件目标：不需要管理员；桩掉所有模态框防阻塞
H.messagebox.askyesno = lambda *a, **k: True
H.messagebox.showinfo = lambda *a, **k: None
H.messagebox.showwarning = lambda *a, **k: None
H.messagebox.showerror = lambda *a, **k: None

app.var_target.set(BIG)
app.var_fio.set(FIO)
app.var_seg.set("64M")            # 64M 区域 → 512MB 盘 8 个区域
app.var_quick.set(True)           # 快速扫描：每区抽 16M
app.var_quick_sample.set("16M")
app._start_scan()
print("扫描线程已启动 | scan_quick=%s | 格数=%d" % (app.scan_quick, len(app.cells)))
assert app.scan_quick is True
assert len(app.cells) == 8, len(app.cells)
assert app.seg_meta[0] == (0, 16 << 20, 64 << 20), app.seg_meta[0]

# 轮询直到扫描完成并消费完 finished/worker_done 事件（_poll_queue 100ms 周期）
t0 = time.time()
while time.time() - t0 < 150:
    app.update()
    if app.summary is not None and app.worker is None:
        break
    time.sleep(0.05)
else:
    raise SystemExit("超时：扫描未在 150s 内结束")
app.update()

s = app.summary
assert s, "扫描未产出汇总"
print("汇总: quick=%s 段数=%d 块数=%d 错误=%d 耗时=%.1fs"
      % (s["quick"], len(s["segments"]), s["n_blocks"],
         len(s["error_blocks"]), s["elapsed_s"]))
assert s["quick"] is True
assert len(s["segments"]) == 8
assert all(g["size"] == 16 << 20 for g in s["segments"]), [g["size"] for g in s["segments"]]
assert s["n_blocks"] == 8 * 32      # 16M / 512K = 32 块/区
assert not s["error_blocks"]

# 热力图：8 格全部有中位数（已读）
filled = sum(1 for c in app.cells if c["median"] is not None)
print("热力图填充: %d/8 格 | cell0 median=%.3fms" % (filled, app.cells[0]["median"] / 1000.0))
assert filled == 8

# 悬停（第一格 = 区域 #1；坐标按自适应 pitch 与居中偏移反算到格内）
app._on_canvas_motion(types.SimpleNamespace(
    x=int(app.grid_ox + app.cell_pitch / 2),
    y=int(app.grid_oy + app.cell_pitch / 2)))
hover = app.lbl_hover.cget("text")
print("悬停: %r" % hover)
assert ("Region #1/8" in hover and "sample 16.0 MB" in hover
        and "/region 64.0 MB" in hover), hover

# 汇总文本含快速扫描覆盖率行（英文口径）
txt = app.txt_summary.get("1.0", "end")
assert "quick scan" in txt and "% of capacity" in txt
print("汇总文本含覆盖率行 OK")

# 导出按钮可用 + 导出写入报告（GUI 语言 = en）
assert str(app.btn_export.cget("state")) == "normal"
import tempfile
exp = tempfile.mkdtemp(prefix="hdtune_gui_export_")
app._export_report = lambda: H.write_reports(
    os.path.join(exp, "hdtune_report_test"), app.summary)
app._export_report()
files = os.listdir(os.path.join(exp, "hdtune_report_test"))
assert set(files) == {"segments.csv", "errors.csv", "summary.txt"}, files
head = open(os.path.join(exp, "hdtune_report_test", "summary.txt"),
            encoding="utf-8").read()
assert "HD Tune Style Disk Error Scan Report" in head
print("GUI 导出 OK（英文报告，3 个文件）")

app._cancel_timers()
app.destroy()

# ---- 第二阶段：普通全段扫描（回归：_run_worker 曾在工作线程读 Tk 变量
# 导致 "main thread is not in main loop"，快速/全段两条路径都要覆盖）----
SMALL = os.path.abspath(os.path.join("..", "fio_test", "it_small.img"))
assert os.path.isfile(SMALL), "缺少 8MB 测试镜像"
app2 = H.HDTuneScanApp(); app2.withdraw()
app2.geometry("1140x820")
app2.canvas_map.winfo_width = lambda: 1100
app2.canvas_map.winfo_height = lambda: 700
app2.update()
app2.var_target.set(SMALL)
app2.var_fio.set(FIO)
app2.var_seg.set("4M")             # 8MB / 4M = 2 段
app2.var_bs.set("1M")              # 显式块大小：8 块，断言确定
app2.var_quick.set(False)
app2._start_scan()
assert app2.scan_quick is False
assert len(app2.cells) == 2, len(app2.cells)
t0 = time.time()
while time.time() - t0 < 60:
    app2.update()
    if app2.summary is not None and app2.worker is None:
        break
    time.sleep(0.05)
else:
    raise SystemExit("超时：全段扫描未在 60s 内结束")
app2.update()
s2 = app2.summary
assert s2 and not s2.get("quick"), s2
assert len(s2["segments"]) == 2
assert s2["n_blocks"] == 8, s2["n_blocks"]
filled2 = sum(1 for c in app2.cells if c["median"] is not None)
print("全段扫描: %d 段 %d 块 | 填充 %d/2 格 | 耗时 %.1fs"
      % (len(s2["segments"]), s2["n_blocks"], filled2, s2["elapsed_s"]))
assert filled2 == 2
app2._on_canvas_motion(types.SimpleNamespace(
    x=int(app2.grid_ox + app2.cell_pitch / 2),
    y=int(app2.grid_oy + app2.cell_pitch / 2)))
hover2 = app2.lbl_hover.cget("text")
assert "Segment #1/2" in hover2 and "size" in hover2, hover2
print("全段扫描悬停: %r" % hover2)
app2._cancel_timers()
app2.destroy()
root.destroy()
print("\nGUI 扫描全链路（快速 + 全段 + 导出）通过")
