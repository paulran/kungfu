# VSCode 调试 Kungfu Trader 各服务程序指南

---

## 一、概述

通常 Kungfu Trader 的各个服务是通过 `kfc run` 命令启动的。本指南介绍如何直接使用 VSCode 调试器启动和调试各个服务程序。

---

## 二、核心启动流程分析

根据代码分析，服务的启动流程如下：

```python
# run.py 中的 Loader.run() 方法
def run(self, mode: str, low_latency: bool):
    self.ctx.location = yjj.location(
        kfj.MODES[mode],           # mode -> LIVE = 1
        lf.enums.category.SYSTEM,  # category
        group,                      # group
        name,                       # name
        self.ctx.runtime_locator,   # 运行时定位器
    )
    self.ctx.logger = find_logger(self.ctx.location, self.ctx.log_level)
    Service(self.ctx).run()
```

**核心依赖**：
1. `ctx.location` - 位置信息
2. `ctx.logger` - 日志记录器
3. `ctx.runtime_locator` - 运行时定位器
4. `ctx.low_latency` - 是否低延迟模式

---

## 三、创建调试启动脚本

### 3.1 创建调试入口文件

创建 `debug_master.py` 文件：

```python
# debug_master.py - Master 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"
os.environ["KF_NO_EXT"] = "on"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))

import kungfu
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger
from kungfu.yijinjing.practice.master import Master

lf = kungfu.__binding__.longfist
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "system"
        self.group = "master"
        self.name = "master"
        self.low_latency = False
        self.log_level = "debug"
        self.location = yjj.location(
            kfj.MODES[self.mode], lf.enums.category.SYSTEM,
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)
        self.apprentices = {}
        self.master = None

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info("Master debug session starting...")
    master = Master(ctx)
    ctx.logger.info("Master instance created, running...")
    master.run()
```

### 3.2 保存位置

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_master.py`

---

## 四、配置 VSCode 调试器

### 4.1 创建 launch.json

在 `.vscode/launch.json` 中添加调试配置，包含所有服务的调试配置：

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug Master",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/debug_master.py",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "KF_HOME": "${env:USERPROFILE}\\.kungfu",
                "KF_LOG_LEVEL": "debug",
                "KF_NO_EXT": "on",
                "PYTHONPATH": "${workspaceFolder}/framework/core/src/python;${workspaceFolder}/framework/core/build",
                "PATH": "${workspaceFolder}/framework/core/build;${env:PATH}"
            },
            "args": [],
            "stopOnEntry": false,
            "justMyCode": false,
            "redirectOutput": true,
            "gevent": false
        },
        {
            "name": "Debug Ledger",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/debug_ledger.py",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "KF_HOME": "${env:USERPROFILE}\\.kungfu",
                "KF_LOG_LEVEL": "debug",
                "PYTHONPATH": "${workspaceFolder}/framework/core/src/python;${workspaceFolder}/framework/core/build",
                "PATH": "${workspaceFolder}/framework/core/build;${env:PATH}"
            },
            "args": [],
            "stopOnEntry": false,
            "justMyCode": false,
            "redirectOutput": true,
            "gevent": false
        },
        {
            "name": "Debug Cached",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/debug_cached.py",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "KF_HOME": "${env:USERPROFILE}\\.kungfu",
                "KF_LOG_LEVEL": "debug",
                "PYTHONPATH": "${workspaceFolder}/framework/core/src/python;${workspaceFolder}/framework/core/build",
                "PATH": "${workspaceFolder}/framework/core/build;${env:PATH}"
            },
            "args": [],
            "stopOnEntry": false,
            "justMyCode": false,
            "redirectOutput": true,
            "gevent": false
        },
        {
            "name": "Debug MD",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/debug_md.py",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "KF_HOME": "${env:USERPROFILE}\\.kungfu",
                "KF_LOG_LEVEL": "debug",
                "PYTHONPATH": "${workspaceFolder}/framework/core/src/python;${workspaceFolder}/framework/core/build;${workspaceFolder}/extensions/sim/src/python",
                "PATH": "${workspaceFolder}/framework/core/build;${env:PATH}"
            },
            "args": [],
            "stopOnEntry": false,
            "justMyCode": false,
            "redirectOutput": true,
            "gevent": false
        },
        {
            "name": "Debug TD",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/debug_td.py",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "KF_HOME": "${env:USERPROFILE}\\.kungfu",
                "KF_LOG_LEVEL": "debug",
                "PYTHONPATH": "${workspaceFolder}/framework/core/src/python;${workspaceFolder}/framework/core/build;${workspaceFolder}/extensions/sim/src/python",
                "PATH": "${workspaceFolder}/framework/core/build;${env:PATH}"
            },
            "args": [],
            "stopOnEntry": false,
            "justMyCode": false,
            "redirectOutput": true,
            "gevent": false
        },
        {
            "name": "Debug Strategy",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/debug_strategy.py",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "KF_HOME": "${env:USERPROFILE}\\.kungfu",
                "KF_LOG_LEVEL": "debug",
                "PYTHONPATH": "${workspaceFolder}/framework/core/src/python;${workspaceFolder}/framework/core/build;${workspaceFolder}/examples/strategy-cpp-exe",
                "PATH": "${workspaceFolder}/framework/core/build;${env:PATH}"
            },
            "args": [],
            "stopOnEntry": false,
            "justMyCode": false,
            "redirectOutput": true,
            "gevent": false
        }
    ]
}
```

