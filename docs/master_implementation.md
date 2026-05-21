# Master 程序实现分析

---

## 一、概述

**Master** 是 Kungfu Trader 交易系统的核心协调进程，负责管理所有子进程（Apprentice）的注册、通信和生命周期。它是整个系统的中枢节点，负责：

1. **进程注册管理** - 接收并管理所有子进程的注册请求
2. **通道协调** - 建立进程间的通信通道
3. **时间同步** - 发布交易日信息和时间基准
4. **生命周期管理** - 在退出时优雅地停止所有子进程

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Master                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                C++ Core (master.cpp)                │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │  Event Loop │  │  Registry   │  │  Session    │ │   │
│  │  │  (事件循环)  │  │  (注册表)    │  │  Builder   │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │   Channel   │  │   Timer     │                  │   │
│  │  │  (通道管理)  │  │  (定时器)    │                  │   │
│  │  └─────────────┘  └─────────────┘                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ▲                                │
│                          │  pybind11                       │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │               Python Layer (master.py)              │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │  Calendar   │  │ Apprentices │  │   Tasks     │ │   │
│  │  │  (交易日)    │  │  (子进程)    │  │  (定时任务) │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │  Ledger │    │  Cached │    │    MD   │
        └─────────┘    └─────────┘    └─────────┘
              │               │               │
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │    TD   │    │Strategy │    │  其他   │
        └─────────┘    └─────────┘    └─────────┘
```

### 2.2 类继承关系

```
hero (基类)
    │
    ▼
master (C++ 核心类)
    │
    ▼
