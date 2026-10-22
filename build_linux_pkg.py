#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_linux_pkg.py —— 把 HD Doc 打成 Linux 安装包（本机 Windows 上即可构建）

支持发行版: Ubuntu 20.04+ / 银河麒麟桌面 V10+ / openKylin / Deepin / UOS
            （rpm 系银河麒麟服务器 V10 可用 .run 装 CLI，依赖需自备）

产物（dist/ 下）:
  HD_Doc-<版本>-linux.tar.gz    源码安装包：解压后 sudo ./HD_Doc-<版本>/install.sh
  HD_Doc-<版本>-linux.run       自解压安装包：chmod +x 后 sudo ./HD_Doc-...run
  HD_Doc-<版本>-kylin.deb       原生 deb 包：sudo apt install ./HD_Doc-...kylin.deb
                                （银河麒麟/Ubuntu/Deepin/UOS 等 deb 系通用）
  *.sha256                      校验和

三个包内容同源，区别只是分发形态：
  - .deb   适合麒麟/Ubuntu 桌面用户：双击或 apt 安装，走系统包管理卸载
  - .run   适合直接发给用户：一条命令完成解包+安装，任意 Linux 通用
  - .tar.gz 适合手动解压安装、或集成到现有部署流程

说明:
  - PyInstaller 不能交叉编译，所以这里打的是"源码安装包"（安装时在目标
    机器上建 venv 装 ttkbootstrap），而不是 Windows exe 那样的单文件二进制。
    想要单文件二进制，请在目标 Linux 上运行同一份 build_exe.py（见 README）。
  - 纯 Python 源码，与 CPU 架构无关（x86_64 / arm64 / loongarch 均可，
    .deb 的 Architecture 为 all）。
  - .deb 用纯 Python 组装（ar 归档 + control.tar.gz + data.tar.gz），
    不依赖 Windows 上没有的 dpkg-deb；结构按 Debian Policy 2.0 生成，
    可用 dpkg -i / apt install ./xxx.deb 安装。
  - 图标由 img/HD_Doc.png（1248x1248）缩放为 256x256 供桌面项使用。

用法:
  python build_linux_pkg.py            # 构建 tar.gz + run + deb + sha256
  python build_linux_pkg.py --no-run   # 不构建自解压 .run
  python build_linux_pkg.py --no-deb   # 不构建 .deb
"""
import argparse
import gzip
import hashlib
import io
import os
import re
import shutil
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
PAYLOAD_DIR = os.path.join(HERE, "packaging", "linux")
MARKER = b"__HD_DOC_PAYLOAD__"

# 打进安装包的源码文件（排除测试/构建产物/镜像）
APP_FILES = ("HD_Doc.py", "HD_Doc_core.py", "HD_Doc_gui.py", "HD_Doc_cli.py",
             "requirements.txt", "README.md", "README.zh-CN.md")
# 目录：整目录打包（内部文件全部收入）
APP_DIRS = ("lang", "img")

RUN_HEADER = """#!/bin/sh
# HD Doc {version} for Linux —— 自解压安装包
#
# 支持: Ubuntu 20.04+ / 银河麒麟桌面 V10+ / openKylin / Deepin / UOS
#       （rpm 系麒麟服务器 V10 可用本包装 CLI，依赖需自备 fio/python3-tkinter）
#
# 用法:
#   chmod +x {name}.run
#   sudo ./{name}.run              # 安装
#   sudo ./{name}.run -y           # 全自动安装（不询问）
#   sudo ./{name}.run --uninstall  # 卸载
#
# 也可以只用 tar.gz 部分:
#   tail -n +$(grep -an '^{marker}$' {name}.run | head -1 | cut -d: -f1) \\
#       {name}.run | tar xzf -

set -e

SELF="$0"
MARK='{marker}'

line=$(grep -an "^$MARK\\$" "$SELF" | head -n1 | cut -d: -f1)
if [ -z "$line" ]; then
    printf '[错误] 安装包损坏：找不到内嵌数据\\n' >&2
    exit 1
fi

WORK=$(mktemp -d /tmp/hd-doc-install.XXXXXX)
trap 'rm -rf "$WORK"' EXIT INT TERM