### 4.2 配置说明

| 配置项 | 说明 |
|--------|------|
| `program` | 调试入口文件路径 |
| `cwd` | 工作目录，设置为项目根目录 |
| `KF_HOME` | Kungfu 数据目录 |
| `KF_LOG_LEVEL` | 日志级别，设置为 debug 便于调试 |
| `KF_NO_EXT` | 禁用扩展加载，加快启动速度 |
| `PYTHONPATH` | Python 模块搜索路径 |
| `PATH` | 系统路径，包含编译后的库 |

---

## 五、设置断点

在以下关键位置设置断点以便调试：

### 5.1 Master 初始化

```python
# master.py 第 34-60 行
class Master(yjj.master):
    def __init__(self, ctx):
        yjj.master.__init__(
            self,
            ctx.location,
            ctx.low_latency,
        )
        # 设置断点：检查 ctx 是否正确初始化
        self.ctx = ctx
        self.ctx.master = self
        self.ctx.apprentices = {}
```

### 5.2 进程注册处理

```python
# master.py 第 79-98 行
def on_register(self, event, register_data):
    pid = register_data.pid
    category = lf.enums.get_category_name(register_data.category)
    mode = lf.enums.get_mode_name(register_data.mode)
    uname = f"{category}/{register_data.group}/{register_data.name}/{mode}"
    # 设置断点：检查注册信息
    self.ctx.logger.info(f"app {pid} {uname} checking in")
```

### 5.3 定时任务执行

```python
# master.py 第 99-105 行
def on_interval_check(self, nanotime):
    try:
        # 设置断点：检查定时任务执行
        run_tasks(self.ctx)
    except RuntimeError:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        err_msg = traceback.format_exception(exc_type, exc_obj, exc_tb)
        self.ctx.logger.error("task error [%s] %s", exc_type, err_msg)
```

---

## 六、启动调试

### 6.1 步骤

1. **打开 VSCode**，确保已安装 Python 扩展
2. **打开项目文件夹**：`d:\workspace\repos\kungfu_demo`
3. **切换到调试视图**：点击左侧活动栏的调试图标（Ctrl+Shift+D）
4. **选择调试配置**：从下拉菜单选择 "Debug Master"
5. **启动调试**：点击绿色三角形按钮或按 F5

### 6.2 预期输出

调试控制台应显示类似以下内容：

```
=== Starting Master in debug mode ===
KF_HOME: C:\Users\YourName\.kungfu
[INFO] master/master/master/live: Master debug session starting...
[INFO] master/master/master/live: Master instance created, running...
```

---

## 七、调试各服务（按启动顺序）

> **重要提示**：服务必须按照以下顺序启动，因为后续服务依赖前面的服务。

### 7.1 调试 Master（核心协调器）

Master 是系统核心协调器，必须最先启动。

创建 `debug_master.py`：

```python
# debug_master.py - Master 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"
os.environ["KF_NO_EXT"] = "on"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))

import kungfu
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger
from kungfu.yijinjing.practice.master import Master

lf = kungfu.__binding__.longfist
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "system"
        self.group = "master"
        self.name = "master"
        self.low_latency = False
        self.log_level = "debug"
        self.location = yjj.location(
            kfj.MODES[self.mode], lf.enums.category.SYSTEM,
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)
        self.apprentices = {}
        self.master = None

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info("Master debug session starting...")
    master = Master(ctx)
    ctx.logger.info("Master instance created, running...")
    master.run()
```

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_master.py`

**Master 推荐断点位置**：

| 文件 | 位置 | 说明 |
|------|------|------|
| `master.py` | `__init__()` | Master 初始化 |
| `master.py` | `on_register()` | 进程注册处理 |
| `master.py` | `on_interval_check()` | 定时任务执行 |

---

### 7.2 调试 Ledger（账本服务）

Ledger 依赖 Master，必须在 Master 之后启动。

创建 `debug_ledger.py`：

```python
# debug_ledger.py - Ledger 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))

import kungfu
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger

