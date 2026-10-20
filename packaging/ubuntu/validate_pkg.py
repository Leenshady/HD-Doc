#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_pkg.py —— 校验 build_ubuntu_pkg.py 产出的 Ubuntu 安装包

检查项:
  1. .run 自解压头：shebang、shell 语法（sh -n）、载荷标记唯一
  2. 从 .run 抽出载荷 → 解 tar → 核对文件树、权限位、属主、行尾（LF）
  3. tar.gz 与 .run 内嵌载荷内容一致
  4. .sha256 校验和匹配
  5. lang/ 双语 key 一致、JSON 可解析
  6. 模拟安装 dry-run（stub id/python3，全部路径落在临时目录，
     不碰系统 /opt、/usr）—— 验证 install.sh 全流程逻辑

用法: python validate_pkg.py [dist/HD_Doc-<版本>-ubuntu.run]
"""
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(os.path.dirname(HERE))     # HD_Doc/
DIST = os.path.join(PKG_DIR, "dist")
MARKER = b"__HD_DOC_PAYLOAD__"

FAILED = []


def check(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print("  [%s] %s%s" % (status, name, (" — " + str(detail)) if detail else ""))
    if not cond:
        FAILED.append(name)
    return cond


def split_run(path):
    """返回 (header_bytes, payload_bytes)"""
    with open(path, "rb") as f:
        data = f.read()
    lines = data.split(b"\n")
    hits = [i for i, ln in enumerate(lines) if ln == MARKER]
    if len(hits) != 1:
        raise SystemExit("[错误] 载荷标记出现 %d 次（应为 1）" % len(hits))
    idx = hits[0]
    header = b"\n".join(lines[:idx]) + b"\n"
    payload = b"\n".join(lines[idx + 1:])
    return header, payload


def tar_members(payload):
    out = {}
    dup = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.name in out:
                dup.append(m.name)
            buf = b""
            if m.isfile():
                buf = tar.extractfile(m).read()
            out[m.name] = (m, buf)
    if dup:
        raise SystemExit("[错误] 归档中存在重复成员: %s" % sorted(set(dup)))
    return out


def main():
    run_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not run_path:
        cands = [f for f in os.listdir(DIST) if f.endswith(".run")] \
            if os.path.isdir(DIST) else []
        if not cands:
            raise SystemExit("[错误] dist/ 下没有 .run，请先运行 build_ubuntu_pkg.py")
        run_path = os.path.join(DIST, sorted(cands)[0])
    print("校验安装包: %s\n" % run_path)

    # ---------- 1. .run 头部 ----------
    print("== 1. 自解压头 ==")
    header, payload = split_run(run_path)
    check("shebang 为 #!/bin/sh", header.startswith(b"#!/bin/sh"))
    with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as tf:
        tf.write(header)
        hdr_path = tf.name
    try:
        r = subprocess.run(["sh", "-n", hdr_path], capture_output=True, text=True)
        check("头部 shell 语法（sh -n）", r.returncode == 0, r.stderr.strip())
    finally:
        os.unlink(hdr_path)

    # ---------- 2. 载荷内容 ----------
    print("\n== 2. 载荷文件树/权限/行尾 ==")
    members = tar_members(payload)
    tops = {n.split("/")[0] for n in members}
    check("唯一顶层目录", len(tops) == 1, tops)
    top = tops.pop()
    ver = top.split("-")[-1]

    need_files = ["HD_Doc.py", "HD_Doc_core.py", "HD_Doc_gui.py",
                  "HD_Doc_cli.py", "requirements.txt", "README.md",
                  "README.zh-CN.md", "install.sh", "uninstall.sh",
                  "lang/en.json", "lang/zh.json", "img/HD_Doc.png",
                  "img/hd-doc-256.png"]
    for f in need_files:
        check("包含 %s" % f, "%s/%s" % (top, f) in members)

    m_install, b_install = members["%s/install.sh" % top]
    check("install.sh 权限 0755", m_install.mode == 0o755, oct(m_install.mode))
    check("uninstall.sh 权限 0755",
          members["%s/uninstall.sh" % top][0].mode == 0o755)
    check("HD_Doc.py 权限 0755",
          members["%s/HD_Doc.py" % top][0].mode == 0o755)
    check("lang/en.json 权限 0644",
          members["%s/lang/en.json" % top][0].mode == 0o644)
    check("目录权限 0755",
          all(m.mode == 0o755 for n, (m, _) in members.items() if m.isdir()))
    check("属主 root(0)", all(m.uid == 0 and m.gid == 0
                              for m, _ in members.values()))
    check("install.sh 为 LF 行尾", b"\r" not in b_install)
    check("install.sh 无危险 rm -rf /",
          b"rm -rf / " not in b_install and b"rm -rf /$" not in b_install)

    # ---------- 3. tar.gz 与 .run 载荷一致 ----------
    print("\n== 3. tar.gz 一致性 ==")
    tgz = os.path.join(DIST, "HD_Doc-%s-ubuntu.tar.gz" % ver)
    if check("tar.gz 存在", os.path.isfile(tgz)):
        with open(tgz, "rb") as f:
            m2 = tar_members(f.read())
        check("成员集合一致", set(m2) == set(members),
              set(m2) ^ set(members) or "完全一致")
        same = all(m2[n][1] == members[n][1] for n in m2 if n in members)
        check("文件内容逐字节一致", same)

    # ---------- 4. sha256 ----------
    print("\n== 4. 校验和 ==")
    for p in (run_path, tgz):
        sf = p + ".sha256"
        if not check("%s.sha256 存在" % os.path.basename(p), os.path.isfile(sf)):
            continue
        want = open(sf, encoding="utf-8").read().split()[0]
        got = hashlib.sha256(open(p, "rb").read()).hexdigest()
        check("%s 校验和匹配" % os.path.basename(p), want == got)

    # ---------- 5. lang key 一致性 ----------
    print("\n== 5. 语言文件 ==")
    en = json.loads(members["%s/lang/en.json" % top][1].decode("utf-8"))
    zh = json.loads(members["%s/lang/zh.json" % top][1].decode("utf-8"))
    check("en/zh key 集合一致", set(en) == set(zh),
          sorted(set(en) ^ set(zh)) or "%d keys" % len(en))

    # ---------- 6. 模拟安装 dry-run ----------
    print("\n== 6. install.sh 模拟安装（dry-run，不碰系统目录） ==")
    work = tempfile.mkdtemp(prefix="hd-doc-dryrun-")
    try:
        src = os.path.join(work, "payload")
        os.makedirs(src)
        for n, (m, buf) in members.items():
            rel = os.path.relpath(n, top)
            dst = os.path.join(src, rel)
            if m.isdir():
                os.makedirs(dst, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(buf)
                os.chmod(dst, 0o755 if m.mode & 0o100 else 0o644)

        stub = os.path.join(work, "stub")
        os.makedirs(stub)
        # stub id → 0（伪装 root）；python3 → 当前解释器
        with open(os.path.join(stub, "id"), "w") as f:
            f.write("#!/bin/sh\necho 0\n")
        py = sys.executable
        with open(os.path.join(stub, "python3"), "w") as f:
            f.write("#!/bin/sh\nexec '%s' \"$@\"\n" % py)
        os.chmod(os.path.join(stub, "id"), 0o755)
        os.chmod(os.path.join(stub, "python3"), 0o755)

        prefix = os.path.join(work, "opt", "hd-doc")
        env = dict(os.environ)
        env["PATH"] = stub + os.pathsep + env.get("PATH", "")
        env["HD_DOC_LAUNCHER"] = os.path.join(work, "bin", "hd-doc")
        env["HD_DOC_DESKTOP"] = os.path.join(work, "hd-doc.desktop")
        env["HD_DOC_ICON"] = os.path.join(work, "hd-doc.png")
        env["HD_DOC_MANIFEST_DIR"] = os.path.join(work, "var-lib", "hd-doc")
        env["HD_DOC_ICON_ROOT"] = os.path.join(work, "icons", "hicolor")
        env["HD_DOC_PIXMAPS"] = os.path.join(work, "pixmaps")
        r = subprocess.run(["sh", os.path.join(src, "install.sh"),
                            "--prefix", prefix, "-y"],
                           capture_output=True, text=True, env=env,
                           cwd=src, timeout=300)
        print("  ---- install.sh 输出 ----")
        for ln in r.stdout.splitlines():
            print("  | " + ln)
        if r.stderr.strip():
            print("  ---- stderr ----")
            for ln in r.stderr.splitlines():
                print("  | " + ln)
        check("install.sh 退出码 0", r.returncode == 0, r.returncode)
        check("程序目录已创建", os.path.isfile(os.path.join(prefix, "HD_Doc.py")))
        check("lang/ 已安装", os.path.isfile(os.path.join(prefix, "lang", "zh.json")))
        check("图标已缩放安装",
              os.path.isfile(os.path.join(prefix, "img", "hd-doc-256.png")))
        check(".python_mode 标记", os.path.isfile(os.path.join(prefix, ".python_mode")))
        launcher = env["HD_DOC_LAUNCHER"]
        check("启动器已生成", os.path.isfile(launcher))
        if os.path.isfile(launcher):
            body = open(launcher, encoding="utf-8").read()
            check("启动器引用 PREFIX", prefix in body)
            r2 = subprocess.run(["sh", "-n", launcher], capture_output=True, text=True)
            check("启动器语法正确", r2.returncode == 0, r2.stderr.strip())
        check("desktop 项已生成", os.path.isfile(env["HD_DOC_DESKTOP"]))
        if os.path.isfile(env["HD_DOC_DESKTOP"]):
            d = open(env["HD_DOC_DESKTOP"], encoding="utf-8").read()
            check("desktop Exec=hd-doc", "Exec=hd-doc" in d)
            check("desktop Icon=hd-doc", "Icon=hd-doc" in d)
            check("desktop StartupWMClass=HD_Doc", "StartupWMClass=HD_Doc" in d)
        # 全套 hicolor 尺寸 + pixmaps 兜底（单尺寸安装会让 GNOME 显示
        # 默认齿轮状兜底图标——用户反馈"图标跟设置的一样"）
        icon_root = env["HD_DOC_ICON_ROOT"]
        got_sizes = sorted(os.listdir(icon_root)) if os.path.isdir(icon_root) else []
        check("hicolor 全套尺寸已安装",
              got_sizes == ["128x128", "256x256", "48x48", "512x512", "64x64"],
              got_sizes)
        for sz in got_sizes:
            p = os.path.join(icon_root, sz, "apps", "hd-doc.png")
            check("图标 %s/apps/hd-doc.png" % sz, os.path.isfile(p))
        check("pixmaps 兜底图标",
              os.path.isfile(os.path.join(env["HD_DOC_PIXMAPS"],
                                          "hd-doc.png")))

        # 卸载
        r3 = subprocess.run(["sh", os.path.join(src, "uninstall.sh"),
                             "--prefix", prefix],
                            capture_output=True, text=True, env=env, timeout=120)
        check("uninstall.sh 退出码 0", r3.returncode == 0, r3.stderr.strip())
        check("卸载后目录已删除", not os.path.exists(prefix))
        check("卸载后启动器已删除", not os.path.exists(launcher))
        icon_root = env["HD_DOC_ICON_ROOT"]
        left = [os.path.join(icon_root, sz, "apps", "hd-doc.png")
                for sz in os.listdir(icon_root)
                if os.path.isfile(os.path.join(icon_root, sz, "apps",
                                               "hd-doc.png"))] \
            if os.path.isdir(icon_root) else []
        check("卸载后 hicolor 图标全部删除", not left, left)
        check("卸载后 pixmaps 图标已删除",
              not os.path.isfile(os.path.join(env["HD_DOC_PIXMAPS"],
                                              "hd-doc.png")))

        # 负例：危险目录
        r4 = subprocess.run(["sh", os.path.join(src, "install.sh"), "--prefix", "/"],
                            capture_output=True, text=True, env=env, timeout=60)
        check("拒绝安装到 / ", r4.returncode != 0 and "危险" in (r4.stderr + r4.stdout))
        # 负例：未知参数
        r5 = subprocess.run(["sh", os.path.join(src, "install.sh"), "--bogus"],
                            capture_output=True, text=True, env=env, timeout=60)
        check("拒绝未知参数", r5.returncode != 0 and "未知参数" in (r5.stderr + r5.stdout))
        # --help 不需要 root
        r6 = subprocess.run(["sh", os.path.join(src, "install.sh"), "--help"],
                            capture_output=True, text=True, env=env, timeout=60)
        check("--help 正常输出用法", r6.returncode == 0 and "用法" in r6.stdout)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n" + "=" * 50)
    if FAILED:
        print("失败 %d 项: %s" % (len(FAILED), FAILED))
        sys.exit(1)
    print("全部校验通过 ✔")


if __name__ == "__main__":
    main()
