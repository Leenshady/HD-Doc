#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_icon.py —— 生成 HD Doc 应用图标（PIL 绘制，结果可复现）

用法:
    python make_icon.py            # 需要 Pillow：pip install Pillow

产出:
    img/HD_Doc.png                          1024x1024 主图（窗口/关于弹窗）
    img/HD_Doc.ico                          多分辨率 Windows 图标（exe --icon）
    img/icons/hicolor/<N>x<N>/apps/hd-doc.png  Linux 桌面图标（48/64/128/256/512）

设计：圆角方形蓝→青渐变底 + 硬盘盘片（同心圆环）+ 读写臂 + 延迟脉搏线。
脉搏线取界面"正常"档绿色 #5DCAA5，与热力图四档图例呼应；深蓝/青底色
与原配色一致。纯代码绘制、不依赖外部素材——改设计只改这里再重跑。

说明：Ubuntu 上"应用图标跟设置图标一样"的反馈，一部分原因是图标只在
256x256 单尺寸安装、GNOME 程序坞找不到匹配的 .desktop（显示默认齿轮状
兜底图标）。这里一次产出全套 hicolor 尺寸，install.sh 会全部安装并
gtk-update-icon-cache；同时换一个明确的磁盘主题图标，避免与任何系统
内置图标混淆。
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024            # 成品边长
SS = 4              # 超采样倍数（边缘抗锯齿）

BG_TOP = (23, 62, 111)       # #173E6F 深蓝（渐变顶）
BG_BOT = (30, 140, 134)      # #1E8C86 青（渐变底）
PLATTER = (13, 43, 74)       # #0D2B4A 盘片底面
PLATTER_IN = (22, 69, 111)   # #16456F 盘片内圈
RING = (62, 198, 184)        # #3EC6B8 盘片外环
TRACK = (96, 176, 210)       # 盘面磁道弧（浅蓝）
ARM = (159, 232, 221)        # #9FE8DD 读写臂
HEAD = (13, 43, 74)          # 磁头（深色）
PULSE = (93, 202, 165)       # #5DCAA5 脉搏线（= 界面"正常"色）

HICOLOR_SIZES = (512, 256, 128, 64, 48)


def draw_master():
    """4× 超采样绘制，返回 1024×1024 RGBA 图"""
    n = S * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    # ---- 1. 蓝→青渐变圆角方底 ----
    grad = Image.new("RGBA", (n, n))
    gd = ImageDraw.Draw(grad)
    for y in range(n):
        t = y / (n - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t)
                  for i in range(3)) + (255,)
        gd.line([(0, y), (n, y)], fill=c)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, n - 1, n - 1], radius=int(n * 0.223), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # ---- 2. 硬盘盘片（中心略偏上）----
    cx, cy, r = n * 0.500, n * 0.455, n * 0.285
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PLATTER + (255,))
    rt = r * 0.80                                   # 磁道弧（两段）
    for a0, a1 in ((18, 150), (210, 342)):
        d.arc([cx - rt, cy - rt, cx + rt, cy + rt],
              start=a0, end=a1, fill=TRACK + (255,),
              width=int(n * 0.011))
    r2 = r * 0.895                                  # 外环
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2],
              outline=RING + (255,), width=int(n * 0.022))
    r3 = r * 0.66                                   # 内圈
    d.ellipse([cx - r3, cy - r3, cx + r3, cy + r3],
              fill=PLATTER_IN + (255,))
    rh = r * 0.17                                   # 中心轴
    d.ellipse([cx - rh, cy - rh, cx + rh, cy + rh], fill=RING + (255,))
    rh2 = rh * 0.42
    d.ellipse([cx - rh2, cy - rh2, cx + rh2, cy + rh2],
              fill=PLATTER + (255,))

    # ---- 3. 读写臂（右上伸入盘片外缘，圆头粗线 + 深色磁头）----
    aw = int(n * 0.062)
    p0 = (n * 0.805, n * 0.230)
    p1 = (n * 0.612, n * 0.398)
    d.line([p0, p1], fill=ARM + (255,), width=aw)
    for px, py in (p0, p1):                          # 圆头
        d.ellipse([px - aw / 2, py - aw / 2,
                   px + aw / 2, py + aw / 2], fill=ARM + (255,))
    hs = aw * 1.05                                   # 磁头
    d.rounded_rectangle([p1[0] - hs * 0.52, p1[1] - hs * 0.30,
                         p1[0] + hs * 0.52, p1[1] + hs * 0.72],
                        radius=hs * 0.22, fill=HEAD + (255,))

    # ---- 4. 延迟脉搏线（底部，"正常"绿）----
    pw = int(n * 0.030)
    pts = [(0.300, 0.815), (0.410, 0.815), (0.452, 0.752),
           (0.500, 0.882), (0.548, 0.700), (0.590, 0.815),
           (0.700, 0.815)]
    pts = [(n * x, n * y) for x, y in pts]
    d.line(pts, fill=PULSE + (255,), width=pw, joint="curve")
    for px, py in (pts[0], pts[-1]):                 # 两端圆头
        d.ellipse([px - pw / 2, py - pw / 2,
                   px + pw / 2, py + pw / 2], fill=PULSE + (255,))

    return img.resize((S, S), Image.LANCZOS)


def main():
    icon = draw_master()

    out = os.path.join(HERE, "img", "HD_Doc.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    icon.save(out, "PNG", optimize=True)
    print("[完成] %s（%dx%d, %d KB）"
          % (out, icon.width, icon.height,
             os.path.getsize(out) // 1024))

    out = os.path.join(HERE, "img", "HD_Doc.ico")
    icon.save(out, "ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                     (64, 64), (128, 128), (256, 256)])
    print("[完成] %s（%d KB，16/24/32/48/64/128/256 多分辨率）"
          % (out, os.path.getsize(out) // 1024))

    for size in HICOLOR_SIZES:
        d_ = os.path.join(HERE, "img", "icons", "hicolor",
                          "%dx%d" % (size, size), "apps")
        os.makedirs(d_, exist_ok=True)
        p = os.path.join(d_, "hd-doc.png")
        icon.resize((size, size), Image.LANCZOS).save(p, "PNG",
                                                      optimize=True)
        print("[完成] %s（%d B）" % (p, os.path.getsize(p)))

    print("\n提示：install.sh 会安装 img/icons/hicolor 下全部尺寸；"
          "Windows exe 图标来自 img/HD_Doc.ico（需重跑 build_exe.py 生效）。")


if __name__ == "__main__":
    main()
