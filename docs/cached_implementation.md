# Cached 程序实现分析

---

## 一、概述

**Cached**（缓存服务）是 Kungfu Trader 交易系统的核心服务之一，负责管理系统的运行时缓存数据。它是整个系统的**数据缓存中心**，为新启动的进程提供历史数据恢复，并实时维护交易状态。

**核心职责**：
1. **数据缓存** - 存储和管理交易相关的状态数据（订单、成交、持仓、资产等）
2. **数据恢复** - 为新注册的进程提供缓存数据恢复
3. **Profile 管理** - 维护系统配置数据（佣金、合约信息等）
4. **数据同步** - 确保各进程间的数据一致性

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         Cached                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Feed Bank (状态数据缓存)                │   │
│  │  Order | Trade | Position | Asset | Quote ...      │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Profile Bank (配置数据缓存)              │   │
│  │  Commission | Instrument | Config ...              │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            App Cache Shift (应用缓存移位)            │   │
│  │  为每个进程维护独立的缓存视图                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │   TD    │    │Strategy │    │  Ledger │
        │ (交易)   │    │ (策略)    │    │ (账本)   │
        └─────────┘    └─────────┘    └─────────┘
```

### 2.2 类继承关系

```
apprentice (Yijinjing 子进程基类)
    │
    ▼
cached (缓存服务)
```

**apprentice 基类**：提供与 Master 通信、事件处理、通道管理等基础能力

**cached**：在 apprentice 基础上实现缓存管理逻辑

### 2.3 核心数据结构

| 数据结构 | 类型 | 说明 |
|----------|------|------|
| `app_cache_shift_` | `map<uint32_t, shift>` | 每个进程的缓存移位器 |
| `feed_bank_` | `cache::bank` | 状态数据缓存库 |
| `profile_` | `practice::profile` | 配置数据管理器 |
| `profile_bank_` | `ProfileStateBank` | 配置数据缓存库 |
| `store_volume_every_loop_` | `int` | 每轮存储的数据量限制 |

---

## 三、核心实现

### 3.1 构造函数

```cpp
#define DEFAULT_STORE_VOLUME_BY_INTERVAL 100
#define LOW_LATENCY_STORE_VOLUME_BY_INTERVAL 10

cached::cached(locator_ptr locator, mode m, bool low_latency)
    : apprentice(location::make_shared(m, category::SYSTEM, "service", "cached", std::move(locator)), low_latency),
      profile_(get_locator()),
      store_volume_every_loop_(low_latency ? LOW_LATENCY_STORE_VOLUME_BY_INTERVAL : DEFAULT_STORE_VOLUME_BY_INTERVAL) {
  profile_.setup();
  profile_get_all(profile_, profile_bank_);  // 加载所有 profile 数据到缓存
}
```

**关键配置**：
- **标准模式**：每轮存储 100 条数据
- **低延迟模式**：每轮存储 10 条数据（减少延迟）

### 3.2 事件处理架构

```cpp
void cached::on_react() {
  // 位置更新事件
  events_ | is(Location::tag) | $$(on_location(event));
  
  // 进程注册事件
  events_ | is(Register::tag) | $$(register_triggger_clear_cache_shift(event->data<Register>()));
  events_ | is(Register::tag) | $$(register_trigger_listen_public(event->gen_time(), event->data<Register>()));
  
  // 缓存请求事件（核心）
  events_ | is(RequestCached::tag) | $([&](const event_ptr &event) {
    auto source_id = event->source();
    
    // 1. 创建缓存移位器
    app_cache_shift_.try_emplace(source_id, locations_.at(source_id));
    auto cached_writer = get_writer(source_id);
    
    // 2. 写入缓存数据
    app_cache_shift_.at(source_id) >> cached_writer;
    
    // 3. 写入 profile 数据
    profile_get_all(profile_, profile_bank_);
    profile_bank_ >> cached_writer;
    
    // 4. 通知 Master 缓存完成
    mark_request_cached_done(source_id);
  });
}

