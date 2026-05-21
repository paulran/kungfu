# KFC 程序实现分析

---

## 一、概述

**kfc**（Kungfu Console）是 Kungfu Trader 交易系统的核心命令行工具，负责启动和管理所有交易相关的服务进程。它是一个基于 Python 的命令行程序，通过 **PyInstaller** 或 **Nuitka** 打包为独立可执行文件。

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      kfc 可执行文件                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Click CLI 框架                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │   run       │  │  journal    │  │  engage     │ │   │
│  │  │  (运行服务)  │  │  (日志管理)  │  │  (子命令)    │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │   service   │  │    cli      │                  │   │
│  │  │  (系统服务)  │  │  (CLI入口)   │                  │   │
│  │  └─────────────┘  └─────────────┘                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              C++ 绑定层 (pybind11)                  │   │
│  │   longfist    │   wingchun    │   yijinjing         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块结构

| 模块 | 说明 | 位置 |
|------|------|------|
| `kfc.py` | 程序入口，调用 `kungfu.__main__.main()` | `src/python/kfc.py` |
| `kfc.spec` | PyInstaller 打包配置 | `src/python/kfc.spec` |
| `kfc.js` | Node.js 包装脚本 | `lib/kfc.js` |
| `commands/__init__.py` | CLI 主入口，Click 命令组定义 | `kungfu/console/commands/__init__.py` |
| `commands/run.py` | 服务运行命令 | `kungfu/console/commands/run.py` |
| `commands/service.py` | 系统服务命令 | `kungfu/console/commands/run.py` |
| `commands/journal.py` | 日志管理命令 | `kungfu/console/commands/journal.py` |
| `commands/engage.py` | 子命令桥接（pdm/nuitka等） | `kungfu/console/commands/engage.py` |
| `commands/cli.py` | CLI 入口命令 | `kungfu/console/commands/cli.py` |

---

## 三、启动流程

### 3.1 程序入口

**kfc.py** - Nuitka 打包入口：

```python
# SPDX-License-Identifier: Apache-2.0

from kungfu import __main__ as origin
origin.main()
```

**Node.js 包装器** (`lib/kfc.js`)：

```javascript
#!/usr/bin/env node

const path = require('path');
const { kfc } = require('./executable');
const shell = require('./shell');

function getCliDir() {
  try {
    return require('@kungfu-trader/kungfu-js-api/toolkit/utils').getCliDir();
  } catch (err) {
    return '.';
  }
}

shell.run(kfc, process.argv.slice(2), true, {
  silent: true,
  env: {
    KF_CLI_DEV_PATH: path.resolve(getCliDir(), 'lib', 'dev', 'cli.dev.js'),
    KF_LOG_LEVEL: 'trace',
    ...process.env,
  },
});
```

### 3.2 CLI 主入口

