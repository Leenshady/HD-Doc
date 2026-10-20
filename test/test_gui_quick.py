# -*- coding: utf-8 -*-
"""GUI 扫描全链路：快速扫描（512MB 镜像抽样区域）+ 全段扫描（8MB 镜像），
验证段级热力图填充、悬停信息与 _run_worker 主线程变量读取（回归）。

界面固定英文（HDTUNE_LANG=en），断言按英文口径。"""
import os, sys, time, types
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
os.environ["HDTUNE_LANG"] = "en"
os.environ["HDTUNE_THEME"] = "bootstrap-light"
os.environ["HD_DOC_LOG"] = "off"   # 运行日志隔离：不写真实配置目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_gui as H

FIO = "C:/Program Files/fio/fio.exe"
BIG = os.path.abspath(os.path.join("..", "fio_test", "it_big.img"))
assert os.path.isfile(BIG), "缺少 512MB 测试镜像，请先跑 test_integration.py"

root = H.tk.Tk(); root.withdraw()
app = H.HDDocApp(); app.withdraw()
app.geometry("1140x820")
app.canvas_map.winfo_width = lambda: 1100
app.canvas_map.winfo_height = lambda: 700
app.update()

# 镜像文件目标：不需要管理员；桩掉所有模态框防阻塞
# （ttkbootstrap Messagebox：镜像目标不会触发确认框，桩上只为兜底）
H.Messagebox.yesno = lambda *a, **k: True
H.Messagebox.show_info = lambda *a, **k: None
H.Messagebox.show_warning = lambda *a, **k: None
H.Messagebox.show_error = lambda *a, **k: None

app.var_target.set(BIG)
app.var_fio.set(FIO)
app.var_seg.set("64M")            # 64M 区域 → 512MB 盘 8 个区域
app.var_quick.set(True)           # 快速扫描：每区抽 16M
app.var_quick_sample.set("16M")
app._start_scan()
print("扫描线程已启动 | scan_quick=%s | 格数=%d" % (app.scan_quick, len(app.cells)))
assert app.scan_quick is True
# 固定格数：512MB 盘与 1TB 盘都是 MAP_CELLS 格、同一套布局（UI 一致性）
assert len(app.cells) == H.MAP_CELLS == 256, len(app.cells)
assert app.seg_meta[0] == (0, 16 << 20, 64 << 20), app.seg_meta[0]
# 段 → 格映射：快速扫描按"区域跨度"点亮（64MB 区域 = 32 格），8 个区域
# 铺满全部 256 格——曾按 16MB 抽样大小点亮（每区仅 8 格），其余 192 格
# 永久灰，用户反馈"有的块保持灰色"
assert [c[0] for c in app.seg_cells] == [0, 32, 64, 96, 128, 160, 192, 224]
assert all(len(c) == 32 for c in app.seg_cells), [len(c) for c in app.seg_cells]
assert app.cell_region[0] == 0 and app.cell_region[255] == 7

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

# 热力图：快速扫描整区点亮。512MB/256 格 = 2MB/格，64MB 区域 = 32 格，
# 8 区 × 32 格 = 全部 256 格有数据（回归：只点亮抽样覆盖的格时 192 格永灰）
filled = sum(1 for c in app.cells if c["median"] is not None)
print("热力图填充: %d/%d 格 | cell0 median=%.3fms"
      % (filled, len(app.cells), app.cells[0]["median"] / 1000.0))
assert filled == H.MAP_CELLS, filled
assert app.cells[0]["n"] == 32 and app.cells[32]["n"] == 32
# 同一区域的格同值（区0 = 格 0-31，区1 = 格 32-63，…）；无灰格
assert all(c["median"] == app.cells[0]["median"] for c in app.cells[:32])
assert all(c["median"] is not None for c in app.cells)

# 悬停（第一格 = 区域 #1 的 16MB 抽样供数；坐标按 pitch 与居中偏移反算）
def _hover_cell(a, idx):
    r, c = divmod(idx, a.grid_cols)
    a._on_canvas_motion(types.SimpleNamespace(
        x=int(a.grid_ox + (c + 0.5) * a.cell_pitch),
        y=int(a.grid_oy + (r + 0.5) * a.cell_pitch)))