void cached::on_start() {
  // 通道变更事件
  events_ | is(Channel::tag) | $$(inspect_channel(event->gen_time(), event->data<Channel>()));
  
  // 缓存重置事件
  events_ | is(CacheReset::tag) | $$(on_cache_reset(event));
  
  // 日志帧事件（过滤掉 master 的消息）
  events_ | instanceof<journal::frame>() | filter([&](const event_ptr &event) {
    auto source_id = event->source();
    return source_id != master_home_location_->uid and 
           source_id != master_cmd_location_->uid;
  }) | $$(feed(event));
}
```

### 3.3 缓存数据恢复流程

```cpp
// 处理缓存请求
events_ | is(RequestCached::tag) | $([&](const event_ptr &event) {
    auto source_id = event->source();

    // 1. 创建缓存移位器实例
    app_cache_shift_.try_emplace(source_id, locations_.at(source_id));
    auto cached_writer = get_writer(source_id);

    // 2. 将缓存数据写入请求进程
    try {
      app_cache_shift_.at(source_id) >> cached_writer;
    } catch (const std::exception &ex) {
      SPDLOG_ERROR("failed to write cache {}", ex.what());
    }

    // 3. 将 profile 数据写入请求进程
    try {
      profile_get_all(profile_, profile_bank_);
      profile_bank_ >> cached_writer;
    } catch (const std::exception &ex) {
      SPDLOG_ERROR("failed to write profile info {}", ex.what());
    }

    // 4. 通知 Master 缓存恢复完成
    mark_request_cached_done(source_id);
  });
```

### 3.4 实时数据缓存

```cpp
void cached::feed(const event_ptr &event) {
  // MD（行情）事件只处理 Instrument 类型
  if (event->msg_type() != Instrument::tag and 
      get_location(event->source())->category == category::MD) {
    return;
  }
  
  // 同时写入状态数据缓存和配置数据缓存
  feed_state_data(event, feed_bank_);
  feed_profile_data(event, profile_bank_);
}
```

### 3.5 主动循环处理

```cpp
void cached::on_active() {
  SPDLOG_TRACE("cached::on_active");
  handle_cached_feeds(store_volume_every_loop_);   // 处理状态数据缓存
  handle_profile_feeds(store_volume_every_loop_);  // 处理配置数据缓存
}

void cached::on_notify() {
  SPDLOG_TRACE("cached::on_notify");
  // 通知时使用低延迟模式（处理更少数据，更快响应）
  handle_cached_feeds(LOW_LATENCY_STORE_VOLUME_BY_INTERVAL);
}
```

### 3.6 缓存数据写入处理

```cpp
void cached::handle_cached_feeds(int store_volume_every_loop) {
  int stored_controller = 0;
  
  // 遍历所有状态数据类型
  boost::hana::for_each(StateDataTypes, [&](auto it) {
    using DataType = typename decltype(+boost::hana::second(it))::type;
    auto hana_type = boost::hana::type_c<DataType>;

    // 获取该类型的缓存映射
    using FeedMap = std::unordered_map<uint64_t, state<DataType>>;
    auto &feed_map = const_cast<FeedMap &>(feed_bank_[hana_type]);

    if (feed_map.size() != 0) {
      auto iter = feed_map.begin();
      // 限制每轮处理的数据量
      while (iter != feed_map.end() and stored_controller <= store_volume_every_loop) {
        auto &s = iter->second;
        auto source_id = s.source;
        auto dest_id = s.dest;
        
        // 如果该源有缓存移位器，则写入缓存
        if (app_cache_shift_.find(source_id) != app_cache_shift_.end()) {
          try {
            app_cache_shift_.at(source_id) << s;
            SPDLOG_TRACE("cache [feed] source {} dest {} {} data {}", 
                         get_location_uname(source_id),
                         get_location_uname(dest_id), 
                         DataType::type_name.c_str(), 
                         s.data.to_string());
          } catch (const std::exception &e) {
            SPDLOG_ERROR("Unexpected exception by handle_cached_feeds {}", e.what());
            break;
          }
          iter = feed_map.erase(iter);
          stored_controller++;
        } else {
          iter++;
        }
      }
    }
  });
}
```

### 3.7 Profile 数据写入处理

```cpp
void cached::handle_profile_feeds(int store_volume_every_loop) {
  int stored_controller = 0;
  
  // 遍历所有配置数据类型
  boost::hana::for_each(ProfileDataTypes, [&](auto it) {
    using DataType = typename decltype(+boost::hana::second(it))::type;
    auto hana_type = boost::hana::type_c<DataType>;

    using FeedMap = std::unordered_map<uint64_t, state<DataType>>;
    auto &feed_map = const_cast<FeedMap &>(profile_bank_[hana_type]);

    if (feed_map.size() != 0) {
      auto iter = feed_map.begin();
      while (iter != feed_map.end() and stored_controller <= store_volume_every_loop) {
        const auto &s = iter->second;
        try {
          profile_ << s;  // 写入持久化存储
          SPDLOG_TRACE("cache [profile] {} data {}", 
                       DataType::type_name.c_str(), 
                       s.data.to_string());
        } catch (const std::exception &e) {
          SPDLOG_ERROR("Unexpected exception by handle_profile_feeds {}", e.what());
          break;
        }
        iter = feed_map.erase(iter);
        stored_controller++;
      }
    }
  });
}
```

### 3.8 通道检测与缓存移位

```cpp
void cached::inspect_channel(int64_t trigger_time, const Channel &channel) {
  // 跳过与自身相关的通道
  if (channel.source_id != get_live_home_uid() and 
      channel.dest_id != get_live_home_uid()) {
    // 订阅该通道的数据
    reader_->join(get_location(channel.source_id), channel.dest_id, trigger_time);
    // 创建缓存移位器
    make_cache_shift(channel.source_id, channel.dest_id);
  }
}