```python
@click.group("kfc", invoke_without_command=True, cls=PrioritizedCommandGroup)
@click.option("-H", "--home", type=str, help="kungfu home folder")
@click.option("-X", "--extension-path", type=str, help="where to find extensions")
@click.option("-l", "--log_level", type=click.Choice(["trace", "debug", "info", "warning", "error", "critical"]), 
              default="warning", help="logging level")
@click.option("-n", "--name", type=str, help="name for the process")
@click.option("-i", "--cli_dev_path", type=str, help="cli entry path")
@click.help_option("-h", "--help")
@click.version_option(kungfu.__version__, "--version", message=kungfu.__version__)
@click.pass_context
def kfc(ctx, home, extension_path, log_level, name, cli_dev_path):
    # 设置默认 home 目录
    if not home:
        osname = platform.system()
        user_home = os.path.expanduser("~")
        if osname == "Linux":
            home = os.getenv("XDG_CONFIG_HOME", os.path.join(user_home, ".config"))
        if osname == "Darwin":
            home = os.path.join(user_home, "Library", "Application Support")
        if osname == "Windows":
            home = os.getenv("APPDATA", os.path.join(os.getenv("USERPROFILE"), "AppData", "Roaming"))
        home = os.path.join(home, "kungfu", "home")
    
    # 设置环境变量
    os.environ["KF_HOME"] = ctx.home = home
    os.environ["KF_LOG_LEVEL"] = ctx.log_level = log_level
    
    # 创建目录结构
    ctx.runtime_dir = ensure_dir(ctx, "runtime")
    ctx.archive_dir = ensure_dir(ctx, "archive")
    ctx.dataset_dir = ensure_dir(ctx, "dataset")
    ctx.inbox_dir = ensure_dir(ctx, "inbox")
    
    # 初始化 C++ 绑定
    lf = kungfu.__binding__.longfist
    yjj = kungfu.__binding__.yijinjing
    
    # 创建 locator 和 locations
    ctx.runtime_locator = yjj.locator(ctx.runtime_dir)
    ctx.config_location = yjj.location(lf.enums.mode.LIVE, lf.enums.category.SYSTEM, "etc", "kungfu", ctx.runtime_locator)
    ctx.console_location = yjj.location(lf.enums.mode.LIVE, lf.enums.category.SYSTEM, "service", "console", ctx.runtime_locator)
    ctx.index_location = yjj.location(lf.enums.mode.LIVE, lf.enums.category.SYSTEM, "journal", "index", ctx.runtime_locator)
```

---

## 四、核心命令分析

### 4.1 run 命令

`run` 命令是最核心的命令，用于启动各种服务进程：

```python
@kfc.command(help_priority=1)
@click.option("-m", "--mode", default="live", type=click.Choice(kfj.MODES.keys()), help="mode")
@click.option("-c", "--category", type=click.Choice(kfj.CATEGORIES.keys()), help="category")
@click.option("-g", "--group", type=str, help="group")
@click.option("-n", "--name", type=str, help="name")
@click.option("-x", "--low-latency", is_flag=True, help="run in low latency mode")
@click.argument("reference", type=str, required=False)
@click.option("-a", "--arguments", type=str, required=False)
@click.option("-v", "--vendor", type=str, required=False)
@kfc.pass_context()
def run(ctx, mode, category, group, name, low_latency, reference, arguments, vendor):
    ctx.mode = mode
    ctx.category = category
    ctx.group = group
    ctx.name = name
    ctx.low_latency = low_latency
    ctx.path = reference
    ctx.arguments = arguments if arguments else ""
    ctx.vendor = vendor
    
    registry = ExecutorRegistry(ctx)
    
    # 快捷命令映射
    cheatsheet = {
        "master": registry["system"]["master"]["master"],
        "ledger": registry["system"]["service"]["ledger"],
        "cached": registry["system"]["service"]["cached"],
    }
    
    if not category and not reference:
        click.echo(run.get_help(ctx))
    elif reference in cheatsheet:
        cheatsheet[reference](mode, low_latency)
    else:
        registry.load_extensions()
        registry[category][group][name](mode, low_latency)
```

**启动参数说明**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-m/--mode` | 运行模式 | `live` |
| `-c/--category` | 服务类别 | 必需 |
| `-g/--group` | 服务组名 | 必需 |
| `-n/--name` | 服务名称 | 必需 |
| `-x/--low-latency` | 低延迟模式 | `false` |
| `-a/--arguments` | 额外参数 | 空 |

### 4.2 service 命令组

```python
@kfc.command(cls=PrioritizedCommandGroup, help_priority=-1)
@kfc.pass_context()
def service(ctx):
    pass

@service.command(help_priority=1)
@service_command_context
def master(ctx):
    Master(ctx).run()

@service.command()
@click.option("-r", "--replay", is_flag=True, help="run in replay mode")
@click.option("-i", "--session_id", type=int, help="replay session id")
@service_command_context
def ledger(ctx, replay, session_id):
    ctx.low_latency = ctx.low_latency if not replay else True
    ctx.replay = replay
    ctx.category = lf.enums.category.SYSTEM
    ctx.mode = lf.enums.mode.REPLAY if ctx.replay else lf.enums.mode.LIVE
    ctx.group = "service"
    ctx.name = "ledger"
    ctx.session_id = session_id
    ledger_instance = wc.Ledger(ctx.runtime_locator, ctx.mode, ctx.low_latency)
    if replay:
        ctx.category = "system"
        setup(ctx, session_id, ledger, ledger_instance)
    ledger_instance.run()