_hover_cell(app, 0)
hover = app.lbl_hover.cget("text")
print("悬停: %r" % hover)
assert ("Cell #1/256" in hover and "region sample 16.0 MB (region 64.0 MB)" in hover
        and "start block 0" in hover and "read 32 blocks" in hover), hover
# 区2 的首格（第 33 格）：同样显示区域抽样上下文
_hover_cell(app, 32)
hover2 = app.lbl_hover.cget("text")
print("区2 格悬停: %r" % hover2)
assert "Cell #33/256" in hover2 and "region sample 16.0 MB" in hover2, hover2
# 未抽样的格（停止过早/区域无数据）：悬停标注"未抽样"而非"未扫描"
# ——白盒清掉一格中位数验证该分支（整区点亮后正常不会有灰格）
app.cells[100]["median"] = None
_hover_cell(app, 100)
hover_gap = app.lbl_hover.cget("text")
print("未抽样格悬停: %r" % hover_gap)
assert "Cell #101/256" in hover_gap and "not sampled" in hover_gap, hover_gap
app.cells[100]["median"] = app.cells[99]["median"]   # 还原，避免影响后续断言

# 汇总文本含快速扫描覆盖率行（英文口径）
txt = app.txt_summary.get("1.0", "end")
assert "quick scan" in txt and "% of capacity" in txt
print("汇总文本含覆盖率行 OK")

# 导出按钮可用 + 导出写入报告（GUI 语言 = en）
assert str(app.btn_export.cget("state")) == "normal"
import tempfile
exp = tempfile.mkdtemp(prefix="HD_Doc_gui_export_")
app._export_report = lambda: H.write_reports(
    os.path.join(exp, "HD_Doc_report_test"), app.summary)
app._export_report()
files = os.listdir(os.path.join(exp, "HD_Doc_report_test"))
assert set(files) == {"segments.csv", "errors.csv", "summary.txt"}, files
head = open(os.path.join(exp, "HD_Doc_report_test", "summary.txt"),
            encoding="utf-8").read()
assert "HD Doc Disk Error Scan Report" in head
print("GUI 导出 OK（英文报告，3 个文件）")

app._cancel_timers()
app.destroy()
root.destroy()      # 连同隐藏 root 一起销毁：ttkbootstrap 的 Style 是进程级
                    # 单例，旧解释器还活着时新 Window 建不出主题对象
                    # （_theme_objects 为空 → KeyError），与 test_gui_stop 相同做法

# ---- 第二阶段：普通全段扫描（回归：_run_worker 曾在工作线程读 Tk 变量
# 导致 "main thread is not in main loop"，快速/全段两条路径都要覆盖）----
SMALL = os.path.abspath(os.path.join("..", "fio_test", "it_small.img"))
assert os.path.isfile(SMALL), "缺少 8MB 测试镜像"
root = H.tk.Tk(); root.withdraw()
app2 = H.HDDocApp(); app2.withdraw()
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
# 固定格数：8MB 小盘同样 256 格（段少格多 → 2 段各覆盖 128 格，全部有数据）
assert len(app2.cells) == H.MAP_CELLS, len(app2.cells)
assert app2.seg_cells[0] == list(range(0, 128)), app2.seg_cells[0][:3]
assert app2.seg_cells[1] == list(range(128, 256)), app2.seg_cells[1][:3]
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
# 段少格多：2 段覆盖全部 256 格，每格 4 块（1M 块大小 / 4M 段）
filled2 = sum(1 for c in app2.cells if c["median"] is not None)
print("全段扫描: %d 段 %d 块 | 填充 %d/%d 格 | 耗时 %.1fs"
      % (len(s2["segments"]), s2["n_blocks"], filled2, len(app2.cells),
         s2["elapsed_s"]))
assert filled2 == H.MAP_CELLS, filled2
assert all(c["n"] == 4 for c in app2.cells), [c["n"] for c in app2.cells[:4]]
app2._on_canvas_motion(types.SimpleNamespace(
    x=int(app2.grid_ox + app2.cell_pitch / 2),
    y=int(app2.grid_oy + app2.cell_pitch / 2)))
hover2 = app2.lbl_hover.cget("text")
assert "Cell #1/256" in hover2 and "read 4 blocks" in hover2, hover2
print("全段扫描悬停: %r" % hover2)
app2._cancel_timers()
app2.destroy()
root.destroy()
print("\nGUI 扫描全链路（快速 + 全段 + 导出）通过")
