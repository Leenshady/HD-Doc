# -*- coding: utf-8 -*-
"""CLI 门禁测试（模块布局：HD_Doc_cli + HD_Doc_core）。

覆盖：提权门禁各分支 + 快速扫描实扫 + --export 按需导出。
CLI 输出固定英文（cli_main 内置 set_language("en")）。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HD_DOC_LOG"] = "off"   # 运行日志隔离：不写真实配置目录

import HD_Doc_core as HC
import HD_Doc_cli as HCLI


def make_args(**kw):
    d = dict(cli=True, target=r"\\.\PhysicalDrive1", bs="4M", segment_gb=0,
             ioengine=None, no_direct=False, fio=None, limit_mb=0, offset_mb=0,
             yellow_mult=3.0, red_mult=8.0, yellow_floor_ms=10.0,
             red_floor_ms=100.0, no_elevate=False, quick=False,
             quick_sample_mb=16.0, export=None)
    d.update(kw)
    return types.SimpleNamespace(**d)


# ---- 场景 1：未提权 + --no-elevate → 报错退出码 2，不启动扫描 ----
HCLI.is_admin = lambda: False
rc = HCLI.cli_main(make_args(no_elevate=True))
print("场景1 退出码 =", rc, "(期望 2)")
assert rc == 2

# ---- 场景 2：未提权 + 自动提权 → 调用 request_elevation(wait=True) 并透传退出码 ----
calls = []


def fake_elev(argv=None, wait=False, gui=False):
    calls.append((argv, wait, gui))
    return (True, 0, None)


HCLI.request_elevation = fake_elev
rc = HCLI.cli_main(make_args())
print("场景2 退出码 =", rc, "(期望 0)；提权调用 =", calls)
assert rc == 0 and calls and calls[0][1] is True

# ---- 场景 3：未提权 + 用户取消 UAC → 退出码 2 ----
HCLI.request_elevation = lambda argv=None, wait=False, gui=False: (
    False, None, "UAC elevation confirmation cancelled by user")
rc = HCLI.cli_main(make_args())
print("场景3 退出码 =", rc, "(期望 2)")
assert rc == 2

# ---- 场景 4：未提权 + 镜像文件目标 → 不触发提权，正常进入扫描流程 ----
calls.clear()
HCLI.request_elevation = fake_elev
rc = HCLI.cli_main(make_args(target="C:/nope_missing.img"))
print("场景4 退出码 =", rc, "；提权调用次数 =", len(calls), "(期望 0)")
assert len(calls) == 0

# ---- 场景 5：已提权 → 物理磁盘直接放行 ----
HCLI.is_admin = lambda: True
calls.clear()
rc = HCLI.cli_main(make_args(target="C:/nope_missing.img"))
print("场景5 退出码 =", rc, "；提权调用次数 =", len(calls), "(期望 0)")
assert len(calls) == 0

# ---- 场景 6：快速扫描 + 已知容量镜像 → 抽样布点并实际扫描（不导出） ----
small = os.path.join("..", "fio_test", "it_small.img")
if os.path.isfile(small):
    size = HC.query_target_size(small)
    bs, segs, sample = HC.quick_scan_setup(size, HC.parse_bs("1M", size),
                                           4 * 1024 * 1024, 2 * 1024 * 1024)
    print("场景6 布点: %d 样本, 抽样 %s, 首样本 %s" % (len(segs), sample, segs[0]))
    assert len(segs) == 2 and sample == 2 * 1024 * 1024
    rc = HCLI.cli_main(make_args(target=small, bs="1M", quick=True,
                                 quick_sample_mb=2.0))
    print("场景6 退出码 =", rc, "(期望 0)")
    assert rc == 0

    # ---- 场景 7：--export → 报告写入指定目录，且为英文 ----
    import tempfile
    exp = tempfile.mkdtemp(prefix="HD_Doc_cli_gate_")
    rc = HCLI.cli_main(make_args(target=small, bs="1M", quick=True,
                                 quick_sample_mb=2.0, export=exp))
    print("场景7 退出码 =", rc, "(期望 0)")
    assert rc == 0
    dirs = [d for d in os.listdir(exp) if d.startswith("HD_Doc_report_")]
    assert dirs, "export dir should contain a report folder"
    outdir = os.path.join(exp, dirs[0])
    files = sorted(os.listdir(outdir))
    assert files == ["errors.csv", "segments.csv", "summary.txt"], files
    head = open(os.path.join(outdir, "summary.txt"),
                encoding="utf-8").read()
    assert "HD Doc Disk Error Scan Report" in head, head[:80]
    seg_head = open(os.path.join(outdir, "segments.csv"),
                    encoding="utf-8-sig").readline()
    assert seg_head.startswith("Segment,"), seg_head
    print("场景7 导出 OK（英文报告 3 文件）: %s" % outdir)
else:
    print("场景6/7 跳过（无 8MB 测试镜像）")

print("\nCLI 门禁全部场景通过")
