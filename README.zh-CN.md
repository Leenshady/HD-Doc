# HD Doc

只读式 HD Tune 风格磁盘错误扫描工具，基于 fio IO 引擎。逐块读取磁盘或镜像
文件，绘制读取延迟热力图，并列出读失败的块。全程不向目标写入任何数据。

支持 Windows（扫描物理磁盘需要管理员权限）与 Linux。

## 功能

- 热力图固定 256 格（任何扫描都是同一套布局，界面一致）；格按全盘字节
  范围均分，段统计按覆盖范围聚合进格，按延迟相对自适应阈值（基于中位数，
  慢盘不会一片红）着色；快速扫描按区域跨度整区点亮（区头抽样代表整区，
  悬停注明抽样量与区域跨度），不会留下未抽样的灰格
- 错误块列表，含 errno 含义解释
- 快速扫描：每区只读开头样本，类 HD Tune Quick Scan
- 按需导出报告：不导出就不落盘（segments.csv / errors.csv / summary.txt）
- GUI（ttkbootstrap，浅色/深色主题）与 CLI 同一套代码；GUI 支持中英双语
  （默认英文，可切中文，记住选择）
- 只读设计：任何时刻不写目标设备

## 用法

GUI：

```
python HD_Doc.py
```

在下拉框中选择目标，设置块大小 / 段大小，点**开始扫描**。语言与浅色/深色
主题分别在 *Language/语言*、*View/视图* 菜单切换，**即时生效、无需重启**
（语言切换就地重建界面，主题切换实时换色；两项选择都会记住）。扫描进行中
也可以切换：扫描本身、进度与结果都不受影响。

CLI（固定英文输出）：

```
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --bs 4M
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --quick
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --export reports
```

扫描物理磁盘需要管理员权限：GUI 在程序启动时即弹 UAC 申请提权（窗口出现
之前，不等扫描时再问），UAC 选"否"则保持标准权限继续运行（扫镜像文件
不受影响）；CLI 在扫描物理盘时申请。`--no-elevate` 可关闭自动提权。

`--export [DIR]` 会把报告写入 `DIR/HD_Doc_report_<时间戳>/`；不带该参数
则不写任何文件。全部参数见 `--help`。

## 语言文件

界面文案放在 `lang/<代码>.json`，一个语言一个文件，启动时自动扫描发现——
代码里没有任何语言清单。每个文件用保留键 `_meta` 自我描述：

```json
{
  "_meta": { "name": "中文", "name_en": "Chinese (Simplified)" },
  "status.ok": "正常",
  "...": "..."
}
```

文件名（去 `.json`）即语言码；`_meta.name` 是该语言的自称，作为
*Language/语言* 菜单里的标签。新增语言：复制 `lang/en.json` 翻译各值，
填好 `_meta.name`，另存为 `lang/<代码>.json` 即可——菜单、配置校验、
英文回退全部自动生效，不用改任何代码。`_` 或 `.` 开头的文件视为模板
会跳过；缺失的键回退英文。

## 运行日志

每次运行都会把关键事件追加到唯一一份日志文件 `HD_Doc.log`（与配置同目录：
Windows 为 `%APPDATA%\HD_Doc\HD_Doc.log`，其他平台为 `~/.config/HD_Doc/`）：
启动信息、带完整参数的扫描开始、结果汇总、报告导出、语言/主题切换，
以及任何异常连同堆栈（含 Tk 回调里未捕获的异常——否则它们只进 stderr，
打包版没有控制台，用户根本看不到）。示例：

```
2026-10-19 12:23:00.014 [INFO] startup: ver=1.0 mode=cli frozen=False admin=True argv=--cli --target ...
2026-10-19 12:23:00.168 [INFO] cli: plan target=... size=8.0 MB bs=512.0 KB segments=1 engine=windowsaio direct=True quick=False fio=C:\Program Files\fio\fio.EXE
2026-10-19 12:23:00.997 [INFO] cli: finished target=... blocks=16 ok=16 slow=0 bad=0 errors=0 aborted=False stopped=False elapsed=0.8s
```

永远只有一份：超过 512KB 即整文件截断重写，不会按日期/次数堆积出多个
日志文件。反馈问题时把这一个文件发出来即可。

- `HD_DOC_LOG_DIR=<目录>` 改日志目录（测试/便携场景）
- `HD_DOC_LOG=off` 整体关闭

写日志失败（只读目录/权限不足）时静默忽略，绝不会影响扫描主流程。

## 打包 Windows 可执行文件

```
python build_exe.py
```

一次打出两个变体到 `dist/`：

| 文件 | fio | 体积 | 适用场景 |
|------|-----|------|----------|
| `HD_Doc.exe` | 内置 | ~31 MB | 分发给没装 fio 的电脑 |
| `HD_Doc_NoFio.exe` | 不内置 | ~29 MB | 目标机已装 fio，或用 `--fio 路径` 指定 |

两者都内置 `lang/` 语言文件与 `img/` 图标，运行时行为完全一致；
`--variant fio` / `--variant nofio` 可只打一个，`--onedir` 切换目录模式。
需要带 tkinter 且装有 PyInstaller 的 Python，并 `pip install ttkbootstrap`
（见 `requirements.txt`）。`--version` 会如实报告 fio 来源
（`bundled` / `not bundled`）。

## 测试

```
python test/test_units.py          # 核心逻辑 + i18n
python test/test_integration.py    # fio 引擎、报告、回归
python test/test_gui_smoke.py      # GUI 行为（含语言/主题切换）
python test/test_gui_stop.py       # 停止 / 竞态
python test/test_gui_quick.py      # 快速扫描端到端
python test/test_cli_stop.py       # CLI Ctrl+C
python test/test_cli_gate.py       # 提权门禁 + CLI 实扫
python test/test_gui_gate.py       # GUI 提权门禁
python test/test_hdd_stop.py       # 真实硬件中途停止
```

依赖 fio 的套件需要机器上装有 fio（会自动找到
`C:\Program Files\fio\fio.exe`）。

## 代码结构

```
HD_Doc_core.py  业务逻辑：提权、分段、fio 引擎、报告导出
                （零 UI 依赖；加载 lang/*.json）
HD_Doc_cli.py   命令行前端（仅英文）
HD_Doc_gui.py   ttkbootstrap 界面（中英双语，浅色/深色主题）
HD_Doc.py       入口：分发到 CLI 或 GUI
build_exe.py    PyInstaller 打包
requirements.txt  运行依赖（ttkbootstrap，GUI 需要）
lang/           界面文案（en.json、zh.json）
img/            程序图标（HD_Doc.ico、HD_Doc.png）
test/           测试套件（python test/test_units.py 等）
```

## 许可

MIT
