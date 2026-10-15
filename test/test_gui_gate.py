# -*- coding: utf-8 -*-
"""GUI 门禁测试（模块布局：HD_Doc_gui + HD_Doc_core）。

界面固定英文（HDTUNE_LANG=en）；覆盖提权目标选择与提权分支。
"""
import os
import sys
import time

os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
os.environ["HDTUNE_LANG"] = "en"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_gui as H
from HD_Doc_core import _pythonw_path, _elevation_target

root = H.tk.Tk()
root.withdraw()
app = H.HDDocApp()
app.withdraw()
app.update()
print("启动权限标签: %r（本会话 is_admin=%s）"
      % (app.lbl_admin.cget("text"), H.is_admin()))
assert "Permission" in app.lbl_admin.cget("text")

B = chr(92)
phys = B + B + "." + B + "PhysicalDrive1"

# ---- 提权目标必须指向 pythonw.exe（无控制台窗口的关键） ----
pw = _pythonw_path()
exe, params = _elevation_target()
print("pythonw 路径: %r" % pw)
print("提权目标 exe=%r params=%r" % (exe, params))
if pw:
    assert os.path.basename(exe).lower() == "pythonw.exe", exe
assert os.path.basename(sys.argv[0]) in params
exe_g, _ = _elevation_target(gui=True)
assert os.path.basename(exe_g).lower() == "pythonw.exe", exe_g
print("提权目标选择 OK（GUI/CLI 均为 pythonw.exe）")

# ---- 场景 A：未提权 + 用户点"否" → 不启动扫描、不提权 ----
H.is_admin = lambda: False
answers = []
H.messagebox.askyesno = lambda *a, **k: (answers.append(a[0]) or False)
app.var_target.set(phys)
app._start_scan()
print("场景A: 弹窗标题=%r scanner=%s worker=%s"
      % (answers, app.scanner, app.worker))
assert answers and app.scanner is None

# ---- 场景 B：未提权 + 用户点"是" → request_elevation(wait=False, gui=True) 并退出 ----
elev_calls = []


def fake_elev(argv=None, wait=False, gui=False):
    elev_calls.append({"argv": argv, "wait": wait, "gui": gui})
    return (True, None, None)


H.request_elevation = fake_elev
H.messagebox.askyesno = lambda *a, **k: True
app._start_scan()
print("场景B: 提权调用=%r" % (elev_calls,))
assert elev_calls and elev_calls[0]["wait"] is False and elev_calls[0]["gui"] is True
for _ in range(10):
    app.update()
    time.sleep(0.05)
alive = True
try:
    alive = bool(app.winfo_exists())
except Exception:
    alive = False
print("场景B: 提权后窗口已退出 =", not alive)
assert not alive
root.destroy()
print("\nGUI 门禁全部场景通过")
