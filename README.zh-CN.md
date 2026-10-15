# hdtune_scan

一个免费、开源、**只读**的磁盘健康扫描工具，界面风格对标 HD Tune 的"错误扫描"（Error Scan），底层基于 [fio](https://fio.readthedocsocs.io/) I/O 引擎，GUI 使用 Python/tkinter 编写。

<p align="center">
  <img src="https://img.shields.io/badge/平台-Windows%2010%2F11-blue" alt="platform">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/许可证-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/只读-100%25-brightgreen" alt="read-only">
</p>

- **English version: [README.md](README.md)**

## 功能概述

`hdtune_scan` 会逐个读取所选磁盘（或磁盘镜像文件）的每一个数据块，并以网格热力图的形式呈现结果——与 HD Tune 的错误扫描完全一致：

| 颜色 | 含义 |
|------|------|
| 绿色 | 读取速度正常 |
| 黄色 | 偏慢（超过自适应"偏慢"阈值） |
| 红色 | 很慢（超过自适应"很慢"阈值） |
| 暗红 | 读取错误（fio 在该数据块上报告 I/O 错误） |
| 灰色 | 尚未扫描 |

本工具**严格只读**：绝不会向目标磁盘写入任何数据。

## 功能特性

- **HD Tune 风格热力图**——按数据块着色，网格布局自适应，分段多少都能合理排布
- **快速扫描**——HD Tune 快速扫描风格：只读取每个区域头部的小样本、跳过其余部分，可快速完成全盘健康体检
- **自适应阈值**——偏慢/很慢阈值由实测延迟中位数推导（中位数 x N，带下限保护），机械硬盘、固态硬盘、SD 卡都适用
- **错误块列表**——逐个列出读取失败的数据块（偏移、长度、errno 名称、状态），热力图中每格标注该段错误数
- **按需导出**——不主动保存任何扫描结果，只有用户明确要求时才写盘：
  - 命令行：`--export [DIR]`，导出 `segments.csv`、`errors.csv`、`summary.txt` 到 `DIR/hdtune_report_<时间戳>/`
  - 图形界面：点击**导出**按钮选择目录，写同样的三个文件
- **GUI 国际化**——界面默认英文，运行时可切换中文（选择会被记住）；命令行输出固定为英文，方便脚本与日志记录
- **少弹窗**——扫描结果、警告、导出完成提示均以界面内彩色横幅和日志行展示，仅保留两个确认对话框（提权同意与退出确认）
- **自动提权**——扫描 `\\.\PhysicalDriveN` 需要管理员权限，程序会自动弹出 UAC 申请提权重启（`--no-elevate` 或环境变量 `HDTUNE_NO_AUTO_ELEVATE=1` 可关闭）
- **窗口自适应**——整体布局随窗口大小缩放，热力图自动重排
- **独立 Windows 可执行文件**——单文件 `.exe`（构建时能找到 `fio.exe` 会自动内置），目标电脑无需安装 Python

## 环境要求

- Windows 10/11（使用 fio 的 `windowsaio` 引擎）
- Python 3.9+ 且自带 tkinter（仅从源码运行 / 打包 GUI 时需要）
- [fio](https://fio.readthedocs.io/)——在 `PATH` 中，或使用已内置 fio 的打包版 `.exe`
- 扫描物理磁盘（`\\.\PhysicalDriveN`）需要管理员权限

## 使用方法

### 图形界面（GUI）

双击 `hdtune_scan.exe`，或运行：

```
python hdtune_scan.py
```

选择目标（物理磁盘或镜像文件），选择块大小、分段大小（0 = 一次性扫全盘）或快速扫描模式，点击**开始扫描**。

在菜单栏 **Language → English / 中文** 中切换界面语言；程序简介见 **Help → About**（帮助 → 关于）。

### 命令行模式（CLI，固定英文输出）

```
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --bs 4M
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --quick
python hdtune_scan.py --cli --target test.img --segment-gb 4 --export ./out
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --limit-mb 64   # 只扫前 64MB
python hdtune_scan.py --cli --target "\\\\.\\PhysicalDrive1" --no-elevate   # 禁止自动提权
python hdtune_scan.py --version
```

不加 `--export` 时不会写入任何文件，结果只打印到控制台。
加 `--export`（可带目录参数，默认当前目录）时，扫描结束后写出三个报告文件：

```
hdtune_report_<时间戳>/
├── segments.csv   # 每段统计：平均/最小/最大延迟、偏慢与错误块数
├── errors.csv     # 每个失败块一行：偏移、长度、errno、状态
└── summary.txt    # 一页纸扫描摘要
```

全部命令行参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--target` | – | `\\.\PhysicalDriveN` 或镜像文件路径 |
| `--bs` | `auto` | 块大小，如 `4M` / `512K` / `auto` |
| `--segment-gb` | `4` | 分段大小（GB）；`0` = 一次性扫全盘 |
| `--quick` | 关 | 快速扫描（区域头部抽样） |
| `--quick-sample-mb` | `16` | 快速扫描每区域抽样大小（MB） |
| `--limit-mb` / `--offset-mb` | `0` | 只扫前 N MB / 从偏移处开始 |
| `--export [DIR]` | 关 | 导出报告到 `DIR/hdtune_report_<时间戳>/` |
| `--no-elevate` | 关 | 禁止自动管理员提权 |
| `--fio` | – | fio 可执行文件路径 |
| `--ioengine` | 自动 | fio ioengine（默认 `windowsaio`） |
| `--no-direct` | 关 | 关闭 `direct=1` |
| `--yellow-mult` / `--red-mult` | `3` / `8` | 偏慢 / 很慢阈值 = 中位数 x N |
| `--yellow-floor-ms` / `--red-floor-ms` | `10` / `100` | 阈值下限（毫秒） |

## 代码结构

UI 与业务逻辑严格分离——命令行路径不会触碰任何 UI 代码：

```
hdtune_scan/
├── hdtune_core.py    # 业务逻辑：提权、分段规划、fio 引擎、磁盘枚举、
│                     # 报告导出（零 tkinter 依赖）
├── hdtune_cli.py     # 命令行模式：只 import hdtune_core，固定英文输出
├── hdtune_gui.py     # tkinter 界面：只 import hdtune_core，i18n（英/中）
├── hdtune_scan.py    # 薄入口：参数解析与分发
├── build_exe.py      # PyInstaller 打包脚本（单文件 exe）
└── test_*.py         # 测试套件（见下）
```

## 打包 Windows 可执行文件

```
python build_exe.py            # 单文件打包 -> dist/hdtune_scan.exe
python build_exe.py --onedir   # 目录打包（启动更快）
```

打包要求：安装 PyInstaller，并使用带 tkinter 的 Python（python.org 安装包自带 tkinter）。
构建机上能找到 `fio.exe` 时会自动内置，打出的 `.exe` 自包含、可直接分发。

## 运行测试

```
python test_units.py          # 单元测试：i18n、阈值、分段规划、报告导出
python test_integration.py    # 报告导出集成测试（英文 + 中文）
python test_gui_smoke.py      # GUI：默认英文界面、快速扫描、热力图、语言切换、关于窗口
python test_gui_stop.py       # GUI：中途停止（真实硬件路径 + 竞态路径）、横幅口径
python test_gui_quick.py      # GUI：快速扫描、英文悬停提示、导出
python test_cli_gate.py       # CLI：提权门禁（5 个分支）+ 快速扫描 + --export
python test_gui_gate.py       # GUI：提权门禁（pythonw.exe 目标）
python test_cli_stop.py       # CLI：中途 Ctrl+C -> 退出码 130，不写报告
python test_hdd_stop.py       # 真实机械硬盘：全盘扫描中途停止，无误报错误块
```

## 工作原理

1. **提权**——目标为 `\\.\PhysicalDriveN` 且当前进程未提权时，通过 UAC 提权重启自身（`--no-elevate` 可关闭）。
2. **规划**——通过 `IOCTL_DISK_GET_LENGTH_INFO` 查询磁盘容量（不支持的设备走二分探测兜底），再按分段大小（默认每段 4GB，0 = 单段）切分扫描计划；快速扫描对每个区域只抽样前 N MB。
3. **扫描**——每段由 `fio` 以顺序读、`direct=1` 执行，流式解析 JSON 输出，逐块记录延迟、状态（正常/偏慢/很慢/错误）与失败时的 Windows errno 名称。
4. **阈值**——偏慢 = `max(中位数 x 3, 10ms)`，很慢 = `max(中位数 x 8, 100ms)`；中位数随磁盘自身速度自适应，同一套参数适用于机械硬盘、固态与 SD 卡。
5. **渲染**——GUI 将数据块排成热力图网格（分段扫描时一格 = 一段），按状态着色，错误块在错误树中逐条列出；摘要页报告总量、延迟分位数与错误数。
6. **导出**——仅在用户明确要求时（CLI `--export` / GUI 导出按钮）写出 `segments.csv`、`errors.csv`、`summary.txt`。

## 已知限制

- 仅支持 Windows（依赖 fio `windowsaio` 引擎、`\\.\PhysicalDriveN` 路径、UAC 提权）
- 扫描速度取决于磁盘本身——1TB 机械硬盘全盘扫描约 1.5–3 小时
- 不读取 SMART 信息——本工具是纯读取错误/慢块扫描器，不是健康监测器
- USB 桥接硬盘可能无法使用 direct 路径，若一开始就报读取失败，可加 `--no-direct` 重试

## 许可证

MIT