Master (Python 扩展类)
```

**hero 基类**：提供基本的事件循环、IO 设备管理等能力

**master (C++)**：核心实现，处理注册、通道、会话管理

**Master (Python)**：扩展 C++ 类，添加交易日管理、任务调度等业务逻辑

---

## 三、C++ 核心实现

### 3.1 构造函数

```cpp
master::master(location_ptr home, bool low_latency)
    : hero(std::make_shared<io_device_master>(home, low_latency)), 
      start_time_(time::now_in_nano()), 
      last_check_(0),
      session_builder_(get_io_device()), 
      profile_(get_locator()) {
  // 1. 设置 profile
  profile_.setup();
  
  // 2. 加载已保存的位置配置
  for (const auto &app_location : profile_.get_all(Location{})) {
    add_location(start_time_, location::make_shared(app_location, get_locator()));
  }
  
  // 3. 加载配置中的位置
  for (const auto &config : profile_.get_all(Config{})) {
    try_add_location(start_time_, location::make_shared(config, get_locator()));
  }

  // 4. 初始化 IO 设备和会话
  auto io_device = std::dynamic_pointer_cast<io_device_master>(get_io_device());
  session_builder_.open_session(master_home_location_, start_time_);
  writers_.emplace(location::PUBLIC, io_device->open_writer(location::PUBLIC));
  get_writer(location::PUBLIC)->mark(start_time_, SessionStart::tag);
}
```

**关键初始化步骤**：
1. 创建 IO 设备（`io_device_master`）
2. 初始化 profile 配置管理
3. 加载持久化的位置信息
4. 创建公共 writer 并标记会话开始

### 3.2 事件处理架构

```cpp
void master::react() {
  // 通道请求处理
  events_ | is(RequestWriteTo::tag) | $$(on_request_write_to(event));
  events_ | is(RequestWriteToBand::tag) | $$(on_request_write_to_band(event));
  events_ | is(RequestReadFrom::tag) | $$(on_request_read_from(event));
  events_ | is(RequestReadFrom::tag) | $$(check_cached_ready_to_read(event));
  events_ | is(RequestReadFromPublic::tag) | $$(on_request_read_from_public(event));
  events_ | is(RequestReadFromSync::tag) | $$(on_request_read_from_sync(event));
  
  // 停止请求
  events_ | is(RequestStop::tag) | filter([&](const event_ptr &event) {
    auto dest = event->dest();
    if (has_location(dest)) {
      auto dest_location = get_location(dest);
      if (dest_location->category == category::SYSTEM and 
          dest_location->group == "master") {
        return true;
      }
    }
    return false;
  }) | $$(signal_stop());
  
  // 其他事件
  events_ | is(ChannelRequest::tag) | $$(on_channel_request(event));
  events_ | is(TimeRequest::tag) | $$(on_time_request(event));
  events_ | is(Location::tag) | $$(on_new_location(event));
  events_ | is(Register::tag) | $$(register_app(event));
  events_ | is(RequestCachedDone::tag) | $$(on_request_cached_done(event));
  events_ | is(Ping::tag) | $$(pong(event));
  events_ | instanceof<journal::frame>() | $$(feed(event));
}
```

### 3.3 进程注册流程

```cpp
void master::register_app(const event_ptr &event) {
  auto io_device = std::dynamic_pointer_cast<io_device_master>(get_io_device());
  auto home = io_device->get_home();

  // 1. 解析注册请求
  auto request_data = event->data_as_string();
  Register register_data(request_data.c_str(), request_data.length());
  auto app_location = location::make_shared(register_data, home->locator);

  // 2. 检查是否已注册
  if (is_location_live(app_location->uid)) {
    SPDLOG_ERROR("location {} has already been registered live", app_location->uname);
    return;
  }

  // 3. 创建 master 命令位置
  auto now = time::now_in_nano();
  auto uid_str = fmt::format("{:08x}", app_location->uid);
  auto master_cmd_location = location::make_shared(
      mode::LIVE, category::SYSTEM, "master", uid_str, home->locator);

  // 4. 添加位置和创建 writer
  try_add_location(event->gen_time(), app_location);
  try_add_location(event->gen_time(), master_cmd_location);
  
  auto app_cmd_writer = get_io_device()->open_writer_at(master_cmd_location, app_location->uid);
  writers_.emplace(app_location->uid, app_cmd_writer);

  // 5. 订阅必要的通道
  reader_->join(app_location, location::PUBLIC, now);
  reader_->join(app_location, location::SYNC, now);
  reader_->join(app_location, master_cmd_location->uid, now);

  // 6. 打开会话并标记开始
  session_builder_.open_session(app_location, event->gen_time());
  app_cmd_writer->mark(event->gen_time(), SessionStart::tag);

  // 7. 发布注册信息到公共通道
  get_writer(location::PUBLIC)->write(event->gen_time(), *app_location);
  get_writer(location::PUBLIC)->write(event->gen_time(), register_data);

  // 8. 设置写权限
  require_write_to(event->gen_time(), app_location->uid, location::PUBLIC);
  require_write_to(event->gen_time(), app_location->uid, location::SYNC);
  require_write_to(event->gen_time(), app_location->uid, master_cmd_location->uid);

  // 9. 发送时间重置和交易日信息
  write_time_reset(event->gen_time(), app_cmd_writer);
  write_trading_day(event->gen_time(), app_cmd_writer);

  // 10. 告知新进程其他活跃位置和注册信息
  write_locations(event->gen_time(), app_cmd_writer);
  write_registries(event->gen_time(), app_cmd_writer);

  // 11. 调用 Python 层的 on_register 回调
  on_register(event, register_data);
}
```

### 3.4 进程注销流程

```cpp
void master::deregister_app(int64_t trigger_time, uint32_t app_location_uid) {
  auto location = get_location(app_location_uid);
  SPDLOG_INFO("app {} gone", location->uname);

  // 1. 关闭会话
  session_builder_.close_session(location, trigger_time);
  
  // 2. 标记会话结束
  get_writer(app_location_uid)->mark(trigger_time, SessionEnd::tag);
  
  // 3. 注销通道和带宽
  deregister_channel(app_location_uid);
  deregister_band(app_location_uid);
  
  // 4. 注销位置
  deregister_location(trigger_time, app_location_uid);
  
  // 5. 清理注册表和 reader
  registry_.erase(app_location_uid);
  reader_->disjoin(app_location_uid);
  
  // 6. 清理 writer 和定时器任务
  writers_.erase(app_location_uid);
  timer_tasks_.erase(app_location_uid);
  
  // 7. 发布注销事件到公共通道
  get_writer(location::PUBLIC)->write(trigger_time, location->to<Deregister>());
}
```

### 3.5 优雅退出机制

```cpp
void master::on_exit() {
  // 1. 通知所有进程注销
  notify_deregister_on_exit();
  
  // 2. 标记所有会话结束
  mark_session_end_on_exit();
  
  // 3. 最后通知 master 自身注销
  notify_master_deregister_on_exit();
}