lf = kungfu.__binding__.longfist
wc = kungfu.__binding__.wingchun
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "system"
        self.group = "service"
        self.name = "ledger"
        self.low_latency = False
        self.log_level = "debug"
        self.location = yjj.location(
            kfj.MODES[self.mode], lf.enums.category.SYSTEM,
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info("Ledger debug session starting...")
    ledger = wc.Ledger(ctx.runtime_locator, kfj.MODES[ctx.mode], ctx.low_latency)
    ledger.run()
```

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_ledger.py`

**Ledger 推荐断点位置**：

| 文件 | 位置 | 说明 |
|------|------|------|
| `ledger.py` | `on_order()` | 订单处理 |
| `ledger.py` | `on_trade()` | 成交处理 |
| `ledger.py` | `update_asset()` | 资产更新 |

---

### 7.3 调试 Cached（缓存服务）

Cached 依赖 Master 和 Ledger，必须在这两个服务之后启动。

创建 `debug_cached.py`：

```python
# debug_cached.py - Cached 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))

import kungfu
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger

lf = kungfu.__binding__.longfist
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "system"
        self.group = "service"
        self.name = "cached"
        self.low_latency = False
        self.log_level = "debug"
        self.location = yjj.location(
            kfj.MODES[self.mode], lf.enums.category.SYSTEM,
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info("Cached debug session starting...")
    cached = yjj.cached(ctx.runtime_locator, kfj.MODES[ctx.mode], ctx.low_latency)
    cached.run()
```

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_cached.py`

**Cached 推荐断点位置**：

| 文件 | 位置 | 说明 |
|------|------|------|
| `cached.py` | `on_register()` | 新进程注册 |
| `cached.py` | `on_request_cached()` | 缓存数据恢复 |
| `cached.py` | `feed()` | 缓存写入 |

---

### 7.4 调试 MD（行情服务）

MD 服务依赖核心服务，需要加载扩展模块。

创建 `debug_md.py`：

```python
# debug_md.py - MD 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'extensions/sim/src/python'))

import kungfu
import importlib
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger

lf = kungfu.__binding__.longfist
wc = kungfu.__binding__.wingchun
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "md"
        self.group = "sim"
        self.name = "sim"
        self.low_latency = False
        self.log_level = "debug"
        self.extension_path = os.path.join(os.path.dirname(__file__), 'extensions/sim')
        self.location = yjj.location(
            kfj.MODES[self.mode], kfj.CATEGORIES[self.category],
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info(f"MD debug session starting... group={ctx.group}, name={ctx.name}")
    vendor = wc.MarketDataVendor(ctx.runtime_locator, ctx.group, ctx.name, ctx.low_latency)
    sys.path.insert(0, ctx.extension_path)
    module = importlib.import_module(ctx.group)
    service = module.marketdata(vendor)
    vendor.set_service(service)
    ctx.logger.info(f"MD vendor ready: {ctx.location.uname}")
    vendor.run()
```

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_md.py`

**MD 推荐断点位置**：

| 文件 | 位置 | 说明 |
|------|------|------|
| `sim/marketdata.py` | `on_start()` | 模拟行情初始化 |
| `sim/marketdata.py` | `update_orderbooks()` | 订单簿更新 |
| `broker/marketdata.py` | `on_start()` | 行情服务启动 |

---

### 7.5 调试 TD（交易服务）

TD 服务依赖核心服务和扩展模块。

创建 `debug_td.py`：

```python
# debug_td.py - TD 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'extensions/sim/src/python'))

import kungfu
import importlib
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger

lf = kungfu.__binding__.longfist
wc = kungfu.__binding__.wingchun
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "td"
        self.group = "sim"
        self.name = "sim001"
        self.low_latency = False
        self.log_level = "debug"
        self.extension_path = os.path.join(os.path.dirname(__file__), 'extensions/sim')
        self.location = yjj.location(
            kfj.MODES[self.mode], kfj.CATEGORIES[self.category],
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info(f"TD debug session starting... group={ctx.group}, name={ctx.name}")
    vendor = wc.TraderVendor(ctx.runtime_locator, ctx.group, ctx.name, ctx.low_latency)
    sys.path.insert(0, ctx.extension_path)
    module = importlib.import_module(ctx.group)
    service = module.trader(vendor)
    vendor.set_service(service)
    ctx.logger.info(f"TD vendor ready: {ctx.location.uname}")
    vendor.run()
```

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_td.py`

**TD 推荐断点位置**：

| 文件 | 位置 | 说明 |
|------|------|------|
| `sim/trader.py` | `insert_order()` | 订单插入 |
| `sim/trader.py` | `cancel_order()` | 撤单处理 |
| `broker/trader.py` | `handle_order_input()` | 订单输入处理 |
| `broker/trader.py` | `has_self_deal_risk()` | 自成交检测 |

---

### 7.6 调试 Strategy（策略引擎）

Strategy 依赖 MD 和 TD 服务，是最后一个启动的服务。

创建 `debug_strategy.py`：

```python
# debug_strategy.py - Strategy 调试入口
import sys
import os

os.environ["KF_HOME"] = os.path.expanduser("~/.kungfu")
os.environ["KF_LOG_LEVEL"] = "debug"
os.environ["KF_STG_GROUP"] = "default"
os.environ["KF_STG_NAME"] = "debug_strategy"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/src/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'framework/core/build'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'examples/strategy-cpp-exe'))

