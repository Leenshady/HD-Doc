# HD Doc

A read-only disk error scanner in the HD Tune style, built on the fio IO engine.
It reads every block of a disk or image file, draws a heat map of read latency,
and lists the blocks that fail to read. Nothing is ever written to the target.

Runs on Windows (admin rights required for physical disks) and Linux.

## Features

- Block-level heat map: each cell is one scan segment, colored by latency
  against adaptive thresholds (median-based, so slow disks are not all red)
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

Pick a target from the dropdown, choose block size / segment size, press
**Start scan**. Switch language or light/dark theme from the *Language* /
*View* menus — both take effect immediately (the interface is rebuilt or
re-themed in place, no restart; both choices are remembered). You can
even switch while a scan is running: the scan, its progress and results
are untouched.

CLI (English output):

```
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --bs 4M
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --quick
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --export reports
```

Scanning a physical disk needs administrator rights. The GUI asks for
elevation via UAC right at startup — before the window appears, not when
a scan starts; declining keeps the program running unelevated (image
files still work). The CLI asks when a physical disk is scanned. Disable
the automatic request with `--no-elevate`. Image files need no special
rights.

`--export [DIR]` writes the report into `DIR/HD_Doc_report_<timestamp>/`.
Without it, no files are written. `--help` lists all options.

## Language files

Interface strings live in `lang/en.json` and `lang/zh.json`, loaded at
runtime. To add a language, drop a `lang/<code>.json` with the same keys
and register the code in `LANGUAGES` in `HD_Doc_core.py`.

## Build the Windows executable

```
python build_exe.py
```

Produces `dist/HD_Doc.exe` (single file). fio.exe, the `lang/` files and the
`img/` icon are bundled when found on the build machine. Requires a Python
with tkinter and PyInstaller, plus `pip install ttkbootstrap` (see
`requirements.txt`).

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

The fio-based suites need `fio` on the machine (`C:\Program Files\fio\fio.exe`
is picked up automatically).

## Layout

```
HD_Doc_core.py  business logic: elevation, segments, fio engine, reports
                (no UI dependency; loads lang/*.json)
HD_Doc_cli.py   command-line front end (English only)
HD_Doc_gui.py   ttkbootstrap GUI (bilingual, light/dark theme)
HD_Doc.py       entry point: dispatches to CLI or GUI
build_exe.py    PyInstaller packaging
requirements.txt  runtime dependencies (ttkbootstrap, for the GUI)
lang/           interface strings (en.json, zh.json)
img/            program icon (HD_Doc.ico, HD_Doc.png)
test/           test suites (python test/test_units.py, ...)
```

## License

MIT
