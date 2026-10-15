# -*- coding: utf-8 -*-
"""test_hdd_stop.py —— 真实 HDD 快速扫描中途停止复现（用户 bug 原始场景）

场景：PhysicalDrive0（WDC WD10EZEX 1TB HDD）快速扫描进行中用户点停止。
期望（修复后）：
  1. cli_main 返回 130（KeyboardInterrupt 停止路径）
  2. 控制台输出含 "Aborted."（CLI 固定英文）
  3. 远早于完整扫描结束

说明：中断发生在写报告之前，不产出报告文件夹（真实 Ctrl+C 同样如此，
也正是"不要每次扫描都落盘"的预期行为）；停止语义的完整断言见
test_gui_stop.py（A/B/C 三场景）与 test_integration.py。
"""
import argparse
import io
import os
import sys
import threading
import time
import _thread

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import HD_Doc_cli  # noqa: E402
import HD_Doc_core as core  # noqa: E402

TARGET = "\\\\.\\PhysicalDrive0"

args = argparse.Namespace(
    cli=True, target=TARGET, bs="auto", segment_gb=4, quick=True,
    quick_sample_mb=16, ioengine=None, no_direct=False, no_elevate=True,
    fio=None, limit_mb=0, offset_mb=0, export=None,
    yellow_mult=3.0, red_mult=8.0, yellow_floor_ms=10.0, red_floor_ms=100.0)

enc = core._console_encoding()
buf = io.TextIOWrapper(io.BytesIO(), encoding=enc)
old = sys.stdout
sys.stdout = buf

def watcher():
    time.sleep(12.0)                # 快速扫描约 1.5-2 分钟，12s 时约 10% 处停止
    try:
        _thread.interrupt_main()    # 等价 Ctrl+C / GUI 停止按钮
    except RuntimeError:
        pass

t = threading.Thread(target=watcher, daemon=True)
t.start()
t0 = time.time()
rc = HD_Doc_cli.cli_main(args)
elapsed = time.time() - t0
buf.flush()
sys.stdout = old
text = buf.detach().getvalue().decode(enc, "replace")

ok = True
def check(name, cond):
    global ok
    print("PASS" if cond else "FAIL", name)
    ok = ok and cond

check("cli_main 返回 130（停止路径）", rc == 130)
check("输出含 'Aborted.'", "Aborted." in text)
check("远早于完整扫描结束（elapsed < 60s）", elapsed < 60.0)

print("\n真实 HDD 中途停止回归：" + ("全部通过" if ok else "存在失败项"))
sys.exit(0 if ok else 1)
