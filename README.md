# hdtune_scan

A free, open-source, read-only disk health scanner inspired by HD Tune's Error Scan, built on the [fio](https://fio.readthedocs.io/) I/O engine with a Python/tkinter GUI.

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-blue" alt="platform">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/read--only-100%25-brightgreen" alt="read-only">
</p>

- **中文说明见 [README.zh-CN.md](README.zh-CN.md)**

## What it does

`hdtune_scan` reads every block of the selected disk (or disk image file) and renders the result as a grid heat map — exactly like HD Tune's Error Scan:

| Color | Meaning |
|-------|---------|
| Green | Normal read speed |
| Yellow | Slow (above the adaptive slow threshold) |
| Red | Very slow (above the adaptive very-slow threshold) |
| Dark red | Read error (fio reported an I/O error on that block) |
| Gray | Not scanned yet |

The tool is **strictly read-only**: it never writes a single byte to the target disk.

## Features

- **HD Tune style heat map** — block-level grid, responsive layout that adapts to the segment count
- **Quick scan** — HD Tune Quick Scan style: reads only a small sample at the head of each region and skips the rest (fast full-disk health check)
- **Adaptive thresholds** — slow/very-slow thresholds are derived from the measured median latency (`median x N` with configurable floors), so they work for both HDDs and SSDs
- **Error block list** — every failing block is listed with its offset, errno name, and status; per-segment error counts are shown in the heat map
- **On-demand export** — nothing is written to disk unless you ask for it:
  - CLI: `--export [DIR]` writes `segments.csv`, `errors.csv` and `summary.txt` into `DIR/hdtune_report_<timestamp>/`
  - GUI: an *Export* button asks for a directory and writes the same three files
- **GUI internationalization** — the GUI ships in English by default and can switch to Chinese at runtime (the choice is remembered); the CLI output is always English for scripts and logs
- **No popup spam** — scan results, warnings and export confirmations are shown as in-window banners and log lines; only two confirm dialogs remain (elevation consent and quit confirmation)
- **Automatic elevation** — scanning `\\.\PhysicalDriveN` requires administrator rights; the tool requests UAC elevation automatically (`--no-elevate` or `HDTUNE_NO_AUTO_ELEVATE=1` disables this)
- **Resizable window** — the whole layout scales with the window; the heat map reflows automatically
- **Standalone Windows build** — a single `.exe` (bundles `fio.exe` when found at build time), no Python installation needed on the target machine

## Requirements

