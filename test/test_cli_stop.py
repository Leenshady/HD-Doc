# -*- coding: utf-8 -*-
"""test_cli_stop.py —— CLI 模式真实中途停止回归（用户 bug：停止后误报磁盘错误）

方案：进程内驱动 HD_Doc_cli.cli_main，看门狗线程在扫描跑起来后调用
_thread.interrupt_main() —— 与 Ctrl+C 等价（主线程收到 KeyboardInterrupt）。
扫描为真实 fio + 真实文件（256MB / 4K 块，约 5s，停止点在 2s）。

必须满足：
  1. cli_main 返回 130（KeyboardInterrupt 路径）
  2. 控制台输出含 "Aborted."（CLI 固定英文）
  3. 在扫描结束前被中断

说明：KeyboardInterrupt 路径在写报告前中断，不产出报告（真实 Ctrl+C
同样如此）；报告按需导出的行为由 test_cli_gate.py 场景 7 覆盖。
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
os.environ["HD_DOC_LOG"] = "off"   # 运行日志隔离：不写真实配置目录
import HD_Doc_cli  # noqa: E402
import HD_Doc_core as core  # noqa: E402

TARGET = os.path.join(HERE, "exe_test_256mb.bin")
if not os.path.isfile(TARGET):
    with open(TARGET, "wb") as f:
        f.truncate(256 * 1024 * 1024)   # 稀疏文件，4K 块整盘扫约 5s
    print("[信息] 已创建测试文件 %s" % TARGET)

args = argparse.Namespace(
    cli=True, target=TARGET, bs="4K", segment_gb=0, quick=False,
    quick_sample_mb=0, ioengine=None, no_direct=False, no_elevate=True,
    fio=None, limit_mb=0, offset_mb=0, export=None,
    yellow_mult=3.0, red_mult=8.0, yellow_floor_ms=10.0, red_floor_ms=100.0)

# 用与终端编码一致的 TextIOWrapper 捕获输出：cli_main 内的 _ensure_console
# 发现编码已匹配会提前返回，不会把 sys.stdout 重建到真实 fd 1
enc = core._console_encoding()
buf = io.TextIOWrapper(io.BytesIO(), encoding=enc)
old = sys.stdout
sys.stdout = buf

def watcher():
    time.sleep(2.0)                 # 扫描进行到约 40% 时停止
    try:
        _thread.interrupt_main()    # 等价 Ctrl+C
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

check("cli_main 返回 130（KeyboardInterrupt 路径）", rc == 130)
check("输出含 'Aborted.'", "Aborted." in text)
check("在扫描结束前被中断（elapsed < 5s）", elapsed < 5.0)

print("\nCLI 中途停止回归：" + ("全部通过" if ok else "存在失败项"))
sys.exit(0 if ok else 1)
