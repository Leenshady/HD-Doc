#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HD_Doc_cli.py —— 命令行模式（只依赖 HD_Doc_core，不 import tkinter / GUI）

用法由入口 HD_Doc.py 解析参数后调用 cli_main(args)；
也可以直接 python HD_Doc.py --cli --target <目标> ...

CLI 输出固定为英文（与界面语言无关）。扫描结果默认不落盘，
加 --export [DIR] 才把报告（segments.csv / errors.csv / summary.txt）
写入 DIR 下的 HD_Doc_report_<时间戳>/ 目录。
"""

import os
import sys
import time
from datetime import datetime

import HD_Doc_core as core                      # 业务逻辑全部经 core
from HD_Doc_core import *                       # 常用名直接可用（调用点不变）
from HD_Doc_core import (_cli_bind_parent_console,  # 下划线名需显式导入
                         _ensure_console,
                         set_language)

# ---------------------------------------------------------------- CLI 模式
def cli_main(args):
    # 提权重启来的 CLI 子进程（pythonw 启动、无控制台）先把输出绑回
    # 原终端；非提权进程此调用直接返回，不做任何事
    _cli_bind_parent_console()
    # 打包版（--windowed，GUI 子系统）在命令行里运行时没有控制台、
    # sys.stdout 为 None，这里绑回父进程终端（cmd/PowerShell 启动时有效）
    _ensure_console()
    # CLI 输出固定英文（界面语言只影响 GUI）
    set_language("en")
    core.log_event("cli: start target=%s bs=%s segment_gb=%s quick=%s "
                   "limit_mb=%s offset_mb=%s export=%s"
                   % (args.target, args.bs, args.segment_gb, args.quick,
                      args.limit_mb, args.offset_mb, args.export))
    fio = resolve_fio(args.fio)
    target = normalize_target_path(args.target)
    if not target:
        core.log_event("cli: --target missing or invalid (%r)" % (args.target,),
                       level="ERROR")
        print("Error: --cli mode requires --target")
        return 2
    if is_physical_target(target) and not is_admin():
        # 打开 \\.\PhysicalDriveN 必须管理员权限，否则 fio 每个块都会报
        # "windowsaio: failed to open file"。这里自动申请 UAC 提权重启。
        if getattr(args, "no_elevate", False) or not auto_elevate_enabled():
            core.log_event("cli: physical disk target but elevation disabled "
                           "(--no-elevate); aborting", level="ERROR")
            print("[Error] Scanning physical disks requires administrator rights "
                  "(fio must be elevated to open \\\\.\\PhysicalDriveN).")
            print("        Right-click the terminal and run as administrator, "
                  "or drop --no-elevate to allow automatic elevation.")
            return 2
        print("[Elevate] Target is a physical disk and not elevated; "
              "requesting administrator rights (UAC)...")
        ok, code, err = request_elevation(wait=True)
        if not ok:
            core.log_event("cli: elevation failed: %s" % (err or "unknown"),
                           level="ERROR")
            print("[Error] Elevation failed: %s" % (err or "unknown error"))
            print("        Right-click the terminal, run as administrator, retry.")
            return 2
        core.log_event("cli: elevated child finished with exit code %s" % (code,))
        print("[Elevate] Elevated process finished with exit code %s." % code)
        return code if isinstance(code, int) else 0
    size = query_target_size(target)
    bs = parse_bs(args.bs, size)
    if size and bs > size:
        bs = clamp_bs(bs, size)
        print("[Note] Block size exceeds disk capacity; adjusted to %s" % fmt_bytes(bs))

    # --segment-gb 显式性判断：0.0 是 falsy 不能当"未指定"，
    # str(0.0)="0.0" 也不在关键词里——整盘一次（显式 0/none/整盘）必须
    # 与"未指定（默认 4G，与 GUI 下拉默认一致）"区分开
    seg_arg = getattr(args, "segment_gb", None)
    seg_whole = False
    seg_explicit = False
    if seg_arg is not None:
        try:
            seg_whole = float(seg_arg) == 0
        except (TypeError, ValueError):
            pass
        seg_whole = seg_whole or str(seg_arg).strip().lower() in ("none", "整盘")
        seg_explicit = not seg_whole

    if args.limit_mb:
        off = int(args.offset_mb * 1024 * 1024)
        aligned_off = (off // bs) * bs
        if aligned_off != off:
            print("[Note] Start offset %d not aligned to block size %s; adjusted to %d"
                  " (direct IO requires aligned offsets, otherwise fio fails with EINVAL)"
                  % (off, fmt_bytes(bs), aligned_off))
        seg = (aligned_off, int(args.limit_mb * 1024 * 1024))
        segments = [seg]
    else:
        # 分段默认与 GUI 下拉一致：未指定时 4G（显式 0/none/整盘 → 整盘
        # 一次，显式大小 → 按大小切）。快速扫描与全段扫描共用同一套分段
        # 设置：按分段大小把磁盘切成若干区域，每区只读开头样本（用户反馈
        # "取消固定 256 段，按照分段设置分段"——旧版快速扫描固定按格数
        # 布 256 区，与 --segment-gb 脱节）。
        quick = bool(getattr(args, "quick", False))
        if seg_explicit:
            seg_bytes = parse_bs("%gG" % float(args.segment_gb))
        elif seg_whole:
            seg_bytes = None            # 显式整盘一次
        else:
            seg_bytes = parse_bs("4G")  # 默认 4G（与 GUI 下拉默认一致）
        quick_sample = 0
        if quick:
            if size:
                bs, segments, quick_sample = quick_scan_setup(
                    size, bs, seg_bytes,
                    int((getattr(args, "quick_sample_mb", 0) or 0) * 1024 * 1024))
            else:
                print("[Warning] Quick scan needs a known capacity to place samples "
                      "evenly; capacity unknown, falling back to a single full pass.")
                segments = plan_segments(size, seg_bytes, bs)
        else:
            segments = plan_segments(size, seg_bytes, bs)
    segments = sanitize_segments(segments, bs)

    if seg_explicit and not size:
        print("[Warning] Could not query target capacity (raw devices usually need "
              "administrator rights; or PowerShell/WMI query is disabled), "
              "cannot segment by %sG.\n"
              "        Falling back to a single full pass: no live progress/ETA, "
              "the heatmap is generated only after the scan ends, and stopping "
              "midway loses per-block data." % args.segment_gb)

    print("=" * 62)
    print("HD Tune Style Disk Error Scanner v%s (read-only)" % VERSION)
    print("=" * 62)
    print("Target    : %s" % target)
    print("Capacity  : %s" % fmt_bytes(size))
    print("Block size: %s (~%d blocks)" % (fmt_bytes(bs), (size // bs) if size else 0))
    if getattr(args, "quick", False) and size:
        covered = sum(s for _o, s in segments if s)
        cov_pct = covered * 100.0 / size if size else 0.0
        span = segments[1][0] - segments[0][0] if len(segments) > 1 else size
        print("Scan mode : quick scan, %d regions (region %s, sample %s each, "
              "covering %s, %.2f%% of capacity)"
              % (len(segments), fmt_bytes(span), fmt_bytes(quick_sample),
                 fmt_bytes(covered), cov_pct))
        if len(segments) > 1 and seg_bytes and span > seg_bytes:
            # 段数超硬上限被翻倍兜底：说明实际区域跨度，避免"设了 512M
            # 怎么变成 16G 一区"的困惑
            print("[Note] Segment size %s would create too many regions (one fio "
                  "launch per region); quick scan regions enlarged to %s."
                  % (fmt_bytes(seg_bytes), fmt_bytes(span)))
    else:
        print("Scan mode : %s" % ("whole disk in one pass" if len(segments) <= 1
                                  else "segmented, %d segments" % len(segments)))
    print("fio       : %s" % fio)
    if not os.path.isfile(fio):
        print("\n[Warning] fio executable not found. Windows: winget install fio.fio")
    engine = args.ioengine or ("windowsaio" if IS_WIN else "libaio")
    engines = list_fio_engines(fio)
    if engines is not None and engine not in engines:
        core.log_event("cli: ioengine %s unsupported by %s (available: %s)"
                       % (engine, fio, ", ".join(sorted(engines))), level="ERROR")
        print("\n[Error] Current fio does not support ioengine '%s'; scan not started." % engine)
        print("        Engines actually supported by this fio: %s" % "、".join(sorted(engines)))
        print("        Note: libaio / posixaio are native Linux engines; the Windows "
              "build of fio does not include them and fails with "
              "\"failed to load engine\".")
        print("        On Windows use: %s" % "、".join(ENGINES_WIN))
        return 2
    core.log_event("cli: plan target=%s size=%s bs=%s segments=%d engine=%s "
                   "direct=%s quick=%s fio=%s"
                   % (target, fmt_bytes(size), fmt_bytes(bs), len(segments),
                      engine, not args.no_direct,
                      bool(getattr(args, "quick", False)), fio))
    print("IO engine : %s" % engine)
    print("-" * 62)

    state = {"last_print": 0.0, "tick": None}
    scanner = FioScanner(fio)
    # onefile 父进程（bootloader）被外部杀死时（任务管理器结束上面那个
    # 同名进程），本进程与 fio 不会跟着退、会变孤儿继续读盘：父进程监控
    # 发现父死后同步杀 fio 并退出（与 GUI 同一机制，见 core.watch_parent_process）
    def _on_parent_died():
        core.log_event("cli: parent bootloader died; killing fio and exiting",
                       level="WARN")
        scanner.kill_fio_now()
        os._exit(3)

    core.watch_parent_process(_on_parent_died)
    # 快速扫描的进度/ETA 按"计划读取量"（抽样总量）计算，而不是磁盘容量：
    # 1TB 盘抽样 1.8GB 若按整盘算 ETA 会显示剩余十几分钟（实测误导），
    # 按 1.8GB 算才是真实剩余时间
    progress_total = size
    if getattr(args, "quick", False) and size:
        planned = sum(s for _o, s in segments if s)
        if planned:
            progress_total = planned

    def on_event(ev):
        et = ev.get("type")
        if et == "tick":
            state["tick"] = ev
            now = time.time()
            if now - state["last_print"] >= 2.0:
                state["last_print"] = now
                _cli_print_progress(ev, progress_total, base_done_of(ev, segments))
        elif et == "segment":
            sz_txt = ("  size %s" % fmt_bytes(ev["size"])) if ev["size"] else "(to end)"
            if getattr(args, "quick", False) and size and ev["size"]:
                sz_txt += " (sampled)"
            print("\n[Segment %d/%d] offset %s%s"
                  % (ev["index"] + 1, ev["total"], fmt_bytes(ev["offset"]), sz_txt))
        elif et == "log" and ev.get("stream") == "stderr":
            print("  [fio] %s" % ev["line"])
        elif et == "finished":
            state["summary"] = ev["summary"]

    def base_done_of(ev, segs):
        i = ev.get("segment") or 0
        return sum(s for _o, s in segs[:i] if s)

    try:
        summary = scanner.run(
            target, bs, segments,
            ioengine=engine, direct=not args.no_direct,
            total_size=size,
            yellow_mult=args.yellow_mult,
            yellow_floor_us=int(args.yellow_floor_ms * 1000),
            on_event=on_event,
            quick=bool(getattr(args, "quick", False) and size))
    except KeyboardInterrupt:
        core.log_event("cli: interrupted by user (KeyboardInterrupt)")
        scanner.stop()
        print("\nAborted.")
        return 130

    if not summary:
        core.log_event("cli: scan failed (no summary); see fio output above",
                       level="ERROR")
        print("\nScan failed; see fio output above.")
        return 1

    core.log_event("cli: finished target=%s blocks=%d ok=%d slow=%d "
                   "errors=%d aborted=%s stopped=%s elapsed=%.1fs"
                   % (target, summary["n_blocks"], summary["ok"],
                      summary["slow"],
                      len(summary["error_blocks"]), summary["aborted"],
                      bool(summary.get("stop_requested")),
                      summary["elapsed_s"]))

    print("\n" + "=" * 62)
    suffix = " (aborted, data incomplete)" if summary["aborted"] else ""
    print("Scan complete%s" % suffix)
    print("=" * 62)
    if summary.get("stop_requested"):
        print("Scan state  : stopped by user (uncovered areas are not errors)")
    if summary.get("quick"):
        covered = sum((s["size"] or 0) for s in summary["segments"])
        cov_pct = covered * 100.0 / size if size else 0.0
        print("Scan mode   : quick scan (%d regions, covering %s, %.2f%% of capacity)"
              % (len(summary["segments"]), fmt_bytes(covered), cov_pct))
    print("Total blocks: %d" % summary["n_blocks"])
    print("OK          : %d" % summary["ok"])
    print("Slow        : %d  (> %.2f ms)" % (summary["slow"], summary["slow_thr_us"] / 1000.0))
    print("Read errors : %d blocks (fio error segments %d, unlocated error lines %d)"
          % (len(summary["error_blocks"]), summary["errno_segments"],
             summary["unlocated_errors"]))
    if summary["last_errno"]:
        print("fio errno   : %d %s" % (summary["last_errno"], summary["last_errno_name"]))
    if summary["unscanned_bytes"]:
        if summary["aborted"]:
            print("Unscanned   : %s (stopped by user, expected)"
                  % fmt_bytes(summary["unscanned_bytes"]))
        else:
            print("Uncovered   : %s (a segment failed early; scan incomplete!)"
                  % fmt_bytes(summary["unscanned_bytes"]))
    if summary.get("unread_tail_bytes"):
        print("Unread tail : %s (less than one block; fio skips it; not an error)"
              % fmt_bytes(summary["unread_tail_bytes"]))
    print("Latency     : median %.3f ms | mean %.3f ms | P99 %.3f ms | max %.3f ms"
          % (summary["median_us"] / 1000.0, summary["mean_us"] / 1000.0,
             summary["p99_us"] / 1000.0, summary["max_us"] / 1000.0))
    print("Elapsed     : %s" % fmt_duration(summary["elapsed_s"]))
    if summary["error_blocks"]:
        print("\nError block details:")
        for idx in sorted(summary["error_blocks"]):
            print("  block #%-10d offset %-12s %s"
                  % (idx, fmt_bytes(idx * bs), summary["error_blocks"][idx]))

    # 报告按需导出：未指定 --export 时不写任何文件
    export_dir = getattr(args, "export", None)
    if export_dir is not None:
        outdir = os.path.join(export_dir or ".", "HD_Doc_report_%s"
                              % datetime.now().strftime("%Y%m%d_%H%M%S"))
        files = write_reports(outdir, summary, lang="en")
        core.log_event("cli: report exported to %s (%d file(s))"
                       % (outdir, len(files)))
        print("\nReport exported to:")
        for p in files:
            print("  %s" % p)
    else:
        print("\nReport not saved (pass --export [DIR] to write "
              "segments.csv / errors.csv / summary.txt).")
    print("fio temp logs: %s" % summary["tmpdir"])
    return 0


def _cli_print_progress(ev, total_size, base_done):
    io_bytes = ev.get("io_bytes") or 0
    done = base_done + io_bytes
    parts = []
    if total_size:
        parts.append("progress %5.1f%%" % (done * 100.0 / total_size))
    else:
        parts.append("read %s" % fmt_bytes(done))
    bw = ev.get("bw_bytes")
    if bw:
        parts.append(fmt_speed(bw))
        if total_size and done < total_size:
            parts.append("ETA %s" % fmt_duration((total_size - done) / float(bw)))
    if ev.get("errors"):
        # fio 的 error 字段是 errno 码而非计数
        code = int(ev["errors"])
        parts.append("error %s(%d)" % (errno_name(code), code))
    print("  " + " | ".join(parts))
