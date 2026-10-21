# HD Doc

只读式 HD Tune 风格磁盘错误扫描工具，基于 fio IO 引擎。逐块读取磁盘或镜像
文件，绘制读取延迟热力图，并列出读失败的块。全程不向目标写入任何数据。

支持 Windows（扫描物理磁盘需要管理员权限）与 Linux。

## 功能

- 热力图固定 256 格（任何扫描都是同一套布局，界面一致）；格按全盘字节
  范围均分，段统计按覆盖范围聚合进格。双模式可切换：**磁盘健康热力图**
  （绿=正常、红=读取错误，类 HD Tune 错误扫描语义）与**磁盘读取速度热力图**
  （绿=快、黄=偏慢、红=读取错误，按延迟相对自适应阈值——基于中位数，慢盘
  不会一片红）。灰色两种模式下都表示"未扫描"，不是判定结果。格子随窗口
  缩放自动重排；快速扫描按区域跨度整区点亮（区头抽样代表整区，悬停注明
  抽样量与区域跨度），不会留下未抽样的灰格
- 错误块列表，含 errno 含义解释
- 快速扫描：每区只读开头样本，类 HD Tune Quick Scan——同样按固定 256 格
  布点（一区对应一格，区域数不随容量漂移；小盘上样本按区域跨度截断，
  保持"每格一个样本"）
- 按需导出报告：不导出就不落盘（segments.csv / errors.csv / summary.txt）
- GUI（ttkbootstrap，浅色/深色主题）与 CLI 同一套代码；GUI 支持中英双语
  （默认英文，可切中文，记住选择）
- 只读设计：任何时刻不写目标设备

## 用法

GUI：

```
python HD_Doc.py
```

在下拉框中选择目标，设置块大小，点**开始扫描**。分段全自动：磁盘**固定切分
256 段**（与容量无关）——一段对应一格，段统计直接就是格的统计（CLI 可用
`--segment-gb 0` 整盘一次，或显式指定段大小）。热力图格子随窗口缩放
自动重排；**热力图**下拉可在**磁盘健康热力图**（绿/红，按读取错误）与
**磁盘读取速度热力图**（绿/黄/红，按延迟）之间切换。语言与浅色/深色主题分别在 *Language/语言*、*View/视图* 菜单切换，
**即时生效、无需重启**（语言切换就地重建界面，主题切换实时换色；两项选择
都会记住）。扫描进行中也可以切换：扫描本身、进度与结果都不受影响。

CLI（固定英文输出）：

```
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --bs 4M
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --quick
python HD_Doc.py --cli --target \\.\PhysicalDrive1 --export reports
```

扫描物理磁盘需要管理员权限：Windows 上 GUI 在程序启动时即弹 UAC 申请提权
（窗口出现之前，不等扫描时再问），UAC 选"否"则保持标准权限继续运行（扫镜像
文件不受影响）；Linux 上对应 root 权限，见下节。CLI 在扫描物理盘时申请。
`--no-elevate` 可关闭自动提权。

`--export [DIR]` 会把报告写入 `DIR/HD_Doc_report_<时间戳>/`；不带该参数
则不写任何文件。全部参数见 `--help`。

## 在 Ubuntu 上运行 GUI

最快的方式是装打包好的安装包（见下文"打包 Ubuntu 安装包"）：

```bash
chmod +x HD_Doc-1.0-ubuntu.run
sudo ./HD_Doc-1.0-ubuntu.run        # 自动装依赖、建 venv、注册菜单项
hd-doc                              # 之后随时启动（应用菜单里搜 "HD Doc" 也行）
```

从源码运行：

```bash
# 1. 安装依赖：tkinter（GUI）+ fio（IO 引擎）
sudo apt update
sudo apt install python3-tk fio

# 2. 安装 ttkbootstrap（建议用 venv，避免动系统 Python）
python3 -m venv ~/.venv/hddoc && ~/.venv/hddoc/bin/pip install -r requirements.txt

# 3. 启动（扫描物理磁盘需要 root；扫镜像文件不需要）
sudo ~/.venv/hddoc/bin/python HD_Doc.py        # 终端里以 root 启动（推荐）
./HD_Doc.py                                    # 或不加 sudo，扫镜像文件/先看界面
```

要点：

- **设备下拉框只列物理整盘**（`/dev/sda`、`/dev/nvme0n1`、`/dev/vdb`…，
  含型号与容量），与 Windows 体验一致；`lsblk` 的 loop（snap 挂载）、
  zram、dm/md、光驱等虚拟块设备已过滤，不会混进来；也可以手动输入
  设备路径
- **点应用图标即以 root 运行**：非 root 启动时会在窗口出现前弹出
  pkexec 授权框（与 Windows 的 UAC 一致，Ubuntu 桌面默认可用）；
  取消则保持标准权限继续启动，也可随时点按钮栏的 **"以 root 重启"**；
  没有 pkexec 时按提示在终端执行 `sudo python3 HD_Doc.py`
- 扫镜像文件（`dd` 出来的 `.img`）不需要 root，直接选文件即可
- 引擎默认 `libaio`（fio 的 Linux 构建自带）；个别 minimal 构建只有
  `psync`/`posixaio`，下拉框切换即可，界面会自动探测可用引擎

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

## 打包可执行文件

```
python build_exe.py
```

一次打出两个变体到 `dist/`：