@service.command()
@click.option("-s", "--source", required=True, help="data source")
@click.option("-t", "--time-interval", default="1m", type=str, help="bar time interval")
@service_command_context
def bar(ctx, source, time_interval):
    ctx.mode = lf.enums.mode.LIVE
    args = {"source": source, "time_interval": time_interval}
    instance = wc.BarGenerator(ctx.runtime_locator, ctx.mode, ctx.low_latency, json.dumps(args))
    instance.run()
```

### 4.3 journal 命令组

日志管理命令：

```python
@kfc.group(cls=PrioritizedCommandGroup, help_priority=2)
@click.option("-m", "--mode", default="*", type=click.Choice(kfj.MODES.keys()))
@click.option("-c", "--category", default="*", type=click.Choice(kfj.CATEGORIES.keys()))
@click.option("-g", "--group", type=str, default="*")
@click.option("-n", "--name", type=str, default="*")
@kfc.pass_context()
def journal(ctx, mode, category, group, name):
    ctx.location = yjj.location(kfj.MODES[mode], kfj.CATEGORIES[category], group, name, ctx.runtime_locator)
    ctx.logger = create_logger("journal", ctx.log_level, ctx.console_location)
```

**子命令**：

| 命令 | 说明 |
|------|------|
| `sessions` | 列出所有会话 |
| `rebuild_index` | 重建索引数据库 |
| `show` | 显示会话详情 |
| `trace` | 追踪会话 |
| `clean` | 清理日志 |
| `archive` | 归档日志 |
| `list-archive` | 列出归档 |

### 4.4 engage 命令组

桥接到其他命令行工具：

```python
@kfc.group(cls=PrioritizedCommandGroup, help_priority=3)
@kfc.pass_context()
def engage(ctx):
    pass

@engage.command(help="Format python files with Black")
@engage_command_context()
def black(ctx):
    ctx.bridging.black()

@engage.command(help="Manage python packages with pdm")
@engage_command_context()
def pdm(ctx):
    ctx.bridging.pdm()

@engage.command(help="Build with SCons")
@engage_command_context()
def scons(ctx):
    ctx.bridging.scons()

@engage.command(help="Compile and bundle python files with Nuitka")
@engaged_nuitka_context()
def nuitka(ctx):
    ctx.bridging.nuitka()
```

### 4.5 cli 命令

启动 Node.js CLI 界面：

```python
@kfc.command(help_priority=1)
@click.argument("commands", nargs=-1, required=False)
@click.option("-l", "--list", is_flag=True, help="list process for monitor")
@click.option("-h", "--help", is_flag=True, help="show help")
@click.option("-v", "--version", is_flag=True, help="show cli version")
@kfc.pass_context()
def cli(ctx, commands, list, help, version):
    os.environ["KFC_AS_VARIANT"] = "node"
    cli_prod_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "app", "dist", "cli", "index.js"))
    cli_path = ctx.cli_dev_path if ctx.cli_dev_path else cli_prod_path
    argv = [sys.argv[0], cli_path, *commands, "-l" if list else "", "-h" if help else "", "-V" if version else ""]
    kungfu.__binding__.libnode.run(*argv)
```

---

## 五、打包配置

### 5.1 PyInstaller 配置

**kfc.spec** 关键配置：

```python
kfc_a = Analysis(
    scripts=["kfc.py"],
    pathex=extra_python_paths,
    binaries=[],
    datas=extend_datas([
        (cmake_dir, "cmake"),
        (make_path(dep_hana_dir, "include"), "include"),
        (make_path(dep_sqlite_orm_dir, "include"), "include"),
        (dep_pybind11_dir, "pybind11"),
        (make_path(build_output_dir, "*"), "."),
        (make_path(build_dir, "include"), "include"),
    ],
    src_dirs=[src_dir],
    build_dirs=[build_cpp_dir],
    packages=[]),
    hiddenimports=extend_hiddenimports(
        modules=[
            "black", "chardet", "pip._internal", "pip._vendor",
            "pkg_resources", "pdm", "pep517", "pyproject_hooks",
            "shellingham", "nuitka", "ordered_set", "SCons",
            "setuptools", "numpy", "pandas", "scipy", "statsmodels",
        ],
        executable_modules=["kungfu", "pip"],
    ),
    excludes=["matplotlib"],
    ...
)