- Windows 10/11 (uses the `windowsaio` fio engine)
- Python 3.9+ with tkinter (only for running from source / building the GUI)
- [fio](https://fio.readthedocs.io/) — either on `PATH` or bundled in the packaged `.exe`
- Administrator rights when scanning physical disks (`\\.\PhysicalDriveN`)

## Usage

### GUI mode

Double-click `hdtune_scan.exe`, or run:

```
python hdtune_scan.py
```

Pick a target (physical drive or image file), choose the block size, segment size (0 = whole disk at once) or the quick scan mode, then press **Start**.

Switch the interface language via **Language → English / 中文** in the menu bar. Program info is available under **Help → About**.

### CLI mode (English output only)

```
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --bs 4M
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --quick
python hdtune_scan.py --cli --target test.img --segment-gb 4 --export ./out
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --limit-mb 64   # first 64 MB only
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --no-elevate   # no auto UAC
python hdtune_scan.py --version
```

Without `--export`, no files are written at all — results are printed to the console only.
With `--export` (optionally followed by a directory, default `.`) the three report files are written after the scan:

```
hdtune_report_<timestamp>/
├── segments.csv   # per-segment stats: avg/min/max latency, slow & error block counts
├── errors.csv     # one row per failing block: offset, length, errno, status
└── summary.txt    # one-page summary of the scan
```

All CLI options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--target` | – | `\\.\PhysicalDriveN` or an image file path |
| `--bs` | `auto` | Block size, e.g. `4M` / `512K` / `auto` |
| `--segment-gb` | `4` | Segment size in GB; `0` = whole disk at once |
| `--quick` | off | Quick scan (region head sampling) |
| `--quick-sample-mb` | `16` | Quick-scan sample size per region (MB) |
| `--limit-mb` / `--offset-mb` | `0` | Scan only the first N MB / start at an offset |
| `--export [DIR]` | off | Export the report into `DIR/hdtune_report_<timestamp>/` |
| `--no-elevate` | off | Forbid automatic administrator elevation |
| `--fio` | – | Path to the `fio` executable |
| `--ioengine` | auto | fio ioengine (default `windowsaio`) |
| `--no-direct` | off | Disable `direct=1` |
| `--yellow-mult` / `--red-mult` | `3` / `8` | Slow / very-slow threshold = median x N |
| `--yellow-floor-ms` / `--red-floor-ms` | `10` / `100` | Threshold floors in ms |

## Project layout

UI and business logic are strictly separated — the CLI never touches any UI code:

```
hdtune_scan/
├── hdtune_core.py    # business logic: elevation, segment planning, fio engine,
│                     # drive enumeration, report export (zero tkinter dependency)
├── hdtune_cli.py     # CLI mode: imports hdtune_core only, English output
├── hdtune_gui.py     # tkinter GUI: imports hdtune_core only, i18n (en/zh)
├── hdtune_scan.py    # thin entry point: argument parsing & dispatch
├── build_exe.py      # PyInstaller packaging helper (single-file exe)
└── test_*.py         # test suite (see below)
```

## Building the Windows executable

```
python build_exe.py            # single-file -> dist/hdtune_scan.exe
python build_exe.py --onedir   # directory build (faster startup)
```

Requirements for building: PyInstaller and a Python with tkinter (the python.org installer bundles tkinter).
When `fio.exe` is found on the build machine it is embedded into the package automatically, so the produced `.exe` is self-contained.

## Running the tests

```
python test_units.py          # unit tests: i18n, thresholds, segment planning, report export
python test_integration.py    # report export (English + Chinese) on a synthetic disk image
python test_gui_smoke.py      # GUI: default English UI, quick scan, heat map, language switch, About
python test_gui_stop.py       # GUI: stop mid-scan (real hardware path + race conditions), banner behavior
python test_gui_quick.py      # GUI: quick scan, English tooltips, export
python test_cli_gate.py       # CLI: elevation gate (5 branches) + quick scan + --export
python test_gui_gate.py       # GUI: elevation gate (pythonw.exe target)
python test_cli_stop.py       # CLI: Ctrl+C mid-scan -> exit code 130, no report written
python test_hdd_stop.py       # real HDD: stop mid full scan, no false error blocks
```

## How it works

1. **Elevation** — if the target is `\\.\PhysicalDriveN` and the process is not elevated, the tool relaunches itself through UAC (`--no-elevate` to opt out).
2. **Planning** — the disk capacity is queried via `IOCTL_DISK_GET_LENGTH_INFO` (with a binary-search fallback for drives that do not support the ioctl), then the scan is split into segments (default 4 GB each; `0` = single pass). Quick scan samples the first N MB of each region instead.
3. **Scanning** — each segment is read by `fio` with sequential reads and `direct=1`; the streamed JSON output is parsed block by block. Each block gets a latency, a status (`ok` / `slow` / `bad` / `error`) and, on failure, the Windows errno name.
4. **Thresholds** — slow = `max(median x 3, 10 ms)`, very slow = `max(median x 8, 100 ms)`; the medians adapt to the disk's own speed, so the same settings work for HDDs, SSDs and SD cards.
5. **Rendering** — the GUI lays the blocks out as a heat map grid (block size cell = 1 segment when scanning in segments), colors each cell by status, and lists all failing blocks in an error tree. The summary tab reports totals, latency percentiles and the error count.
6. **Export** — only on demand (CLI `--export` / GUI *Export* button) are `segments.csv`, `errors.csv` and `summary.txt` written.

## Known limitations

- Windows only (fio `windowsaio` engine, `\\.\PhysicalDriveN` paths, UAC elevation)
- Scan speed depends on the disk itself — a full 1 TB HDD scan takes roughly 1.5–3 hours
- No SMART data — this is a pure read-error/slow-block scanner, not a health monitor
- USB bridges may drop the direct path; use `--no-direct` if reads fail immediately

## License

MIT
