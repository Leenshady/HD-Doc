#!/bin/sh
# HD Doc Ubuntu 安装脚本
#
# 用法（需要 root）:
#   sudo ./install.sh                # 交互式安装（缺失组件询问后 apt 安装）
#   sudo ./install.sh -y             # 全自动（不询问，直接装缺失组件）
#   sudo ./install.sh --no-fio       # 不安装 fio（已单独装过时）
#   sudo ./install.sh --no-apt       # 完全不调用 apt（自行准备依赖）
#   sudo ./install.sh --prefix DIR   # 自定义安装目录（默认 /opt/hd-doc）
#
# 安装内容:
#   /opt/hd-doc/                 程序文件（源码 + lang/ + img/）
#   /opt/hd-doc/venv/            Python 虚拟环境（ttkbootstrap）
#   /usr/local/bin/hd-doc        启动器（GUI 与 CLI 统一入口）
#   /usr/share/applications/hd-doc.desktop   应用菜单项
#   /usr/share/icons/hicolor/256x256/apps/hd-doc.png   图标
#
# 扫描物理磁盘（/dev/sda 等）需要 root：启动器检测到非 root 时会用
# pkexec 申请图形化提权；扫描镜像文件无需 root。

set -e

PREFIX=/opt/hd-doc
ASSUME_YES=0
USE_APT=1
INSTALL_FIO=1
# 以下路径可用环境变量覆盖（测试/自定义布局用），默认装到系统标准位置
LAUNCHER=${HD_DOC_LAUNCHER:-/usr/local/bin/hd-doc}
DESKTOP_FILE=${HD_DOC_DESKTOP:-/usr/share/applications/hd-doc.desktop}
ICON_FILE=${HD_DOC_ICON:-/usr/share/icons/hicolor/256x256/apps/hd-doc.png}

# ---------------------------------------------------------------- 工具函数
info() { printf '\033[32m[信息]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[错误]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

ask() {
    # ask "问题" → 返回 0(是)/1(否)；-y 时恒返回 0
    [ "$ASSUME_YES" = 1 ] && return 0
    printf '%s [Y/n] ' "$*"
    read ans || return 1
    case "$ans" in
        n*|N*) return 1 ;;
        *) return 0 ;;
    esac
}

# ---------------------------------------------------------------- 参数解析
while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1 ;;
        --no-fio) INSTALL_FIO=0 ;;
        --no-apt) USE_APT=0 ;;
        --prefix) shift; [ $# -gt 0 ] || die "--prefix 缺少参数"; PREFIX="$1" ;;
        --prefix=*) PREFIX="${1#--prefix=}" ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) die "未知参数: $1（--help 查看用法）" ;;
    esac
    shift
done

# 安全护栏：禁止把东西装到危险目录
case "$PREFIX" in
    ""|/|/usr|/etc|/bin|/sbin|/lib|/var|/home|/boot|/System) die "拒绝使用危险安装目录: $PREFIX" ;;
esac

[ "$(id -u)" = 0 ] || die "请用 root 运行：sudo ./install.sh"

SRC=$(cd "$(dirname "$0")" && pwd)
[ -f "$SRC/HD_Doc.py" ] || die "未找到 HD_Doc.py（应在解包后的目录里运行本脚本）"

# ---------------------------------------------------------------- 依赖检查
PYTHON=$(command -v python3 || command -v python || true)
[ -n "$PYTHON" ] || die "未找到 python3。Ubuntu 请先安装: sudo apt install python3"

py_major=$($PYTHON -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo 0)
py_minor=$($PYTHON -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)
if [ "$py_major" -lt 3 ] || { [ "$py_major" = 3 ] && [ "$py_minor" -lt 8 ]; }; then
    die "Python 版本过低（需要 >= 3.8，当前 $py_major.$py_minor）"
fi
info "Python: $PYTHON ($py_major.$py_minor)"

APT_PKGS=""
apt_updated=0

apt_install() {
    [ -n "$1" ] || return 0
    [ "$USE_APT" = 1 ] || { warn "跳过 apt 安装: $1（--no-apt）"; return 0; }
    command -v apt-get >/dev/null 2>&1 || {
        warn "未找到 apt-get（非 Debian/Ubuntu 系统？）。请手动安装: $1"
        return 0
    }
    ask "需要安装缺失的组件: $1，是否继续？" || { warn "已跳过，稍后需自行安装: $1"; return 0; }
    [ "$apt_updated" = 1 ] || { info "apt-get update ..."; apt-get update -qq; apt_updated=1; }
    info "apt-get install $1 ..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $1 \
        || warn "apt 安装失败: $1（可稍后手动重试）"
}

# tkinter（GUI 必需；CLI 模式不需要）
if ! $PYTHON -c 'import tkinter' >/dev/null 2>&1; then
    warn "当前 Python 缺少 tkinter（GUI 需要）"
    APT_PKGS="python3-tk"
fi
# venv（优先方案；失败时可回退到系统 Python）
if ! $PYTHON -m venv --help >/dev/null 2>&1; then
    APT_PKGS="$APT_PKGS python3-venv python3-pip"
