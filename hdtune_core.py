#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hdtune_core.py —— 业务逻辑层（零 UI 依赖：不 import tkinter，不弹任何窗口）

职责
  - 管理员权限检测与自动提权（is_admin / request_elevation）
  - 控制台输出绑定与终端编码自适应（_bind_console / _console_encoding）
  - 参数解析工具（parse_bs / parse_segment_size / clamp_bs）
  - 分段规划（plan_segments / sanitize_segments）与快速扫描布点
    （plan_quick_segments / quick_scan_setup）
  - 热力图自适应布局纯函数 plan_grid
  - Windows 物理磁盘枚举与容量查询（list_drives / query_target_size）
  - fio 扫描引擎 FioScanner（分段执行 / 流式 JSON 解析 / 段级统计）
  - 报告导出 write_reports

本模块被 hdtune_cli（命令行）与 hdtune_gui（tkinter 界面）共同依赖；
CLI 路径只 import 本模块，不会触碰任何 UI 代码。
"""

import csv
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from array import array
from bisect import bisect_right
from datetime import datetime

IS_WIN = sys.platform.startswith("win")
VERSION = "1.0"

# ---------------------------------------------------------------- 常量
COLOR_OK = "#5DCAA5"       # 正常
COLOR_SLOW = "#EF9F27"     # 偏慢
COLOR_BAD = "#D85A30"      # 很慢
COLOR_ERROR = "#A32D2D"    # 读取错误
COLOR_PENDING = "#D3D1C7"  # 未扫描
CELL_GAP = 1              # 格子间隙（px）
CELL_SIZE_MAX = 40        # 单格最大边长（段太少时封顶，避免巨型块）
CELL_SIZE_MIN = 3         # 单格最小边长（段极多时保底可辨）

# 状态图例与总线类型的中文名（兼容旧引用）；GUI 显示请用
# status_text() / bus_type_name()（随界面语言切换）
STATUS_TEXT = {"ok": "正常", "slow": "偏慢", "bad": "很慢",
               "error": "读取错误", "pending": "未扫描"}

BUS_TYPES = {0: "未知", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA",
             6: "Fibre", 7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA",
             12: "SD", 13: "MMC", 14: "虚拟", 15: "文件虚拟", 16: "存储空间",
             17: "NVMe", 18: "SCM"}
# 需要翻译的总线类型键（其余为专有名词，中英一致）
_BUS_I18N_KEY = {0: "bus.unknown", 14: "bus.virtual",
                 15: "bus.file_virtual", 16: "bus.storage_space"}

IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400

# ---------------------------------------------------------------- i18n 多语言
# GUI 界面语言：默认英文，可切换中文；CLI 固定英文（cli_main 入口
# set_language("en")）。语言选择持久化在用户配置目录：
#   Windows: %APPDATA%\hdtune_scan\config.json
#   其他:    ~/.config/hdtune_scan/config.json
# 环境变量 HDTUNE_LANG=en|zh 可临时覆盖（测试用，不落盘）。
LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"
_LANGUAGE = DEFAULT_LANGUAGE
_LANG_LOADED = False

_I18N = {
    # ---------------- 英文（默认） ----------------
    "en": {
        # 状态图例
        "status.ok": "OK",
        "status.slow": "Slow",
        "status.bad": "Very slow",
        "status.error": "Read error",
        "status.pending": "Pending",
        # 总线类型（专有名词不翻译，仅通用项）
        "bus.unknown": "Unknown",
        "bus.virtual": "Virtual",
        "bus.file_virtual": "File-backed virtual",
        "bus.storage_space": "Storage Spaces",
        # errno 含义
        "errno.1": "EPERM permission denied",
        "errno.2": "ENOENT file/device not found",
        "errno.5": "EIO read error (bad block or media failure)",
        "errno.13": "EACCES access denied (permission or path issue)",
        "errno.22": "EINVAL invalid argument (misaligned offset or direct IO unsupported)",
        "errno.28": "ENOSPC no space left",
        "errno.unknown": "Unknown error",
        # 通用
        "unknown": "Unknown",
        "none": "(none)",
        # 异常 / 提权
        "err.uac_cancelled": "UAC elevation confirmation cancelled by user",
        "err.shellexec_failed": "ShellExecuteExW failed (err={err})",
        "err.no_sudo": "sudo not found",
        "err.parse_bs": "Cannot parse block size: {text!r}",
        "err.bs_too_small": "Block size cannot be smaller than 512 bytes",
        # FioScanner 运行时日志
        "log.scan_range_small": "Scan range {size} is smaller than block size {bs}; block size adjusted to {new_bs}",
        "log.lat_unit_ns": "Detected lat log in nanoseconds; converted to microseconds",
        "log.segment_fio_error": "Segment {i}/{n} fio reported error: {name} (errno {code})",
        "log.segment_stopped": "Segment {i}/{n} stopped by user request (read {done}/{total} blocks)",
        "log.unscanned_aborted": "Unscanned (job aborted after reading {n} blocks, errno {code})",
        "log.unstarted_segments": "{size} in not-yet-started segments counted as unscanned due to stop",
        "errblk.eio": "fio read failure EIO (offset {off})",
        # 报告（write_reports）
        "rep.title": "HD Tune Style Disk Error Scan Report",
        "rep.generated": "Generated: {ts}",
        "rep.target": "Target: {t}",
        "rep.bs": "Block size: {bs}",
        "rep.ioengine": "IO engine: {e} (direct={d})",
        "rep.capacity": "Disk capacity: {sz}",
        "rep.mode_whole": "Whole disk in one pass",
        "rep.mode_segmented": "Segmented scan ({n} segments)",
        "rep.mode": "Scan mode: {mode}",
        "rep.mode_quick": "Scan mode: quick scan ({n} regions sampled, covering {cov}, {pct:.2f}% of capacity)",
        "rep.note_quick": "Note: quick scan reads only the head sample of each region; latency stats below are based on samples.",
        "rep.state_stopped": "Scan state: stopped by user (results are incomplete; uncovered areas are not errors)",
        "rep.results": "-- Results --",
        "rep.n_blocks": "Total blocks: {n}",
        "rep.ok": "OK: {n}",
        "rep.slow": "Slow (>{thr:.2f}ms): {n}",
        "rep.bad": "Very slow (>{thr:.2f}ms): {n}",
        "rep.read_errors": "Read error blocks: {n} (fio error segments {es}, unlocated error lines {ul})",
        "rep.fio_errno": "fio error code: {code} {name}",
        "rep.unscanned_stopped": "Unscanned bytes: {sz} (stopped by user, expected)",
        "rep.unscanned_failed": "Uncovered bytes: {sz} (a segment failed early; scan incomplete)",
        "rep.unread_tail": "Unread tail: {sz} (less than one block; fio skips it; not an error)",
        "rep.latency": "-- Latency --",
        "rep.median": "Median: {v:.3f} ms",
        "rep.mean": "Mean: {v:.3f} ms",
        "rep.p99": "P99: {v:.3f} ms",
        "rep.max": "Max: {v:.3f} ms",
        "rep.elapsed": "-- Elapsed --",
        "rep.total_time": "Total time: {d}",
        "rep.aborted_note": "Note: scan was aborted by user; results are incomplete.",
        "rep.threshold_note": "-- Thresholds --",
        "rep.threshold_detail": "Thresholds adapt to the overall block latency median: slow > max(median x3, 10ms), very slow > max(median x8, 100ms).",
        "rep.err_detail": "-- Error block details --",
        "rep.err_line": "Block #{i}  offset {off}  {desc}",
        "rep.csv_seg_header": "Segment,Start offset (bytes),Segment size (bytes),Blocks,Actual I/Os,Expected I/Os,Errno,Errno meaning,Median latency (ms),Max latency (ms)",
        "rep.csv_err_header": "Block,Offset (bytes),Offset (readable),Description",
        # ---------------- GUI 界面 ----------------
        "gui.title": "HD Tune Style Disk Error Scanner (fio + tkinter, read-only) v{ver}",
        "gui.menu.language": "Language",
        "gui.menu.help": "Help",
        "gui.menu.about": "About",
        "gui.about.title": "About",
        "gui.about.body": ("HD Tune Style Disk Error Scanner\n"
                           "\n"
                           "A read-only disk error scanner built on fio.\n"
                           "\n"
                           "Features\n"
                           "- Segmented scanning with a live latency heatmap\n"
                           "- Quick scan (HD Tune Quick Scan style): head sample per region\n"
                           "- Adaptive slow / very-slow thresholds from the block latency median\n"
                           "- Error block list with offsets\n"
                           "- Reports are exported on demand (GUI button / CLI --export)\n"
                           "- Read-only: never writes to the disk\n"
                           "\n"
                           "Usage\n"
                           "- GUI: run without arguments\n"
                           "- CLI: hdtune_scan.exe --cli --target <target> [--export DIR]\n"
                           "\n"
                           "Author: "),
        "gui.target": "Target:",
        "gui.refresh": "Refresh drives",
        "gui.browse_file": "Browse file...",
        "gui.bs": "Block size:",
        "gui.engine": "IO engine:",
        "gui.direct": "Direct IO",
        "gui.segment": "Segment:",
        "gui.quick": "Quick scan",
        "gui.sample": "Sample:",
        "gui.fio_path": "fio path:",
        "gui.browse": "Browse...",
        "gui.start": "Start scan",
        "gui.stop": "Stop",
        "gui.export": "Export report",
        "gui.hint": ("Tip: smaller segments give a more live heatmap but cost about 1s "
                     "startup each; whole-disk is fastest but the map appears only at "
                     "the end; quick scan reads only the head sample of each region "
                     "for a fast full-disk checkup"),
        "gui.perm_checking": "Permission: checking...",
        "gui.perm_admin": "Permission: administrator",
        "gui.perm_standard": "Permission: standard user (admin required for physical disks)",
        "gui.relaunch": "Restart as administrator",
        "gui.bs_values": "Auto,512K,1M,2M,4M,8M,16M,32M,64M",
        "gui.seg_values": ("Whole disk at once (fastest),512M,1G,2G,4G,8G,16G,"
                           "32G,64G"),
        "gui.sample_values": "1M,2M,4M,8M,16M,32M,64M",
        "gui.map_title": ("Segment heatmap (horizontal - one cell = one scan segment - "
                          "color = median read latency of that segment)"),
        "gui.progress": "Progress: --",
        "gui.speed": "Speed: --",
        "gui.elapsed": "Elapsed: --",
        "gui.eta": "ETA: --",
        "gui.errors": "Errors: {n}",
        "gui.state_ready": "Ready",
        "gui.state_scanning": "Scanning...",
        "gui.state_stopping": "Stopping...",
        "gui.state_done": "Done",
        "gui.state_done_aborted": "Done (aborted)",
        "gui.state_failed": "Failed",
        "gui.state_stopped": "Stopped",
        "gui.errors_none": "Errors: none",
        "gui.errors_code": "Errors: {name}({code})",
        "gui.progress_pct": "Progress: {pct:.1f}%",
        "gui.progress_read": "Read {sz}",
        "gui.speed_fmt": "Speed: {v}",
        "gui.elapsed_fmt": "Elapsed: {v}",
        "gui.eta_fmt": "ETA: {v}",
        "gui.tab_log": "fio log",
        "gui.tab_errors": "Error blocks",
        "gui.tab_summary": "Summary",
        "gui.col_block": "Block",
        "gui.col_offset": "Offset",
        "gui.col_desc": "Description",
        "gui.hover_region": "Region #{i}/{n} | offset {off}",
        "gui.hover_segment": "Segment #{i}/{n} | offset {off}",
        "gui.hover_sample": " | sample {sz}",
        "gui.hover_size": " | size {sz}",
        "gui.hover_region_span": "/region {sz}",
        "gui.hover_to_end": " | to end",
        "gui.hover_blocks": " | block {b} on | read {n} blocks | errors {e}",
        "gui.hover_median": " | median latency {v:.2f} ms",
        "gui.hover_max": " | max {v:.2f} ms",
        "gui.log.admin_ok": "Running with administrator rights; physical disks can be scanned",
        "gui.log.not_admin": ("Not running as administrator. Scanning physical disks "
                              "(\\\\.\\PhysicalDriveN) requires administrator rights, "
                              "otherwise fio cannot open the device and every block "
                              "reports \"failed to open file\"."),
        "gui.log.elevate_requested": "Elevation requested; this process will exit...",
        "gui.log.no_pythonw": ("pythonw.exe not found; a console window may appear "
                               "after elevation"),
        "gui.log.bs_clamped": "Block size exceeds disk capacity; adjusted to {sz}",
        "gui.log.quick_plan": ("Quick scan: {n} regions, {sample} sampled each "
                               "(total {total}, {pct:.2f}% of capacity)"),
        "gui.log.quick_no_size": ("Quick scan needs a known capacity to place samples "
                                  "evenly; capacity unknown, falling back to a single "
                                  "full pass"),
        "gui.log.capacity_plan": "Capacity {sz} | {n} segments | about {b} blocks",
        "gui.log.no_size_map": ("Could not query target capacity; heatmap unavailable "
                                "(stats only); fio will still auto-detect the device "
                                "size and complete the scan"),
        "gui.log.segment": "Segment {i}/{n} offset {off}{extra}",
        "gui.log.segment_size": "  size {sz}",
        "gui.log.segment_to_end": " (to end)",
        "gui.log.segment_sampled": " (sampled)",
        "gui.log.start_scan": "Scan started: {t} | block size {bs} | {n} {kind} | fio={fio}",
        "gui.log.kind_region": "regions (quick scan)",
        "gui.log.kind_segment": "segments",
        "gui.log.stop_requested": ("Stop requested. Note: fio's per-block latency log "
                                   "is written only on normal exit; after a forced "
                                   "kill the current segment's heatmap data is lost "
                                   "(progress/error counts are kept up to the last "
                                   "second before the stop)"),
        "gui.log.no_engine_probe": "Cannot probe the fio engine list; skipping engine check",
        "gui.log.exported": "Report exported: {d}",
        "gui.log.readonly_note": "Read-only scan of {t}; nothing will be written to the disk",
        "gui.log.fio_missing": ("fio executable not found: {f}. "
                                "Windows: winget install fio.fio"),
        "gui.log.no_size_degraded": ("Cannot query the capacity of {t}; falling back to "
                                     "whole-disk-at-once: no live progress/speed/ETA, "
                                     "the heatmap appears only after the scan, and "
                                     "stopping midway loses per-block data"),
        "gui.msg.no_target": "Please select or enter a scan target first",
        "gui.msg.admin_needed_title": "Administrator rights required",
        "gui.msg.admin_needed": ("Scanning {t} requires administrator rights\n"
                                 "(fio must be elevated to open \\\\.\\PhysicalDriveN).\n\n"
                                 "Restart as administrator now?\n"
                                 "(The window closes after the UAC confirmation; "
                                 "start the scan in the new window)"),
        "gui.msg.elevate_failed_title": "Elevation failed",
        "gui.msg.elevate_failed": ("Cannot restart as administrator: {err}\n\n"
                                   "Right-click this program and choose "
                                   "\"Run as administrator\"."),
        "gui.msg.engine_bad_title": "IO engine unavailable",
        "gui.msg.engine_bad": ("Current fio does not support the '{e}' engine; "
                               "scan not started.\n\n"
                               "Engines actually supported by this fio:\n{list}\n\n"
                               "Note: libaio / posixaio are native Linux engines; the "
                               "Windows build of fio does not include them and fails "
                               "with \"failed to load engine\". On Windows use {win}."),
        "gui.msg.exit_title": "Exit",
        "gui.msg.exit_scanning": "A scan is in progress. Exit anyway?",
        "gui.msg.param_error_title": "Invalid parameter",
        "gui.banner.clean": ("Scan complete: {ok}/{n} blocks OK, {slow} slow, "
                             "{bad} very slow, {err} read errors."),
        "gui.banner.errors": ("Scan found {n} error blocks (fio error segments {es}). "
                              "The disk may have physical damage; back up important "
                              "data immediately. See the Error blocks tab."),
        "gui.banner.stopped_with_errors": ("Scan stopped by user. {n} error blocks were "
                                           "found before the stop (fio error segments "
                                           "{es}); see the Error blocks tab."),
        "gui.banner.failed": "Scan failed: {msg}",
        "gui.sum.target": "Target       : {t}",
        "gui.sum.bs": "Block size   : {bs} ({n} blocks)",
        "gui.sum.ioengine": "IO engine    : {e} (direct={d})",
        "gui.sum.capacity": "Disk capacity: {sz}",
        "gui.sum.mode_quick": ("Scan mode    : quick scan ({n} regions sampled, "
                               "covering {cov}, {pct:.2f}% of capacity)"),
        "gui.sum.state_stopped": ("Scan state   : stopped by user "
                                  "(uncovered areas are not errors)"),
        "gui.sum.elapsed": "Elapsed      : {d}",
        "gui.sum.ok": "OK           : {n}",
        "gui.sum.slow": "Slow         : {n} (> {thr:.2f} ms)",
        "gui.sum.bad": "Very slow    : {n} (> {thr:.2f} ms)",
        "gui.sum.read_errors": ("Read errors  : {n} blocks (fio error segments {es}, "
                                "unlocated error lines {ul})"),
        "gui.sum.fio_errno": "fio errno    : {code} {name}",
        "gui.sum.unscanned_stopped": "Unscanned    : {sz} (stopped by user, expected)",
        "gui.sum.uncovered": ("Uncovered    : {sz} (a segment failed early; "
                              "scan incomplete!)"),
        "gui.sum.unread_tail": ("Unread tail  : {sz} (less than one block; fio skips "
                                "it; not an error)"),
        "gui.sum.median": "Median latency: {v:.3f} ms",
        "gui.sum.mean": "Mean         : {v:.3f} ms",
        "gui.sum.p99": "P99          : {v:.3f} ms",
        "gui.sum.max": "Max          : {v:.3f} ms",
        "gui.sum.aborted_note": "Note: the scan was aborted; results below are incomplete.",
        "gui.sum.threshold_note": ("Thresholds: slow > max(median x3, 10ms), "
                                   "very slow > max(median x8, 100ms)."),
    },
    # ---------------- 中文 ----------------
    "zh": {
        "status.ok": "正常",
        "status.slow": "偏慢",
        "status.bad": "很慢",
        "status.error": "读取错误",
        "status.pending": "未扫描",
        "bus.unknown": "未知",
        "bus.virtual": "虚拟",
        "bus.file_virtual": "文件虚拟",
        "bus.storage_space": "存储空间",
        "errno.1": "EPERM 权限不足",
        "errno.2": "ENOENT 文件/设备不存在",
        "errno.5": "EIO 读取错误（坏块或介质故障）",
        "errno.13": "EACCES 拒绝访问（权限或路径问题）",
        "errno.22": "EINVAL 参数错误（offset 未对齐或直接 IO 不支持）",
        "errno.28": "ENOSPC 空间不足",
        "errno.unknown": "未知错误",
        "unknown": "未知",
        "none": "（无）",
        "err.uac_cancelled": "用户取消了 UAC 提权确认",
        "err.shellexec_failed": "ShellExecuteExW 失败 (err={err})",
        "err.no_sudo": "未找到 sudo",
        "err.parse_bs": "无法解析块大小: {text!r}",
        "err.bs_too_small": "块大小不能小于 512 字节",
        "log.scan_range_small": "扫描范围 {size} 小于块大小 {bs}，块大小已调整为 {new_bs}",
        "log.lat_unit_ns": "检测到 lat 日志单位为纳秒，已换算为微秒",
        "log.segment_fio_error": "段 {i}/{n} fio 报告错误: {name}（错误码 {code}）",
        "log.segment_stopped": "段 {i}/{n} 已按用户请求停止（已读 {done}/{total} 块）",
        "log.unscanned_aborted": "未扫描（任务在读取 {n} 块后中止，错误码 {code}）",
        "log.unstarted_segments": "有 {size} 位于尚未启动的段，已按停止计入未扫描",
        "errblk.eio": "fio 读失败 EIO（偏移 {off}）",
        "rep.title": "HD Tune 风格磁盘错误扫描报告",
        "rep.generated": "生成时间: {ts}",
        "rep.target": "目标: {t}",
        "rep.bs": "块大小: {bs}",
        "rep.ioengine": "IO 引擎: {e} (direct={d})",
        "rep.capacity": "磁盘容量: {sz}",
        "rep.mode_whole": "整盘一次",
        "rep.mode_segmented": "分段扫描（{n} 段）",
        "rep.mode": "扫描模式: {mode}",
        "rep.mode_quick": "扫描模式: 快速扫描（抽样 {n} 区域，覆盖 {cov}，占容量 {pct:.2f}%）",
        "rep.note_quick": "注: 快速扫描只读每区域开头样本，以下延迟统计基于样本数据。",
        "rep.state_stopped": "扫描状态: 用户主动停止（结果为不完整数据，未覆盖区域不是错误）",
        "rep.results": "-- 结果 --",
        "rep.n_blocks": "总块数: {n}",
        "rep.ok": "正常: {n}",
        "rep.slow": "偏慢(>{thr:.2f}ms): {n}",
        "rep.bad": "很慢(>{thr:.2f}ms): {n}",
        "rep.read_errors": "读取错误块: {n}（fio 报错段 {es}，未定位错误行 {ul}）",
        "rep.fio_errno": "fio 错误码: {code} {name}",
        "rep.unscanned_stopped": "未扫描字节: {sz}（已主动停止，属预期）",
        "rep.unscanned_failed": "未覆盖字节: {sz}（有段提前失败，扫描不完整）",
        "rep.unread_tail": "未读尾巴: {sz}（不足一个块的字节，fio 不读，非错误）",
        "rep.latency": "-- 延迟统计 --",
        "rep.median": "中位数: {v:.3f} ms",
        "rep.mean": "平均值: {v:.3f} ms",
        "rep.p99": "P99: {v:.3f} ms",
        "rep.max": "最大值: {v:.3f} ms",
        "rep.elapsed": "-- 耗时 --",
        "rep.total_time": "总耗时: {d}",
        "rep.aborted_note": "注意: 扫描被用户中止，结果为不完整数据。",
        "rep.threshold_note": "-- 阈值说明 --",
        "rep.threshold_detail": "阈值基于全体块延迟中位数自适应计算: 偏慢 > max(中位数x3, 10ms)，很慢 > max(中位数x8, 100ms)。",
        "rep.err_detail": "-- 错误块明细 --",
        "rep.err_line": "块 #{i}  偏移 {off}  {desc}",
        "rep.csv_seg_header": "段号,起始偏移(字节),段大小(字节),块数,实际I/O数,预期I/O数,错误码(errno),错误含义,延迟中位数(ms),最大延迟(ms)",
        "rep.csv_err_header": "块号,偏移(字节),偏移(可读),说明",
        # ---------------- GUI 界面 ----------------
        "gui.title": "HD Tune 风格磁盘错误扫描器（fio + tkinter · 只读）v{ver}",
        "gui.menu.language": "语言",
        "gui.menu.help": "帮助",
        "gui.menu.about": "关于",
        "gui.about.title": "关于",
        "gui.about.body": ("HD Tune 风格磁盘错误扫描器\n"
                           "\n"
                           "基于 fio 的只读磁盘错误扫描器。\n"
                           "\n"
                           "功能特性\n"
                           "- 分段扫描，实时延迟热力图\n"
                           "- 快速扫描（类 HD Tune Quick Scan）：每区只读开头样本\n"
                           "- 依据全体块延迟中位数自适应的偏慢/很慢阈值\n"
                           "- 错误块列表（含偏移）\n"
                           "- 报告按需导出（GUI 导出按钮 / CLI --export）\n"
                           "- 只读：绝不向磁盘写入任何数据\n"
                           "\n"
                           "用法\n"
                           "- GUI：不带参数直接运行\n"
                           "- CLI：hdtune_scan.exe --cli --target <目标> [--export 目录]\n"
                           "\n"
                           "作者："),
        "gui.target": "目标:",
        "gui.refresh": "刷新磁盘",
        "gui.browse_file": "浏览文件…",
        "gui.bs": "块大小:",
        "gui.engine": "IO 引擎:",
        "gui.direct": "直接 IO",
        "gui.segment": "分段:",
        "gui.quick": "快速扫描",
        "gui.sample": "抽样:",
        "gui.fio_path": "fio 路径:",
        "gui.browse": "浏览…",
        "gui.start": "▶ 开始扫描",
        "gui.stop": "■ 停止",
        "gui.export": "导出报告",
        "gui.hint": ("提示: 分段越小热力图越实时，但每段约 1 秒启动开销；整盘最快但"
                     "结束后才出图；快速扫描每区只读开头样本，适合全盘快速体检"),
        "gui.perm_checking": "权限: 检测中…",
        "gui.perm_admin": "权限: 管理员",
        "gui.perm_standard": "权限: 标准用户（扫描物理磁盘需管理员）",
        "gui.relaunch": "以管理员身份重启",
        "gui.bs_values": "自动,512K,1M,2M,4M,8M,16M,32M,64M",
        "gui.seg_values": "整盘一次（最快）,512M,1G,2G,4G,8G,16G,32G,64G",
        "gui.sample_values": "1M,2M,4M,8M,16M,32M,64M",
        "gui.map_title": "分段热力图（横向 · 每格 = 一个扫描段 · 颜色 = 该段读取延迟中位数）",
        "gui.progress": "进度: --",
        "gui.speed": "速度: --",
        "gui.elapsed": "已用: --",
        "gui.eta": "剩余: --",
        "gui.errors": "错误: {n}",
        "gui.state_ready": "就绪",
        "gui.state_scanning": "扫描中…",
        "gui.state_stopping": "正在停止…",
        "gui.state_done": "完成",
        "gui.state_done_aborted": "完成（中止）",
        "gui.state_failed": "失败",
        "gui.state_stopped": "已停止",
        "gui.errors_none": "错误: 无",
        "gui.errors_code": "错误: {name}({code})",
        "gui.progress_pct": "进度: {pct:.1f}%",
        "gui.progress_read": "已读 {sz}",
        "gui.speed_fmt": "速度: {v}",
        "gui.elapsed_fmt": "已用: {v}",
        "gui.eta_fmt": "剩余: {v}",
        "gui.tab_log": "fio 日志",
        "gui.tab_errors": "错误块列表",
        "gui.tab_summary": "汇总",
        "gui.col_block": "块号",
        "gui.col_offset": "偏移",
        "gui.col_desc": "说明",
        "gui.hover_region": "区域 #{i}/{n} | 偏移 {off}",
        "gui.hover_segment": "段 #{i}/{n} | 偏移 {off}",
        "gui.hover_sample": " | 抽样 {sz}",
        "gui.hover_size": " | 大小 {sz}",
        "gui.hover_region_span": "/区域 {sz}",
        "gui.hover_to_end": " | 到末尾",
        "gui.hover_blocks": " | 块 {b} 起 | 已读 {n} 块 | 错误 {e}",
        "gui.hover_median": " | 延迟中位数 {v:.2f} ms",
        "gui.hover_max": " | 最大 {v:.2f} ms",
        "gui.log.admin_ok": "已以管理员权限运行，可扫描物理磁盘",
        "gui.log.not_admin": ("当前未以管理员身份运行。扫描物理磁盘"
                              "（\\\\.\\PhysicalDriveN）需要管理员权限，"
                              "否则 fio 打不开设备，每个块都会报 "
                              "“failed to open file”。"),
        "gui.log.elevate_requested": "已申请提权重启，本进程即将退出…",
        "gui.log.no_pythonw": "未找到 pythonw.exe，提权重启后可能出现命令窗口",
        "gui.log.bs_clamped": "块大小超过磁盘容量，已调整为 {sz}",
        "gui.log.quick_plan": ("快速扫描：{n} 个区域，每区抽样 {sample}"
                               "（共 {total}，占容量 {pct:.2f}%）"),
        "gui.log.quick_no_size": ("快速扫描需要已知容量来均匀布点；未能查询到容量，"
                                  "退化为整盘一次扫描"),
        "gui.log.capacity_plan": "容量 {sz} | {n} 段 | 预计 {b} 块",
        "gui.log.no_size_map": ("未能查询到目标容量，热力图不可用（仅显示统计）；"
                                "fio 仍会自动探测设备大小完成扫描"),
        "gui.log.segment": "段 {i}/{n} 偏移 {off}{extra}",
        "gui.log.segment_size": "  大小 {sz}",
        "gui.log.segment_to_end": "（到末尾）",
        "gui.log.segment_sampled": "（抽样）",
        "gui.log.start_scan": "开始扫描: {t} | 块大小 {bs} | {n} {kind} | fio={fio}",
        "gui.log.kind_region": "区域（快速扫描）",
        "gui.log.kind_segment": "段",
        "gui.log.stop_requested": ("已请求停止。注意：fio 的逐块延迟日志仅在正常退出时写入，"
                                   "强杀后当前段的热力图数据会丢失（进度/错误计数保留到"
                                   "停止前最后一秒）"),
        "gui.log.no_engine_probe": "无法探测 fio 引擎列表，跳过引擎校验",
        "gui.log.exported": "报告已导出: {d}",
        "gui.log.readonly_note": "将对 {t} 进行只读扫描，不会写入任何数据",
        "gui.log.fio_missing": "找不到 fio 可执行文件：{f}。Windows: winget install fio.fio",
        "gui.log.no_size_degraded": ("无法查询 {t} 的容量，退化为整盘一次扫描："
                                     "无实时进度/速度/ETA，热力图需扫描结束后才生成，"
                                     "中途停止会丢失逐块数据"),
        "gui.msg.no_target": "请先选择或输入扫描目标",
        "gui.msg.admin_needed_title": "需要管理员权限",
        "gui.msg.admin_needed": ("扫描 {t} 需要管理员权限\n"
                                 "（fio 必须提升权限才能打开 \\\\.\\PhysicalDriveN）。\n\n"
                                 "是否立即以管理员身份重启本程序？\n"
                                 "（UAC 确认后本窗口关闭，请在重启后的窗口中开始扫描）"),
        "gui.msg.elevate_failed_title": "提权失败",
        "gui.msg.elevate_failed": ("无法以管理员身份重启：{err}\n\n"
                                   "请手动右键本程序 → “以管理员身份运行”。"),
        "gui.msg.engine_bad_title": "IO 引擎不可用",
        "gui.msg.engine_bad": ("当前 fio 不支持「{e}」引擎，扫描未开始。\n\n"
                               "该 fio 实际支持的引擎：\n{list}\n\n"
                               "说明：libaio / posixaio 是 Linux 原生引擎，\n"
                               "Windows 版 fio 未编译它们，加载即报\n"
                               "“failed to load engine”。Windows 请用 {win}。"),
        "gui.msg.exit_title": "退出",
        "gui.msg.exit_scanning": "扫描正在进行，确定退出吗？",
        "gui.msg.param_error_title": "参数错误",
        "gui.banner.clean": ("扫描完成：{ok}/{n} 块正常，{slow} 偏慢，"
                             "{bad} 很慢，{err} 个读取错误。"),
        "gui.banner.errors": ("扫描发现 {n} 个错误块（fio 报错段 {es}）。"
                              "该盘存在物理损伤风险，建议立即备份重要数据。"
                              "详见「错误块列表」。"),
        "gui.banner.stopped_with_errors": ("扫描已由用户主动停止。停止前已发现 {n} 个错误块"
                                           "（fio 报错段 {es}），详见「错误块列表」。"),
        "gui.banner.failed": "扫描失败: {msg}",
        "gui.sum.target": "目标      : {t}",
        "gui.sum.bs": "块大小    : {bs}（共 {n} 块）",
        "gui.sum.ioengine": "IO 引擎   : {e} (direct={d})",
        "gui.sum.capacity": "磁盘容量  : {sz}",
        "gui.sum.mode_quick": ("扫描模式  : 快速扫描（{n} 区域抽样，覆盖 {cov}，"
                               "占容量 {pct:.2f}%）"),
        "gui.sum.state_stopped": "扫描状态  : 用户主动停止（未覆盖区域不是错误）",
        "gui.sum.elapsed": "总耗时    : {d}",
        "gui.sum.ok": "正常      : {n}",
        "gui.sum.slow": "偏慢      : {n}（> {thr:.2f} ms）",
        "gui.sum.bad": "很慢      : {n}（> {thr:.2f} ms）",
        "gui.sum.read_errors": ("读取错误  : {n} 块（fio 报错段 {es}，未定位错误行 {ul}）"),
        "gui.sum.fio_errno": "fio 错误码: {code} {name}",
        "gui.sum.unscanned_stopped": "未扫描字节: {sz}（已主动停止，属预期）",
        "gui.sum.uncovered": "未覆盖字节: {sz}（有段提前失败，扫描不完整！）",
        "gui.sum.unread_tail": "未读尾巴  : {sz}（不足一块，fio 不读，非错误）",
        "gui.sum.median": "延迟中位数: {v:.3f} ms",
        "gui.sum.mean": "平均      : {v:.3f} ms",
        "gui.sum.p99": "P99       : {v:.3f} ms",
        "gui.sum.max": "最大      : {v:.3f} ms",
        "gui.sum.aborted_note": "注意：扫描被中止，以下为不完整结果。",
        "gui.sum.threshold_note": "阈值说明：偏慢 > max(中位数×3, 10ms)，很慢 > max(中位数×8, 100ms)。",
    },
}


def _config_dir():
    """用户配置目录（语言选择等持久化）"""
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "hdtune_scan")
    base = (os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "hdtune_scan")


def _config_path():
    return os.path.join(_config_dir(), "config.json")


def load_config():
    """读取用户配置；失败返回空 dict"""
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def save_config(cfg):
    """写用户配置；失败静默返回 False（只读文件系统等场景不影响主流程）"""
    try:
        os.makedirs(_config_dir(), exist_ok=True)
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_language():
    """当前界面语言代码（"en" / "zh"）。

    HDTUNE_LANG 环境变量仅在首次加载时生效（测试/调试用的一次性覆盖），
    之后以 set_language 的进程内切换为准（GUI 语言菜单即走该路径）。
    """
    global _LANGUAGE, _LANG_LOADED
    if not _LANG_LOADED:
        env = os.environ.get("HDTUNE_LANG", "").strip().lower()
        if env in LANGUAGES:
            _LANGUAGE = env
        else:
            lang = str(load_config().get("language",
                                         DEFAULT_LANGUAGE)).strip().lower()
            _LANGUAGE = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
        _LANG_LOADED = True
    return _LANGUAGE


def set_language(lang):
    """切换界面语言并持久化；非法语言码返回 False"""
    global _LANGUAGE, _LANG_LOADED
    lang = str(lang).strip().lower()
    if lang not in LANGUAGES:
        return False
    _LANGUAGE = lang
    _LANG_LOADED = True
    cfg = load_config()
    cfg["language"] = lang
    save_config(cfg)
    return True


def tr(key, _lang=None, **kw):
    """取指定（或当前）语言的文案；缺失键回退英文，再缺失返回键名本身。
    占位符用 str.format：{name}，避免与文案里的 % 冲突。"""
    lang = _lang or get_language()
    table = _I18N.get(lang) or _I18N["en"]
    s = table.get(key)
    if s is None:
        s = _I18N["en"].get(key, key)
    if kw:
        try:
            s = s.format(**kw)
        except Exception:
            pass
    return s


def tr_list(key, _lang=None):
    """取指定（或当前）语言的列表型文案（如 CSV 表头），按逗号分割"""
    return [c.strip() for c in tr(key, _lang=_lang).split(",")]


def status_text(key):
    """状态图例文案（ok/slow/bad/error/pending）"""
    return tr("status." + key)


def errno_name(code, default=None):
    """errno 码 → 当前语言的含义文案"""
    s = tr("errno.%d" % int(code))
    if s == "errno.%d" % int(code):
        return default if default is not None else tr("errno.unknown")
    return s


def bus_type_name(code):
    """总线类型码 → 当前语言的名称"""
    if code is None:
        return ""
    key = _BUS_I18N_KEY.get(int(code))
    if key:
        return tr(key)
    return BUS_TYPES.get(int(code), tr("unknown"))


# fio 文本 eta 行（Linux 构建会出现），形如：
# Jobs: 1 (f=1): [R(1)][50.0%][r=1670MiB/s][r=417 IOPS][eta 00m:03s]
ETA_RE = re.compile(r"\[(\d+(?:\.\d+)?)%\]\[r=([\d.]+)([KMGT]?i?B)/s\]")
OFFSET_RE = re.compile(r"offset[=:\s]*(\d+)", re.I)
DRIVE_PATH_RE = re.compile(r"^\\\\\.\\", re.I)
# windowsaio 引擎扫描普通文件时，每个 I/O 会往 stderr 打一条无害的
# "failed to open file "C""（读取实际全部成功，error=0），过滤掉以免污染日志
NOISE_RE = re.compile(r'failed to open file "?[A-Za-z]:?"?\s*$')

# ---------------------------------------------------------------- 管理员权限
def is_admin():
    """当前进程是否已提权（Windows: 令牌已提升；Linux/macOS: euid=0）"""
    if not IS_WIN:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    # 首选 TokenElevation：真实反映“进程令牌是否已提升”。
    # 不能只看 IsUserAnAdmin()——UAC 开启时管理员的标准（半提升）令牌里
    # Administrators 组是 deny-only 的，个别环境下该 API 会误判为已提权。
    try:
        import ctypes
        from ctypes import wintypes
        TOKEN_QUERY = 0x0008
        TokenElevation = 20
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        token = wintypes.HANDLE()
        if not kernel32.OpenProcessToken(
                kernel32.GetCurrentProcess(), TOKEN_QUERY,
                ctypes.byref(token)):
            raise OSError("OpenProcessToken err=%d" % ctypes.get_last_error())
        try:
            elevated = wintypes.DWORD()
            ret_len = wintypes.DWORD()
            if not advapi32.GetTokenInformation(
                    token, TokenElevation, ctypes.byref(elevated),
                    ctypes.sizeof(elevated), ctypes.byref(ret_len)):
                raise OSError("GetTokenInformation err=%d"
                              % ctypes.get_last_error())
            return bool(elevated.value)
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        pass
    # 兜底：shell32.IsUserAnAdmin
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_physical_target(target):
    """是否是 Windows 物理磁盘路径（打开它必须具有管理员权限）"""
    if not IS_WIN:
        return False
    t = str(target).strip()
    return bool(DRIVE_PATH_RE.match(t) or t.lower().startswith("//./")
                or re.match(r"^physicaldrive\d+$", t, re.I))


def auto_elevate_enabled():
    """是否允许自动申请提权（--no-elevate / HDTUNE_NO_AUTO_ELEVATE=1 关闭）"""
    return os.environ.get("HDTUNE_NO_AUTO_ELEVATE", "").strip().lower() \
        not in ("1", "true", "yes", "on")


def _shell_execute(verb, exe, params, wait=False):
    """ShellExecuteExW 启动进程（verb="runas" 即 UAC 提权）。

    返回 (ok, exit_code, error)，语义同 request_elevation。
    """
    import ctypes
    from ctypes import wintypes

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_SHOWNORMAL = 1

    # 字段顺序必须与 shellapi.h 的 SHELLEXECUTEINFOW 完全一致：
    # nShow 之后是 hInstApp，hProcess 在结构体【末尾】（dwHotKey 与
    # hIcon/hMonitor union 之后）。顺序错了进程照样启动，但 hProcess
    # 读回来是 NULL，拿不到退出码（实测踩坑）。
    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HANDLE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),      # 与 hMonitor 同为 HANDLE 的 union
            ("hProcess", wintypes.HANDLE),   # out，SEE_MASK_NOCLOSEPROCESS 时有效
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    if verb:
        sei.lpVerb = verb
    sei.lpFile = exe
    sei.lpParameters = params
    sei.lpDirectory = os.getcwd()
    sei.nShow = SW_SHOWNORMAL

    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.get_last_error()
        if err == 1223:  # ERROR_CANCELLED：用户取消了 UAC 确认
            return (False, None, tr("err.uac_cancelled"))
        return (False, None, tr("err.shellexec_failed", err=err))
    if not sei.hProcess:
        return (True, None, None)
    if not wait:
        kernel32.CloseHandle(sei.hProcess)
        return (True, None, None)
    kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)  # INFINITE
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(sei.hProcess)
    return (True, code.value, None)


def _pythonw_path():
    """当前解释器旁边的 pythonw.exe（GUI 子系统，不分配控制台）；
    不存在时返回 None。"""
    if not IS_WIN:
        return None
    try:
        base = os.path.dirname(os.path.abspath(sys.executable or ""))
    except Exception:
        return None
    if not base:
        return None
    cand = os.path.join(base, "pythonw.exe")
    return cand if os.path.isfile(cand) else None


def _elevation_target(gui=False):
    """构造提权重启的 (exe, 参数字符串)。

    统一优先使用 pythonw.exe：python.exe 是控制台子系统程序，经
    ShellExecuteEx("runas") 启动的提权子进程由 AppInfo 服务创建、
    无法继承父进程标准流，Windows 会为它【新分配一个控制台窗口】——
    GUI 提权重启后就伴随一个黑色命令窗口（用户反馈）。pythonw.exe 是
    GUI 子系统，任何时候都不分配控制台。CLI 模式需要的输出由提权子进程
    AttachConsole 绑回原终端解决（见 _cli_bind_parent_console）。
    """
    argv = list(sys.argv)
    if getattr(sys, "frozen", False):
        # 打包版本身就是独立可执行文件，子系统由打包参数决定
        return sys.executable, subprocess.list2cmdline(argv[1:])
    exe = _pythonw_path() or (sys.executable or "python")
    params = [os.path.abspath(argv[0])] + argv[1:]
    return exe, subprocess.list2cmdline(params)


def request_elevation(argv=None, wait=False, gui=False):
    """以管理员身份重新启动本程序（Windows: 弹 UAC；其他平台: sudo）。

    提权子进程统一以 pythonw.exe 启动，避免 Windows 分配新的控制台
    窗口；GUI 模式到此为止，CLI 模式另需子进程把输出绑回原终端
    （环境变量握手，见 _cli_bind_parent_console）。

    返回 (ok, exit_code, error)：
      ok=True, exit_code=None —— 已启动提权进程（wait=False 时拿不到退出码）
      ok=True, exit_code=N    —— 已等待提权进程结束并拿到其退出码（wait=True）
      ok=False                —— 启动失败（error 说明原因，如用户取消 UAC）
    """
    argv = list(sys.argv if argv is None else argv)

    if not IS_WIN:
        try:
            if os.geteuid() == 0:
                return (True, None, None)
        except AttributeError:
            pass
        sudo = shutil.which("sudo")
        if not sudo:
            return (False, None, tr("err.no_sudo"))
        try:
            code = subprocess.call(
                [sudo, "--", sys.executable or "python3"] + argv)
            return (True, code, None)
        except Exception as e:
            return (False, None, str(e))

    exe, param_str = _elevation_target(gui=gui)
    # CLI 提权子进程以 pythonw.exe 启动时没有控制台，通过环境变量握手
    # 让子进程把输出绑回父进程终端。ShellExecuteEx 不能传环境块，
    # 只能临时改本进程环境让子进程继承，调用后还原。
    # 必须传原进程 PID：经 UAC 提权的子进程，其内核父进程是 AppInfo
    # 服务（svchost，无控制台），ATTACH_PARENT_PROCESS 会失效。
    if not gui:
        os.environ["HDTUNE_ATTACH_PARENT_CONSOLE"] = "1"
        os.environ["HDTUNE_PARENT_PID"] = str(os.getpid())
    try:
        return _shell_execute("runas", exe, param_str, wait)
    finally:
        os.environ.pop("HDTUNE_ATTACH_PARENT_CONSOLE", None)
        os.environ.pop("HDTUNE_PARENT_PID", None)


def _ancestor_processes(max_up=8):
    """返回本进程祖先进程的图像名集合（小写，最多向上 max_up 层）。

    用于识别宿主终端类型（bash/mintty → UTF-8 字节透传；cmd/PowerShell
    → ConHost/ConPTY 按 OEM 代码页解码）。取不到时返回空集合。
    """
    if not IS_WIN:
        return set()
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD,
                                                      wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return set()
        table = {}
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            table[pe.th32ProcessID] = (pe.th32ParentProcessID,
                                       pe.szExeFile.lower())
            ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
        kernel32.CloseHandle(snap)
        names = set()
        pid = os.getpid()
        for _ in range(max_up):
            ent = table.get(pid)
            if not ent:
                break
            ppid, name = ent
            names.add(name)
            pid = ppid
        return names
    except Exception:
        return set()


def _console_encoding():
    """选择控制台输出的编码（尽量让中文在各终端都不乱码）。

    判定顺序（先匹配先返回）：
      1. MSYSTEM 环境变量 → Git Bash/MSYS2 → utf-8（mintty 按 UTF-8 解码）
      2. PSModulePath → PowerShell → mbcs（ConPTY/ConHost 按 OEM CP 解码）
      3. ConEmuPID → ConEmu → utf-8
      4. 祖先进程是 bash/mintty/wsl/ssh/code → utf-8（终端模拟器普遍
         按 UTF-8 处理字节流；Git Bash 工具、VS Code 集成终端属此类）
      5. 祖先进程是 cmd.exe → mbcs（cmd 只在 ConHost/ConPTY 下用）
      6. fd 1 是真控制台句柄（GetConsoleMode 成功）→ mbcs（ConHost 直接渲染）
      7. 兜底 → utf-8（管道/重定向等场景最通用）
    """
    if not IS_WIN:
        return "utf-8"
    if os.environ.get("MSYSTEM"):
        return "utf-8"
    if os.environ.get("PSModulePath"):
        return "mbcs"
    if os.environ.get("ConEmuPID"):
        return "utf-8"
    ancestors = _ancestor_processes()
    if ancestors & {"bash.exe", "mintty.exe", "wsl.exe", "ssh.exe",
                    "code.exe", "code-insiders.exe", "cursor.exe"}:
        return "utf-8"
    if "cmd.exe" in ancestors:
        return "mbcs"
    try:
        import ctypes
        import msvcrt
        h = msvcrt.get_osfhandle(1)
        mode = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            return "mbcs"
    except Exception:
        pass
    return "utf-8"


def _bind_console(targets=None):
    """把本进程的标准流绑定到可用输出并重建 Python 标准流。

    供 GUI 子系统进程（pythonw / --windowed 打包版）使用：这类进程
    Python 不创建 sys.stdout（值为 None），但 C 层 fd 0/1/2 通常仍继承
    自父进程。分三步：
      1. fd 1 有效（cmd 控制台 / 管道 / 重定向文件）→ 直接用它重建；
      2. 句柄无效（如 UAC 提权子进程由 AppInfo 启动，不继承标准句柄）→
         AttachConsole(候选 PID → ATTACH_PARENT_PROCESS)，失败则
         AllocConsole 兜底（会多一个命令窗口，但保证输出可见）；
      3. 按终端类型选编码重建 sys.stdout/stderr/stdin（见
         _console_encoding）。
    返回 (attached, allocated)。
    """
    if not IS_WIN:
        return (False, False)
    try:
        # 1) 继承的标准句柄是否可用
        inherited = True
        try:
            os.fstat(1)
        except OSError:
            inherited = False
        attached = allocated = False
        if not inherited:
            # 2) 绑父进程控制台 / 兜底自建控制台，并重开控制台设备 dup2
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.AttachConsole.argtypes = [wintypes.DWORD]
            kernel32.AttachConsole.restype = wintypes.BOOL
            kernel32.AllocConsole.restype = wintypes.BOOL
            ATTACH_PARENT_PROCESS = 0xFFFFFFFF  # (DWORD)-1
            for target in (targets or []) + [ATTACH_PARENT_PROCESS]:
                if kernel32.AttachConsole(target):
                    attached = True
                    break
            if not attached:
                allocated = bool(kernel32.AllocConsole())
            for fd, dev, mode in ((0, "CONIN$", os.O_RDONLY),
                                  (1, "CONOUT$", os.O_WRONLY),
                                  (2, "CONOUT$", os.O_WRONLY)):
                try:
                    h = os.open(dev, mode)
                    os.dup2(h, fd)
                    if h > 2:
                        os.close(h)
                except OSError:
                    pass
        # 3) 重建 Python 标准流（GUI 子系统启动时 sys.stdout 是 None）
        enc = _console_encoding()
        try:
            sys.stdout = open(1, "w", encoding=enc, errors="replace",
                              closefd=False, buffering=1)
            sys.stderr = open(2, "w", encoding=enc, errors="replace",
                              closefd=False, buffering=1)
            try:
                sys.stdin = open(0, "r", encoding=enc, errors="replace",
                                 closefd=False)
            except OSError:
                pass
        except OSError:
            # 极端情况（拿不到任何输出）：至少保证 print 不崩
            sys.stdout = open(os.devnull, "w")
            sys.stderr = open(os.devnull, "w")
        return (attached, allocated)
    except Exception:
        return (False, False)


def _ensure_console():
    """CLI 模式入口：保证标准流可用且编码与终端匹配。

    场景：
      - GUI 子系统程序（pythonw / --windowed 打包版）没有控制台、
        sys.stdout 为 None → 走 _bind_console 绑回父进程终端；
      - 打包版从命令行启动时 sys.stdout 非 None，但 Python 默认按 ANSI
        代码页（中文系统 GBK）编码，在按 UTF-8 解码的终端（Git Bash /
        mintty）里会乱码 → 按 _console_encoding 的判定重建为标准流；
      - 已是目标编码（cmd / ConHost / ConPTY 下的 GBK）时不动，避免
        无谓重建。
    """
    if not IS_WIN:
        return
    enc = _console_encoding()
    cur = ""
    try:
        cur = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    except Exception:
        pass
    if cur == enc.lower().replace("-", ""):
        return
    if sys.stdout is None:
        _bind_console()
        return
    try:
        sys.stdout = open(1, "w", encoding=enc, errors="replace",
                          closefd=False, buffering=1)
        sys.stderr = open(2, "w", encoding=enc, errors="replace",
                          closefd=False, buffering=1)
    except OSError:
        pass


def _fix_stdout_encoding():
    """只按终端编码重建已存在的标准流，绝不绑定/新建控制台。

    供入口 main() 在 argparse 之前调用：--help 与参数错误信息由 argparse
    直接打印后退出，若晚于 _ensure_console 才修编码，打包版（--windowed）
    在 UTF-8 终端里这些信息会乱码。

    与 _ensure_console 的区别：sys.stdout 为 None 时直接返回（双击 GUI
    的无控制台场景），不触发 _bind_console 的 AttachConsole/AllocConsole
    兜底——否则 GUI 双击运行会多弹一个命令窗口。CLI 路径随后仍会调用
    _ensure_console 处理 None 标准流的绑定。
    """
    if not IS_WIN or sys.stdout is None:
        return
    enc = _console_encoding()
    cur = ""
    try:
        cur = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    except Exception:
        pass
    if cur == enc.lower().replace("-", ""):
        return
    try:
        sys.stdout = open(1, "w", encoding=enc, errors="replace",
                          closefd=False, buffering=1)
        sys.stderr = open(2, "w", encoding=enc, errors="replace",
                          closefd=False, buffering=1)
    except OSError:
        pass


def _cli_bind_parent_console():
    """CLI 提权重启后把标准流绑回原终端，避免多一个命令窗口。

    背景：CLI 提权子进程同样以 pythonw.exe 启动（否则必带控制台窗口），
    pythonw 没有控制台、sys.stdout 为 None。本函数在子进程入口调用
    （环境变量握手）：优先 AttachConsole(原进程 PID) —— 经 UAC 提权的
    子进程内核父进程是 AppInfo 服务（无控制台），ATTACH_PARENT_PROCESS
    会失效，必须显式传 PID；随后 ATTACH_PARENT_PROCESS、AllocConsole
    兜底。非提权子进程（无握手环境变量）直接返回 False。
    """
    if not IS_WIN:
        return False
    if os.environ.get("HDTUNE_ATTACH_PARENT_CONSOLE") != "1":
        return False
    targets = []
    pid_env = os.environ.get("HDTUNE_PARENT_PID", "")
    if pid_env.isdigit():
        targets.append(int(pid_env))
    attached, _allocated = _bind_console(targets)
    return attached



# ---------------------------------------------------------------- 工具函数
def fmt_bytes(n):
    """字节数 → 人类可读"""
    if n is None:
        return tr("unknown")
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if x < 1024.0:
            return "%.1f %s" % (x, unit)
        x /= 1024.0
    return "%.1f EB" % x


def fmt_duration(sec):
    if sec is None:
        return "--"
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


def fmt_speed(bytes_per_sec):
    if not bytes_per_sec:
        return "--"
    return fmt_bytes(bytes_per_sec) + "/s"


def parse_bs(text, size_hint=None):
    """'4M' / '512K' / 'auto' / 纯数字 → 字节数"""
    t = str(text).strip().lower()
    if t in ("auto", "自动", ""):
        return auto_bs(size_hint)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kmgt]?)b?$", t)
    if not m:
        raise ValueError(tr("err.parse_bs", text=text))
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}[m.group(2)]
    v = int(float(m.group(1)) * mult)
    if v < 512:
        raise ValueError(tr("err.bs_too_small"))
    return v


def auto_bs(size):
    """自动块大小：让总块数约 26 万，兼顾精度与解析开销"""
    if not size:
        return 4 * 1024 * 1024
    target = size / 262144.0
    for cand in (512 * 1024, 1 << 20, 2 << 20, 4 << 20, 8 << 20, 16 << 20, 32 << 20, 64 << 20):
        if target <= cand:
            return cand
    return 64 << 20


def parse_segment_size(text):
    """分段大小字符串 → 字节数；'整盘一次'/'Whole disk at once' 返回 None"""
    t = str(text).strip().lower()
    if (not t or "整盘" in t or "一次" in t or t == "none"
            or "whole" in t or "entire" in t):
        return None
    return parse_bs(text)


def plan_segments(total_size, seg_bytes, bs=None):
    """把 [0, total_size) 切成段列表 [(offset, size)]；无法得知总大小时返回 [(0, None)]。
    seg_bytes 向下对齐到 bs 的倍数：direct IO 要求 offset 对齐，未对齐的段起始偏移
    会让 fio 直接以 EINVAL 失败（实测 error=22, total_ios=0）。
    "整盘一次"（seg_bytes=None）且已知容量时返回 [(0, total_size)] 而非 [(0, None)]：
    fio 对文件大小的隐式探测不可靠（实测个别文件会读出近两倍数据），显式传
    --size 才准确；容量未知时才交给 fio 自行探测（裸设备场景）。"""
    if seg_bytes is None:
        return [(0, total_size)] if total_size else [(0, None)]
    if not total_size:
        return [(0, None)]
    if bs and seg_bytes < bs:
        return [(0, None)]  # 段比一个块还小没有意义，退化为整盘一次
    if bs and seg_bytes > bs:
        seg_bytes = (seg_bytes // bs) * bs
    segs = []
    off = 0
    while off < total_size:
        sz = min(seg_bytes, total_size - off)
        segs.append((off, sz))
        off += sz
    if len(segs) > 8192:  # 防御：段数过多时退化为整盘一次
        return [(0, None)]
    return segs


def sanitize_segments(segments, bs):
    """修整分段列表：fio 会拒绝 size < bs 的段（直接报错导致尾部数据漏扫），
    过小的末段合并进前一段。返回新列表，不修改入参。"""
    segs = [(o, s) for o, s in segments if s is None or s > 0]
    if not segs:
        return [(0, None)]
    i = len(segs) - 1
    while i > 0 and segs[i][1] is not None and segs[i][1] < bs:
        o2, s2 = segs.pop(i)
        o1, s1 = segs[i - 1]
        segs[i - 1] = (o1, None if s1 is None else s1 + s2)
        i -= 1
    return segs


def expected_io_count(size, off, total_size, bs, seg_bytes_done=0):
    """一个段预期能被 fio 读走的整块数，返回 (expected_ios, unread_tail_bytes)。

    为什么必须是【向下取整】而不是向上：
    fio 对不足一个块的尾巴有两种行为——
      1. 尾巴 512 对齐（如文件场景）：会多发一次部分块 IO
         （实测 6.5MB/1M → 7 次 IO）；
      2. 尾巴不对齐（物理盘末尾，direct IO 无法做不对齐读）：直接跳过不读
         （实测 13.69MB/1M → 只读 13 块）。
    用 ceil 会把"段尾/盘尾的不对齐余数"误判成"任务中止、未扫描"，
    凭空生成假错误块并触发"物理损伤风险"弹窗——用户反馈的
    "停止扫描就报磁盘错误"根因就是它（停止信号落在最后一段解析前后时，
    aborted 可能为 False，假错误块直接触发弹窗）。
    floor 是安全下限：actual < expected ⟺ fio 确实提前中止了。

    size=None 表示"读到设备末尾"：已知 total_size 时按 (total_size - off)
    推算（修复整盘一次模式停止后漏记未扫描字节的问题）；两者都未知时
    退化为段内实际读数（保持旧行为）。
    """
    if size:
        eff = size
        if total_size and off is not None:
            # 段超出设备末尾（快速扫描末区/--limit-mb 越界）时按设备大小截断
            eff = max(0, min(off + size, total_size) - off)
    elif total_size and off is not None:
        eff = max(0, total_size - off)
    else:
        eff = seg_bytes_done or 0
    if eff <= 0:
        return 0, 0
    full = eff // bs
    return full, eff - full * bs


# 快速扫描（类 HD Tune Quick Scan）：把磁盘切成若干"区域"，每区只读开头
# 一小段样本，跳过其余数据。坏道通常成簇分布，抽样足以发现明显损伤区域，
# 耗时约为全盘扫描的几十分之一。
QUICK_MAX_REGIONS = 128     # 区域数上限：每个区域一次 fio 启动（约 1 秒），
                            # 过多时启动开销会累积成主要耗时，故自动放大区域
QUICK_DEFAULT_SAMPLE = 16 * 1024 * 1024   # 默认每区抽样 16MB


def plan_quick_segments(total_size, seg_bytes, sample_bytes, bs=None,
                        max_regions=QUICK_MAX_REGIONS):
    """快速扫描分段：返回 [(offset, sample_size)]，每区只读开头样本。

    seg_bytes 为 None（整盘一次）时区域大小按 max_regions 均分；区域过多时
    自动放大（2 的幂次）到上限以内。样本不超过区域大小；offset 与样本大小
    都对齐到 bs（direct IO 要求，未对齐会 EINVAL，实测 error=22）。
    容量未知时退化为 [(0, None)]（整盘一次），由调用方提示。
    """
    if not total_size:
        return [(0, None)]
    if not sample_bytes or sample_bytes <= 0:
        sample_bytes = QUICK_DEFAULT_SAMPLE
    region = seg_bytes if seg_bytes else max(bs or 512, -(-total_size // max_regions))
    while region < total_size and (total_size + region - 1) // region > max_regions:
        region *= 2
    if region > total_size:
        region = total_size
    if bs:
        region = max(bs, (region // bs) * bs)
        sample_bytes = min(sample_bytes, region)
        sample_bytes = max(bs, (sample_bytes // bs) * bs)
    else:
        sample_bytes = min(sample_bytes, region)
    segs = []
    off = 0
    while off < total_size:
        sz = min(sample_bytes, total_size - off)
        if sz <= 0:
            break
        segs.append((off, sz))
        off += region
    return segs or [(0, None)]


def quick_scan_setup(size, bs, seg_bytes, sample_bytes):
    """快速扫描参数收口（GUI/CLI 共用）：返回 (bs, segments, sample_bytes)。

    容量未知时无法布点，退化为整盘一次（调用方应提示）；块大小超过抽样
    大小时缩小块大小（否则抽样会被抬到块大小，失去快速意义）。"""
    if not size:
        return bs, plan_segments(0, seg_bytes, bs), 0
    sample = int(sample_bytes or 0)
    if sample < 512:
        # 过小的抽样没有意义（且易被 bs 兜底成整段），视为未指定
        sample = QUICK_DEFAULT_SAMPLE
    if bs > sample:
        bs = sample
    segs = plan_quick_segments(size, seg_bytes, sample, bs)
    return bs, segs, (segs[0][1] if segs and segs[0][1] else 0)


def plan_grid(canvas_w, canvas_h, n_cells, size_max=CELL_SIZE_MAX):
    """热力图自适应平铺布局：给定画布尺寸与格子数，返回
    (pitch, cols, rows, ox, oy)。

    pitch 为格子间距（含 CELL_GAP 间隙），格子行优先填充（从左到右铺满
    一行再下一行）。设计目标：
      1. 全部格子可见（cols*rows >= n_cells 恒成立）；
      2. 格子尽量大：pitch 取"能把全部格子铺进画布"的最大值，封顶
         size_max（段太少时避免出现巨型块，周围留白居中）；
      3. 行列比例贴近画布宽高比（cols/rows ≈ w/h），网格接近正方格。
    pitch 关于 rows 单峰（w/cols 阶梯递减、h/rows 递减，min 先升后降），
    从宽高比估算值向两边扩展取最优即可。
    """
    w = max(1, int(canvas_w))
    h = max(1, int(canvas_h))
    n = max(1, int(n_cells))
    ratio = w / float(h)
    guess = max(1, int(math.sqrt(n / ratio)))
    best_pitch, best_rows = None, 1
    for rows in range(max(1, guess - 64), min(n, guess + 64) + 1):
        cols = -(-n // rows)  # ceil
        pitch = min(w / float(cols), h / float(rows))
        if best_pitch is None or pitch > best_pitch:
            best_pitch, best_rows = pitch, rows
    pitch = min(best_pitch, size_max)
    # 按取整后的 cols 重新收敛：cols 变小会使 rows 变多、总高度可能超画布，
    # 此时加宽列数（等价缩 pitch）直到放下——cols 最大到 n 时 rows=1 必放下
    cols = max(1, int(w // pitch))
    rows = -(-n // cols)
    while rows * pitch > h and cols < n:
        cols += 1
        rows = -(-n // cols)
    ox = max(0.0, (w - cols * pitch) / 2.0)
    oy = max(0.0, (h - rows * pitch) / 2.0)
    return pitch, cols, rows, ox, oy


# 各平台的默认引擎候选：Windows 官方构建只有 windowsaio/sync/psync；
# libaio/posixaio 是 Linux 原生异步引擎，Windows 版 fio 未编译进去
# （实测加载即报 "fio: engine libaio not loadable / failed to load engine"）。
ENGINES_WIN = ("windowsaio", "sync", "psync")
ENGINES_POSIX = ("libaio", "posixaio", "sync", "psync")
ENGINE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def platform_engines():
    """当前平台的默认引擎下拉列表"""
    return list(ENGINES_WIN if IS_WIN else ENGINES_POSIX)


def list_fio_engines(fio_path=None, timeout=20):
    """查询 fio 实际可用的 ioengine（执行 fio --enghelp 并解析）。
    返回 set；指定路径无效/fio 不存在/超时/输出无法识别时返回 None
    （调用方应放行，由既有的"未找到 fio"逻辑处理）。
    注意：不做路径兜底——调用方传什么就测什么，避免掩盖配置错误。"""
    if fio_path:
        fio = fio_path
    else:
        fio = resolve_fio(None)
    if not fio or not os.path.isfile(fio):
        return None
    try:
        p = subprocess.run([fio, "--enghelp"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None
    if p.returncode != 0:
        return None
    engines = set()
    for line in (p.stdout or "").splitlines():
        s = line.strip()
        if s and ENGINE_NAME_RE.match(s):
            engines.add(s)
    return engines or None


def clamp_bs(bs, size):
    """块大小超过目标容量时缩小到不超过容量的最大 2 的幂（最小 512B）"""
    if not size or bs <= size:
        return bs
    v = 512
    while v * 2 <= size:
        v *= 2
    return v


def resolve_fio(user_path=None):
    """按优先级定位 fio 可执行文件"""
    cands = []
    if user_path:
        cands.append(user_path)
    # PyInstaller 打包版：fio.exe 随包分发（build_exe.py --add-binary），
    # 解压后在 sys._MEIPASS 根目录；本机另装有 fio 时也可在 GUI 里改路径
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "fio.exe"))
    w = shutil.which("fio")
    if w:
        cands.append(w)
    if IS_WIN:
        cands += [
            r"C:\Program Files\fio\fio.exe",
            r"C:\Program Files (x86)\fio\fio.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\fio.exe"),
            r"C:\msys64\usr\bin\fio.exe",
            r"C:\msys32\usr\bin\fio.exe",
        ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return user_path or "fio"


def extract_drive_path(text):
    """从下拉框标签中提取纯净裸设备路径。

    GUI 下拉框的值为展示标签，形如：
        \\\\.\\PhysicalDrive1  —  WDC WD10EZEX-22MFCA0 | 931.5 GB | ATA
    而 fio 的 --filename 与 CreateFileW 只接受纯净盘号路径（设备名不含空格），
    整串标签传进去会直接打不开设备（实测 fio: failed opening blockdev），
    且容量查询也会因路径非法而失败、导致分段退化为 1 段。
    裸设备路径本身不含空白字符，故取开头到第一个空白/竖线为止。"""
    if not text:
        return text
    t = text.strip().strip('"').strip("'")
    if not t:
        return t
    if DRIVE_PATH_RE.match(t) or t.lower().startswith("//./"):
        m = re.match(r"((?:\\\\\.\\|//\./)[^\s|]+)", t)
        if m:
            return m.group(1)
    return t


def normalize_target_path(p):
    """规范化扫描目标路径：剥离下拉框标签、兼容 Git Bash 风格 /c/... → C:/...，
    保留裸设备路径。
    普通文件路径的反斜杠统一转成正斜杠——fio 两种都接受，但正斜杠可避免
    Git Bash/MSYS2 对反斜杠参数的篡改（实测 C:\\x 会被改成 //x）。"""
    p = extract_drive_path(p)
    if not p:
        return p
    p = p.strip().strip('"').strip("'")
    if DRIVE_PATH_RE.match(p) or p.lower().startswith("//./"):
        return p
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)
    if m:
        return m.group(1).upper() + ":/" + m.group(2)
    if re.match(r"^[a-zA-Z]:[\\/]", p):
        return p[0].upper() + ":/" + p[3:].replace("\\", "/")
    if "\\" in p:
        return p.replace("\\", "/")
    return p


