# HD Doc

A read-only disk error scanner in the HD Tune style, built on the fio IO engine.
It reads every block of a disk or image file, draws a heat map of read latency,
and lists the blocks that fail to read. Nothing is ever written to the target.

Runs on Windows (admin rights required for physical disks) and Linux.

## Features

- Heat map with a fixed 256-cell grid (same layout for every scan, so the
  UI stays consistent); cells split the disk into equal byte ranges and
  segment stats are aggregated per cell, colored by latency against
  adaptive thresholds (median-based, so slow disks are not all red);
  quick scan lights whole regions (the head sample represents its region,
  hover shows sample size vs region span), leaving no unsampled gray cells
- Error block list with errno interpretation
- Quick scan: reads only a head sample of each region, like HD Tune Quick Scan
- On-demand reports: nothing is saved unless you export (segments.csv,
  errors.csv, summary.txt)
- GUI (ttkbootstrap, light/dark themes) and CLI from the same code base;
  GUI is bilingual (English default, Chinese switchable, choice remembered)
- Read-only by design: no writes to the target at any point

## Usage

GUI:

```
python HD_Doc.py
```

Pick a target from the dropdown, choose block size, press **Start scan**.
Segmentation is automatic: the disk is divided into 256 segments — one per
heatmap cell — so every segment's stats map directly onto one cell (CLI:
`--segment-gb 0` for a single whole-disk pass, or an explicit size). The
heatmap re-tiles itself whenever you resize the window. Switch language or
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

## Running the GUI on Ubuntu

The quickest path is the prebuilt install package (see "Build the Ubuntu
install package" below):

```bash
chmod +x HD_Doc-1.0-ubuntu.run
sudo ./HD_Doc-1.0-ubuntu.run        # installs dependencies, venv, menu entry
hd-doc                              # launch any time (or search "HD Doc" in the app menu)
```

From source:

```bash
# 1. Install dependencies: tkinter (GUI) + fio (IO engine)
sudo apt update
sudo apt install python3-tk fio

# 2. Install ttkbootstrap (a venv is recommended over system Python)
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
  Windows UAC, available on the Ubuntu desktop by default); cancel to keep
  standard rights, or click **"Restart as root"** in the button bar at any
  time; without pkexec, run `sudo python3 HD_Doc.py` from a terminal as
  instructed
- Image files (e.g. `dd` output) need no root — just pick the file
- The default engine is `libaio` (ships with the usual fio builds); some
  minimal builds only offer `psync`/`posixaio` — switch it in the dropdown,
  available engines are probed automatically

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
and any exception with its traceback (including uncaught Tk callback
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
| Windows | `HD_Doc.exe` | bundled | ~31 MB | distributing to machines without fio |
| Windows | `HD_Doc_NoFio.exe` | not bundled | ~29 MB | fio is already installed, or you pass `--fio PATH` |
| Linux | `HD_Doc` | bundled (needs fio on the build machine) | ~35 MB | run on Ubuntu without a Python environment |
| Linux | `HD_Doc_NoFio` | not bundled | ~33 MB | fio is already installed, or you pass `--fio PATH` |

Both bundle the `lang/` files and the `img/` icon; runtime behavior is
identical. `--variant fio` / `--variant nofio` builds just one,
`--onedir` switches to directory mode. Requires a Python with tkinter
and PyInstaller, plus `pip install ttkbootstrap` (see
`requirements.txt`). `--version` reports where fio comes from
(`bundled` / `not bundled`). A Linux build still needs root for physical
disks: `sudo ./dist/HD_Doc`.

## Build the Ubuntu install package

```
python build_ubuntu_pkg.py
```

Builds on **any machine** (Windows included) and puts the results in
`dist/`:

| File | Form | Use |
|------|------|-----|
| `HD_Doc-1.0-ubuntu.run` | self-extracting installer | hand it to users; one command installs |
| `HD_Doc-1.0-ubuntu.tar.gz` | source archive | manual install, or fold into your deployment |
| `*.sha256` | checksums | transfer integrity |

Since PyInstaller cannot cross-compile, this is a **source install
package** (pure Python, architecture independent — x86_64 and arm64
alike): on the target machine it checks dependencies, creates a venv,
installs ttkbootstrap and registers the menu entry. Nothing needs to be
prepared on the target machine.

Using the package (on Ubuntu):

```bash
# Option 1: self-extracting installer (recommended)
chmod +x HD_Doc-1.0-ubuntu.run
sudo ./HD_Doc-1.0-ubuntu.run                 # install (-y for unattended)
sudo ./HD_Doc-1.0-ubuntu.run --uninstall     # uninstall (--uninstall --purge also removes config)

# Option 2: tarball
tar xzf HD_Doc-1.0-ubuntu.tar.gz
sudo ./HD_Doc-1.0/install.sh                 # install
sudo ./HD_Doc-1.0/uninstall.sh               # uninstall
```

What the installer does:

1. Checks `python3 >= 3.8`, `tkinter` and `fio`; missing pieces are
   installed via `apt` after a prompt (`-y` skips the prompt, `--no-apt`
   never touches apt, `--no-fio` skips fio)
2. Copies the program to `/opt/hd-doc` (`--prefix DIR` to change it) and
   creates a venv with `requirements.txt`; falls back to the system
   Python automatically if a venv is not possible
3. Writes the launcher `/usr/local/bin/hd-doc` (one entry point for GUI
   and CLI), the desktop menu entry and the icon; the actual install
   paths are recorded in `/var/lib/hd-doc/install.manifest` so that
   uninstall cleans up correctly even for a custom prefix

After changing the packaged content, rebuild and self-check:

```bash
python build_ubuntu_pkg.py && python packaging/ubuntu/validate_pkg.py
```

`validate_pkg.py` verifies archive integrity (file tree, permission
bits, LF line endings, no duplicate members), the `.run` extraction
chain, sha256 sums and bilingual key parity, and runs a **simulated
install and uninstall** with stubbed `id`/`python3` — everything stays
in a temp directory, your system `/opt` and `/usr` are never touched.

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
```

The fio-based suites need `fio` on the machine (on Windows
`C:\Program Files\fio\fio.exe` is picked up automatically; on Linux the
`fio` on PATH or `/usr/bin/fio`).

## Layout

```
HD_Doc_core.py  business logic: elevation, segments, fio engine, reports
                (no UI dependency; loads lang/*.json)
HD_Doc_cli.py   command-line front end (English only)
HD_Doc_gui.py   ttkbootstrap GUI (bilingual, light/dark theme)
HD_Doc.py       entry point: dispatches to CLI or GUI
build_exe.py    PyInstaller packaging (Windows/Linux single-file executables)
build_ubuntu_pkg.py  Ubuntu install package builder (.run + .tar.gz)
make_icon.py    app icon generation (PIL: 1024 master + hicolor set + multi-res .ico)
packaging/ubuntu/    installer scripts (install.sh / uninstall.sh) and package validator
requirements.txt  runtime dependencies (ttkbootstrap, for the GUI)
lang/           interface strings (en.json, zh.json)
img/            program icon (HD_Doc.ico, HD_Doc.png)
test/           test suites (python test/test_units.py, ...)
```

## License

MIT