void master::notify_deregister_on_exit() {
  auto now = time::now_in_nano();
  auto &live_sessions = session_builder_.close_all_sessions(now);
  for (auto &iter : live_sessions) {
    auto &session = iter.second;
    auto location_from_session = location::make_shared(session, get_locator());
    // 跳过 master 自身
    if (session.location_uid != master_home_location_->uid) {
      get_writer(location::PUBLIC)->write(now, location_from_session->to<Deregister>());
    }
  }
}
```

---

## 四、Python 层扩展实现

### 4.1 Master 类定义

```python
class Master(yjj.master):
    def __init__(self, ctx):
        yjj.master.__init__(
            self,
            ctx.location,
            ctx.low_latency,
        )
        self.ctx = ctx
        self.ctx.master = self
        self.ctx.apprentices = {}  # 存储子进程信息

        # 初始化交易日日历
        self.ctx.calendar = Calendar(ctx)
        self.ctx.trading_day = ctx.calendar.trading_day

        # 加载佣金配置
        self.profile = yjj.profile(ctx.runtime_locator)
        self.commissions = {}
        for commission in self.profile.get_all(lf.types.Commission()):
            self.commissions[commission.product_id] = commission
        
        # 应用默认佣金
        try:
            default_commissions.apply(
                lambda default: self.set_default_commission(default), 1
            )
        except RuntimeError:
            self.ctx.logger.error(f"failed to load default commissions")
```

### 4.2 注册回调

```python
def on_register(self, event, register_data):
    pid = register_data.pid
    category = lf.enums.get_category_name(register_data.category)
    mode = lf.enums.get_mode_name(register_data.mode)
    uname = f"{category}/{register_data.group}/{register_data.name}/{mode}"
    self.ctx.logger.info(f"app {pid} {uname} checking in")
    
    if pid not in self.ctx.apprentices:
        try:
            self.ctx.apprentices[pid] = {
                "process": psutil.Process(pid),  # 使用 psutil 监控进程
                "pid": pid,
                "uname": uname,
                "register": register_data,
            }
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            # 进程不存在或无权限访问
            exc_type, exc_obj, exc_tb = sys.exc_info()
            err_msg = traceback.format_exception(exc_type, exc_obj, exc_tb)
            self.ctx.logger.error(f"app [{pid}] {uname} checkin failed: {err_msg}")
            self.deregister_app(event.gen_time, register_data.location_uid)
```

### 4.3 定时任务机制

```python
TASKS = dict()

def task(func):
    @functools.wraps(func)
    def task_wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    TASKS[func.__name__] = task_wrapper
    return task_wrapper

def run_tasks(*args, **kwargs):
    for task_name in TASKS:
        TASKS[task_name](*args, **kwargs)

def on_interval_check(self, nanotime):
    try:
        run_tasks(self.ctx)
    except RuntimeError:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        err_msg = traceback.format_exception(exc_type, exc_obj, exc_tb)
        self.ctx.logger.error("task error [%s] %s", exc_type, err_msg)
```

**内置定时任务**：

```python
@task
def health_check(ctx):
    """健康检查任务 - 清理僵死进程"""
    for pid in list(ctx.apprentices.keys()):
        if not ctx.apprentices[pid]["process"].is_running():
            app = ctx.apprentices[pid]
            ctx.logger.warn(f'cleaning up stale app {app["uname"]} with pid {pid}')
            ctx.master.deregister_app(yjj.now_in_nano(), app["register"].__uid__)
            del ctx.apprentices[pid]

