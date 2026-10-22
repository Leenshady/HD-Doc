"""集成测试：停止扫描的错误语义 + 引擎可用性探测。
需要 fio 与测试镜像（自动创建）。运行：
    python test/test_integration.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_core as H

FIO = "C:/Program Files/fio/fio.exe"
# 测试镜像放在仓库外的 ../fio_test（与其余测试套件共用），避免落进版本库
BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "..", "fio_test")
BIG = os.path.join(BASE, "it_big.img")     # 512MB，保证扫描持续数秒
SMALL = os.path.join(BASE, "it_small.img")  # 8MB，保证 3 秒内能扫完
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("   got : %r\n   want: %r" % (got, want))
        FAILS.append(name)


def make_file(path, size):
    if os.path.exists(path) and os.path.getsize(path) == size:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(size))


def scan_with_stop(target, segs, bs, stop_after, total_size):
    """跑扫描并在 stop_after 秒后调用 stop()，返回 (summary, error_block_events)"""
    sc = H.FioScanner(FIO)
    err_events = []

    def on_event(ev):
        if ev["type"] == "error_block":
            err_events.append(ev["index"])

    timer = threading.Timer(stop_after, sc.stop)
    timer.start()
    try:
        s = sc.run(target, bs, segs, ioengine="windowsaio", direct=True,
                   total_size=total_size, on_event=on_event)
    finally:
        timer.cancel()
    return s, err_events


def main():
    make_file(BIG, 512 * 1024 * 1024)
    make_file(SMALL, 8 * 1024 * 1024)
    big_size = H.query_target_size(BIG)
    small_size = H.query_target_size(SMALL)
    segs_big = [(0, 256 * 1024 * 1024), (256 * 1024 * 1024, 256 * 1024 * 1024)]

    print("== 引擎可用性 ==")
    engines = H.list_fio_engines(FIO)
    check("探测返回非空集合", bool(engines), True)
    if engines:
        check("libaio 不在 Windows fio 引擎列表（选它必报 failed to load engine）",
              "libaio" in engines and H.IS_WIN, False)
        check("posixaio 不在 Windows fio 引擎列表",
              "posixaio" in engines and H.IS_WIN, False)
        check("windowsaio 在引擎列表", "windowsaio" in engines, True)
    check("GUI 引擎下拉不含 libaio（Windows）",
          "libaio" in H.platform_engines() and H.IS_WIN, False)

    print("\n== 停止场景 A：扫描未完成时点停止（1.2s，确保仍在扫）==")
    s, errs = scan_with_stop(BIG, segs_big, 4 * 1024 * 1024, 1.2, big_size)
    # 1.2s 时 fio 刚启动完（进程启动约 1s），512MB 必然没扫完；
    # 不断言具体段表（时序相关），只断言停止语义。
    check("A aborted", s["aborted"], True)
    check("A 无错误块", len(s["error_blocks"]), 0)
    check("A errno_segments=0", s["errno_segments"], 0)
    check("A 无 error_block 事件", len(errs), 0)
    check("A 记录了停止未扫描字节", s["stopped_unscanned_bytes"] > 0, True)
    check("A 未扫完（总块数 < 128）", s["n_blocks"] < 128, True)

    print("\n== 停止场景 B：段0 读到一半时停止 ==")
    s, errs = scan_with_stop(BIG, segs_big, 4 * 1024 * 1024, 0.8, big_size)
    check("B aborted", s["aborted"], True)
    check("B 无错误块", len(s["error_blocks"]), 0)
    check("B 无 error_block 事件", len(errs), 0)
    check("B 记录了停止未扫描字节", s["stopped_unscanned_bytes"] > 0, True)

    print("\n== 停止场景 C：扫描完成后才到达停止信号 ==")
    s, errs = scan_with_stop(SMALL, [(0, 4 * 1024 * 1024),
                                     (4 * 1024 * 1024, 4 * 1024 * 1024)],
                             1024 * 1024, 3.5, small_size)
    check("C 不标记 aborted（确实扫完了）", s["aborted"], False)
    check("C 无错误块", len(s["error_blocks"]), 0)
    check("C 块数完整", s["n_blocks"], 8)
    check("C stopped_unscanned=0", s["stopped_unscanned_bytes"], 0)

    print("\n== 快速扫描（抽样布点，类 HD Tune Quick Scan）==")
    # 8MB 镜像：4MB 区域 × 2MB 抽样 → 2 个样本，1 秒内扫完
    q_segs = H.plan_quick_segments(small_size, 4 * 1024 * 1024, 2 * 1024 * 1024,
                                   1024 * 1024)
    check("快速扫描样本数=2", len(q_segs), 2)
    check("快速扫描样本=2MB", [s for _o, s in q_segs], [2 * 1024 * 1024] * 2)
    check("快速扫描 offset 对齐 4MB", [o for o, _s in q_segs],
          [0, 4 * 1024 * 1024])
    sc = H.FioScanner(FIO)
    s = sc.run(SMALL, 1024 * 1024, q_segs, ioengine="windowsaio", direct=True,
               total_size=small_size, quick=True, on_event=lambda e: None)
    check("快速扫描 quick 标记", s["quick"], True)
    check("快速扫描 2 段", len(s["segments"]), 2)
    check("快速扫描无错误", len(s["error_blocks"]), 0)
    check("快速扫描未中止", s["aborted"], False)
    check("快速扫描块数=4（2 样本 × 2 块）", s["n_blocks"], 4)
    check("快速扫描只读 4MB/8MB", sum(g["size"] for g in s["segments"]),
          4 * 1024 * 1024)
    outdir_q = os.path.join(BASE, "it_report_quick")
    files_q = H.write_reports(outdir_q, s, lang="en")
    check("快速扫描报告生成 3 个", len(files_q), 3)
    txt_q = open(os.path.join(outdir_q, "summary.txt"), encoding="utf-8").read()
    check("快速扫描报告含模式行", "Scan mode: quick scan" in txt_q, True)
    check("快速扫描报告含覆盖率", "% of capacity" in txt_q, True)

    print("\n== 段尾余数不产生假错误块（停止误报磁盘错误的根因回归）==")
    # 场景 1：段大小不是块的整数倍。实测差异——文件上 fio 会读不对齐的
    # 部分块（6.69MB/1M → 7 次 IO）；物理盘上不对齐尾巴直接跳过
    # （13.69MB/1M → 13 次 IO，旧代码 expected 用 ceil=14 → 假"未扫描"
    # 错误块 + 弹"物理损伤风险"，即用户反馈的停止扫描误报磁盘错误）。
    # 两种行为下 expected 取 floor 都不会误报。
    tail_seg = (0, 6 * 1024 * 1024 + 723519)   # 6.69MB，尾巴 723519B 不对齐
    sc = H.FioScanner(FIO)
    s = sc.run(SMALL, 1024 * 1024, [tail_seg], ioengine="windowsaio", direct=True,
               total_size=small_size, on_event=lambda e: None)
    check("不对齐尾巴: 无错误块（旧 ceil 在物理盘上会误报）",
          len(s["error_blocks"]), 0)
    check("不对齐尾巴: errno_segments=0", s["errno_segments"], 0)
    check("不对齐尾巴: 未读尾巴已记录", s["unread_tail_bytes"], 723519)
    check("不对齐尾巴: expected_ios=floor=6", s["segments"][0]["expected_ios"], 6)
    check("不对齐尾巴: 文件上实际读 7 块（>expected 不算错）",
          s["n_blocks"], 7)

    # 场景 2：段超出文件末尾。扫描器按容量钳制（fio 会把镜像文件扩展到
    # offset+size，只读工具绝不写目标），实际只读 [6M, 8M] 两块；
    # 不产生错误块/未扫描记录，目标文件大小不变。
    sc = H.FioScanner(FIO)
    s = sc.run(SMALL, 1024 * 1024, [(6 * 1024 * 1024, 4 * 1024 * 1024)],
               ioengine="windowsaio", direct=True,
               total_size=small_size, on_event=lambda e: None)
    check("EOF 截断: 无错误块", len(s["error_blocks"]), 0)
    check("EOF 截断: expected_ios 按可读范围截断=2",
          s["segments"][0]["expected_ios"], 2)
    check("EOF 截断: 不记未扫描字节（越界部分本就不可读）",
          s["unscanned_bytes"], 0)
    check("EOF 截断: aborted=False（没人点停止）", s["aborted"], False)
    check("EOF 截断: 目标文件未被扩展（只读承诺）",
          os.path.getsize(SMALL), small_size)

    # 场景 3：部分块 512 对齐时 fio 会读它（actual=7 > expected=6），也不算错
    sc = H.FioScanner(FIO)
    s = sc.run(SMALL, 1024 * 1024, [(0, 6 * 1024 * 1024 + 524288)],
               ioengine="windowsaio", direct=True,
               total_size=small_size, on_event=lambda e: None)
    check("对齐部分块: 无错误块", len(s["error_blocks"]), 0)
    check("对齐部分块: 读了 7 块", s["n_blocks"], 7)

    print("\n== fio 冒号拆分回归（绝对路径不得在当前目录留下 C 垃圾文件）==")
    # 背景：fio 的 --filename 把冒号当多文件分隔符，"C:\\...\\it_small.img"
    # 会被拆成 "C"（当前目录凭空创建的垃圾文件，分走一半 I/O）和真实路径。
    # 修复：_fio_target_arg 去掉盘符冒号改根相对路径 + fio 子进程 cwd=盘符根。
    # 断言：绝对路径扫描后 cwd 无新增文件，且块数 = 单文件完整读取的期望值。
    cwd_before = set(os.listdir("."))
    sc = H.FioScanner(FIO)
    s = sc.run(SMALL, 1024 * 1024, [(0, 4 * 1024 * 1024)],
               ioengine="windowsaio", direct=True,
               total_size=small_size, on_event=lambda e: None)
    cwd_new = set(os.listdir(".")) - cwd_before
    check("绝对路径扫描: cwd 无新增文件（无 C 垃圾）", cwd_new, set())
    check("绝对路径扫描: 块数=4（4MB/1M 全来自真实文件）", s["n_blocks"], 4)
    check("绝对路径扫描: 无错误块", len(s["error_blocks"]), 0)
    check("_fio_target_arg: 带盘符路径去冒号", H._fio_target_arg("C:\\a\\b.img"),
          ("a\\b.img", "C:\\"))
    check("_fio_target_arg: 正斜杠盘符路径", H._fio_target_arg("D:/x/y.img"),
          ("x/y.img", "D:\\"))
    check("_fio_target_arg: 物理盘路径不动", H._fio_target_arg("\\\\.\\PhysicalDrive0"),
          ("\\\\.\\PhysicalDrive0", None))
    check("_fio_target_arg: 相对路径不动", H._fio_target_arg("it_small.img"),
          ("it_small.img", None))
    # UNC 别名（//./PhysicalDriveN）必须转回反斜杠形式再交给 fio：正斜杠
    # 形式会让 fio 走"普通文件"分支 unlink 探测，直接 EACCES（实测
    # errno 13, filesetup.c:151）——整盘每个分段都读失败
    check("_fio_target_arg: UNC 设备别名转反斜杠",
          H._fio_target_arg("//./PhysicalDrive0"),
          ("\\\\.\\PhysicalDrive0", None))
    check("_fio_target_arg: UNC 卷别名转反斜杠",
          H._fio_target_arg("//./C:"), ("\\\\.\\C:", None))

    print("\n== 报告导出（aborted 语义 + 双语）==")
    outdir = os.path.join(BASE, "it_report")
    files = H.write_reports(outdir, s, lang="en")
    check("报告文件生成 3 个", len(files), 3)
    txt = open(os.path.join(outdir, "summary.txt"), encoding="utf-8").read()
    check("summary.txt 含 IO 引擎行", "IO engine: windowsaio" in txt, True)
    # 中文报告（同一汇总，lang=zh）
    outdir_zh = os.path.join(BASE, "it_report_zh")
    H.write_reports(outdir_zh, s, lang="zh")
    txt_zh = open(os.path.join(outdir_zh, "summary.txt"),
                  encoding="utf-8").read()
    check("中文报告含 IO 引擎行", "IO 引擎: windowsaio" in txt_zh, True)
    seg_head = open(os.path.join(outdir_zh, "segments.csv"),
                    encoding="utf-8-sig").readline()
    check("中文报告 CSV 表头", seg_head.startswith("段号,"), True)

    print()
    if FAILS:
        print("失败 %d 项: %s" % (len(FAILS), FAILS))
        return 1
    print("集成测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