# fio JSON 的 job.error 字段是 errno 码而非错误计数（实测踩坑）
ERRNO_NAMES = {
    1: "EPERM 权限不足",
    2: "ENOENT 文件/设备不存在",
    5: "EIO 读取错误（坏块或介质故障）",
    13: "EACCES 拒绝访问（权限或路径问题）",
    22: "EINVAL 参数错误（offset 未对齐或直接 IO 不支持）",
    28: "ENOSPC 空间不足",
}


# ---------------------------------------------------------------- Windows 磁盘枚举
def _win_query_drive(path):
    """通过 IOCTL 查询磁盘容量/型号/总线。返回 (size|None, model|None, bus|None)"""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return (None, None, None)
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                        wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        h = k32.CreateFileW(path, 0x80000000, 3, None, 3, 0, None)  # GENERIC_READ, 共享读写
        if not h or h == wintypes.HANDLE(-1).value:
            return (None, None, None)
        try:
            size = ctypes.c_ulonglong(0)
            ret = wintypes.DWORD()
            ok = k32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO, None, 0,
                                     ctypes.byref(size), 8, ctypes.byref(ret), None)
            sz = size.value if ok else None
            import struct
            query = struct.pack("II", 0, 0)  # StorageDeviceProperty, PropertyStandardQuery
            buf = (ctypes.c_ubyte * 1024)()
            ret2 = wintypes.DWORD()
            ok2 = k32.DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, query, len(query),
                                      buf, 1024, ctypes.byref(ret2), None)
            model, bus = None, None
            if ok2 and ret2.value >= 40:
                voff, poff = struct.unpack_from("II", buf, 24)
                bus = struct.unpack_from("I", buf, 36)[0]

                def cstr(o):
                    if 0 < o < ret2.value:
                        return ctypes.string_at(ctypes.byref(buf, o)).decode("ascii", "replace").strip()
                    return ""

                model = ((cstr(voff) + " " + cstr(poff)).strip()) or None
            return (sz, model, bus)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return (None, None, None)