import kungfu
from kungfu.yijinjing import journal as kfj
from kungfu.yijinjing.log import find_logger
from kungfu.yijinjing.practice.coloop import KungfuEventLoop
from kungfu.wingchun.strategy import Runner, Strategy

lf = kungfu.__binding__.longfist
yjj = kungfu.__binding__.yijinjing

class DebugContext:
    def __init__(self):
        self.runtime_locator = yjj.locator(os.environ.get("KF_HOME"))
        self.mode = "live"
        self.category = "strategy"
        self.group = "default"
        self.name = "debug_strategy"
        self.low_latency = False
        self.log_level = "debug"
        self.path = os.path.join(os.path.dirname(__file__), 'examples/strategy-cpp-exe/strategy.py')
        self.arguments = ""
        self.vendor = None
        self.location = yjj.location(
            kfj.MODES[self.mode], lf.enums.category.STRATEGY,
            self.group, self.name, self.runtime_locator,
        )
        self.logger = find_logger(self.location, self.log_level)

if __name__ == "__main__":
    ctx = DebugContext()
    ctx.logger.info(f"Strategy debug session starting... path={ctx.path}")
    ctx.runner = Runner(ctx, kfj.MODES[ctx.mode])
    ctx.strategy = Strategy(ctx)
    ctx.runner.add_strategy(ctx.strategy)
    ctx.loop = KungfuEventLoop(ctx, ctx.runner)
    ctx.logger.info("Strategy ready to run...")
    ctx.loop.run_forever()
```

将文件保存到项目根目录：`d:\workspace\repos\kungfu_demo\debug_strategy.py`

**策略调试要点**：

1. **设置策略文件路径**：修改 `self.path` 指向你的策略文件
2. **在策略代码中设置断点**：直接在你的策略脚本中设置断点
3. **常用断点位置**：

| 文件 | 位置 | 说明 |
|------|------|------|
| `你的策略.py` | `pre_start()` | 策略初始化 |
| `你的策略.py` | `on_quote()` | 行情回调 |
| `你的策略.py` | `on_bar()` | K线回调 |
| `你的策略.py` | `on_order()` | 订单状态更新 |
| `你的策略.py` | `on_trade()` | 成交回调 |
| `strategy.py` | `pre_start()` | 策略框架初始化 |

---

## 八、调试注意事项

### 8.1 依赖顺序

调试多个服务时，必须按正确顺序启动：

```
1. 启动 Master（调试）
2. 启动 Ledger（调试或命令行）
3. 启动 Cached（调试或命令行）
4. 启动 MD（调试）
5. 启动 TD（调试）
6. 启动 Strategy（调试）
```

### 8.2 端口冲突

如果之前使用 kfc 启动过服务，确保先停止：

```bash
kfc service stop all
```

### 8.3 日志查看

调试时日志会输出到：
- VSCode 调试控制台
- `KF_HOME/runtime/logs/<category>/<group>/<name>/<mode>/*.log`

### 8.4 常见问题

| 问题 | 解决方案 |
|------|----------|
| 模块找不到 | 检查 PYTHONPATH 是否包含正确路径 |
| 绑定错误 | 确保已编译 C++ 核心库 |
| 权限错误 | 检查 KF_HOME 目录权限 |
| 端口占用 | 使用 `kfc service stop all` 停止服务 |

---

## 九、完整调试工作流

```
1. 确保已编译项目
   cd d:\workspace\repos\kungfu_demo
   yarn build

2. 停止任何已运行的服务
   kfc service stop all

3. 在 VSCode 中设置断点

4. 按顺序启动调试会话
   - 启动 Master 调试（会话1）
   - 启动 Ledger 调试（会话2）
   - 启动 Cached 调试（会话3）
   - 启动 MD 调试（会话4）
   - 启动 TD 调试（会话5）
   - 启动 Strategy 调试（会话6）

5. 观察断点触发和日志输出

6. 使用调试工具：
   - 变量查看
   - 调用栈分析
   - 条件断点
   - 监视表达式
```

---

**文档生成时间**：2026-05-20