fi
# fio（扫描引擎）
if [ "$INSTALL_FIO" = 1 ] && ! command -v fio >/dev/null 2>&1; then
    warn "未找到 fio（扫描引擎）"
    APT_PKGS="$APT_PKGS fio"
fi
[ -n "$APT_PKGS" ] && apt_install "$APT_PKGS"

# ---------------------------------------------------------------- 安装文件
info "安装目录: $PREFIX"
if [ -e "$PREFIX" ]; then
    # 覆盖安装（升级）：配置在 ~/.config/HD_Doc，不受影响
    case "$PREFIX" in
        /opt/hd-doc) rm -rf "$PREFIX" ;;
        *) ask "目录 $PREFIX 已存在，是否覆盖？" || die "已取消"; rm -rf "$PREFIX" ;;
    esac
fi
mkdir -p "$PREFIX"
for f in HD_Doc.py HD_Doc_core.py HD_Doc_gui.py HD_Doc_cli.py requirements.txt; do
    cp "$SRC/$f" "$PREFIX/"
done
[ -d "$SRC/lang" ] && cp -r "$SRC/lang" "$PREFIX/"
[ -d "$SRC/img" ]  && cp -r "$SRC/img"  "$PREFIX/"
chmod 755 "$PREFIX/HD_Doc.py"

# ---------------------------------------------------------------- 虚拟环境
PY_MODE=system
if $PYTHON -m venv --system-site-packages "$PREFIX/venv" >/dev/null 2>&1; then
    info "创建虚拟环境并安装依赖（ttkbootstrap）..."
    if "$PREFIX/venv/bin/pip" install --quiet --disable-pip-version-check \
            -r "$PREFIX/requirements.txt" >/dev/null 2>&1 \
            && "$PREFIX/venv/bin/python" -c 'import ttkbootstrap' >/dev/null 2>&1; then
        PY_MODE=venv
    else
        warn "venv 内安装 ttkbootstrap 失败（网络？），尝试回退系统 Python"
        rm -rf "$PREFIX/venv"
    fi
else
    warn "无法创建 venv（缺 python3-venv？），尝试使用系统 Python"
fi
if [ "$PY_MODE" = system ]; then
    if $PYTHON -c 'import ttkbootstrap' >/dev/null 2>&1; then
        info "系统 Python 已具备 ttkbootstrap，直接使用"
    else
        warn "未找到 ttkbootstrap，GUI 暂无法启动。安装任选其一："
        warn "  sudo $PREFIX/venv/bin/pip install ttkbootstrap   （先 apt install python3-venv）"
        warn "  sudo apt install python3-pip && pip install ttkbootstrap"
        warn "CLI 模式不依赖 ttkbootstrap，可先用：hd-doc --cli --target 镜像文件"
    fi
fi
printf '%s' "$PY_MODE" > "$PREFIX/.python_mode"

# ---------------------------------------------------------------- 启动器
mkdir -p "$(dirname "$LAUNCHER")"
cat > "$LAUNCHER" <<EOF
#!/bin/sh
# HD Doc 启动器（由 install.sh 生成）
PREFIX="$PREFIX"
MODE=\$(cat "\$PREFIX/.python_mode" 2>/dev/null || echo system)
if [ "\$MODE" = venv ] && [ -x "\$PREFIX/venv/bin/python" ]; then
    exec "\$PREFIX/venv/bin/python" "\$PREFIX/HD_Doc.py" "\$@"
fi
exec $PYTHON "\$PREFIX/HD_Doc.py" "\$@"
EOF
chmod 755 "$LAUNCHER"

# ---------------------------------------------------------------- 图标 + 桌面项
ICON_SRC="$SRC/img/hd-doc-256.png"
[ -f "$ICON_SRC" ] || ICON_SRC="$SRC/img/HD_Doc.png"
if [ -f "$ICON_SRC" ]; then
    mkdir -p "$(dirname "$ICON_FILE")"
    cp "$ICON_SRC" "$ICON_FILE"
fi

mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
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
EOF
chmod 644 "$DESKTOP_FILE"
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q /usr/share/applications 2>/dev/null || true

# ---------------------------------------------------------------- 安装清单
# 记录本次安装的实际路径，供 uninstall.sh 定位（支持自定义 --prefix/环境变量覆盖）
MANIFEST_DIR=${HD_DOC_MANIFEST_DIR:-/var/lib/hd-doc}
mkdir -p "$MANIFEST_DIR"
cat > "$MANIFEST_DIR/install.manifest" <<EOF
PREFIX=$PREFIX
LAUNCHER=$LAUNCHER
DESKTOP=$DESKTOP_FILE
ICON=$ICON_FILE
EOF

# ---------------------------------------------------------------- 完成
cat <<EOF

============================================================
 HD Doc 安装完成
============================================================
 程序目录   $PREFIX
 Python     $PY_MODE
 启动命令   hd-doc                # GUI 模式
            hd-doc --cli --help   # 命令行模式
 应用菜单   系统应用列表中搜索 "HD Doc"

 扫描物理磁盘需要 root（打不开设备时点界面里的"以 root 重启"）；
 扫描镜像文件（dd 出来的 .img）无需 root。
 日志位置   ~/.config/HD_Doc/HD_Doc.log
 卸载       sudo $PREFIX/uninstall.sh
============================================================
EOF