| 平台 | 文件 | fio | 体积 | 适用场景 |
|------|------|-----|------|----------|
| Windows | `HD_Doc.exe` | 内置 | ~31 MB | 分发给没装 fio 的电脑 |
| Windows | `HD_Doc_NoFio.exe` | 不内置 | ~29 MB | 目标机已装 fio，或用 `--fio 路径` 指定 |
| Linux | `HD_Doc` | 内置（需本机装有 fio） | ~35 MB | Ubuntu 上免 Python 环境直接运行 |
| Linux | `HD_Doc_NoFio` | 不内置 | ~33 MB | 目标机已装 fio，或用 `--fio 路径` 指定 |

在哪个系统上运行 `build_exe.py` 就打哪个平台的包（PyInstaller 不做交叉
编译）。两者都内置 `lang/` 语言文件与 `img/` 图标，运行时行为完全一致；
`--variant fio` / `--variant nofio` 可只打一个，`--onedir` 切换目录模式。
需要带 tkinter 且装有 PyInstaller 的 Python，并 `pip install ttkbootstrap`
（见 `requirements.txt`）。`--version` 会如实报告 fio 来源
（`bundled` / `not bundled`）。Linux 打包出的可执行文件同样需要 root 才能
扫物理磁盘：`sudo ./dist/HD_Doc`。

## 打包 Ubuntu 安装包

```
python build_ubuntu_pkg.py
```

在**任意机器上**（包括 Windows）都能构建，产物在 `dist/`：

| 文件 | 形态 | 用途 |
|------|------|------|
| `HD_Doc-1.0-ubuntu.run` | 自解压安装包 | 直接发给用户，一条命令装完 |
| `HD_Doc-1.0-ubuntu.tar.gz` | 源码归档 | 手动解压安装、集成到部署流程 |
| `*.sha256` | 校验和 | 传输完整性校验 |

因为 PyInstaller 不能交叉编译，这里打的是**源码安装包**（纯 Python，与
CPU 架构无关，x86_64 / arm64 通用）：安装时在目标机器上自动完成依赖检查、
建 venv、装 ttkbootstrap、注册菜单项——不要求目标机提前有任何准备。

安装包用法（Ubuntu 上）：

```bash
# 方式一：自解压安装包（推荐）
chmod +x HD_Doc-1.0-ubuntu.run
sudo ./HD_Doc-1.0-ubuntu.run            # 安装（-y 全自动不询问）
sudo ./HD_Doc-1.0-ubuntu.run --uninstall   # 卸载（--uninstall --purge 连配置一起删）

# 方式二：tar.gz
tar xzf HD_Doc-1.0-ubuntu.tar.gz
sudo ./HD_Doc-1.0/install.sh            # 安装
sudo ./HD_Doc-1.0/uninstall.sh          # 卸载
```

安装过程会做的事：

1. 检查 `python3 >= 3.8`、`tkinter`、`fio`，缺失的组件询问后 `apt` 安装
   （`-y` 全自动；`--no-apt` 完全不动 apt；`--no-fio` 跳过 fio）
2. 复制程序到 `/opt/hd-doc`（`--prefix DIR` 可改），建 venv 装
   `requirements.txt`；venv 不可用时自动回退系统 Python
3. 生成启动器 `/usr/local/bin/hd-doc`（GUI/CLI 统一入口）、桌面菜单项
   和图标；实际安装路径记入 `/var/lib/hd-doc/install.manifest`，
   卸载时按清单清理（自定义目录也能干净卸载）

改打包内容后重新构建 + 自检：

```bash
python build_ubuntu_pkg.py && python packaging/ubuntu/validate_pkg.py
```

`validate_pkg.py` 会校验归档完整性（文件树/权限位/LF 行尾/无重复成员）、
`.run` 解包链路、sha256、双语 key 一致性，并以打桩 `id`/`python3` 的方式
**模拟完整安装与卸载**（全程只写临时目录，不碰系统 `/opt`、`/usr`）。

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
python test/test_job_kill.py       # fio 随父进程连坐终止（任务管理器强杀）
```

依赖 fio 的套件需要机器上装有 fio（Windows 自动找
`C:\Program Files\fio\fio.exe`；Linux 用 PATH 中的 `fio` 或
`/usr/bin/fio`）。

## 代码结构

```
HD_Doc_core.py  业务逻辑：提权、分段、fio 引擎、报告导出
                （零 UI 依赖；加载 lang/*.json）
HD_Doc_cli.py   命令行前端（仅英文）
HD_Doc_gui.py   ttkbootstrap 界面（中英双语，浅色/深色主题）
HD_Doc.py       入口：分发到 CLI 或 GUI
build_exe.py    PyInstaller 打包（Windows/Linux 单文件可执行程序）
build_ubuntu_pkg.py   Ubuntu 安装包打包（.run 自解压 + .tar.gz）
make_icon.py    应用图标生成（PIL 绘制：1024 主图 + hicolor 全套 + 多分辨率 .ico）
packaging/ubuntu/    安装脚本（install.sh / uninstall.sh）与安装包校验
requirements.txt  运行依赖（ttkbootstrap，GUI 需要）
lang/           界面文案（en.json、zh.json）
img/            程序图标（HD_Doc.ico、HD_Doc.png）
test/           测试套件（python test/test_units.py 等）
```

## 许可

MIT