printf '[信息] 正在解包 ...\\n'
tail -n +$((line + 1)) "$SELF" | tar xzf - -C "$WORK"

DIR=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n1)
[ -n "$DIR" ] || DIR="$WORK"

if [ "${{1:-}}" = "--uninstall" ]; then
    shift
    exec sh "$DIR/uninstall.sh" "$@"
fi
exec sh "$DIR/install.sh" "$@"
"""


# ---------------------------------------------------------------- deb 资产
# deb 内的启动器（/usr/bin/hd-doc）：与 install.sh 生成的启动器同逻辑，
# 读 postinst 写的 .python_mode 决定用 venv 还是系统 Python。
DEB_LAUNCHER = """#!/bin/sh
# HD Doc 启动器（由 hd-doc deb 安装）
PREFIX=/opt/hd-doc
MODE=$(cat "$PREFIX/.python_mode" 2>/dev/null || echo system)
if [ "$MODE" = venv ] && [ -x "$PREFIX/venv/bin/python" ]; then
    exec "$PREFIX/venv/bin/python" "$PREFIX/HD_Doc.py" "$@"
fi
exec python3 "$PREFIX/HD_Doc.py" "$@"
"""

DEB_DESKTOP = """[Desktop Entry]
Type=Application
Name=HD Doc
Name[zh_CN]=HD Doc 硬盘检测
GenericName=Disk Health Scanner
GenericName[zh_CN]=硬盘读取延迟检测
Comment=Scan disk read latency with fio and show a block heatmap
Comment[zh_CN]=基于 fio 检测硬盘读取延迟并显示热力图
Exec=hd-doc
Icon=hd-doc
Terminal=false
Categories=System;Utility;HardwareSettings;
Keywords=disk;health;fio;scan;harddisk;
StartupNotify=true
StartupWMClass=HD_Doc
"""

DEB_POSTINST = """#!/bin/sh
# HD Doc deb 安装后配置（dpkg 传入 configure 时执行）：
#   1. 创建 venv 并安装 ttkbootstrap（离线机器失败时回退系统 Python，
#      CLI 模式不依赖 ttkbootstrap，不受影响）
#   2. 写 .python_mode 标记 + 安装清单（供手动 uninstall.sh 定位）
#   3. 刷新图标/桌面数据库（缺工具时静默跳过）
set -e
PREFIX=/opt/hd-doc
case "$1" in
    configure)
        PYTHON=$(command -v python3 || command -v python || true)
        MODE=system
        if [ -n "$PYTHON" ] \\
           && "$PYTHON" -m venv --system-site-packages "$PREFIX/venv" >/dev/null 2>&1; then
            if "$PREFIX/venv/bin/pip" install --quiet --disable-pip-version-check \\
                    -r "$PREFIX/requirements.txt" >/dev/null 2>&1 \\
                    && "$PREFIX/venv/bin/python" -c 'import ttkbootstrap' >/dev/null 2>&1; then
                MODE=venv
            else
                rm -rf "$PREFIX/venv"
            fi
        fi
        printf '%s' "$MODE" > "$PREFIX/.python_mode"
        # 安装清单（deb 卸载用 apt remove；这里仅供手动清理脚本定位）
        mkdir -p /var/lib/hd-doc
        cat > /var/lib/hd-doc/install.manifest <<EOF
PREFIX=$PREFIX
LAUNCHER=/usr/bin/hd-doc
DESKTOP=/usr/share/applications/hd-doc.desktop
ICON=/usr/share/icons/hicolor/256x256/apps/hd-doc.png
EOF
        command -v gtk-update-icon-cache >/dev/null 2>&1 && \\
            gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
        command -v update-desktop-database >/dev/null 2>&1 && \\
            update-desktop-database -q /usr/share/applications 2>/dev/null || true
        ;;
esac
exit 0
"""

DEB_POSTRM = """#!/bin/sh
# HD Doc deb 卸载后清理：venv/.python_mode 由 postinst 生成、不在 data.tar
# 里，dpkg 不会删，需手动清理；purge 时连程序目录与安装清单一起删。
set -e
case "$1" in
    remove|purge)
        rm -rf /opt/hd-doc/venv
        rm -f /opt/hd-doc/.python_mode
        rmdir /opt/hd-doc 2>/dev/null || true
        if [ "$1" = purge ]; then
            rm -rf /opt/hd-doc /var/lib/hd-doc
        fi
        command -v gtk-update-icon-cache >/dev/null 2>&1 && \\
            gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
        command -v update-desktop-database >/dev/null 2>&1 && \\
            update-desktop-database -q /usr/share/applications 2>/dev/null || true
        ;;