@task
def switch_trading_day(ctx):
    """交易日切换任务"""
    trading_day = ctx.calendar.trading_day
    if ctx.trading_day < trading_day:
        ctx.trading_day = trading_day
        ctx.master.publish_trading_day()
```

### 4.4 退出处理

```python
def on_exit(self):
    # 调用 C++ 层退出逻辑
    yjj.master.on_exit(self)
    
    # Python 层额外处理：终止所有子进程
    for app in self.get_live_processes():
        self.ctx.logger.info(f'terminating apprentice {app["uname"]} pid {app["pid"]}')
        self.deregister_app(yjj.now_in_nano(), app["register"].__uid__)
        try:
            app["process"].terminate()  # 先尝试优雅终止
        except psutil.Error:
            self.ctx.logger.error(f'failed to terminate apprentice {app["uname"]} pid {app["pid"]}')

    # 等待进程退出（最多10秒）
    count = 0
    time_to_wait = 10
    while count < time_to_wait:
        remaining = self.get_live_processes()
        if remaining:
            names = list(map(lambda app: app["uname"], remaining))
            self.ctx.logger.info(
                f"terminating apprentices, remaining {names}, count down {time_to_wait - count}s"
            )
            time.sleep(1)
            count = count + 1
        else:
            break

    # 强制终止仍存活的进程
    for app in self.get_live_processes():
        self.ctx.logger.warn(f'killing apprentice {app["uname"]} pid {app["pid"]}')
        try:
            app["process"].kill()
        except psutil.Error:
            self.ctx.logger.error(f'failed to kill apprentice {app["uname"]} pid {app["pid"]}')

    self.ctx.logger.info("master cleaned up")
```

---

## 五、核心数据结构

### 5.1 Apprentice 信息结构

```python
{
    "process": psutil.Process(pid),  # 进程对象
    "pid": pid,                       # 进程ID
    "uname": "category/group/name/mode",  # 唯一名称
    "register": register_data,        # 注册数据
}
```

### 5.2 Timer Task 结构

```cpp
struct timer_task {
  int64_t checkpoint;      // 下次执行时间
  int64_t duration;        // 执行间隔
  int64_t repeat_limit;    // 重复次数限制
  int64_t repeat_count;    // 已重复次数
};
```

---

## 六、关键方法说明

| 方法 | 说明 | 层级 |
|------|------|------|
| `register_app()` | 处理进程注册请求 | C++ |
| `deregister_app()` | 处理进程注销 | C++ |
| `on_register()` | 注册回调（可扩展） | Python |
| `on_interval_check()` | 定时检查回调 | Python |
| `on_exit()` | 退出处理 | C++/Python |
| `publish_trading_day()` | 发布交易日信息 | C++ |
| `write_time_reset()` | 发送时间基准 | C++ |
| `write_locations()` | 发送位置列表 | C++ |
| `write_registries()` | 发送注册列表 | C++ |

---

## 七、启动方式

### 命令行启动

```bash
# 直接启动
kfc run -m live -c system -g master -n master

# 快捷命令
kfc run master
```

### 启动流程

```
1. kfc CLI 解析命令参数
       │
       ▼
2. 创建 ctx 上下文（包含 location、logger、runtime_locator）
       │
       ▼
3. 初始化 Master 类（Python）
       │
       ▼
4. 调用 C++ master 构造函数
       │
       ▼
5. 启动事件循环（react）
       │
       ▼
6. 等待子进程注册
```

---

## 八、总结

| 特性 | 说明 |
|------|------|
| **核心职责** | 进程注册管理、通道协调、时间同步、生命周期管理 |
| **架构层次** | C++ 核心 + Python 扩展 |
| **通信机制** | Yijinjing 事件总线 |
| **定时任务** | 健康检查、交易日切换 |
| **退出策略** | 优雅终止 → 超时等待 → 强制杀死 |
| **关键依赖** | psutil（进程监控）、pybind11（C++绑定） |

Master 是 Kungfu Trader 的核心协调器，通过事件驱动架构实现高效的进程管理和通信协调。C++ 层提供高性能的事件处理，Python 层提供灵活的业务逻辑扩展。

---

**文档生成时间**：2026-05-20
