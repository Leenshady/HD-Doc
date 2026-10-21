# -*- coding: utf-8 -*-
"""进程连坐回归：fio/本进程随父进程共存亡（任务管理器强杀场景）。

用户实测：扫描中用任务管理器"结束任务"，程序被杀后 fio.exe 残留继续
把整盘读完（任务管理器还会因拒绝访问连弹多个"无法终止该进程"提示框）。
修复一：Windows Job Object + JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE——本进程
被任何方式杀死时内核连坐终止 job 内 fio。
修复二：父进程监控（watch_parent_process，Windows 版 PDEATHSIG）——onefile
进程树是 bootloader(父) → python(本进程) → fio(子)，任务管理器结束**上面
那个同名进程**（bootloader）时本进程与 fio 不会跟着退，父进程句柄等待
发现父死后同步杀 fio 并退出。

覆盖五档：
  1. 静态：job 创建 / assign 自己进程成功 / assign 无效句柄不抛
  2. spy：真实扫描中 fio 的 Popen 句柄被 assign 进 job
  3. 端到端：外部 taskkill 强杀父进程 → 子进程连坐死亡（job 方向）
  4. 静态：父进程句柄可打开 / 监控线程可启动（watch_parent_process）
  5. 端到端：杀 bootloader 父进程 → python 子与 fio 全部退出（父监控方向）

非 Windows 平台跳过（Linux 等价机制 PR_SET_PDEATHSIG 未引入，见
core._create_kill_on_close_job 注释）。运行：
    python test/test_job_kill.py
"""
import ctypes
import csv
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
BIG = os.path.join(BASE, "it_big.img")         # 512MB，quick 扫几分钟
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(REPO, "dist", "HD_Doc.exe")  # onefile 产物（build_exe.py）
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("   got : %r\n   want: %r" % (got, want))
        FAILS.append(name)


def _csv_fields(line):
    """解析 tasklist CSV 行（字段可能带引号、内存值内含千位逗号，
    裸 split(',') 会把 "11,140 K" 打散——必须用 csv.reader）。"""
    try:
        return next(csv.reader([line]))
    except StopIteration:
        return []


def proc_alive(pid, name="python.exe"):
    """跨 Windows 的进程存活探测（tasklist CSV，无 psutil 依赖）"""
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO",
                          "CSV", "/NH"], capture_output=True)
    txt = out.stdout.decode("gbk", errors="replace")
    return any(f[0].lower() == name.lower() and str(pid) in line
               for line in txt.splitlines()
               for f in [_csv_fields(line)] if f)


def image_pids(name):
    """返回 [(pid, mem_kb)]：某映像名全部进程（按内存升序）。"""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/FO",
                          "CSV", "/NH"], capture_output=True)
    txt = out.stdout.decode("gbk", errors="replace")
    rows = []
    for line in txt.splitlines():
        f = _csv_fields(line)
        if len(f) >= 5 and f[0].lower() == name.lower():
            try:
                rows.append((int(f[1]),
                             int(f[4].replace(",", "").replace(" K", ""))))
            except ValueError:
                pass
    return sorted(rows, key=lambda r: r[1])


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

# ------------------------------------------------------------ 4. 父进程监控（静态）
print("\n== 4. 父进程监控静态行为（watch_parent_process） ==")
if H.IS_WIN:
    h = H._parent_process_handle()
    check("父进程句柄可打开（测试进程的父：pytest/终端）", bool(h), True)
    if h:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CloseHandle(h)
    fired = []
    t = H.watch_parent_process(lambda: fired.append(1))
    check("watch_parent_process 返回守护线程",
          (t is not None and t.is_alive() and t.daemon), True)
    check("父进程存活期间回调不触发", fired, [])
    time.sleep(0.3)
    check("回调仍不误触发（父还活着）", fired, [])
else:
    check("非 Windows 返回 None", H.watch_parent_process(lambda: None), None)

# ------------------------------------------------------------ 5. 端到端：杀 bootloader 父
print("\n== 5. 杀 bootloader 父进程 → python 子与 fio 全部退出（端到端） ==")
# 复现用户场景：onefile 进程树 bootloader(父) → python(子) → fio，任务
# 管理器结束上面那个同名进程（bootloader）后，子与 fio 必须全部退出、
# 扫描输出停止增长。缺 exe 产物时跳过（开发机未 build_exe.py）。
if not (H.IS_WIN and os.path.isfile(EXE) and os.path.isfile(BIG)):
    print("跳过（需要 dist/HD_Doc.exe 与 it_big.img，先跑 build_exe.py）")
else:
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "hd_doc_jobkill_parent.out")
    env = dict(os.environ, HDTUNE_NO_AUTO_ELEVATE="1")
    logf = open(out, "wb")
    proc = subprocess.Popen(
        [EXE, "--cli", "--target", BIG, "--quick"],
        stdout=logf, stderr=subprocess.STDOUT, env=env, cwd=REPO)
    try:
        # 等进程树成形：bootloader + python 子 + fio 各就位
        hd, fio = [], []
        for _ in range(40):
            time.sleep(0.5)
            hd = image_pids("HD_Doc.exe")
            fio = image_pids("fio.exe")
            if len(hd) >= 2 and fio:
                break
        check("进程树成形（bootloader + python 子 + fio）",
              len(hd) >= 2 and bool(fio), True)
        boot_pid, _kb = hd[0]            # 内存小的是 bootloader 父
        child_pid, _kb2 = hd[-1]         # 内存大的是 python 子
        fio_pid = fio[0][0]
        logf.flush()
        size_before = os.path.getsize(out)
        print("bootloader=%d python-child=%d fio=%d，杀父进程…"
              % (boot_pid, child_pid, fio_pid))
        subprocess.run(["taskkill", "/F", "/PID", str(boot_pid)],
                       capture_output=True)   # 模拟任务管理器结束父进程
        # 父死后 python 子应立即杀 fio 并退出（watch_parent_process）
        for _ in range(20):
            time.sleep(0.5)
            if not proc_alive(child_pid, "HD_Doc.exe"):
                break
        logf.flush()
        size_after = os.path.getsize(out)
        check("杀前扫描输出已有内容", size_before > 0, True)
        check("python 子进程随父进程退出", proc_alive(child_pid, "HD_Doc.exe"), False)
        check("fio 不再残留", image_pids("fio.exe"), [])
        check("扫描输出停止增长", size_after >= size_before, True)
        time.sleep(1.5)
        logf.flush()
        check("输出确认不再增长（无孤儿继续读）",
              os.path.getsize(out), size_after)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
        for name in ("HD_Doc.exe", "fio.exe"):
            for pid, _kb in image_pids(name):
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True)
        logf.close()
        try:
            os.remove(out)
        except OSError:
            pass

print()
if FAILS:
    print("失败 %d 项: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("进程连坐回归全部通过")
