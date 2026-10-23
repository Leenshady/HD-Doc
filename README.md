# HD Doc

A read-only disk error scanner in the HD Tune style, built on the fio IO engine.
It reads every block of a disk or image file, draws a heat map of read latency,
and lists the blocks that fail to read. Nothing is ever written to the target.

Runs on Windows (admin rights required for physical disks) and Linux.

[中文说明](README.zh-CN.md)

## Features

- Heat map with a fixed 256-cell grid (same layout for every scan, so the
  UI stays consistent); cells split the disk into equal byte ranges and
  segment stats are aggregated per cell. Two switchable modes:
  **Disk health** (green = OK, red = read error — HD Tune error-scan
  semantics) and **Read speed** (green = fast, yellow = slow, red = read
  error, latency against adaptive median-based thresholds). Gray always
  means "not scanned yet", never a verdict. Cells render **one at a time**
  as segments complete — a segment spanning several cells lights them
  sequentially, never a whole batch at once — so the map fills in step
  with the scan. The grid re-tiles itself when
  you resize the window; quick scan lights whole regions (the head sample
  represents its region, hover shows sample size vs region span), leaving
  no unsampled gray cells
- Error block list with errno interpretation
- Quick scan: reads only a head sample of each region, like HD Tune Quick
  Scan — it shares the same segment setting as full scans (default 4G): the
  disk is split into regions of the chosen segment size and only the first
  16MB of each region is read, so the region count = ⌈capacity/segment⌉
  (1TB disk at 4G → 233 regions); "whole disk at once" (no segment size
  given) splits evenly up to the region cap; a segment larger than the
  disk collapses into a single region
- On-demand reports: nothing is saved unless you export (segments.csv,
  errors.csv, summary.txt)
- GUI (PyQt5, light/dark themes) and CLI from the same code base;
  GUI is bilingual (English default, Chinese switchable, choice remembered).
  PyQt5 draws the whole interface itself, so the GUI looks identical on
  Windows, Ubuntu and Kylin and scales natively on HiDPI screens
- Read-only by design: no writes to the target at any point

## Usage

GUI:

```
python HD_Doc.py
```

Pick a target from the dropdown, choose block size and segment size
(default **4G**; "whole disk at once" or 512M–64G), press **Start scan**.
A segment can span several heatmap cells — cells light up **one at a time**
as each segment completes (never a whole batch at once), so the map fills
in step with the scan (CLI: `--segment-gb` defaults to 4 as well, `0` for a
single whole-disk pass, or an explicit size). The
heatmap re-tiles itself whenever you resize the window, and the *Heatmap*
dropdown switches between **Disk health** (green/red by read errors) and
**Read speed** (green/yellow/red by latency). Switch language or
light/dark theme from the *Language* / *View* menus — both take effect
immediately (the interface is rebuilt or re-themed in place, no restart;
both choices are remembered). You can even switch while a scan is running:
the scan, its progress and results are untouched.

CLI (English output):

```
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --bs 4M
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --quick
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --export reports
```

Scanning a physical disk needs administrator rights. The GUI asks for
elevation via UAC right at startup — before the window appears, not when
a scan starts; declining keeps the program running unelevated (image
files still work). The CLI asks when a physical disk is scanned. On Linux
the equivalent is root (see below). Disable the automatic request with
`--no-elevate`. Image files need no special rights.

`--export [DIR]` writes the report into `DIR/HD_Doc_report_<timestamp>/`.
Without it, no files are written. `--help` lists all options.

## Running the GUI on Linux (Ubuntu / Galaxy Kylin)