def _ps_disk_info():
    """PowerShell 备用查询：{index: (size, model, interface)}"""
    script = ("Get-CimInstance Win32_DiskDrive | ForEach-Object { "
              "'{0}|{1}|{2}|{3}' -f $_.DeviceID,$_.Size,$_.Model,$_.InterfaceType }")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = p.stdout or b""
        if raw[:2] == b"\xff\xfe":
            txt = raw.decode("utf-16-le", "replace")
        else:
            try:
                txt = raw.decode("utf-8", "replace")
            except Exception:
                txt = raw.decode("latin-1", "replace")
        info = {}
        for line in txt.splitlines():
            parts = [x.strip() for x in line.split("|")]
            if len(parts) >= 2 and parts[0]:
                m = re.search(r"PHYSICALDRIVE(\d+)\s*$", parts[0], re.I)
                if m:
                    size = int(parts[1]) if parts[1].isdigit() else None
                    info[int(m.group(1))] = (size,
                                             parts[2] if len(parts) > 2 else "",
                                             parts[3] if len(parts) > 3 else "")
        return info
    except Exception:
        return {}


def list_drives():
    """枚举物理磁盘，返回 [{index, path, size, model, bus}]"""
    drives = {}
    if IS_WIN:
        for i in range(33):
            path = "\\\\.\\PhysicalDrive%d" % i
            sz, model, bus = _win_query_drive(path)
            if sz or model:
                drives[i] = {"index": i, "path": path, "size": sz,
                             "model": model or "", "bus": bus}
        if not drives:  # IOCTL 全部失败（如权限受限）→ 仅用 PowerShell
            for i, (sz, model, iface) in _ps_disk_info().items():
                drives[i] = {"index": i, "path": "\\\\.\\PhysicalDrive%d" % i,
                             "size": sz, "model": model or "", "bus": None}
        else:
            ps = _ps_disk_info()
            for i, d in drives.items():
                if (not d["size"] or not d["model"]) and i in ps:
                    sz, model, _iface = ps[i]
                    d["size"] = d["size"] or sz
                    d["model"] = d["model"] or model
    return [drives[k] for k in sorted(drives)]