esac
exit 0
"""


def read_version():
    with open(os.path.join(HERE, "HD_Doc_core.py"), encoding="utf-8") as f:
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
    if not m:
        sys.exit("[错误] 无法从 HD_Doc_core.py 读取 VERSION")
    return m.group(1)


def make_icon(stage):
    """img/HD_Doc.png → img/hd-doc-256.png（桌面项图标；无 PIL 时跳过）"""
    src = os.path.join(stage, "img", "HD_Doc.png")
    dst = os.path.join(stage, "img", "hd-doc-256.png")
    if not os.path.isfile(src):
        return None
    try:
        from PIL import Image
    except ImportError:
        print("[警告] 未安装 Pillow，跳过图标缩放（桌面项将使用原始大图标）")
        return None
    im = Image.open(src).convert("RGBA")
    im.thumbnail((256, 256), Image.LANCZOS)
    im.save(dst, "PNG", optimize=True)
    print("[信息] 图标已缩放: %dx%d -> %dx%d (%d KB)"
          % (Image.open(src).width, Image.open(src).height,
             im.width, im.height, os.path.getsize(dst) // 1024))
    return dst


def stage_tree(version):
    """组装暂存目录，返回路径"""
    stage = tempfile.mkdtemp(prefix="hd-doc-pkg-")
    top = os.path.join(stage, "HD_Doc-%s" % version)
    os.makedirs(top)
    for f in APP_FILES:
        src = os.path.join(HERE, f)
        if not os.path.isfile(src):
            sys.exit("[错误] 缺少文件: %s" % f)
        shutil.copy2(src, os.path.join(top, f))
    for d in APP_DIRS:
        src = os.path.join(HERE, d)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(top, d))
    for f in ("install.sh", "uninstall.sh"):
        src = os.path.join(PAYLOAD_DIR, f)
        if not os.path.isfile(src):
            sys.exit("[错误] 缺少文件: %s" % src)
        shutil.copy2(src, os.path.join(top, f))
    make_icon(top)
    return stage, top


def _tarinfo(tarinfo):
    """统一权限位与属主，避免把 Windows 的 0777/管理员 SID 带进安装包"""
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = "root"
    tarinfo.gname = "root"
    name = tarinfo.name.rsplit("/", 1)[-1]
    if tarinfo.isdir():
        tarinfo.mode = 0o755
    elif name.endswith(".sh"):
        tarinfo.mode = 0o755
    elif name in ("HD_Doc.py",):
        tarinfo.mode = 0o755
    else:
        tarinfo.mode = 0o644
    return tarinfo


def build_targz(top, out_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        # 确定性排序，保证重复构建产物一致
        entries = []
        for root, dirs, files in os.walk(top):
            dirs.sort()
            for d in dirs:
                entries.append(os.path.join(root, d))
            for f in sorted(files):
                entries.append(os.path.join(root, f))
        entries.sort()
        base = os.path.dirname(top)
        for p in entries:
            # 目录项必须关掉递归，否则目录内容会被展开一次、
            # 随后单独的文件项又加一次 → 归档里出现重复文件
            tar.add(p, arcname=os.path.relpath(p, base),
                    filter=_tarinfo, recursive=not os.path.isdir(p))
    raw = buf.getvalue()
    with open(out_path, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            gz.write(raw)
    return len(raw)


def build_run(version, targz_path, out_path):
    name = "HD_Doc-%s-linux" % version
    header = RUN_HEADER.format(version=version, name=name, marker=MARKER.decode())
    with open(targz_path, "rb") as f:
        payload = f.read()
    with open(out_path, "wb") as f:
        f.write(header.encode("utf-8"))
        f.write(b"\n" + MARKER + b"\n")
        f.write(payload)
    return len(payload)


# ---------------------------------------------------------------- .deb 构建
def _deb_control(version, installed_size):
    return "\n".join([
        "Package: hd-doc",
        "Version: %s" % version,
        "Section: utils",
        "Priority: optional",
        "Architecture: all",
        "Maintainer: HD Doc Project <hd-doc@localhost>",
        "Installed-Size: %d" % installed_size,
        "Depends: python3 (>= 3.8), python3-tk, python3-venv, fio, policykit-1",
        "Description: Disk health scanner based on fio with block heatmap",
        " HD Doc scans physical disks or image files with fio and renders read",
        " latency / health as a block heatmap. Supports full scan, quick scan",
        " (head sample per region), health and read-speed color modes, CSV/JSON",
        " report export, and both GUI and CLI front-ends.",
        " .",
        " 基于 fio 的硬盘读取检测工具：全盘/快速扫描，热力图显示读取延迟与",
        " 健康状态，支持 GUI 与 CLI、报告导出。适用于 Ubuntu / 银河麒麟等",
        " Linux 发行版。",
    ]) + "\n"


def _deb_data_items(top):
    """返回 data.tar 成员 [(arcname, src(None=目录 | bytes | 文件路径), mode)]"""
    items = []

    def add_dir(arc):
        items.append((arc, None, 0o755))

    def add_file(arc, src, mode=0o644):
        items.append((arc, src, mode))

    def walk(rel_dir):
        """把 top/rel_dir 整目录加入（./ 前缀、root 属主、确定顺序）"""
        base = os.path.join(top, rel_dir)
        add_dir("./opt/hd-doc/" + rel_dir)
        for root, dirs, files in os.walk(base):
            dirs.sort()
            rel = os.path.relpath(root, top).replace(os.sep, "/")
            if rel != rel_dir:
                add_dir("./opt/hd-doc/" + rel)
            for fn in sorted(files):
                add_file("./opt/hd-doc/%s/%s" % (rel, fn),
                         os.path.join(root, fn))

    add_dir("./opt")
    add_dir("./opt/hd-doc")
    for f in APP_FILES:
        add_file("./opt/hd-doc/" + f, os.path.join(top, f),
                 0o755 if f == "HD_Doc.py" else 0o644)
    walk("lang")
    walk("img")

    add_dir("./usr")
    add_dir("./usr/bin")
    add_file("./usr/bin/hd-doc", DEB_LAUNCHER.encode("utf-8"), 0o755)

    add_dir("./usr/share")
    add_dir("./usr/share/applications")
    add_file("./usr/share/applications/hd-doc.desktop",
             DEB_DESKTOP.encode("utf-8"))

    # 全套 hicolor 尺寸图标 + pixmaps 兜底（与 install.sh 一致：
    # 只装单一尺寸时 UKUI/GNOME 程序坞可能匹配不到图标）
    add_dir("./usr/share/icons")
    add_dir("./usr/share/icons/hicolor")
    icon_root = os.path.join(top, "img", "icons", "hicolor")
    if os.path.isdir(icon_root):
        for sz in sorted(os.listdir(icon_root)):
            src = os.path.join(icon_root, sz, "apps", "hd-doc.png")
            if not os.path.isfile(src):
                continue
            add_dir("./usr/share/icons/hicolor/" + sz)
            add_dir("./usr/share/icons/hicolor/%s/apps" % sz)
            add_file("./usr/share/icons/hicolor/%s/apps/hd-doc.png" % sz, src)
    add_dir("./usr/share/pixmaps")
    pix = os.path.join(top, "img", "hd-doc-256.png")
    if not os.path.isfile(pix):
        pix = os.path.join(top, "img", "HD_Doc.png")
    if os.path.isfile(pix):
        add_file("./usr/share/pixmaps/hd-doc.png", pix)
    return items


def _tar_bytes(items):
    """[(arcname, src, mode)] → tar 字节（root 属主、mtime=0 确定性输出）"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for arcname, src, mode in items:
            if src is None:
                data, is_dir = b"", True
            elif isinstance(src, bytes):
                data, is_dir = src, False
            else:
                with open(src, "rb") as f:
                    data = f.read()
                is_dir = False
            ti = tarfile.TarInfo(arcname)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = 0
            ti.mode = mode
            if is_dir:
                ti.type = tarfile.DIRTYPE
                ti.size = 0
                tar.addfile(ti)
            else:
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _ar_bytes(members):
    """[(name, data)] → ar 归档字节（.deb 容器；成员 2 字节对齐）"""
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        hdr = ("%-16s%-12d%-6d%-6d%-8o%-10d`\n"
               % (name, 0, 0, 0, 0o100644, len(data))).encode("ascii")
        assert len(hdr) == 60, "ar 头长度异常: %d" % len(hdr)
        out.write(hdr)
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def _gz_bytes(raw):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return buf.getvalue()


