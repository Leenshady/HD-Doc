#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_ubuntu_pkg.py —— 把 HD Doc 打成 Ubuntu 安装包（本机 Windows 上即可构建）

产物（dist/ 下）:
  HD_Doc-<版本>-ubuntu.tar.gz    源码安装包：解压后 sudo ./HD_Doc-<版本>/install.sh
  HD_Doc-<版本>-ubuntu.run       自解压安装包：chmod +x 后 sudo ./HD_Doc-...run
  *.sha256                       校验和

两个包内容完全一致（同一份 tar.gz），区别只是分发形态：
  - .tar.gz 适合手动解压安装、或集成到现有部署流程
  - .run   适合直接发给用户：一条命令完成解包+安装

说明：
  - PyInstaller 不能交叉编译，所以这里打的是"源码安装包"（安装时在目标
    机器上建 venv 装 ttkbootstrap），而不是 Windows exe 那样的单文件二进制。
    想要单文件二进制，请在 Ubuntu 上运行同一份 build_exe.py（见 README）。
  - 纯 Python 源码，与 CPU 架构无关（x86_64 / arm64 均可）。
  - 图标由 img/HD_Doc.png（1248x1248）缩放为 256x256 供桌面项使用。

用法:
  python build_ubuntu_pkg.py            # 构建 tar.gz + run + sha256
  python build_ubuntu_pkg.py --no-run   # 只构建 tar.gz
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
PAYLOAD_DIR = os.path.join(HERE, "packaging", "ubuntu")
MARKER = b"__HD_DOC_PAYLOAD__"

# 打进安装包的源码文件（排除测试/构建产物/镜像）
APP_FILES = ("HD_Doc.py", "HD_Doc_core.py", "HD_Doc_gui.py", "HD_Doc_cli.py",
             "requirements.txt", "README.md", "README.zh-CN.md")
# 目录：整目录打包（内部文件全部收入）
APP_DIRS = ("lang", "img")

RUN_HEADER = """#!/bin/sh
# HD Doc {version} for Ubuntu —— 自解压安装包
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
    name = "HD_Doc-%s-ubuntu" % version
    header = RUN_HEADER.format(version=version, name=name, marker=MARKER.decode())
    with open(targz_path, "rb") as f:
        payload = f.read()
    with open(out_path, "wb") as f:
        f.write(header.encode("utf-8"))
        f.write(b"\n" + MARKER + b"\n")
        f.write(payload)
    return len(payload)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="构建 HD Doc Ubuntu 安装包")
    ap.add_argument("--no-run", action="store_true",
                    help="只构建 tar.gz，不构建自解压 .run")
    args = ap.parse_args()

    version = read_version()
    os.makedirs(DIST, exist_ok=True)
    name = "HD_Doc-%s-ubuntu" % version

    stage, top = stage_tree(version)
    try:
        targz = os.path.join(DIST, name + ".tar.gz")
        n = build_targz(top, targz)
        print("[完成] %s（%.1f MB，未压缩 %.1f MB）"
              % (targz, os.path.getsize(targz) / 1048576.0, n / 1048576.0))

        outs = [targz]
        if not args.no_run:
            run = os.path.join(DIST, name + ".run")
            build_run(version, targz, run)
            print("[完成] %s（%.1f MB）"
                  % (run, os.path.getsize(run) / 1048576.0))
            outs.append(run)

        for p in outs:
            with open(p + ".sha256", "w", encoding="utf-8") as f:
                f.write("%s  %s\n" % (sha256_of(p), os.path.basename(p)))
            print("[完成] %s.sha256" % p)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    print("""
使用方法（在 Ubuntu 上）:
  # 方式一：自解压安装包
  chmod +x {name}.run
  sudo ./{name}.run            # 安装（加 -y 全自动；--uninstall 卸载）

  # 方式二：tar.gz
  tar xzf {name}.tar.gz
  sudo ./{name}/install.sh     # 安装
  sudo ./{name}/uninstall.sh   # 卸载

安装后: 应用菜单搜索 "HD Doc"，或终端运行 hd-doc（GUI）/ hd-doc --cli（命令行）。
扫描物理磁盘需 root；扫描镜像文件无需 root。""".format(name=name))


if __name__ == "__main__":
    main()