void cached::make_cache_shift(uint32_t source_id, uint32_t dest_id) {
  // 验证源位置存在
  if (locations_.find(source_id) == locations_.end()) {
    SPDLOG_ERROR("no source {} in locations_", get_location_uname(source_id));
    return;
  }

  // 验证源位置活跃
  if (not is_location_live(source_id)) {
    SPDLOG_ERROR("no source {} in registry_", get_location_uname(source_id));
    return;
  }

  // 创建缓存移位器
  const location_ptr &location = locations_.at(source_id);
  app_cache_shift_.emplace(source_id, location);
  ensure_cached_storage(source_id, dest_id);
}
```

### 3.9 进程注册处理

```cpp
void cached::register_trigger_listen_public(int64_t gen_time, const Register &register_data) {
  auto app_uid = register_data.location_uid;
  auto app_location = get_location(app_uid);

  // 只处理 TD（交易）进程
  if (app_location->category != category::TD) {
    return;
  }

  // 订阅公共通道
  reader_->join(app_location, location::PUBLIC, gen_time);
  make_cache_shift(app_uid, location::PUBLIC);
  SPDLOG_INFO("resume {} connection from {}", get_location_uname(app_uid), time::strftime(gen_time));
}

void cached::register_triggger_clear_cache_shift(const Register &register_data) {
  uint32_t location_uid = register_data.location_uid;
  
  // 如果没有缓存移位器，无需清理
  if (app_cache_shift_.find(location_uid) == app_cache_shift_.end()) {
    SPDLOG_INFO("no location_uid {} in app_cache_shift_, no need to clear cache", 
                get_location_uname(location_uid));
    return;
  }

  // 清理缓存移位器（确保下次能正常工作）
  app_cache_shift_.erase(location_uid);
}
```

### 3.10 缓存重置处理

```cpp
void cached::on_cache_reset(const event_ptr &event) {
  auto msg_type = event->data<CacheReset>().msg_type;
  
  // 找到匹配的数据类型并重置
  boost::hana::for_each(StateDataTypes, [&](auto it) {
    using DataType = typename decltype(+boost::hana::second(it))::type;
    if (DataType::tag == msg_type) {
      app_cache_shift_[event->source()] -= typed_event_ptr<DataType>(event);
      app_cache_shift_[event->dest()] /= typed_event_ptr<DataType>(event);
    }
  });
}
```

---

## 四、核心组件说明

### 4.1 Cache Bank（缓存库）

| 类型 | 说明 |
|------|------|
| `feed_bank_` | 存储实时状态数据（订单、成交、持仓、资产等） |
| `profile_bank_` | 存储配置数据（佣金、合约、配置等） |

### 4.2 Cache Shift（缓存移位器）

为每个进程维护独立的缓存视图，支持：
- **写入缓存**：`shift << state`
- **读取缓存**：`shift >> writer`
- **重置缓存**：`shift -= event` 或 `shift /= event`

### 4.3 Profile（配置管理器）

管理系统级配置数据：
- **Commission**：佣金配置
- **Instrument**：合约信息
- **Config**：系统配置

---

## 五、事件处理架构

### 5.1 事件订阅列表

| 事件类型 | 处理函数 | 说明 |
|----------|----------|------|
| `Location` | `on_location()` | 位置更新 |
| `Register` | `register_triggger_clear_cache_shift()` | 清理旧缓存 |
| `Register` | `register_trigger_listen_public()` | 订阅公共通道 |
| `RequestCached` | 匿名处理 | 缓存数据恢复请求 |
| `Channel` | `inspect_channel()` | 通道变更检测 |
| `CacheReset` | `on_cache_reset()` | 缓存重置 |
| `journal::frame` | `feed()` | 实时数据缓存 |

### 5.2 数据流图

```
实时事件 ──> feed() ──> feed_bank_ / profile_bank_
                              │
                              ▼
                    handle_cached_feeds() / handle_profile_feeds()
                              │
                              ▼
                       app_cache_shift_ (持久化)
                              │
                              ▼
                     RequestCached ──> 数据恢复给请求进程