def query_target_size(target):
    """查询扫描目标的总字节数；失败返回 None"""
    t = normalize_target_path(target)
    if DRIVE_PATH_RE.match(t) or t.lower().startswith("//./"):
        if IS_WIN:
            sz, _model, _bus = _win_query_drive(t)
            if sz:
                return sz
            m = re.search(r"physicaldrive(\d+)", t, re.I)
            if m:
                info = _ps_disk_info()
                i = int(m.group(1))
                if i in info and info[i][0]:
                    return info[i][0]
        return None
    if os.path.exists(t):
        try:
            return os.path.getsize(t)
        except OSError:
            return None
    return None



# ---------------------------------------------------------------- fio 扫描引擎
def extract_json_docs(text):
    """从 fio stdout 中提取所有完整 JSON 文档（--output-format=json 时每秒一个快照）"""
    docs = []
    rest = text
    while True:
        start = rest.find("{")
        if start < 0:
            break
        depth, end, in_str, esc = 0, -1, False, False
        for i in range(start, len(rest)):
            ch = rest[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            break
        try:
            docs.append(json.loads(rest[start:end + 1]))
            rest = rest[end + 1:]
        except Exception:
            nxt = rest.find("{", start + 1)
            if nxt < 0:
                break
            rest = rest[nxt:]
    return docs, rest


class FioScanner:
    """fio 扫描编排：分段执行、流式解析、聚合统计"""

    def __init__(self, fio_path="fio"):
        self.fio_path = fio_path
        self._stop_evt = threading.Event()
        self._proc = None
        self._last_tmpdir = None

    def stop(self):
        self._stop_evt.set()
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    # ---------------------------------------------------------- 命令构建
    def _build_cmd(self, target, bs, ioengine, direct, lat_base, offset, size):
        cmd = [self.fio_path,
               "--name=hdtune_scan",
               "--filename=" + target,
               "--rw=read",
               "--bs=%d" % bs,
               "--iodepth=1",
               "--ioengine=" + ioengine,
               "--thread=1",                 # 关键：启用每秒 JSON 状态快照
               "--continue_on_error=read",    # 坏块不中断，继续扫完
               "--status-interval=1",
               "--eta=always",
               "--output-format=json",
               "--write_lat_log=" + lat_base]
        if direct and ioengine not in ("sync", "psync"):
            cmd.append("--direct=1")
        if offset:
            cmd.append("--offset=%d" % offset)
        if size:
            cmd.append("--size=%d" % size)
        return cmd

    @staticmethod
    def _find_lat_log(base):
        for suffix in ("_clat.1.log", "_lat.1.log", "_clat.log", "_lat.log"):
            p = base + suffix
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def _parse_clat_log(path):
        """解析 clat 日志 → [(序号, 延迟微秒)]。
        格式: 时间ms, clat_us, 方向, 块大小, offset(恒0,不可用)
        iodepth=1 顺序读时完成顺序 = 偏移顺序，故用序号映射块索引。"""
        blocks = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                seq = 0
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) < 3:
                        continue
                    try:
                        clat_us = float(parts[1])
                        dd = int(parts[2])
                    except ValueError:
                        continue
                    if dd != 0:
                        continue
                    blocks.append((seq, clat_us))
                    seq += 1
        except OSError:
            pass
        return blocks

    @staticmethod
    def _offset_to_index(offset, seg_off, seg_size, bs):
        """fio 报错的 offset → 全局块索引（兼容绝对/段内两种解释）"""
        if seg_off is not None and seg_size and seg_off <= offset < seg_off + seg_size:
            return (offset - seg_off) // bs
        return offset // bs

    # ---------------------------------------------------------- stdout / stderr 泵
    def _pump_stdout(self, proc, state, emit, ctx):
        """逐行读 stdout：提取完整 JSON 快照发 tick 事件；文本 eta 行兜底"""
        text = ""
        last_emit = 0.0
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            text += line
            m = ETA_RE.search(line)
            if m:  # Linux 构建的文本 eta 行
                try:
                    pct = float(m.group(1))
                    val = float(m.group(2))
                    mult = {"KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3,
                            "TiB": 1024 ** 4, "B": 1}.get(m.group(3), 1024 ** 2)
                    emit({"type": "tick", "segment": ctx["index"],
                          "pct": pct, "bw_bytes": val * mult, "errors": None})
                except ValueError:
                    pass
            now = time.time()
            if now - last_emit >= 0.4:
                last_emit = now
                docs, text = extract_json_docs(text)
                for d in docs:
                    state["docs"].append(d)
                    if len(state["docs"]) > 4:
                        state["docs"].pop(0)
                    self._emit_doc_tick(d, emit, ctx)
        docs, text = extract_json_docs(text)
        for d in docs:
            state["docs"].append(d)
            if len(state["docs"]) > 4:
                state["docs"].pop(0)
            self._emit_doc_tick(d, emit, ctx)

    @staticmethod
    def _emit_doc_tick(doc, emit, ctx):
        try:
            job = (doc.get("jobs") or [{}])[0]
            rd = job.get("read") or {}
            emit({"type": "tick",
                  "segment": ctx["index"],
                  "io_bytes": rd.get("io_bytes"),
                  "bw_bytes": rd.get("bw_bytes"),
                  "errors": job.get("error"),
                  "runtime_ms": rd.get("runtime")})
        except Exception:
            pass

    def _pump_stderr(self, proc, state, emit):
        while True:
            line = proc.stderr.readline()
            if not line:
                break
            line = line.rstrip("\r\n")
            if NOISE_RE.search(line):
                continue  # windowsaio 扫文件时的无害噪音，读取实际成功
            state["lines"].append(line)
            if len(state["lines"]) > 2000:
                state["lines"].pop(0)
            emit({"type": "log", "stream": "stderr", "line": line})

    # ---------------------------------------------------------- 主流程
    def run(self, target, bs, segments, ioengine=None, direct=True,
            total_size=None, yellow_mult=3.0, red_mult=8.0,
            yellow_floor_us=10000, red_floor_us=100000, on_event=None,
            quick=False):
        """执行扫描（阻塞）。segments: [(offset, size|None)]，size=None 表示到设备末尾。
        quick=True 表示快速扫描（抽样）：segments 即区域样本列表，仅记录模式
        供报告标注，扫描流程与全盘一致。事件通过 on_event(dict) 回调；返回汇总 dict。"""
        emit = on_event if callable(on_event) else (lambda e: None)
        self._stop_evt.clear()
        if ioengine is None:
            ioengine = "windowsaio" if IS_WIN else "libaio"
        # 修整分段：fio 拒绝 size < bs 的段（直接报错导致尾部数据漏扫），
        # 过小的末段合并进前一段；扫描范围整体小于一个块时缩小块大小。
        segments = sanitize_segments(segments, bs)
        if (len(segments) == 1 and segments[0][1] is not None
                and segments[0][1] < bs):
            rng = segments[0][1]
            new_bs = 512
            while new_bs * 2 <= rng:
                new_bs *= 2
            emit({"type": "log", "stream": "info",
                  "line": tr("log.scan_range_small",
                             size=fmt_bytes(rng), bs=fmt_bytes(bs),
                             new_bs=fmt_bytes(new_bs))})
            bs = new_bs

        tmpdir = tempfile.mkdtemp(prefix="hdtune_scan_")
        if self._last_tmpdir:
            shutil.rmtree(self._last_tmpdir, ignore_errors=True)
        self._last_tmpdir = tmpdir

        all_lats = array("d")
        error_blocks = {}       # 全局块索引 → 说明
        unlocated_errors = 0    # stderr 里出现但无法定位到块的错误行数
        errno_segments = 0      # fio 报告了非零 errno 的段数
        last_errno = 0          # 最后一个非零 errno 码
        unscanned_bytes = 0     # 因任务提前失败而从未尝试读取的字节数
        unread_tail_bytes = 0   # 段尾不足一块的余数字节（fio 不读，非错误）
        seg_table = []
        first_error_off = None
        base_done = 0           # 已完成段的总字节数
        aborted = False
        stopped_unscanned = 0   # 其中因主动停止而未扫描的字节数
        t_start = time.time()

        try:
            for seg_i, (off, size) in enumerate(segments):
                if self._stop_evt.is_set():
                    aborted = True
                    break
                lat_base = os.path.join(tmpdir, "seg%d" % seg_i)
                cmd = self._build_cmd(target, bs, ioengine, direct, lat_base, off, size)
                emit({"type": "log", "stream": "cmd", "line": " ".join(cmd)})
                emit({"type": "segment", "index": seg_i, "total": len(segments),
                      "offset": off, "size": size})

                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    bufsize=1, text=True, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._proc = proc
                out_state = {"docs": []}
                err_state = {"lines": []}
                ctx = {"index": seg_i, "offset": off, "size": size,
                       "base_done": base_done, "total": total_size}
                t_out = threading.Thread(target=self._pump_stdout,
                                         args=(proc, out_state, emit, ctx), daemon=True)
                t_err = threading.Thread(target=self._pump_stderr,
                                         args=(proc, err_state, emit), daemon=True)
                t_out.start()
                t_err.start()

                while True:
                    if proc.poll() is not None:
                        break
                    if self._stop_evt.is_set():
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except Exception:
                            proc.kill()
                        aborted = True
                        break
                    time.sleep(0.1)
                t_out.join(timeout=15)
                t_err.join(timeout=15)
                self._proc = None

                # ---- 解析本段结果 ----
                doc = out_state["docs"][-1] if out_state["docs"] else {}
                job = (doc.get("jobs") or [{}])[0]
                rd = job.get("read") or {}

                # 单位自检：fio 不同版本/平台的 lat 日志单位可能是 ns 或 µs
                # （实测 Windows fio 3.43 为 ns）。用 JSON 的 clat_ns.mean 标定：
                # 日志中位数与 clat_ns 同量级（比值≈1）→ 日志是纳秒；
                # 日志中位数是 clat_ns 的千分之一（比值≈0.001）→ 日志是微秒。
                scale = 1.0
                lat_path = self._find_lat_log(lat_base)
                blocks = self._parse_clat_log(lat_path) if lat_path else []
                if blocks:
                    log_med = statistics.median([l for _, l in blocks])
                    json_mean = (rd.get("clat_ns") or {}).get("mean")
                    if json_mean and log_med > 0:
                        ratio = log_med / float(json_mean)
                        if 0.1 < ratio < 10:
                            scale = 0.001      # 日志是纳秒 → 换算为微秒
                        elif 0.0001 < ratio < 0.01:
                            scale = 1.0        # 日志本就是微秒
                    elif log_med > 5000000:
                        scale = 0.001  # 无 JSON 兜底：单块超 5 秒的"微秒"不合常理
                    if scale != 1.0:
                        emit({"type": "log", "stream": "info",
                              "line": tr("log.lat_unit_ns")})

                base_idx = (off // bs) if off else 0
                seg_lats = []
                for rel, lat in blocks:
                    lat_us = lat * scale
                    all_lats.append(lat_us)
                    seg_lats.append(lat_us)
                seg_bytes_done = len(blocks) * bs
                # 热力图一格 = 一个段：段读完发一条段级统计事件即可。
                # 不再逐块发 block 事件——1TB 盘按 1M 块约 100 万次事件
                # 会把队列消费（每轮至多 4000 条）拖成瓶颈。
                if seg_lats:
                    emit({"type": "seg_stat", "index": seg_i,
                          "median_us": statistics.median(seg_lats),
                          "max_us": max(seg_lats),
                          "n_blocks": len(seg_lats)})

                # fio JSON 的 job.error 是 errno 码（0=无错误），不是错误计数。
                # 常见：5=EIO 读失败(坏块)；22=EINVAL(offset 未对齐/direct IO 不支持)；
                #       13=EACCES(权限或路径问题)。
                seg_errno = int(job.get("error") or 0)
                if seg_errno:
                    errno_segments += 1
                    last_errno = seg_errno
                    emit({"type": "log", "stream": "warn",
                          "line": tr("log.segment_fio_error",
                                     i=seg_i + 1, n=len(segments),
                                     name=errno_name(seg_errno), code=seg_errno)})
                # 预期 I/O 数 vs 实际：差值即因任务提前中止而未扫描的块。
                # 主动停止（用户点停止按钮）是预期行为，只做信息性统计，
                # 不计入错误块——否则停止后 GUI 会弹"发现读取错误/物理损伤风险"。
                # 判定依据是停止事件本身而非 aborted_seg：stop() 会直接
                # terminate 进程，主循环可能走 poll() 分支 break 而来不及
                # 记 aborted_seg（实测竞态：段0扫完瞬间点停止，段1 fio 被
                # terminate 后 poll() 非 None，aborted_seg 保持 -1）。
                # 预期值用 expected_io_count（floor 语义，见函数文档）：
                # 段尾/盘尾不足一块且不对齐的余数 fio 根本不读，按 ceil 算
                # 会把余数误判成"未扫描"假错误（停止扫描误报磁盘错误的根因）。
                actual_ios = int(rd.get("total_ios") or 0)
                expected_ios, unread_tail = expected_io_count(
                    size, off, total_size, bs, seg_bytes_done)
                if unread_tail:
                    unread_tail_bytes += unread_tail
                if expected_ios and actual_ios < expected_ios:
                    missing = expected_ios - actual_ios
                    unscanned_bytes += missing * bs
                    if self._stop_evt.is_set():
                        stopped_unscanned += missing * bs
                        emit({"type": "log", "stream": "info",
                              "line": tr("log.segment_stopped",
                                         i=seg_i + 1, n=len(segments),
                                         done=actual_ios, total=expected_ios)})
                    else:
                        miss_idx = base_idx + actual_ios
                        error_blocks[miss_idx] = tr(
                            "log.unscanned_aborted", n=actual_ios, code=seg_errno)
                        emit({"type": "error_block", "index": miss_idx})
                located_here = 0

                fe = job.get("first_error") or 0
                # first_error 仅在真实读错误（EIO）时才是字节偏移；失败于打开/对齐
                # 等场景时它只是回显 errno 码（实测值 22 == EINVAL）
                if fe and seg_errno == 5 and int(fe) >= (off or 0):
                    if first_error_off is None:
                        first_error_off = int(fe)
                    idx = self._offset_to_index(int(fe), off, size, bs)
                    if idx not in error_blocks:
                        error_blocks[idx] = tr("errblk.eio", off=int(fe))
                        located_here += 1
                        emit({"type": "error_block", "index": idx})

                for line in err_state["lines"]:
                    m = OFFSET_RE.search(line)
                    if m:
                        idx = self._offset_to_index(int(m.group(1)), off, size, bs)
                        if idx not in error_blocks:
                            error_blocks[idx] = line.strip()[:100]
                            located_here += 1
                            emit({"type": "error_block", "index": idx})
                    elif "err=" in line or "error" in line.lower():
                        unlocated_errors += 1

                seg_table.append({
                    "index": seg_i, "offset": off,
                    "size": size if size else seg_bytes_done,
                    "blocks": len(blocks),
                    "errno": seg_errno,
                    "errno_name": ERRNO_NAMES.get(seg_errno, "") if seg_errno else "",
                    "actual_ios": actual_ios, "expected_ios": expected_ios,
                    "median_us": statistics.median(seg_lats) if seg_lats else None,
                    "max_us": max(seg_lats) if seg_lats else None,
                    "runtime_ms": rd.get("runtime"),
                    "bw_bytes": rd.get("bw_bytes"),
                })
                base_done += (size if size else seg_bytes_done)

            # ---- 停止记账补丁：从未启动的段 ----
            # 段边界竞态：停止信号落在"前一段已解析完、后段尚未启动"的
            # 窗口时，for 循环在顶部 break，这些段的字节不会经过
            # actual_ios<expected_ios 分支，stopped_unscanned 会漏记
            # （实测：512MB 两段扫描 1.2s 点停止，stopped_unscanned=0）。
            # seg_table 只收录真正启动过 fio 的段，其余段整段计入。
            if self._stop_evt.is_set():
                for _o, sz in segments[len(seg_table):]:
                    if sz:
                        stopped_unscanned += sz
                        emit({"type": "log", "stream": "info",
                              "line": tr("log.unstarted_segments",
                                         size=fmt_bytes(sz))})

            # ---- 汇总 ----
            # 停止竞态兜底：stop() 会直接 terminate 进程，主循环可能走
            # poll() 分支 break 而没设 aborted。只要停止请求发出后确有
            # 未覆盖字节，就应标记为"已中止"；若停止时恰好全部扫完
            # （stopped_unscanned=0 且未 break），保持 aborted=False。
            # stop_requested 作为一等事实透出：调用方（GUI/CLI）据此
            # 抑制"磁盘错误"类警报——用户主动停止造成的不完整绝不是坏道。
            stop_requested = self._stop_evt.is_set()
            if stop_requested and (aborted or stopped_unscanned or unscanned_bytes):
                aborted = True
            lats = list(all_lats)
            n = len(lats)
            if n:
                med = statistics.median(lats)
                mean = sum(lats) / n
                mx = max(lats)
                srt = sorted(lats)
                p99 = srt[min(n - 1, int(n * 0.99))]
            else:
                med = mean = mx = p99 = 0.0
            slow_thr = max(med * yellow_mult, yellow_floor_us)
            bad_thr = max(med * red_mult, red_floor_us)
            ok = sum(1 for x in lats if x <= slow_thr)
            bad = sum(1 for x in lats if x > bad_thr)
            slow = n - ok - bad
            summary = {
                "target": target, "bs": bs, "ioengine": ioengine, "direct": direct,
                "total_size": total_size, "segments": seg_table,
                "n_blocks": n, "ok": ok, "slow": slow, "bad": bad,
                "error_blocks": error_blocks, "unlocated_errors": unlocated_errors,
                "median_us": med, "mean_us": mean, "max_us": mx, "p99_us": p99,
                "slow_thr_us": slow_thr, "bad_thr_us": bad_thr,
                "elapsed_s": time.time() - t_start, "aborted": aborted,
                "stop_requested": stop_requested,
                "errno_segments": errno_segments, "last_errno": last_errno,
                "last_errno_name": errno_name(last_errno, "") if last_errno else "",
                "unscanned_bytes": unscanned_bytes,
                "stopped_unscanned_bytes": stopped_unscanned,
                "unread_tail_bytes": unread_tail_bytes,
                "json_errors": errno_segments,  # 兼容旧字段名：报告错误的段数
                "first_error_offset": first_error_off,
                "quick": bool(quick),
                "tmpdir": tmpdir, "fio": self.fio_path,
            }
        except Exception as e:
            emit({"type": "failed", "message": "%s: %s" % (type(e).__name__, e)})
            return None

        # finished 事件放在 try 之外发射：on_event 回调自身抛异常时不应把
        # 已成功的扫描吞成 failed（实测踩坑：回调里 KeyError 被 except 捕获）
        emit({"type": "finished", "summary": summary})
        return summary



# ---------------------------------------------------------------- 报告导出
def write_reports(outdir, summary, lang=None):
    """把汇总写成 CSV/TXT 报告，返回生成的文件列表。

    lang: 报告语言（"en"/"zh"）；None 用当前界面语言。CLI 固定传 "en"。"""
    os.makedirs(outdir, exist_ok=True)
    bs = summary["bs"]
    files = []

    def T(key, **kw):
        return tr(key, _lang=lang, **kw)

    p = os.path.join(outdir, "segments.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(tr_list("rep.csv_seg_header", _lang=lang))
        for seg in summary["segments"]:
            w.writerow([seg["index"] + 1, seg["offset"], seg["size"], seg["blocks"],
                        seg["actual_ios"], seg["expected_ios"],
                        seg["errno"] or "", seg["errno_name"],
                        round(seg["median_us"] / 1000.0, 3) if seg["median_us"] is not None else "",
                        round(seg["max_us"] / 1000.0, 3) if seg["max_us"] is not None else ""])
    files.append(p)

    p = os.path.join(outdir, "errors.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(tr_list("rep.csv_err_header", _lang=lang))
        for idx in sorted(summary["error_blocks"]):
            off = idx * bs
            w.writerow([idx, off, fmt_bytes(off), summary["error_blocks"][idx]])
    files.append(p)

    p = os.path.join(outdir, "summary.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(T("rep.title") + "\n")
        f.write("=" * 46 + "\n")
        f.write(T("rep.generated",
                  ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")) + "\n")
        f.write(T("rep.target", t=summary["target"]) + "\n")
        f.write(T("rep.bs", bs=fmt_bytes(summary["bs"])) + "\n")
        f.write(T("rep.ioengine", e=summary["ioengine"], d=summary["direct"]) + "\n")
        f.write(T("rep.capacity", sz=fmt_bytes(summary["total_size"])) + "\n")
        if summary.get("quick"):
            covered = sum((s["size"] or 0) for s in summary["segments"])
            cov_pct = (covered * 100.0 / summary["total_size"]) if summary["total_size"] else 0.0
            f.write(T("rep.mode_quick", n=len(summary["segments"]),
                      cov=fmt_bytes(covered), pct=cov_pct) + "\n")
            f.write(T("rep.note_quick") + "\n")
        else:
            mode = T("rep.mode_whole") if len(summary["segments"]) <= 1 \
                else T("rep.mode_segmented", n=len(summary["segments"]))
            f.write(T("rep.mode", mode=mode) + "\n")
        if summary.get("stop_requested"):
            f.write(T("rep.state_stopped") + "\n")
        f.write("\n" + T("rep.results") + "\n")
        f.write(T("rep.n_blocks", n=summary["n_blocks"]) + "\n")
        f.write(T("rep.ok", n=summary["ok"]) + "\n")
        f.write(T("rep.slow", thr=summary["slow_thr_us"] / 1000.0,
                  n=summary["slow"]) + "\n")
        f.write(T("rep.bad", thr=summary["bad_thr_us"] / 1000.0,
                  n=summary["bad"]) + "\n")
        f.write(T("rep.read_errors", n=len(summary["error_blocks"]),
                  es=summary["errno_segments"],
                  ul=summary["unlocated_errors"]) + "\n")
        if summary["last_errno"]:
            f.write(T("rep.fio_errno", code=summary["last_errno"],
                      name=summary["last_errno_name"]) + "\n")
        if summary["unscanned_bytes"]:
            if summary["aborted"]:
                f.write(T("rep.unscanned_stopped",
                          sz=fmt_bytes(summary["unscanned_bytes"])) + "\n")
            else:
                f.write(T("rep.unscanned_failed",
                          sz=fmt_bytes(summary["unscanned_bytes"])) + "\n")
        if summary.get("unread_tail_bytes"):
            f.write(T("rep.unread_tail",
                      sz=fmt_bytes(summary["unread_tail_bytes"])) + "\n")
        f.write("\n" + T("rep.latency") + "\n")
        f.write(T("rep.median", v=summary["median_us"] / 1000.0) + "\n")
        f.write(T("rep.mean", v=summary["mean_us"] / 1000.0) + "\n")
        f.write(T("rep.p99", v=summary["p99_us"] / 1000.0) + "\n")
        f.write(T("rep.max", v=summary["max_us"] / 1000.0) + "\n")
        f.write("\n" + T("rep.elapsed") + "\n")
        f.write(T("rep.total_time", d=fmt_duration(summary["elapsed_s"])) + "\n")
        if summary["aborted"]:
            f.write(T("rep.aborted_note") + "\n")
        f.write("\n" + T("rep.threshold_note") + "\n")
        f.write(T("rep.threshold_detail") + "\n")
        f.write("\n" + T("rep.err_detail") + "\n")
        if summary["error_blocks"]:
            for idx in sorted(summary["error_blocks"]):
                f.write(T("rep.err_line", i=idx, off=fmt_bytes(idx * bs),
                          desc=summary["error_blocks"][idx]) + "\n")
        else:
            f.write(T("none") + "\n")
    files.append(p)
    return files