The quickest path is the prebuilt install package (see "Build the Linux
install packages" below):

```bash
chmod +x HD_Doc-1.0-linux.run
sudo ./HD_Doc-1.0-linux.run        # installs dependencies, venv, menu entry
hd-doc                              # launch any time (or search "HD Doc" in the app menu)
```

From source:

```bash
# 1. Install dependencies: PyQt5 (GUI) + fio (IO engine)
sudo apt update
sudo apt install python3-pyqt5 fio

# 2. (Optional) a venv keeps things tidy; system Python works too.
#    Kylin V10 / Ubuntu 20.04 ship python3-pyqt5 in their repos;
#    PyQt6 has no distro package, so PyQt5 is the version we target.
#    ttkbootstrap is gone — the GUI now draws itself with PyQt5.
python3 -m venv ~/.venv/hddoc && ~/.venv/hddoc/bin/pip install -r requirements.txt

# 3. Start (root is required for physical disks; not for image files)
sudo ~/.venv/hddoc/bin/python HD_Doc.py        # from a terminal as root (recommended)
./HD_Doc.py                                    # or without sudo: image files / just looking
```

Notes:

- The target dropdown lists **whole physical disks only** (`/dev/sda`,
  `/dev/nvme0n1`, `/dev/vdb`, ... with model and capacity), same experience
  as on Windows; virtual block devices from `lsblk` (loop mounts for snaps,
  zram, dm/md, optical drives) are filtered out; you can also type a device
  path by hand
- **Clicking the app icon runs as root**: an unelevated start pops up the
  pkexec authorization prompt before the window appears (same flow as the
  Windows UAC, available on the Ubuntu / Galaxy Kylin desktop by default;
  `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` are forwarded, so UKUI's Wayland
  sessions work too); cancel to keep standard rights, or click
  **"Restart as root"** in the button bar at any time; without pkexec, run
  `sudo python3 HD_Doc.py` from a terminal as instructed
- Image files (e.g. `dd` output) need no root — just pick the file
- The default engine is `libaio` (ships with the usual fio builds); some
  minimal builds only offer `psync`/`posixaio` — switch it in the dropdown,
  available engines are probed automatically

### The prompt appears and vanishes / no window after authorizing?

If the authorization prompt flashes away, or the main window never shows up
after entering the password, the elevated instance almost certainly died on
startup because it could not reach the graphical display (pkexec closes its
window as soon as the target process exits — which looks like "the prompt
disappeared by itself"). Work through this list:

1. **Read the in-app hint**: when pkexec exits non-zero, the original window
   stays and shows a yellow banner pointing at the environment snapshot log
   (`/tmp/hd-doc-elevated-<pid>.log` by default, override with
   `HDTUNE_ELEV_LOG`)
2. **Compare the snapshot**: the first thing the elevated instance does is
   write `DISPLAY`, `XAUTHORITY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`,
   `QT_QPA_PLATFORM` and friends into that file; diff them against the same
   variables in your own session — the usual suspects are a `DISPLAY` that
   `sudo` scrubbed, or an `XAUTHORITY` pointing somewhere root cannot read
   (check with `xauth list`)
3. **Wayland sessions (UKUI/KDE)**: make sure `WAYLAND_DISPLAY` and
   `XDG_RUNTIME_DIR` are non-empty in the snapshot; on some distros root's
   Qt cannot use Wayland — force the X11 compatibility layer with
   `export QT_QPA_PLATFORM=xcb` before starting
4. **Still stuck? Elevate from a terminal** (skips the graphical prompt and
   prints errors straight to the screen):

```bash
sudo python3 HD_Doc.py        # run from source
sudo hd-doc                    # installed package
```

Note: authorization is waited on for up to 90 seconds (`HDTUNE_ELEVATE_WAIT`
to change) — typing the password slowly no longer makes the prompt vanish.
The parent process only steps aside once the elevated instance's window is
really up (a `READY` line in the snapshot file); on timeout the prompt is
closed and the app starts with standard rights, with a banner explaining it.

## Language files

Interface strings live in `lang/<code>.json` — one file per language,
auto-discovered at startup. There is no language list in code. Each
file names itself with a reserved `_meta` block:

```json
{
  "_meta": { "name": "中文", "name_en": "Chinese (Simplified)" },
  "status.ok": "正常",
  "...": "..."
}
```

The file name (minus `.json`) is the language code; `_meta.name` is the
language's own name, used as the label in the *Language* menu. To add a
language: copy `lang/en.json`, translate the values, set `_meta.name`,
save as `lang/<code>.json` — the menu, the config validation and the
English fallback all follow automatically, no code change. Files whose
name starts with `_` or `.` are treated as templates and skipped;
missing keys fall back to English.

## Run log

Every run appends its key events to a single log file — `HD_Doc.log`
next to the config (`%APPDATA%\HD_Doc\HD_Doc.log` on Windows,
`~/.config/HD_Doc/` elsewhere): startup, scan start with its full
parameters, the result summary, report export, language/theme changes,
and any exception with its traceback (including uncaught Qt callback
exceptions, which otherwise only reach stderr and are invisible in the
windowed build). Example:

```
2026-10-19 12:23:00.014 [INFO] startup: ver=1.0 mode=cli frozen=False admin=True argv=--cli --target ...
2026-10-19 12:23:00.168 [INFO] cli: plan target=... size=8.0 MB bs=512.0 KB segments=1 engine=windowsaio direct=True quick=False fio=C:\Program Files\fio\fio.EXE
2026-10-19 12:23:00.997 [INFO] cli: finished target=... blocks=16 ok=16 slow=0 bad=0 errors=0 aborted=False stopped=False elapsed=0.8s
```

There is always exactly one file: past 512 KB it is truncated and
rewritten from the top, so no per-date or per-run logs pile up. Send
this one file when reporting a problem.

- `HD_DOC_LOG_DIR=<dir>` moves the log (tests, portable setups)
- `HD_DOC_LOG=off` disables it entirely

Logging never raises: an unwritable path is silently ignored, so it can
not break a scan.

## Build the executable

```
python build_exe.py
```

Produces two single-file variants in `dist/`, for whichever platform the
script runs on (PyInstaller does not cross-compile):

| Platform | File | fio | Size | Use when |
|----------|------|-----|------|----------|
| Windows | `HD_Doc.exe` | bundled | ~65 MB | distributing to machines without fio |
| Windows | `HD_Doc_NoFio.exe` | not bundled | ~63 MB | fio is already installed, or you pass `--fio PATH` |
| Linux | `HD_Doc` | bundled (needs fio on the build machine) | ~62 MB | run on Ubuntu without a Python environment |
| Linux | `HD_Doc_NoFio` | not bundled | ~60 MB | fio is already installed, or you pass `--fio PATH` |

Both bundle the `lang/` files and the `img/` icon; runtime behavior is
identical. `--variant fio` / `--variant nofio` builds just one,
`--onedir` switches to directory mode. Requires a Python with PyQt5
(`--collect-all PyQt5` bundles the Qt libs) and PyInstaller (see
`requirements.txt`). `--version` reports where fio comes from
(`bundled` / `not bundled`). A Linux build still needs root for physical
disks: `sudo ./dist/HD_Doc`.

## Build the Linux install packages

```
python build_linux_pkg.py
```

Builds on **any machine** (Windows included) and puts the results in
`dist/`:

| File | Form | Use |
|------|------|-----|
| `HD_Doc-1.0-kylin.deb` | native deb package | Galaxy Kylin / Ubuntu / Deepin / UOS — apt install, package-managed removal |
| `HD_Doc-1.0-linux.run` | self-extracting installer | any Linux; hand it to users, one command installs |
| `HD_Doc-1.0-linux.tar.gz` | source archive | manual install, or fold into your deployment |
| `*.sha256` | checksums | transfer integrity |

Since PyInstaller cannot cross-compile, these are **source install
packages** (pure Python, architecture independent — x86_64, arm64 and
loongarch alike): on the target machine they check dependencies, create
a venv, install PyQt5 and register the menu entry. Nothing needs
to be prepared on the target machine.

### Galaxy Kylin (银河麒麟)

**Kylin Desktop V10 (and openKylin / Deepin / UOS — all deb based):**

```bash
# Option 1: native deb package (recommended, uses the system package manager)
sudo apt install ./HD_Doc-1.0-kylin.deb
sudo apt remove hd-doc            # uninstall (apt purge hd-doc also removes config)

# Option 2: self-extracting installer (any Linux)
chmod +x HD_Doc-1.0-linux.run
sudo ./HD_Doc-1.0-linux.run                 # install (-y for unattended)
sudo ./HD_Doc-1.0-linux.run --uninstall     # uninstall (--uninstall --purge also removes config)

# Option 3: tarball
tar xzf HD_Doc-1.0-linux.tar.gz
sudo ./HD_Doc-1.0/install.sh                 # install
sudo ./HD_Doc-1.0/uninstall.sh               # uninstall
```

**Kylin Advanced Server V10 (rpm based, no GUI, CLI only):** use the
`.run` or `.tar.gz`; when `install.sh` finds no apt it switches to
dnf/yum automatically (`fio`, `python3-qt5`), then run
`hd-doc --cli --target /dev/sda`.

What the installer does:

1. Identifies the distro (`/etc/os-release`; Kylin/openKylin get their
   own note), checks `python3 >= 3.8`, PyQt5 and `fio`; missing
   pieces are installed via apt (deb based) or dnf/yum (rpm based)
   after a prompt (`-y` skips the prompt, `--no-apt` never touches a
   package manager, `--no-fio` skips fio)
2. Copies the program to `/opt/hd-doc` (`--prefix DIR` to change it) and
   creates a venv with `requirements.txt`; falls back to the system
   Python automatically if a venv is not possible
3. Writes the launcher `/usr/local/bin/hd-doc` (one entry point for GUI
   and CLI), the desktop menu entry and the icon; the actual install
   paths are recorded in `/var/lib/hd-doc/install.manifest` so that
   uninstall cleans up correctly even for a custom prefix

After changing the packaged content, rebuild and self-check:

```bash
python build_linux_pkg.py && python packaging/linux/validate_pkg.py
```

`validate_pkg.py` verifies archive integrity (file tree, permission
bits, LF line endings, no duplicate members), the `.run` extraction
chain, sha256 sums and bilingual key parity, and runs a **simulated
install and uninstall** with stubbed `id`/`python3` — everything stays
in a temp directory, your system `/opt` and `/usr` are never touched.
For the `.deb` it checks the ar structure, control fields
(dependencies/architecture/version), maintainer script syntax and the
data.tar path whitelist, and confirms it is byte-identical in content
to the tarball payload.

## Tests

```
python test/test_units.py          # core logic + i18n
python test/test_integration.py    # fio engine, reports, regressions
python test/test_gui_smoke.py      # GUI behavior incl. language/theme switch
python test/test_gui_stop.py       # stop / race conditions
python test/test_gui_quick.py      # quick scan end to end
python test/test_cli_stop.py       # CLI Ctrl+C handling
python test/test_cli_gate.py       # elevation gate + CLI scan
python test/test_gui_gate.py       # elevation gate in GUI
python test/test_hdd_stop.py       # real hardware mid-scan stop
python test/test_job_kill.py       # fio dies with parent / parent watch (Task Manager kill)
```

The fio-based suites need `fio` on the machine (on Windows
`C:\Program Files\fio\fio.exe` is picked up automatically; on Linux the
`fio` on PATH or `/usr/bin/fio`).

## Layout

```
HD_Doc_core.py  business logic: elevation, segments, fio engine, reports
                (no UI dependency; loads lang/*.json)
HD_Doc_cli.py   command-line front end (English only)
HD_Doc_gui.py   PyQt5 GUI (bilingual, light/dark theme, self-drawn widgets)
HD_Doc.py       entry point: dispatches to CLI or GUI
build_exe.py    PyInstaller packaging (Windows/Linux single-file executables)
build_linux_pkg.py  Linux install package builder (.deb native + .run + .tar.gz)
make_icon.py    app icon generation (PIL: 1024 master + hicolor set + multi-res .ico)
packaging/linux/    installer scripts (install.sh / uninstall.sh) and package validator
requirements.txt  runtime dependencies (PyQt5, for the GUI)
lang/           interface strings (en.json, zh.json)
img/            program icon (HD_Doc.ico, HD_Doc.png)
test/           test suites (python test/test_units.py, ...)
```

## License

**GPL-3.0-or-later** — the full text is in [LICENSE](LICENSE). Redistribution
and reuse must keep the same license and provide source code.

### Authorship

This project was written **entirely by AI**. Signed: **WorkBuddy**.

The publisher's role was limited to providing prompts, requirements, and
testing — no human-authored code is included in this repository.

---

*Written entirely by AI — signed, **WorkBuddy**, 2026.*