```

---

## 六、启动方式

### 命令行启动

```bash
# 直接启动
kfc run -m live -c system -g service -n cached

# 快捷命令
kfc run cached

# 低延迟模式
kfc run -x cached
```

### 启动流程

```
1. kfc CLI 解析命令参数
       │
       ▼
2. 创建 Cached 实例
       │
       ▼
3. 初始化 Profile 和缓存库
       │
       ▼
4. 加载所有 Profile 数据到内存
       │
       ▼
5. 注册事件处理回调
       │
       ▼
6. 开始事件循环，等待请求
```

---

## 七、关键方法说明

| 方法 | 说明 |
|------|------|
| `on_react()` | 响应事件，处理注册和缓存请求 |
| `on_start()` | 启动初始化，注册通道和缓存事件 |
| `on_active()` | 主动循环处理缓存写入 |
| `on_notify()` | 通知处理，低延迟模式 |
| `feed()` | 实时数据缓存入口 |
| `handle_cached_feeds()` | 处理状态数据缓存写入 |
| `handle_profile_feeds()` | 处理配置数据缓存写入 |
| `make_cache_shift()` | 创建缓存移位器 |
| `mark_request_cached_done()` | 通知缓存恢复完成 |
| `inspect_channel()` | 检测通道并订阅 |

---

## 八、性能优化策略

### 8.1 数据量限制

| 模式 | 每轮处理量 | 说明 |
|------|-----------|------|
| 标准模式 | 100 条 | 正常处理速度 |
| 低延迟模式 | 10 条 | 更快响应，减少延迟 |

### 8.2 异步写入

缓存数据先写入内存（`feed_bank_`、`profile_bank_`），然后在 `on_active()` 中批量写入持久化存储，避免阻塞事件循环。

### 8.3 过滤机制

- MD（行情）事件只处理 `Instrument` 类型，避免大量行情数据进入缓存
- 过滤掉 Master 的消息，减少不必要的处理

---

## 九、总结

| 特性 | 说明 |
|------|------|
| **核心职责** | 数据缓存、数据恢复、Profile 管理、数据同步 |
| **架构层次** | 基于 Yijinjing apprentice 框架 |
| **数据存储** | 内存缓存（feed_bank_）+ 持久化（profile_） |
| **性能优化** | 每轮处理量限制、异步写入、事件过滤 |
| **容错机制** | 异常捕获和日志记录 |

Cached 是 Kungfu Trader 的数据缓存中心，通过内存缓存和持久化存储的结合，为系统提供高效的数据恢复和状态管理能力。

---

**文档生成时间**：2026-05-20
