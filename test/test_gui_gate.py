# -*- coding: utf-8 -*-
"""GUI 门禁测试（模块布局：HD_Doc_gui + HD_Doc_core）。

界面固定英文（HDTUNE_LANG=en）；覆盖提权目标选择与提权分支。
提权策略（启动即提权，不再先弹"是否重启"确认框）：
  入口 ensure_admin_at_startup：非管理员 + 允许自动提权 → 直接弹 UAC；
    UAC 确认 → 返回 True（调用方退出，提权进程接管）；取消 → False（继续运行）
  扫描物理盘时仍未提权 + 允许自动提权 → 同样直接弹 UAC；
    --no-elevate 关闭自动提权 → 不提权不扫描，只出横幅

offscreen 平台；提权分支全部用假 request_elevation 驱动，不真弹 UAC。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
os.environ["HDTUNE_LANG"] = "en"
os.environ["HDTUNE_THEME"] = "bootstrap-light"
os.environ["HD_DOC_LOG"] = "off"   # 运行日志隔离：不写真实配置目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtWidgets import QApplication
import HD_Doc_gui as H
from HD_Doc_core import _pythonw_path, _elevation_target, tr

qt_app = QApplication.instance() or QApplication(sys.argv)
app = H.HDDocApp()
app.show()
QApplication.processEvents()
print("启动权限标签: %r（本会话 is_admin=%s）"
      % (app.lbl_admin.text(), H.is_admin()))
assert "Permission" in app.lbl_admin.text()

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

# ---- 场景 A：未提权 + 自动提权开 + UAC 被取消 → 不扫描、不出确认框、不退出 ----
H.is_admin = lambda: False
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "0"      # 本场景打开自动提权
elev_calls = []


def fake_elev_cancel(argv=None, wait=False, gui=False):
    elev_calls.append({"argv": argv, "wait": wait, "gui": gui})
    # 用户在 UAC 点了"否"：ShellExecuteExW 返回 ERROR_CANCELLED
    return (False, None, tr("err.uac_cancelled"))


H.request_elevation = fake_elev_cancel
app._set_target_text(phys)
app._start_scan()
QApplication.processEvents()
print("场景A: 提权调用=%r scanner=%s worker=%s 横幅=%r"
      % (elev_calls, app.scanner, app.worker, app.lbl_banner.text()))
assert elev_calls and elev_calls[0]["wait"] is False and elev_calls[0]["gui"] is True
assert app.scanner is None and app.worker is None, "UAC 取消不得启动扫描"
assert "Cannot restart as administrator" in app.lbl_banner.text(), \
    "UAC 取消应出横幅提示"
assert app.isVisible(), "UAC 取消不应退出程序"
print("场景A OK（UAC 取消：直接提权无确认框，只出横幅，不扫描、不退出）")

# ---- 场景 B：未提权 + UAC 确认 → request_elevation(wait=False, gui=True) 并退出 ----
elev_calls.clear()


def fake_elev(argv=None, wait=False, gui=False):
    elev_calls.append({"argv": argv, "wait": wait, "gui": gui})
    return (True, None, None)


H.request_elevation = fake_elev
app._start_scan()
print("场景B: 提权调用=%r" % (elev_calls,))
assert elev_calls and elev_calls[0]["wait"] is False and elev_calls[0]["gui"] is True
for _ in range(10):
    QApplication.processEvents()
    time.sleep(0.05)
alive = True
try:
    alive = bool(app.isVisible())
except Exception:
    alive = False
print("场景B: 提权后窗口已退出 =", not alive)
assert not alive
print("场景B OK（UAC 确认：直接提权重启，本进程退出）")

# ---- 场景 C：--no-elevate 关闭自动提权 → 不提权、不扫描、只出横幅 ----
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
app = H.HDDocApp()
app.show()
QApplication.processEvents()
H.is_admin = lambda: False
elev_calls.clear()
app._set_target_text(phys)
app._start_scan()
QApplication.processEvents()
print("场景C: 提权调用=%r scanner=%s 横幅=%r"
      % (elev_calls, app.scanner, app.lbl_banner.text()))
assert elev_calls == [], "--no-elevate 时不得发起提权"
assert app.scanner is None
assert "administrator rights" in app.lbl_banner.text(), \
    "--no-elevate 时应出横幅提示需要管理员权限"
app._cancel_timers()
app.close()
print("场景C OK（--no-elevate：只提示，不提权不扫描）")

# ---- 场景 D：入口 ensure_admin_at_startup（启动即提权的策略函数） ----
ensure = H.ensure_admin_at_startup

# D1 已提权：直接放行，不提权
H.is_admin = lambda: True
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "0"
calls = []
H.request_elevation = lambda *a, **k: calls.append(k) or (True, None, None)
assert ensure() is False and calls == []
print("D1 已提权 → 不提权 OK")

# D2 未提权 + 自动提权 + UAC 确认 → True（调用方退出，提权进程接管）
H.is_admin = lambda: False
calls.clear()
assert ensure() is True, "UAC 确认后应请求调用方退出"
assert len(calls) == 1 and calls[0].get("wait") is False \
    and calls[0].get("gui") is True, calls
print("D2 UAC 确认 → 返回 True（调用方退出）OK")

# D3 未提权 + UAC 取消 → False（继续标准权限运行）
H.request_elevation = lambda *a, **k: (False, None, tr("err.uac_cancelled"))
assert ensure() is False, "UAC 取消后应继续运行"
print("D3 UAC 取消 → 返回 False（继续运行）OK")

# D4 未提权 + --no-elevate → 不提权
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
calls.clear()
H.request_elevation = lambda *a, **k: calls.append(k) or (True, None, None)
assert ensure() is False and calls == []
print("D4 --no-elevate → 不提权 OK")

print("\nGUI 门禁全部场景通过")
