# HD Doc

只读式 HD Tune 风格磁盘错误扫描工具，基于 fio IO 引擎。逐块读取磁盘或镜像
文件，绘制读取延迟热力图，并列出读失败的块。全程不向目标写入任何数据。

支持 Windows（扫描物理磁盘需要管理员权限）与 Linux。

## 功能

- 块级热力图：每格对应一个扫描段，按延迟相对自适应阈值（基于中位数，
  慢盘不会一片红）着色
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

界面文案独立于代码，放在 `lang/en.json` 与 `lang/zh.json`，运行时加载。
新增语言：放入同键集的 `lang/<代码>.json`，并在 `HD_Doc_core.py` 的
`LANGUAGES` 里注册即可。

## 打包 Windows 可执行文件

```
python build_exe.py
```

产出 `dist/HD_Doc.exe`（单文件）。构建机上找得到 fio.exe 时会一并打入，
`lang/` 语言文件与 `img/` 图标也会打入。需要带 tkinter 且装有 PyInstaller
的 Python，并 `pip install ttkbootstrap`（见 `requirements.txt`）。

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