def build_deb(version, top, out_path):
    """组装 HD_Doc-<版本>-kylin.deb（Debian Policy 2.0 结构）"""
    data_items = _deb_data_items(top)
    installed = sum(
        (os.path.getsize(s) if isinstance(s, str) else len(s))
        for _a, s, _m in data_items if s is not None)
    installed_size = (installed + 1023) // 1024

    control_items = [
        ("./control", _deb_control(version, installed_size).encode("utf-8"), 0o644),
        ("./postinst", DEB_POSTINST.encode("utf-8"), 0o755),
        ("./postrm", DEB_POSTRM.encode("utf-8"), 0o755),
    ]
    deb = _ar_bytes([
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", _gz_bytes(_tar_bytes(control_items))),
        ("data.tar.gz", _gz_bytes(_tar_bytes(data_items))),
    ])
    with open(out_path, "wb") as f:
        f.write(deb)
    return installed_size, len(data_items)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="构建 HD Doc Linux 安装包")
    ap.add_argument("--no-run", action="store_true",
                    help="不构建自解压 .run")
    ap.add_argument("--no-deb", action="store_true",
                    help="不构建 .deb（麒麟/Ubuntu 原生包）")
    args = ap.parse_args()

    version = read_version()
    os.makedirs(DIST, exist_ok=True)

    stage, top = stage_tree(version)
    try:
        outs = []

        targz = os.path.join(DIST, "HD_Doc-%s-linux.tar.gz" % version)
        n = build_targz(top, targz)
        print("[完成] %s（%.1f MB，未压缩 %.1f MB）"
              % (targz, os.path.getsize(targz) / 1048576.0, n / 1048576.0))
        outs.append(targz)

        if not args.no_run:
            run = os.path.join(DIST, "HD_Doc-%s-linux.run" % version)
            build_run(version, targz, run)
            print("[完成] %s（%.1f MB）"
                  % (run, os.path.getsize(run) / 1048576.0))
            outs.append(run)

        if not args.no_deb:
            deb = os.path.join(DIST, "HD_Doc-%s-kylin.deb" % version)
            size_kib, n_items = build_deb(version, top, deb)
            print("[完成] %s（%.1f MB，Installed-Size %d KiB，data 成员 %d 个）"
                  % (deb, os.path.getsize(deb) / 1048576.0, size_kib, n_items))
            outs.append(deb)

        for p in outs:
            with open(p + ".sha256", "w", encoding="utf-8") as f:
                f.write("%s  %s\n" % (sha256_of(p), os.path.basename(p)))
            print("[完成] %s.sha256" % p)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    print("""
使用方法:
  # 方式一：原生 deb 包（银河麒麟桌面 V10 / Ubuntu 20.04+ / Deepin / UOS）
  sudo apt install ./HD_Doc-{version}-kylin.deb
  sudo apt remove hd-doc            # 卸载（purge 连配置一起清）

  # 方式二：自解压安装包（任意 Linux，含 rpm 系麒麟服务器 CLI 场景）
  chmod +x HD_Doc-{version}-linux.run
  sudo ./HD_Doc-{version}-linux.run            # 安装（加 -y 全自动；--uninstall 卸载）

  # 方式三：tar.gz
  tar xzf HD_Doc-{version}-linux.tar.gz
  sudo ./HD_Doc-{version}/install.sh     # 安装
  sudo ./HD_Doc-{version}/uninstall.sh   # 卸载

安装后: 应用菜单搜索 "HD Doc"，或终端运行 hd-doc（GUI）/ hd-doc --cli（命令行）。
扫描物理磁盘需 root；扫描镜像文件无需 root。""".format(version=version))


if __name__ == "__main__":
    main()
