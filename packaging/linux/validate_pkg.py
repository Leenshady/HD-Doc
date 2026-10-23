#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_pkg.py —— 校验 build_linux_pkg.py 产出的 Linux 安装包

检查项:
  1. .run 自解压头：shebang、shell 语法（sh -n）、载荷标记唯一、声明支持麒麟
  2. 从 .run 抽出载荷 → 解 tar → 核对文件树、权限位、属主、行尾（LF）
  3. tar.gz 与 .run 内嵌载荷内容一致
  4. .sha256 校验和匹配
  5. lang/ 双语 key 一致、JSON 可解析
  6. 模拟安装 dry-run（stub id/python3，全部路径落在临时目录，
     不碰系统 /opt、/usr）—— 验证 install.sh 全流程逻辑
  7. .deb（麒麟/Ubuntu 原生包）：ar 结构、control 字段、维护脚本语法、
     data.tar 路径白名单/权限/属主、与 tar.gz 载荷同源

用法: python validate_pkg.py [dist/HD_Doc-<版本>-linux.run]
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


def sh_syntax_ok(data, suffix=".sh"):
    """把字节写入临时文件跑 sh -n，返回 (ok, err)"""
    with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as tf:
        tf.write(data)
        path = tf.name
    try:
        r = subprocess.run(["sh", "-n", path], capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip()
    finally:
        os.unlink(path)


def ar_members(data):
    """解析 ar 归档（.deb 容器）→ {name: bytes}；校验 magic 与成员完整性"""
    if not data.startswith(b"!<arch>\n"):
        raise SystemExit("[错误] .deb 不是合法 ar 归档（缺 !<arch> 魔数）")
    out = {}
    pos = 8
    while pos < len(data):
        hdr = data[pos:pos + 60]
        if len(hdr) < 60:
            raise SystemExit("[错误] ar 成员头截断（offset %d）" % pos)
        name = hdr[0:16].decode("ascii").rstrip()
        size = int(hdr[48:58].decode("ascii").strip())
        body = data[pos + 60:pos + 60 + size]
        if len(body) != size:
            raise SystemExit("[错误] ar 成员 %s 数据截断" % name)
        out[name] = body
        pos += 60 + size + (size % 2)      # ar 要求成员 2 字节对齐
    return out


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
            raise SystemExit("[错误] dist/ 下没有 .run，请先运行 build_linux_pkg.py")
        run_path = os.path.join(DIST, sorted(cands)[0])
    print("校验安装包: %s\n" % run_path)

    # ---------- 1. .run 头部 ----------
    print("== 1. 自解压头 ==")
    header, payload = split_run(run_path)
    check("shebang 为 #!/bin/sh", header.startswith(b"#!/bin/sh"))
    ok, err = sh_syntax_ok(header)
    check("头部 shell 语法（sh -n）", ok, err)
    check("头部声明支持银河麒麟", "麒麟" in header.decode("utf-8", "replace"))

    # ---------- 2. 载荷内容 ----------
    print("\n== 2. 载荷文件树/权限/行尾 ==")
    members = tar_members(payload)
    tops = {n.split("/")[0] for n in members}
    check("唯一顶层目录", len(tops) == 1, tops)
    top = tops.pop()
    ver = top.split("-")[-1]

    need_files = ["HD_Doc.py", "HD_Doc_core.py", "HD_Doc_gui.py",
                  "HD_Doc_cli.py", "requirements.txt", "README.md",
                  "README.zh-CN.md", "LICENSE", "install.sh", "uninstall.sh",
                  "lang/en.json", "lang/zh.json", "img/HD_Doc.png",
                  "img/hd-doc-256.png"]
    for f in need_files:
        check("包含 %s" % f, "%s/%s" % (top, f) in members)
    # GPL 硬性要求：随包分发的许可文本必须是完整 GPL-3.0（含 17 章与
    # 应用指引），且带有本项目的版权/作者声明头
    lic_txt = members["%s/LICENSE" % top][1].decode("utf-8")
    check("LICENSE 为完整 GPL-3.0",
          ("GNU GENERAL PUBLIC LICENSE" in lic_txt
           and "END OF TERMS AND CONDITIONS" in lic_txt
           and "How to Apply These Terms to Your New Programs" in lic_txt
           and "17. Interpretation of Sections 15 and 16." in lic_txt))
    check("LICENSE 含项目版权与 AI 作者声明",
          ("HD Doc" in lic_txt and "WorkBuddy" in lic_txt
           and "entirely by AI" in lic_txt))

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
    tgz = os.path.join(DIST, "HD_Doc-%s-linux.tar.gz" % ver)
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

    # ---------- 7. .deb（麒麟/Ubuntu 原生包） ----------
    print("\n== 7. .deb 原生包（银河麒麟/Ubuntu） ==")
    deb_path = os.path.join(DIST, "HD_Doc-%s-kylin.deb" % ver)
    if check(".deb 存在", os.path.isfile(deb_path)):
        ar = {}
        try:
            ar = ar_members(open(deb_path, "rb").read())
            check("ar 结构可解析", True)
        except SystemExit as e:
            check("ar 结构可解析", False, e)
        check("ar 成员 = debian-binary/control.tar.gz/data.tar.gz",
              set(ar) == {"debian-binary", "control.tar.gz", "data.tar.gz"},
              sorted(ar))
        check("debian-binary 版本 2.0", ar.get("debian-binary") == b"2.0\n")

        ctl = {}
        if "control.tar.gz" in ar:
            try:
                ctl = tar_members(ar["control.tar.gz"])
            except SystemExit as e:
                check("control.tar.gz 可解析", False, e)
        if ctl:
            for script in ("./control", "./postinst", "./postrm"):
                check("control.tar 含 %s" % script, script in ctl)
            if "./control" in ctl:
                fields = {}
                for ln in ctl["./control"][1].decode("utf-8").splitlines():
                    if ln.startswith(" ") or ":" not in ln:
                        continue          # 续行 / 分隔行
                    k, v = ln.split(":", 1)
                    fields[k.strip()] = v.strip()
                check("Package=hd-doc", fields.get("Package") == "hd-doc",
                      fields.get("Package"))
                check("Architecture=all（与 CPU 架构无关）",
                      fields.get("Architecture") == "all",
                      fields.get("Architecture"))
                check("Version=%s" % ver, fields.get("Version") == ver,
                      fields.get("Version"))
                dep = fields.get("Depends", "")
                for p in ("python3", "python3-pyqt5", "python3-venv", "fio",
                          "policykit-1"):
                    check("Depends 含 %s" % p, p in dep, dep)
                check("Installed-Size 为正整数",
                      fields.get("Installed-Size", "").isdigit(),
                      fields.get("Installed-Size"))
                check("Description 非空",
                      len(fields.get("Description", "")) > 10)
            for script in ("./postinst", "./postrm"):
                if script not in ctl:
                    continue
                m, b = ctl[script]
                check("%s 权限 0755" % script, m.mode == 0o755, oct(m.mode))
                check("%s 属主 root" % script, m.uid == 0 and m.gid == 0)
                check("%s LF 行尾" % script, b"\r" not in b)
                ok, err = sh_syntax_ok(b)
                check("%s 语法（sh -n）" % script, ok, err)

        data = {}
        if "data.tar.gz" in ar:
            try:
                data = tar_members(ar["data.tar.gz"])
            except SystemExit as e:
                check("data.tar.gz 可解析", False, e)
        if data:
            check("所有路径以 ./ 开头", all(n.startswith("./") for n in data))
            check("无 .. 路径穿越",
                  not any(".." in n.split("/") for n in data))
            # 顶层目录（./opt、./usr 等）本身合法，其下必须落在白名单内
            top_ok = ("./opt", "./usr", "./var", "./etc", "./lib")
            allowed = ("./opt/hd-doc", "./usr/bin", "./usr/share",
                       "./usr/lib", "./var/lib", "./etc")
            bad = [n for n in data
                   if n not in top_ok
                   and not any(n == p or n.startswith(p + "/")
                               for p in allowed)]
            check("路径白名单（/opt/hd-doc、/usr、/var/lib）", not bad, bad[:5])
            check("属主 root(0)",
                  all(m.uid == 0 and m.gid == 0 for m, _ in data.values()))
            check("权限位仅 0755/0644",
                  all(m.mode in (0o755, 0o644) for m, _ in data.values()))
            check("无符号链接", all(m.isfile() or m.isdir()
                                   for m, _ in data.values()))
            if "./usr/bin/hd-doc" in data:
                check("启动器 /usr/bin/hd-doc 0755",
                      data["./usr/bin/hd-doc"][0].mode == 0o755)
                body = data["./usr/bin/hd-doc"][1].decode("utf-8")
                check("启动器引用 /opt/hd-doc", "/opt/hd-doc" in body)
            if "./opt/hd-doc/HD_Doc.py" in data:
                check("HD_Doc.py 0755",
                      data["./opt/hd-doc/HD_Doc.py"][0].mode == 0o755)
            if "./usr/share/applications/hd-doc.desktop" in data:
                d = data["./usr/share/applications/hd-doc.desktop"][1] \
                    .decode("utf-8")
                check("desktop Exec=hd-doc", "Exec=hd-doc" in d)
                check("desktop Icon=hd-doc", "Icon=hd-doc" in d)
                check("desktop StartupWMClass=HD_Doc",
                      "StartupWMClass=HD_Doc" in d)
            icons = sorted(n for n in data
                           if n.startswith("./usr/share/icons/hicolor/")
                           and n.endswith("hd-doc.png"))
            check("hicolor 全套 5 尺寸图标", len(icons) == 5, icons)
            check("pixmaps 兜底图标",
                  "./usr/share/pixmaps/hd-doc.png" in data)
            check("lang/en.json 已打包",
                  "./opt/hd-doc/lang/en.json" in data)
            # deb 与 tar.gz 载荷同源（/opt/hd-doc 下逐字节一致）
            diff = [n for n, (_m, buf) in data.items()
                    if n.startswith("./opt/hd-doc/")
                    and ("%s/%s" % (top, n[len("./opt/hd-doc/"):])) in members
                    and members["%s/%s" % (top, n[len("./opt/hd-doc/"):])][1]
                    != buf]
            check("deb 与 tar.gz 载荷同源（/opt/hd-doc 逐字节一致）",
                  not diff, diff[:5])

        sf = deb_path + ".sha256"
        if check(".deb.sha256 存在", os.path.isfile(sf)):
            want = open(sf, encoding="utf-8").read().split()[0]
            got = hashlib.sha256(open(deb_path, "rb").read()).hexdigest()
            check(".deb 校验和匹配", want == got)

    print("\n" + "=" * 50)
    if FAILED:
        print("失败 %d 项: %s" % (len(FAILED), FAILED))
        sys.exit(1)
    print("全部校验通过 ✔")


if __name__ == "__main__":
    main()