kfc_exe = EXE(
    kfc_pyz,
    kfc_a.scripts,
    name=kfc_name,
    console=True,
    debug=False,
    exclude_binaries=True,
    strip=False,
)
```

### 5.2 Nuitka 配置

**kfc.py** 中的 Nuitka 配置：

```python
# nuitka-project: --standalone
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --prefer-source-code
# nuitka-project: --python-flag=nosite
# nuitka-project: --python-flag=no_warnings
# nuitka-project: --remove-output
# nuitka-project: --static-libpython=no
# nuitka-project: --include-package=numpy
# nuitka-project: --include-package=pandas
# nuitka-project: --include-package=plotly
# nuitka-project: --enable-plugin=anti-bloat
# nuitka-project: --enable-plugin=numpy
# nuitka-project: --enable-plugin=pylint-warnings
```

---

## 六、C++ 绑定层

kfc 通过 pybind11 调用 C++ 核心库：

```python
# 导入 C++ 绑定
lf = kungfu.__binding__.longfist    # 长拳 - 核心交易引擎
wc = kungfu.__binding__.wingchun    # 咏春 - 策略框架
yjj = kungfu.__binding__.yijinjing  # 易经 - 事件总线/日志系统

# 创建 locator
ctx.runtime_locator = yjj.locator(ctx.runtime_dir)

# 创建 location
ctx.config_location = yjj.location(lf.enums.mode.LIVE, lf.enums.category.SYSTEM, "etc", "kungfu", ctx.runtime_locator)
```

---

## 七、目录结构

```
KF_HOME/
├── runtime/          # 运行时数据
│   ├── md/           # 行情数据
│   ├── td/           # 交易数据
│   ├── journal/      # 日志文件
│   └── log/          # 运行日志
├── archive/          # 归档数据
├── dataset/          # 数据集
└── inbox/            # 临时文件
```

---

## 八、常用命令示例

### 启动核心服务

```bash
# 启动 master
kfc run master

# 启动 ledger
kfc run ledger

# 启动 cached
kfc run cached

# 完整参数启动
kfc run -m live -c system -g master -n master
```

### 启动行情服务

```bash
kfc run -m live -c md -g ctp -n ctp
```

### 启动交易服务

```bash
kfc run -m live -c td -g ctp -n my_account
```

### 启动策略

```bash
kfc run -m live -c strategy -g default -n my_strategy /path/to/strategy.so
```

### 日志管理

```bash
# 列出会话
kfc journal sessions

# 显示会话详情
kfc journal show -i 12345

# 归档日志
kfc journal archive

# 清理日志
kfc journal clean
```

### 工具命令

```bash
# 格式化 Python 代码
kfc engage black .

# 管理 Python 依赖
kfc engage pdm install

# 使用 Nuitka 编译
kfc engage nuitka my_script.py
```

---

## 九、总结

| 特性 | 说明 |
|------|------|
| **语言** | Python + Click CLI 框架 |
| **打包工具** | PyInstaller / Nuitka |
| **核心绑定** | pybind11 调用 C++ 库 |
| **主要命令** | run, service, journal, engage, cli |
| **运行模式** | live, replay, backtest |
| **延迟模式** | 标准模式 / 低延迟模式 |

kfc 是 Kungfu Trader 的核心命令行工具，负责协调整个交易系统的启动和管理，通过 Python CLI 框架提供友好的命令行接口，底层调用 C++ 核心库实现高性能交易功能。

---

**文档生成时间**：2026-05-20
