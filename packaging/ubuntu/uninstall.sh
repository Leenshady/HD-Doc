#!/bin/sh
# HD Doc Ubuntu 卸载脚本
#
# 用法:
#   sudo ./uninstall.sh                # 按安装清单卸载（默认安装）
#   sudo ./uninstall.sh --prefix DIR   # 卸载指定目录
#   sudo ./uninstall.sh --purge        # 同时删除用户配置（~/.config/HD_Doc）
#
# 路径解析优先级: --prefix 参数 > 安装清单(/var/lib/hd-doc/install.manifest)
#                > 环境变量(HD_DOC_LAUNCHER 等) > 系统默认路径

set -e

PREFIX=/opt/hd-doc
PREFIX_GIVEN=0
PURGE=0
MANIFEST_DIR=${HD_DOC_MANIFEST_DIR:-/var/lib/hd-doc}
MANIFEST=$MANIFEST_DIR/install.manifest

info() { printf '\033[32m[信息]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[错误]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) shift; [ $# -gt 0 ] || die "--prefix 缺少参数"
                  PREFIX="$1"; PREFIX_GIVEN=1 ;;
        --prefix=*) PREFIX="${1#--prefix=}"; PREFIX_GIVEN=1 ;;
        --purge) PURGE=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) die "未知参数: $1" ;;
    esac
    shift
done

case "$PREFIX" in
    ""|/|/usr|/etc|/bin|/sbin|/lib|/var|/home|/boot) die "拒绝操作危险目录: $PREFIX" ;;
esac

[ "$(id -u)" = 0 ] || die "请用 root 运行：sudo ./uninstall.sh"

# 未显式指定 --prefix 时，读安装清单拿真实路径（自定义安装也能干净卸载）
if [ "$PREFIX_GIVEN" = 0 ] && [ -f "$MANIFEST" ]; then
    . "$MANIFEST"
    info "读取安装清单: $MANIFEST"
fi
LAUNCHER=${LAUNCHER:-${HD_DOC_LAUNCHER:-/usr/local/bin/hd-doc}}
DESKTOP_FILE=${DESKTOP_FILE:-${HD_DOC_DESKTOP:-/usr/share/applications/hd-doc.desktop}}
ICON_FILE=${ICON_FILE:-${HD_DOC_ICON:-/usr/share/icons/hicolor/256x256/apps/hd-doc.png}}

rm -rf "$PREFIX"
info "已删除程序目录: $PREFIX"

for f in "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE"; do
    [ -e "$f" ] && rm -f "$f" && info "已删除: $f"
done

[ -f "$MANIFEST" ] && rm -f "$MANIFEST" && info "已删除安装清单: $MANIFEST"
[ -d "$MANIFEST_DIR" ] && rmdir "$MANIFEST_DIR" 2>/dev/null || true

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q /usr/share/applications 2>/dev/null || true

if [ "$PURGE" = 1 ]; then
    for d in /root/.config/HD_Doc; do
        [ -e "$d" ] && rm -rf "$d" && info "已删除配置: $d"
    done
    # 调用者的 HOME（sudo 下默认是 /root，$HOME 可能仍是普通用户）
    if [ -n "$SUDO_USER" ]; then
        _h=$(eval echo "~$SUDO_USER") && [ -e "$_h/.config/HD_Doc" ] && \
            rm -rf "$_h/.config/HD_Doc" && info "已删除配置: $_h/.config/HD_Doc"
    fi
    [ -n "$HOME" ] && [ -e "$HOME/.config/HD_Doc" ] && \
        rm -rf "$HOME/.config/HD_Doc" && info "已删除配置: $HOME/.config/HD_Doc"
fi

info "卸载完成"
