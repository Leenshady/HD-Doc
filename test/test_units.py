# -*- coding: utf-8 -*-
"""HD Doc 单元测试：分段对齐 / 路径规范化 / 修整逻辑（避开 shell 转义）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import HD_Doc_core as H

BS = 4 * 1024 * 1024
SIZE = 79691776  # 76 MiB 测试文件
fails = []


def check(name, got, want):
    ok = got == want
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("   got : %r" % (got,))
        print("   want: %r" % (want,))
        fails.append(name)


# ---------- plan_segments：offset 必须 bs 对齐 ----------
segs = H.plan_segments(SIZE, 26843545, BS)  # 0.025G 未对齐
check("0.025G 对齐分段", segs,
      [(0, 25165824), (25165824, 25165824), (50331648, 25165824), (75497472, 4194304)])
check("offset 全部 bs 对齐", all(o % BS == 0 for o, _ in segs), True)
check("段覆盖全盘", sum(s for _, s in segs), SIZE)

segs = H.plan_segments(SIZE, 1024 * 1024, BS)  # seg < bs
check("seg<bs 退化整盘", segs, [(0, None)])

check("整盘一次(已知容量→显式size)", H.plan_segments(SIZE, None, BS), [(0, SIZE)])
check("整盘一次(容量未知)", H.plan_segments(0, None, BS), [(0, None)])
check("无 bs 保持旧行为", H.plan_segments(SIZE, 26843545),
      [(0, 26843545), (26843545, 26843545), (53687090, 26004686)])
check("size 未知", H.plan_segments(0, 26843545, BS), [(0, None)])

# ---------- sanitize_segments ----------
check("末段过小合并",
      H.sanitize_segments([(0, 25165824), (25165824, 25165824),
                           (50331648, 25165824), (75497472, 1048576)], BS),
      [(0, 25165824), (25165824, 25165824), (50331648, 26214400)])
check("连续过小全部合并",
      H.sanitize_segments([(0, 25165824), (25165824, 1048576), (27262976, 1048576)], BS),
      [(0, 27262976)])
check("单段过小不动", H.sanitize_segments([(0, 1048576)], BS), [(0, 1048576)])
check("None 段保留", H.sanitize_segments([(0, 25165824), (25165824, None)], BS),
      [(0, 25165824), (25165824, None)])
check("空列表", H.sanitize_segments([], BS), [(0, None)])

# ---------- clamp_bs ----------
check("clamp 64M→32M", H.clamp_bs(64 << 20, 32 << 20), 32 << 20)
check("clamp 不变", H.clamp_bs(4 << 20, 76 << 20), 4 << 20)
check("clamp 无 size", H.clamp_bs(512, 0), 512)
check("clamp 1字节文件", H.clamp_bs(4 << 20, 1), 512)

# ---------- normalize_target_path（用 chr(92) 构造反斜杠，避开转义） ----------
B = chr(92)  # backslash
check("git bash 风格", H.normalize_target_path("/c/Users/x/test.img"), "C:/Users/x/test.img")
check("反斜杠绝对路径", H.normalize_target_path("C:" + B + "Users" + B + "x" + B + "test.img"),
      "C:/Users/x/test.img")
check("正斜杠绝对路径", H.normalize_target_path("C:/Users/x/test.img"), "C:/Users/x/test.img")
check("裸设备路径保留", H.normalize_target_path(B + B + "." + B + "PhysicalDrive0"),
      B + B + "." + B + "PhysicalDrive0")
check("UNC 风格裸设备保留", H.normalize_target_path("//./PhysicalDrive0"), "//./PhysicalDrive0")
check("相对路径反斜杠", H.normalize_target_path("sub" + B + "dir" + B + "file.img"),
      "sub/dir/file.img")
check("空值", H.normalize_target_path(""), "")
check("None", H.normalize_target_path(None), None)

# ---------- errno 表 ----------
check("errno 5", H.ERRNO_NAMES.get(5), "EIO 读取错误（坏块或介质故障）")
check("errno 22", H.ERRNO_NAMES.get(22), "EINVAL 参数错误（offset 未对齐或直接 IO 不支持）")

# ---------- parse_bs ----------
check("parse 4M", H.parse_bs("4M"), 4194304)
check("parse 512K", H.parse_bs("512K"), 524288)
check("parse 自动", H.parse_bs("自动", SIZE), 512 * 1024)
check("parse 自动大盘", H.parse_bs("auto", 2 * 1024 ** 4), 8 << 20)  # 2TiB/262144=8MiB
check("parse 纯数字", H.parse_bs("1048576"), 1048576)

# ---------- extract_drive_path：下拉框标签剥离（回归：1TB 盘只出 1 段的 bug） ----------
PD = B + B + "." + B + "PhysicalDrive"
LABEL = PD + "1  —  WDC WD10EZEX-22MFCA0 | 931.5 GB | ATA"
check("标签→纯净盘号", H.extract_drive_path(LABEL), PD + "1")
check("标签经 normalize", H.normalize_target_path(LABEL), PD + "1")
check("纯净盘号不变", H.extract_drive_path(PD + "1"), PD + "1")
check("normalize 幂等", H.normalize_target_path(H.normalize_target_path(LABEL)), PD + "1")
check("卷标标签", H.extract_drive_path(B + B + "." + B + "C:  —  系统 | 476 GB | ATA"),
      B + B + "." + B + "C:")
check("UNC 风格标签", H.extract_drive_path("//./PhysicalDrive2  —  SSD | 1 TB | NVMe"),
      "//./PhysicalDrive2")
check("带引号标签", H.extract_drive_path('"' + LABEL + '"'), PD + "1")
check("空串", H.extract_drive_path(""), "")
check("None", H.extract_drive_path(None), None)
# 普通文件路径（含空格/竖线）绝不能被截断——它们不是设备路径
check("文件路径含空格不截断",
      H.extract_drive_path("C:/Users/my dir/a b.img"), "C:/Users/my dir/a b.img")
check("文件路径含竖线不截断",
      H.extract_drive_path("C:/data/weird|name.img"), "C:/data/weird|name.img")
check("文件路径 normalize 含空格",
      H.normalize_target_path("C:" + B + "my dir" + B + "a b.img"), "C:/my dir/a b.img")

# ---------- 1TB 机械盘 4G 分段计划（用户实际场景） ----------
HDD_1TB = 1000204886016  # 实测 WD WD10EZEX 931.5 GB
segs_1t = H.sanitize_segments(H.plan_segments(HDD_1TB, 4 << 30, 4 << 20), 4 << 20)
check("1TB/4G 段数=233", len(segs_1t), 233)
check("1TB 段 offset 全部 4MiB 对齐", all(o % (4 << 20) == 0 for o, _ in segs_1t), True)
check("1TB 段覆盖全盘", sum(s for _, s in segs_1t), HDD_1TB)
check("1TB 首段 4GiB", segs_1t[0], (0, 4294967296))
check("1TB 末段合并后>=4MiB", segs_1t[-1][1] >= 4 << 20, True)
check("1TB 每段大小>=bs", all(s >= (4 << 20) for _, s in segs_1t), True)
# 自动块大小下的 1TB 分段（GUI 默认"自动"）
bs_auto = H.parse_bs("auto", HDD_1TB)
check("1TB 自动块大小=4MiB", bs_auto, 4 << 20)
segs_auto = H.sanitize_segments(H.plan_segments(HDD_1TB, 4 << 30, bs_auto), bs_auto)
check("1TB 自动块大小段数=233", len(segs_auto), 233)
# 容量未知时（bug 场景）必须仍然退化为单段但由 GUI/CLI 预警
check("容量未知退化为单段", H.plan_segments(None, 4 << 30, 4 << 20), [(0, None)])

# ---------- plan_quick_segments：快速扫描抽样布点 ----------
G = 1024 ** 3
q_segs = H.plan_quick_segments(HDD_1TB, 4 * G, 16 << 20, 4 << 20)
check("快速扫描区域数=117（4G×233 超上限，放大到 8G）", len(q_segs), 117)
check("快速扫描区域跨度 8GiB", q_segs[1][0] - q_segs[0][0], 8 * G)
check("快速扫描每区抽样 16MiB", q_segs[0][1], 16 << 20)
check("快速扫描 offset 全部 bs 对齐", all(o % (4 << 20) == 0 for o, _ in q_segs), True)
check("快速扫描末区不越界", q_segs[-1][0] + q_segs[-1][1] <= HDD_1TB, True)
check("快速扫描覆盖 117×16MiB", sum(s for _, s in q_segs), 117 * (16 << 20))
check("快速扫描容量未知退化为整盘", H.plan_quick_segments(0, 4 * G, 16 << 20, 4 << 20),
      [(0, None)])
q_small = H.plan_quick_segments(64 << 20, None, 16 << 20, 4 << 20)
check("快速扫描无分段参数时区域不小于块大小", len(q_small), 16)
check("快速扫描区域=块大小（64MiB/16 区被 bs 兜底）", q_small[0][1], 4 << 20)
q_tiny = H.plan_quick_segments(8 << 20, None, 64 << 20, 1 << 20)
check("快速扫描抽样不超过磁盘", sum(s for _, s in q_tiny), 8 << 20)
q_last = H.plan_quick_segments(100 << 20, 40 << 20, 30 << 20, 1 << 20)
check("快速扫描末区样本截到剩余 20MiB", q_last[-1][1], 20 << 20)
check("快速扫描末区偏移 80MiB", q_last[-1][0], 80 << 20)
# 块大小大于抽样大小时，quick_scan_setup 缩小块大小而非放大抽样
_bs2, _segs2, _samp2 = H.quick_scan_setup(HDD_1TB, 64 << 20, 4 * G, 16 << 20)
check("quick_scan_setup 块大小缩到抽样大小", _bs2, 16 << 20)
check("quick_scan_setup 抽样仍 16MiB", _samp2, 16 << 20)
check("quick_scan_setup 容量未知退化", H.quick_scan_setup(0, 4 << 20, 4 * G, 0),
      (4 << 20, [(0, None)], 0))

# ---------- expected_io_count：停止扫描误报磁盘错误的根因修复 ----------
# fio 对不足一个块的尾巴：512 对齐会读（文件 6.5MB/1M → 7 次 IO），
# 不对齐直接跳过（物理盘尾 13.69MB/1M → 13 次 IO）。expected 必须用
# floor：用 ceil 会把盘尾余数误判成"未扫描"假错误块并弹"物理损伤风险"。
M = 1 << 20
check("预期IO: 整数块无尾巴", H.expected_io_count(16 * M, 0, None, M), (16, 0))
check("预期IO: 不对齐尾巴按 floor（物理盘尾场景）",
      H.expected_io_count(13 * M + 723517, 0, None, M), (13, 723517))
check("预期IO: 文件部分块场景 expected=floor（actual 可为 7>6，不算错）",
      H.expected_io_count(6 * M + 524288, 0, None, M), (6, 524288))
# 段超出设备末尾时按设备大小截断（快速扫描末区 / --limit-mb 越界）
check("预期IO: 段越界截断到设备大小",
      H.expected_io_count(16 * M, 100 * M, 108 * M, M), (8, 0))
check("预期IO: 段整个在设备外 → 0",
      H.expected_io_count(16 * M, 200 * M, 108 * M, M), (0, 0))
# size=None（读到设备末尾）：已知容量按 total-off 推算
check("预期IO: size=None 已知容量按剩余空间",
      H.expected_io_count(None, 100 * M, 108 * M, M), (8, 0))
check("预期IO: size=None 容量未知退化为段内实际读数",
      H.expected_io_count(None, 0, None, M, 5 * M), (5, 0))
check("预期IO: 全零输入", H.expected_io_count(0, 0, None, M), (0, 0))

# ---------- plan_grid：热力图自适应平铺 ----------
W, HH = 1100, 700
_g = lambda n: H.plan_grid(W, HH, n)
pitch, cols, rows, ox, oy = _g(19)
check("自适应: 格子远大于旧固定 6px", pitch > 20, True)
check("自适应: 行列覆盖全部格子", cols * rows >= 19, True)
check("自适应: 不超出画布宽度", ox + cols * pitch <= W + 1e-6, True)
check("自适应: 不超出画布高度", oy + rows * pitch <= HH + 1e-6, True)
check("自适应: 水平居中偏移非负", ox >= 0, True)
check("自适应: 段少时格子封顶 40px", _g(4)[0], H.CELL_SIZE_MAX)
check("自适应: 段多时格子更小(233→封顶、1862→更小)",
      (_g(233)[0], _g(1862)[0] < _g(19)[0]), (H.CELL_SIZE_MAX, True))
check("自适应: 1TB 盘 4G 分段(233 段) 27 列 x 9 行",
      (_g(233)[1], _g(233)[2]), (27, 9))
check("自适应: 极端段数(5000)仍全部可见", _g(5000)[1] * _g(5000)[2] >= 5000, True)
check("自适应: 极端段数不超出画布高度(oy 偏移)",
      _g(5000)[4] + _g(5000)[2] * _g(5000)[0] <= HH + 1e-6, True)
check("自适应: 1 段时单行", _g(1)[2], 1)
check("自适应: 宽画布下列数更多",
      H.plan_grid(2000, 400, 20)[1] > H.plan_grid(400, 2000, 20)[1], True)

# ---------- 热力图固定格数：UI 一致性（任何容量/分段都是同样多的格） ----------
check("固定格数常量", H.MAP_CELLS, 256)
check("固定格数平铺后全覆盖",
      H.plan_grid(1100, 350, H.MAP_CELLS)[1] * H.plan_grid(1100, 350, H.MAP_CELLS)[2]
      >= H.MAP_CELLS, True)
check("固定格数不超出画布",
      H.plan_grid(1100, 350, H.MAP_CELLS)[4]
      + H.plan_grid(1100, 350, H.MAP_CELLS)[2] * H.plan_grid(1100, 350, H.MAP_CELLS)[0]
      <= 350 + 1e-6, True)

# ---------- weighted_median：段统计聚合进格（按块数加权） ----------
check("加权中位数: 空列表", H.weighted_median([]), None)
check("加权中位数: 权重全 0", H.weighted_median([(100.0, 0)]), None)
check("加权中位数: 单值", H.weighted_median([(2200.0, 1024)]), 2200.0)
check("加权中位数: 零权重项被忽略",
      H.weighted_median([(999.0, 0), (2200.0, 4)]), 2200.0)
check("加权中位数: 大权重决定中位",
      H.weighted_median([(2200.0, 9), (9000.0, 1)]), 2200.0)
check("加权中位数: 反向权重", H.weighted_median([(2200.0, 1), (9000.0, 9)]), 9000.0)
check("加权中位数: 等权取较低中位",
      H.weighted_median([(2200.0, 1), (2400.0, 1)]), 2200.0)

# ---------- seg_cell_span / block_cell_index：段与块 → 格 的字节映射 ----------
N = H.MAP_CELLS
check("段跨度: 8MB 盘首段占一半格", H.seg_cell_span(0, 4 << 20, 8 << 20, N),
      (0, 127))
check("段跨度: 8MB 盘第二段", H.seg_cell_span(4 << 20, 4 << 20, 8 << 20, N),
      (128, 255))
check("段跨度: 小段少格（1MB/8MB → 32 格）",
      H.seg_cell_span(0, 1 << 20, 8 << 20, N), (0, 31))
check("段跨度: 容量未知 → 广播", H.seg_cell_span(0, None, None, N), None)
check("段跨度: 读到末尾覆盖到末格",
      H.seg_cell_span(4 << 20, None, 8 << 20, N), (128, 255))
check("段跨度: 越界钳制到末格", H.seg_cell_span(100 << 20, 4 << 20, 8 << 20, N),
      (255, 255))
check("块→格: 首块", H.block_cell_index(0, 1 << 20, 8 << 20, N), 0)
check("块→格: 中间块(5MB/8MB)", H.block_cell_index(5, 1 << 20, 8 << 20, N), 160)
check("块→格: 末块(7MB/8MB)", H.block_cell_index(7, 1 << 20, 8 << 20, N), 224)
check("块→格: 越界钳制末格", H.block_cell_index(99, 1 << 20, 8 << 20, N), 255)
check("块→格: 容量未知 → 广播", H.block_cell_index(5, 1 << 20, None, N), None)
check("块→格: 块大小未知 → 广播", H.block_cell_index(5, 0, 8 << 20, N), None)
# 1TB 盘 4G 分段（用户实际场景）：233 段全部落进 256 格、无越界
_seg1t = H.sanitize_segments(H.plan_segments(HDD_1TB, 4 << 30, 4 << 20), 4 << 20)
_spans = [H.seg_cell_span(o, s, HDD_1TB, N) for o, s in _seg1t]
check("1TB/4G: 每段都映射到合法格区间",
      all(a is not None and 0 <= a <= b < N for a, b in _spans), True)
check("1TB/4G: 首段从第 0 格起", _spans[0][0], 0)
check("1TB/4G: 末段到第 255 格止", _spans[-1][1], N - 1)
check("1TB/4G: 格全覆盖（段跨度并集覆盖全部格）",
      sum(b - a + 1 for a, b in _spans) >= N, True)

# ---------- 快速扫描按区域跨度点亮：区域跨度必须铺满全部格 ----------
# 用户实际场景（931.5GB 盘、4G 分段、16MB 抽样、4MB 块，见运行日志）：
# 117 个区域每区只读开头 16MB。若按抽样大小点亮，16MB 只覆盖约 1 格
# （每格 3.9GB）→ 约 117/256 格有数据、其余永久灰（"有的块保持灰色"）；
# 按区域跨度点亮（区域才是取样单位）则整盘铺满、无灰格。
_qcov = set()
for _i, (_o, _s) in enumerate(q_segs):
    _nxt = q_segs[_i + 1][0] if _i + 1 < len(q_segs) else HDD_1TB
    _a, _b = H.seg_cell_span(_o, _nxt - _o, HDD_1TB, N)
    _qcov.update(range(_a, _b + 1))
check("快速扫描: 区域跨度铺满全部 256 格（无永久灰格）", len(_qcov), N)
_scov = set()
for _o, _s in q_segs:      # 反证：只按抽样大小点亮确实会露灰
    _a, _b = H.seg_cell_span(_o, _s, HDD_1TB, N)
    _scov.update(range(_a, _b + 1))
check("快速扫描: 抽样大小仅覆盖少部分格（修复前灰格来源）",
      len(_scov) < N, True)

# ---------- 热力图颜色：四档（正常/偏慢/读取错误/未扫描），很慢档已取消 ----------
# 读取错误必须是红色系；与偏慢金黄必须一眼可辨。
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def _hue(c):
    r, g, b = [x / 255.0 for x in c]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return None
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60

def _pair_gap(c1, c2):
    a, b = _rgb(c1), _rgb(c2)
    dist = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    h1, h2 = _hue(a), _hue(b)
    gap = (min(abs(h1 - h2), 360 - abs(h1 - h2))
           if h1 is not None and h2 is not None else 180.0)
    return dist, gap

# "很慢"档取消：常量与状态键都不应再存在
check("COLOR_BAD 常量已移除", hasattr(H, "COLOR_BAD"), False)
check("STATUS_TEXT 无很慢键", "bad" in H.STATUS_TEXT, False)
check("图例状态键四档", sorted(H.STATUS_TEXT), ["error", "ok", "pending", "slow"])
# 读取错误 = 红色系（色相落在红区，或极接近无彩色边界不算）
_err_hue = _hue(_rgb(H.COLOR_ERROR))
check("读取错误为红色系(色相<15°或>345°)",
      _err_hue is not None and (_err_hue < 15 or _err_hue > 345), True)
# 偏慢 vs 读取错误必须可辨（回归：旧橙红/暗红距离仅 70、色相差 15°）
_dist, _gap = _pair_gap(H.COLOR_SLOW, H.COLOR_ERROR)
check("偏慢 vs 读取错误 RGB 距离 > 40", _dist > 40, True)
check("偏慢 vs 读取错误 色相差 > 8°", _gap > 8, True)
# 其余相邻档也要可辨（正常/偏慢 + 读取错误/未扫描）
for _a, _b, _n in ((H.COLOR_OK, H.COLOR_SLOW, "正常vs偏慢"),
                   (H.COLOR_ERROR, H.COLOR_PENDING, "错误vs未扫描")):
    d, g = _pair_gap(_a, _b)
    check("相邻档可辨(%s): RGB 距离 > 40" % _n, d > 40, True)
    check("相邻档可辨(%s): 色相差 > 8°" % _n, g > 8, True)

# ---------- _console_encoding：终端编码自适应 ----------
_saved_msys = os.environ.pop("MSYSTEM", None)
try:
    if H.IS_WIN:
        os.environ["MSYSTEM"] = "MINGW64"
        check("控制台编码: Git Bash 环境识别为 UTF-8",
              H._console_encoding(), "utf-8")
        os.environ.pop("MSYSTEM", None)
    # 无 MSYSTEM 时：管道/重定向 → utf-8；真控制台 → mbcs（两者都合法）
    check("控制台编码: 无 MSYSTEM 时返回受支持编码",
          H._console_encoding() in ("mbcs", "utf-8"), True)
finally:
    if _saved_msys is not None:
        os.environ["MSYSTEM"] = _saved_msys

# ---------- IO 引擎可用性（libaio/posixaio 在 Windows 不存在） ----------
check("平台引擎列表不含 libaio",
      "libaio" in H.platform_engines() and H.IS_WIN, False)
check("平台引擎列表不含 posixaio",
      "posixaio" in H.platform_engines() and H.IS_WIN, False)
check("Windows 引擎列表", H.platform_engines() if H.IS_WIN else ["跳过"],
      ["windowsaio", "sync", "psync"] if H.IS_WIN else ["跳过"])
check("引擎名正则匹配", bool(H.ENGINE_NAME_RE.match("windowsaio")), True)
check("引擎名正则拒绝带点", bool(H.ENGINE_NAME_RE.match("a.b")), False)
check("引擎名正则拒绝大写", bool(H.ENGINE_NAME_RE.match("WindowsAIO")), False)
# 真实 fio 探测（环境无 fio 时返回 None，测试放行）
_engines = H.list_fio_engines("C:/Program Files/fio/fio.exe")
if _engines is not None:
    check("实测 fio 引擎含 windowsaio", "windowsaio" in _engines, True)
    check("实测 fio 引擎含 sync", "sync" in _engines, True)
    check("实测 fio 引擎含 psync", "psync" in _engines, True)
    check("实测 fio 引擎不含 libaio（Windows 构建）",
          "libaio" in _engines and H.IS_WIN, False)
    check("实测 fio 引擎不含 posixaio（Windows 构建）",
          "posixaio" in _engines and H.IS_WIN, False)
    check("实测 fio 引擎探测返回 set", isinstance(_engines, set), True)
else:
    print("  [跳过] 环境无 fio，跳过引擎实测")
check("不存在的 fio 探测返回 None", H.list_fio_engines("Z:/nope/fio.exe"), None)

# ---------- Linux 设备枚举（Ubuntu GUI 运行适配） ----------
class _FakeStat:
    """假 stat 结果：只带 st_mode（测试 is_physical_target 的设备类型分支）"""
    def __init__(self, mode):
        self.st_mode = mode


_LSBLK_JSON = """{
  "blockdevices": [
    {"name": "sda", "size": 1000204886016, "model": "WDC WD10EZEX-22MFCA0", "tran": "sata"},
    {"name": "nvme0n1", "size": 500107862016, "model": "Samsung SSD 980", "tran": "nvme"},
    {"name": "sdb", "size": "0", "model": null, "tran": "usb"}
  ]
}"""
_d = H._parse_lsblk_json(_LSBLK_JSON)
check("lsblk 解析: 三块盘", len(_d), 3)
check("lsblk 解析: sda 容量", _d[0]["size"], 1000204886016)
check("lsblk 解析: sda 型号", _d[0]["model"], "WDC WD10EZEX-22MFCA0")
check("lsblk 解析: nvme 总线", _d[1]["tran"], "nvme")
check("lsblk 解析: size=0 → None（伪设备/异常输出）", _d[2]["size"], None)
check("lsblk 解析: model 空 → None", _d[2]["model"], None)
check("lsblk 解析: 坏 JSON → []", H._parse_lsblk_json("{not json"), [])
check("lsblk 解析: 空输出 → []", H._parse_lsblk_json(""), [])
check("lsblk 解析: 无 blockdevices → []",
      H._parse_lsblk_json('{"blockdevices": []}'), [])
check("lsblk 解析: 无 name 跳过",
      H._parse_lsblk_json('{"blockdevices": [{"size": 100}]}'), [])

# list_drives 的 Linux 分支：patch IS_WIN + _linux_list_drives，验证透传
import unittest.mock as _mock
try:
    _saved_win = H.IS_WIN
    H.IS_WIN = False
    with _mock.patch.object(H, "_linux_list_drives",
                            return_value=[{"index": 0, "path": "/dev/sda",
                                           "size": 999, "model": "M1", "bus": "sata"},
                                          {"index": 1, "path": "/dev/nvme0n1",
                                           "size": 500, "model": "M2", "bus": "nvme"}]):
        _ld = H.list_drives()
    check("list_drives(Linux) 透传枚举结果", _ld,
          [{"index": 0, "path": "/dev/sda", "size": 999, "model": "M1", "bus": "sata"},
           {"index": 1, "path": "/dev/nvme0n1", "size": 500, "model": "M2", "bus": "nvme"}])
    # is_physical_target：Linux 上 /dev/ 块设备算物理盘（触发 root 检查）
    check("物理磁盘识别(Linux /dev/sda)", H.is_physical_target("/dev/sda"), True)
    check("物理磁盘识别(Linux /dev/nvme0n1)", H.is_physical_target("/dev/nvme0n1"), True)
    check("物理磁盘识别(Linux 普通文件)", H.is_physical_target("/home/u/test.img"), False)
    check("物理磁盘识别(Linux /tmp)", H.is_physical_target("/tmp"), False)
    with _mock.patch.object(H.os, "stat",
                            side_effect=lambda p: _FakeStat(0o020000)):  # S_IFCHR
        check("物理磁盘识别(Linux /dev/null 字符设备不算)",
              H.is_physical_target("/dev/null"), False)
    with _mock.patch.object(H.os, "stat",
                            side_effect=lambda p: _FakeStat(0o060000)):  # S_IFBLK
        check("物理磁盘识别(Linux 块设备)",
              H.is_physical_target("/dev/sda"), True)
    # query_target_size：Linux 块设备 st_size 恒 0，必须 lseek(SEEK_END)
    with _mock.patch.object(H.os, "open", return_value=7), \
         _mock.patch.object(H.os, "lseek", return_value=1000204886016), \
         _mock.patch.object(H.os, "close"):
        check("块设备容量走 lseek(SEEK_END)",
              H.query_target_size("/dev/sda"), 1000204886016)
    with _mock.patch.object(H.os, "open", side_effect=OSError("EPERM")):
        check("块设备打不开时容量 None", H.query_target_size("/dev/sda"), None)
    # request_elevation gui=True：同步 sudo 会卡死 GUI，必须异步 pkexec
    _popen_calls = []
    with _mock.patch("shutil.which", return_value="/usr/bin/pkexec"), \
         _mock.patch.object(H.subprocess, "Popen",
                            side_effect=lambda cmd, **kw: _popen_calls.append(
                                (cmd, kw)) or None), \
         _mock.patch.object(H.os, "geteuid", return_value=1000, create=True), \
         _mock.patch.dict(H.os.environ, {"DISPLAY": ":0",
                                         "XAUTHORITY": "/run/user/1000/.Xauthority"}):
        _ok, _code, _err = H.request_elevation(wait=False, gui=True,
                                               argv=["HD_Doc.py"])
    check("GUI 提权走 pkexec", _ok, True)
    check("pkexec 命令已构造", len(_popen_calls), 1)
    if _popen_calls:
        _cmd, _kw = _popen_calls[0]
        check("pkexec 命令行", _cmd[0], "/usr/bin/pkexec")
        check("pkexec env 透传 DISPLAY", "DISPLAY=:0" in _cmd, True)
        check("pkexec env 透传 XAUTHORITY",
              "XAUTHORITY=/run/user/1000/.Xauthority" in _cmd, True)
        check("pkexec 目标为绝对路径脚本",
              any(a.endswith("HD_Doc.py") and os.path.isabs(a) for a in _cmd), True)
        check("pkexec 异步启动(不等待子进程)",
              _kw.get("start_new_session"), True)
    with _mock.patch.object(H.os, "geteuid", return_value=1000, create=True), \
         _mock.patch("shutil.which", return_value=None):
        _ok2, _c2, _err2 = H.request_elevation(wait=False, gui=True,
                                               argv=["HD_Doc.py"])
    check("无 pkexec 时报错", (_ok2, "pkexec" in (_err2 or "")), (False, True))
    with _mock.patch.object(H.os, "geteuid", return_value=0, create=True):
        check("已是 root 直接放行", H.request_elevation(gui=True)[0], True)
finally:
    H.IS_WIN = _saved_win

# ---------- 管理员权限检测 ----------
check("物理磁盘路径识别(反斜杠)", H.is_physical_target(B + B + "." + B + "PhysicalDrive1"), True)
check("物理磁盘路径识别(正斜杠)", H.is_physical_target("//./PhysicalDrive0"), True)
check("物理磁盘路径识别(裸名)", H.is_physical_target("PhysicalDrive1"), True)
check("物理磁盘路径识别(大小写/多位)", H.is_physical_target("physicaldrive12"), True)
check("物理磁盘路径识别(带空格)", H.is_physical_target("  PhysicalDrive1  "), True)
check("镜像文件不是物理磁盘", H.is_physical_target("C:/Users/x/test.img"), False)
check("普通路径不是物理磁盘", H.is_physical_target("D:/data"), False)
check("PhysicalDrive 后缀非数字", H.is_physical_target("PhysicalDriveX"), False)
check("is_admin 返回布尔值", isinstance(H.is_admin(), bool), True)
check("默认允许自动提权", H.auto_elevate_enabled(), True)
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "1"
check("环境变量关闭自动提权", H.auto_elevate_enabled(), False)
os.environ["HDTUNE_NO_AUTO_ELEVATE"] = "0"
check("环境变量=0 仍允许", H.auto_elevate_enabled(), True)
del os.environ["HDTUNE_NO_AUTO_ELEVATE"]
check("删除环境变量后恢复", H.auto_elevate_enabled(), True)

# ---------- 提权重启目标：pythonw.exe（避免命令窗口） ----------
pw = H._pythonw_path()
check("_pythonw_path 返回 pythonw.exe 或 None",
      pw is None or os.path.basename(pw).lower() == "pythonw.exe", True)
if pw:
    check("_pythonw_path 文件真实存在", os.path.isfile(pw), True)
exe, params = H._elevation_target()
if pw:
    check("提权目标用 pythonw.exe（无控制台窗口）",
          os.path.basename(exe).lower(), "pythonw.exe")
check("提权参数含脚本路径", os.path.basename(sys.argv[0]) in params, True)
exe_g, _params_g = H._elevation_target(gui=True)
if pw:
    check("GUI 提权同样用 pythonw.exe",
          os.path.basename(exe_g).lower(), "pythonw.exe")
check("_cli_bind_parent_console 无握手环境变量时为 no-op",
      H._cli_bind_parent_console(), False)
os.environ.pop("HDTUNE_ATTACH_PARENT_CONSOLE", None)

# ---------- i18n：默认英文、可切中文、占位符、键集合一致 ----------
import json as _json

os.environ.pop("HDTUNE_LANG", None)   # 排除测试环境的临时覆盖
H.set_language("en")                  # 显式置英，排除本机配置干扰
_langdir = H._lang_dir()
with open(os.path.join(_langdir, "en.json"), encoding="utf-8") as _f:
    _en_file = _json.load(_f)
with open(os.path.join(_langdir, "zh.json"), encoding="utf-8") as _f:
    _zh_file = _json.load(_f)
check("默认语言为英文", H.get_language(), "en")
check("tr 取英文", H.tr("rep.target", t="X"), "Target: X")
check("status_text 英文", H.status_text("ok"), "OK")
check("errno_name 英文", H.errno_name(5), "EIO read error (bad block or media failure)")
check("bus_type_name 专有名词不翻译", H.bus_type_name(11), "SATA")
check("bus_type_name 通用项英文", H.bus_type_name(16), "Storage Spaces")
check("tr_list CSV 表头英文", H.tr_list("rep.csv_seg_header", _lang="en")[0], "Segment")
check("tr 指定语言参数", H.tr("rep.target", _lang="zh", t="X"), "目标: X")
check("tr 占位符含 % 不乱码", "%.2f" in H.tr("rep.mode_quick", n=1, cov="1 GB",
                                            pct=0.2) or "%" in H.tr("rep.mode_quick",
                                                                   n=1, cov="1 GB", pct=0.2), True)
check("缺失键回退键名", H.tr("no.such.key"), "no.such.key")
check("两种语言键集合一致（lang/*.json）",
      set(_en_file) == set(_zh_file), True)
check("运行时表与 en.json 一致（_meta 已剔除）",
      set(H._I18N["en"]) == set(_en_file) - {"_meta"}, True)
check("运行时表与 zh.json 一致（_meta 已剔除）",
      set(H._I18N["zh"]) == set(_zh_file) - {"_meta"}, True)
check("语言目录为 lang/", os.path.basename(H._lang_dir()), "lang")
check("LANGUAGES 由 lang/*.json 推导（默认语言优先）",
      H.LANGUAGES, ("en", "zh"))
check("available_languages 给出菜单用的自称",
      dict(H.available_languages()), {"en": "English", "zh": "中文"})
check("set_language 拒绝未安装码", H.set_language("fr"), False)
check("set_language 接受 zh", H.set_language("zh"), True)
check("切换后 get_language=zh", H.get_language(), "zh")
check("tr 中文", H.tr("rep.target", t="X"), "目标: X")
check("errno_name 中文", H.errno_name(22),
      "EINVAL 参数错误（offset 未对齐或直接 IO 不支持）")
check("bus_type_name 中文", H.bus_type_name(16), "存储空间")
check("恢复英文", H.set_language("en"), True)
check("恢复后 get_language=en", H.get_language(), "en")

# ---------- 语言自动发现：放个 JSON 即新语言，零代码改动 ----------
import shutil as _shutil
import tempfile as _tempfile

_tmp = _tempfile.mkdtemp(prefix="HD_Doc_lang_")
try:
    _shutil.copy(os.path.join(_langdir, "en.json"),
                 os.path.join(_tmp, "en.json"))
    # 新语言：自带 _meta 自称 + 一条翻译，其余键缺失（应回退英文）
    with open(os.path.join(_tmp, "ja.json"), "w", encoding="utf-8") as _f:
        _json.dump({"_meta": {"name": "日本語"},
                    "rep.target": "目標: {t}"}, _f)
    # 无 _meta 的文件：自称退化为语言码
    with open(os.path.join(_tmp, "de.json"), "w", encoding="utf-8") as _f:
        _json.dump({"rep.target": "Ziel: {t}"}, _f)
    # 下划线开头 = 模板/草稿，不应被发现
    with open(os.path.join(_tmp, "_template.json"), "w", encoding="utf-8") as _f:
        _json.dump({"_meta": {"name": "x"}}, _f)
    # 损坏文件：告警跳过，不影响其他语言
    with open(os.path.join(_tmp, "broken.json"), "w", encoding="utf-8") as _f:
        _f.write("{ not json")
    _orig_dir, _orig_i18n, _orig_names = (H._lang_dir, H._I18N, H._LANG_NAMES)
    H._lang_dir = lambda: _tmp
    try:
        _tables, _names = H._load_languages()
        check("自动发现新语言 ja/de（未改任何代码）",
              {"ja", "de"} <= set(_tables), True)
        check("模板文件 _template.json 被跳过", "_template" in _tables, False)
        check("损坏文件被跳过", "broken" in _tables, False)
        check("_meta 不进文案表", "_meta" in _tables.get("ja", {}), False)
        check("自称取自 _meta.name", _names.get("ja"), "日本語")
        check("缺失 _meta 时自称退化为码", _names.get("de"), "de")
        # 换上临时注册表：菜单/校验/翻译全部跟着变
        H._I18N, H._LANG_NAMES = _tables, _names
        check("available_languages 动态含新语言",
              dict(H.available_languages()).get("ja"), "日本語")
        check("set_language 接受新语言", H.set_language("ja"), True)
        check("tr 用新语言译文", H.tr("rep.target", t="X"), "目標: X")
        check("新语言缺键回退英文", H.tr("rep.mode_full"),
              H.tr("rep.mode_full", _lang="en"))
        check("菜单顺序：默认优先其余按码序",
              [c for c, _ in H.available_languages()], ["en", "de", "ja"])
    finally:
        H._lang_dir, H._I18N, H._LANG_NAMES = (_orig_dir, _orig_i18n,
                                               _orig_names)
        H.set_language("en")   # 还原进程内语言
finally:
    _shutil.rmtree(_tmp, ignore_errors=True)
# 英文分段值解析（GUI 英文下拉）
check("parse_segment_size 英文整盘", H.parse_segment_size("Whole disk at once (fastest)"), None)
check("parse_segment_size 中文整盘", H.parse_segment_size("整盘一次（最快）"), None)
check("parse_segment_size 4G", H.parse_segment_size("4G"), 4 * 1024 ** 3)

# ---------- 运行日志：单文件、上限截断、开关、异常堆栈 ----------
_log_tmp = _tempfile.mkdtemp(prefix="HD_Doc_log_")
try:
    _orig_log_dir = os.environ.get("HD_DOC_LOG_DIR")
    _orig_log_sw = os.environ.get("HD_DOC_LOG")
    os.environ["HD_DOC_LOG_DIR"] = _log_tmp
    os.environ["HD_DOC_LOG"] = "1"
    check("run_log_path 指向覆盖目录",
          H.run_log_path(), os.path.join(_log_tmp, "HD_Doc.log"))
    check("log_event 写入成功", H.log_event("unit test line"), True)
    _txt = open(H.run_log_path(), encoding="utf-8").read()
    check("日志含消息正文", "unit test line" in _txt, True)
    check("日志格式含时间戳与级别",
          _txt.startswith("20") and "[INFO]" in _txt, True)
    # 超过上限 → 整文件截断重写（旧内容丢弃），目录里始终只有一个文件
    with open(H.run_log_path(), "w", encoding="utf-8") as _f:
        _f.write("x" * (H.LOG_MAX_BYTES + 16))
    H.log_event("after truncate")
    _txt2 = open(H.run_log_path(), encoding="utf-8").read()
    check("超限后截断重写（旧内容丢弃、不超上限）",
          "after truncate" in _txt2 and len(_txt2) < H.LOG_MAX_BYTES, True)
    check("目录下始终只有一份日志", os.listdir(_log_tmp), ["HD_Doc.log"])
    # 异常堆栈（含上下文与类型）
    try:
        raise ValueError("boom")
    except ValueError:
        check("log_exception 记录堆栈", H.log_exception("unit ctx"), True)
    _txt3 = open(H.run_log_path(), encoding="utf-8").read()
    check("堆栈含上下文与异常类型",
          "unit ctx" in _txt3 and "ValueError: boom" in _txt3, True)
    # HD_DOC_LOG=off 整体关闭
    os.environ["HD_DOC_LOG"] = "off"
    check("HD_DOC_LOG=off 时不写盘", H.log_event("should not appear"), False)
    _txt4 = open(H.run_log_path(), encoding="utf-8").read()
    check("关闭后日志内容不变", "should not appear" in _txt4, False)
    # 路径不可写时静默失败（日志绝不拖垮主流程）
    os.environ["HD_DOC_LOG"] = "1"
    os.environ["HD_DOC_LOG_DIR"] = os.path.join(_log_tmp, "HD_Doc.log")
    check("日志路径不可写时静默失败", H.log_event("x"), False)
finally:
    if _orig_log_dir is None:
        os.environ.pop("HD_DOC_LOG_DIR", None)
    else:
        os.environ["HD_DOC_LOG_DIR"] = _orig_log_dir
    if _orig_log_sw is None:
        os.environ.pop("HD_DOC_LOG", None)
    else:
        os.environ["HD_DOC_LOG"] = _orig_log_sw
    _shutil.rmtree(_log_tmp, ignore_errors=True)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
