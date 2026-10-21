# -*- coding: utf-8 -*-
"""Job Object 回归：fio 子进程随本程序共存亡（任务管理器强杀场景）。

用户实测：扫描中用任务管理器"结束任务"，程序被杀后 fio.exe 残留继续
把整盘读完（任务管理器还会因拒绝访问连弹多个"无法终止该进程"提示框）。
修复：Windows Job Object + JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE，父进程被
任何方式杀死时内核连坐终止 job 内全部进程。

覆盖三档：
  1. 静态：job 创建 / assign 自己进程成功 / assign 无效句柄不抛
  2. spy：真实扫描中 fio 的 Popen 句柄被 assign 进 job
  3. 端到端：外部 taskkill 强杀父进程 → 子进程死亡

非 Windows 平台跳过（Linux 等价机制 PR_SET_PDEATHSIG 未引入，见
core._create_kill_on_close_job 注释）。运行：
    python test/test_job_kill.py
"""
import ctypes
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_core as H

FIO = "C:/Program Files/fio/fio.exe"
BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "..", "fio_test")
SMALL = os.path.join(BASE, "it_small.img")     # 8MB，1 秒内扫完
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("   got : %r\n   want: %r" % (got, want))
        FAILS.append(name)


def proc_alive(pid):
    """跨 Windows 的进程存活探测（tasklist CSV，无 psutil 依赖）"""
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO",
                          "CSV", "/NH"], capture_output=True)
    txt = out.stdout.decode("gbk", errors="replace")
    return any(line.split(",")[0].strip('"') == "python.exe"
               and str(pid) in line for line in txt.splitlines())


# ------------------------------------------------------------ 角色进程
# 端到端测试需要"父进程被外部杀死、子进程应连坐死亡"，用本文件自身扮演：
#   --job-child  长睡 60s 的 fio 替身
#   --job-parent 起 child、assign 进 job、长睡等控制端强杀
if "--job-child" in sys.argv:
    time.sleep(60)
    sys.exit(0)

if "--job-parent" in sys.argv:
    child = subprocess.Popen([sys.executable, os.path.abspath(__file__),
                              "--job-child"])
    job, assign = H._create_kill_on_close_job()
    assert job and assign, "job 创建失败（仅 Windows 可跑）"
    ok = assign(getattr(child, "_handle", 0))
    print("child pid=%d assigned=%s" % (child.pid, ok), flush=True)
    time.sleep(60)                    # 等控制端 taskkill 本进程
    child.kill()
    sys.exit(0)


if not H.IS_WIN or not os.path.isfile(FIO) or not os.path.isfile(SMALL):
    print("非 Windows 或缺少 fio/测试镜像，跳过（Job Object 仅 Windows 生效）")
    sys.exit(0)

# ------------------------------------------------------------ 1. 静态
print("== 1. Job Object 静态行为 ==")
job, assign = H._create_kill_on_close_job()
check("job 创建成功", bool(job) and callable(assign), True)
if job:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    self_h = k32.OpenProcess(0x0100 | 0x0001, False, os.getpid())  # SET_QUOTA|TERMINATE
    check("assign 自己的进程句柄成功", bool(self_h) and assign(self_h), True)
    if self_h:
        k32.CloseHandle(self_h)
    check("assign 无效句柄返回 False 不抛", assign(0), False)

# ------------------------------------------------------------ 2. spy 真实扫描
print("\n== 2. 真实扫描中 fio 被 assign 进 job ==")
spy = {"creates": 0, "assigns": []}
orig_create = H._create_kill_on_close_job


def spy_create():
    spy["creates"] += 1
    job, assign = orig_create()
    if job:
        def spy_assign(proc_handle):
            r = assign(proc_handle)
            spy["assigns"].append((proc_handle, r))
            return r
        return job, spy_assign
    return job, assign


H._create_kill_on_close_job = spy_create
try:
    sc = H.FioScanner(FIO)
    s = sc.run(SMALL, 512 * 1024, [(0, 8 << 20)], ioengine="windowsaio",
               direct=True, total_size=8 << 20, on_event=lambda e: None)
finally:
    H._create_kill_on_close_job = orig_create
check("扫描成功（无错误块）", len(s["error_blocks"]), 0)
check("job 每次扫描创建一次", spy["creates"], 1)
check("fio 句柄被 assign 进 job", len(spy["assigns"]) >= 1, True)
check("assign 全部成功", all(r for _ph, r in spy["assigns"]), True)
check("scanner 持有 job 句柄（防 GC 触发杀 job）",
      sc._job is not None, True)

# ------------------------------------------------------------ 3. 端到端连坐
print("\n== 3. 强杀父进程 → 子进程连坐终止（端到端） ==")
parent = subprocess.Popen([sys.executable, os.path.abspath(__file__),
                           "--job-parent"], stdout=subprocess.PIPE, text=True)
line = parent.stdout.readline().strip()
print("parent pid=%d | %s" % (parent.pid, line))
child_pid = int(line.split("child pid=")[1].split()[0])
time.sleep(1.5)
check("杀前父子都在", proc_alive(parent.pid) and proc_alive(child_pid), True)
subprocess.run(["taskkill", "/F", "/PID", str(parent.pid)],
               capture_output=True)      # 模拟任务管理器"结束任务"
time.sleep(3)
check("父进程已死", proc_alive(parent.pid), False)
check("子进程连坐死亡（程序被杀 fio 不留后台）", proc_alive(child_pid), False)
if proc_alive(child_pid):                # 失败时清理，别真留 60s 睡眠
    subprocess.run(["taskkill", "/F", "/PID", str(child_pid)],
                   capture_output=True)
parent.wait(timeout=10)

print()
if FAILS:
    print("失败 %d 项: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("Job Object 回归全部通过")
