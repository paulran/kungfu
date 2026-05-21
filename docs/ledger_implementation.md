# Ledger 程序实现分析

---

## 一、概述

**Ledger**（账本服务）是 Kungfu Trader 交易系统的核心服务之一，负责管理所有交易账户的资产、持仓和订单状态。它是整个系统的**交易数据中心**，实时追踪每一笔交易的状态变化，并将这些信息分发给需要的策略和组件。

**核心职责**：
1. **资产管理** - 追踪每个账户的资金余额、可用资金、保证金等
2. **持仓管理** - 实时更新多头/空头持仓数量和成本
3. **订单统计** - 记录订单的完整生命周期（输入、确认、成交）
4. **经纪状态** - 维护各个交易通道的连接状态
5. **数据同步** - 定期同步资产和持仓数据

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Ledger                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Broker Client                          │   │
│  │  (与交易通道通信，订阅行情)                         │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Bookkeeper                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │   BookMap   │  │  Position   │  │ Accounting  │ │   │
│  │  │  (账本映射)  │  │  (持仓管理)  │  │  (核算方法)  │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Order Statistics                       │   │
│  │  (订单生命周期统计：输入时间、确认时间、成交时间)     │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Broker State Map                       │   │
│  │  (各交易通道的连接状态)                             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │   TD    │    │Strategy │    │  Master │
        │ (交易)   │    │ (策略)    │    │ (核心)   │
        └─────────┘    └─────────┘    └─────────┘
```

### 2.2 类继承关系

```
apprentice (Yijinjing 子进程基类)
    │
    ▼
Ledger (账本服务)
```

**apprentice 基类**：提供与 Master 通信、事件处理、通道管理等基础能力

**Ledger**：在 apprentice 基础上实现交易账本管理逻辑

### 2.3 核心数据结构

| 数据结构 | 类型 | 说明 |
|----------|------|------|
| `broker_client_` | `broker::AutoClient` | 自动重连的经纪客户端 |
| `bookkeeper_` | `book::Bookkeeper` | 账本管理器 |
| `tmp_books_` | `book::BookMap` | 临时账本（用于策略重建） |
| `order_stats_` | `map<uint64_t, state<OrderStat>>` | 订单统计信息 |
| `broker_states_` | `map<uint32_t, BrokerStateUpdate>` | 经纪状态映射 |

---

## 三、核心实现

### 3.1 构造函数

```cpp
Ledger::Ledger(locator_ptr locator, mode m, bool low_latency)
    : apprentice(location::make_shared(m, category::SYSTEM, "service", "ledger", std::move(locator)), low_latency),
      broker_client_(*this), 
      bookkeeper_(*this, broker_client_, true) {}
```

**初始化步骤**：
1. 调用父类 apprentice 构造函数，创建位置标识
2. 初始化 BrokerClient，用于与交易通道通信
3. 初始化 Bookkeeper，用于管理账本

### 3.2 启动流程

```cpp
void Ledger::on_start() {
  // 1. 启动 BrokerClient 和 Bookkeeper
  broker_client_.on_start(events_);
  bookkeeper_.on_start(events_);
  
  // 2. 保护持仓（从缓存恢复）
  bookkeeper_.guard_positions();

  // 3. 注册事件处理
  events_ | is(BrokerStateUpdate::tag) | $$(update_broker_state_map(event->source(), event->data<BrokerStateUpdate>()));
  events_ | is(Deregister::tag) | $$(update_broker_state_map(event->source(), event->data<Deregister>()));
  events_ | is(OrderInput::tag) | $$(update_order_stat(event, event->data<OrderInput>()));
  events_ | is(Order::tag) | $$(update_order_stat(event, event->data<Order>()));
  events_ | is(Trade::tag) | $$(update_order_stat(event, event->data<Trade>()));
  events_ | is(Channel::tag) | $$(inspect_channel(event->gen_time(), event->data<Channel>()));
  events_ | is(KeepPositionsRequest::tag) | $$(keep_positions(event->gen_time(), event->source()));
  events_ | is(RebuildPositionsRequest::tag) | $$(rebuild_positions(event->gen_time(), event->source()));
  events_ | is(MirrorPositionsRequest::tag) | $$(bookkeeper_.mirror_positions(event->gen_time(), event->source()));
  events_ | is(BrokerStateRequest::tag) | $$(write_broker_state(event->gen_time(), event->source()));
  events_ | is(AssetRequest::tag) | $$(write_book_reset(event->gen_time(), event->source()));
  events_ | is(PositionRequest::tag) | $$(write_strategy_data(event->gen_time(), event->source()));
  events_ | is(PositionEnd::tag) | $$(update_account_book(event->gen_time(), event->data<PositionEnd>().holder_uid));

  // 4. 设置定时同步任务（每分钟）
  if (bookkeeper_.is_sync_asset() or bookkeeper_.is_sync_asset_margin()) {
    add_time_interval(time_unit::NANOSECONDS_PER_MINUTE,
                      [&](const event_ptr &e) { request_asset_sync(e->gen_time()); });
  }
  if (bookkeeper_.is_sync_position()) {
    add_time_interval(time_unit::NANOSECONDS_PER_MINUTE,
                      [&](const event_ptr &e) { request_position_sync(e->gen_time()); });
  }
  
  // 5. 刷新所有账本
  refresh_books();
}
```

### 3.3 订单生命周期管理

#### OrderInput 处理

```cpp
void Ledger::update_order_stat(const event_ptr &event, const OrderInput &data) {
  // 1. 更新账本（冻结资金）
  write_book(event->gen_time(), event->dest(), event->source(), data);
  
  // 2. 创建或获取订单统计
  auto &stat = get_order_stat(data.order_id, event);
  stat.order_id = data.order_id;
  stat.md_time = event->trigger_time();
  stat.input_time = event->gen_time();
}
```

#### Order 处理

```cpp
void Ledger::update_order_stat(const event_ptr &event, const Order &data) {
  // 1. 如果没有错误，更新账本
  if (data.error_id == 0) {
    write_book(event->gen_time(), event->source(), event->dest(), data);
  }
  
  // 2. 更新订单统计状态
  auto &stat = get_order_stat(data.order_id, event);
  auto inserted = stat.insert_time != 0;
  auto acked = stat.ack_time != 0;
  
  // 订单首次插入
  if (not inserted) {
    stat.insert_time = event->gen_time();
    write_to(event->gen_time(), stat, event->source());
  }
  
  // 订单确认
  if (inserted and not acked) {
    stat.ack_time = event->gen_time();
    write_to(event->gen_time(), stat, event->source());
  }
}
```

#### Trade 处理

```cpp
void Ledger::update_order_stat(const event_ptr &event, const Trade &data) {
  // 1. 更新账本（成交后更新持仓和资金）
  write_book(event->gen_time(), event->source(), event->dest(), data);
  
  // 2. 更新订单统计
  auto &stat = get_order_stat(data.order_id, event);
  if (stat.trade_time < event->gen_time()) {
    stat.trade_time = event->gen_time();
    stat.total_price += data.price * double(data.volume);
    stat.total_volume += double(data.volume);
    if (stat.total_volume > 0) {
      stat.avg_price = int((stat.total_price / stat.total_volume) * 10000) / 10000.0;
    }
    write_to(event->gen_time(), stat, event->source());
  }
}
```

### 3.4 账本写入机制

```cpp
template <typename TradingData>
void write_book(int64_t trigger_time, uint32_t account_uid, uint32_t strategy_uid, const TradingData &data) {
  write_book(trigger_time, account_uid, data);   // 更新账户账本
  write_book(trigger_time, strategy_uid, data);  // 更新策略账本
}

template <typename TradingData> 
void write_book(int64_t trigger_time, uint32_t book_uid, const TradingData &data) {
  if (not bookkeeper_.has_book(book_uid) or not has_writer(book_uid)) {
    return;
  }
  auto book = bookkeeper_.get_book(book_uid);
  write_to(trigger_time, book->get_position_for(data), book_uid);   // 写入持仓
  write_to(trigger_time, book->asset, book_uid);                     // 写入资产
  write_to(trigger_time, book->asset_margin, book_uid);              // 写入保证金
}
```

### 3.5 经纪状态管理

```cpp
void Ledger::update_broker_state_map(uint32_t location_uid, const BrokerStateUpdate &state) {
  broker_states_.insert_or_assign(location_uid, state);
  write_broker_state_to_public();  // 广播到公共通道
}

void Ledger::update_broker_state_map(uint32_t location_uid, [[maybe_unused]] const Deregister &deregister) {
  broker_states_.erase(location_uid);
  write_broker_state_to_public();  // 广播到公共通道
}

void Ledger::write_broker_state_to_public() {
  auto writer = get_writer(0);  // 公共位置
  for (const auto &pair : broker_states_) {
    auto &broker_state = pair.second;
    writer->write(now(), broker_state);
  }
}
```

### 3.6 持仓重建机制

```cpp
void Ledger::keep_positions([[maybe_unused]] int64_t trigger_time, uint32_t strategy_uid) {
  if (bookkeeper_.has_book(strategy_uid)) {
    auto strategy_book = bookkeeper_.get_book(strategy_uid);
    tmp_books_.insert_or_assign(strategy_uid, strategy_book);  // 保存到临时存储
    bookkeeper_.drop_book(strategy_uid);                        // 从主存储移除
  }
}

void Ledger::rebuild_positions(int64_t trigger_time, uint32_t strategy_uid) {
  auto strategy_book = bookkeeper_.get_book(strategy_uid);
  
  auto rebuild_book = [&](const auto &positions) {
    for (const auto &pair : positions) {
      auto &position = pair.second;
      if (strategy_book->has_position_for(position)) {
        auto &strategy_position = strategy_book->get_position_for(position.direction, position);
        longfist::copy(strategy_position, position);
        strategy_position.update_time = trigger_time;
      }
    }
  };

  if (tmp_books_.find(strategy_uid) != tmp_books_.end()) {
    auto tmp_book = tmp_books_.at(strategy_uid);
    rebuild_book(tmp_book->long_positions);
    rebuild_book(tmp_book->short_positions);
  }
  strategy_book->update(trigger_time);
}
```

### 3.7 定时同步任务

```cpp
void Ledger::request_asset_sync(int64_t trigger_time) {
  for (const auto &pair : bookkeeper_.get_books()) {
    auto &book = pair.second;
    auto &asset = book->asset;
    if (asset.ledger_category == LedgerCategory::Account and has_writer(asset.holder_uid)) {
      get_writer(asset.holder_uid)->mark(trigger_time, AssetSync::tag);
    }
  }
}

void Ledger::request_position_sync(int64_t trigger_time) {
  for (const auto &pair : bookkeeper_.get_books()) {
    auto &book = pair.second;
    auto &asset = book->asset;
    if (asset.ledger_category == LedgerCategory::Account and has_writer(asset.holder_uid)) {
      get_writer(asset.holder_uid)->mark(trigger_time, PositionSync::tag);
    }
  }
}
```

---

## 四、Bookkeeper 核心组件

### 4.1 主要功能

Bookkeeper 是 Ledger 的核心组件，负责管理所有账本：

| 功能 | 说明 |
|------|------|
| **账本创建/删除** | 根据位置UID创建或删除账本 |
| **持仓管理** | 管理多头/空头持仓 |
| **资产更新** | 更新账户资产信息 |
| **核算方法** | 支持不同工具类型的核算方法 |
| **持仓保护** | 从缓存恢复持仓状态 |
| **镜像持仓** | 将持仓同步到策略 |

### 4.2 数据结构

```cpp
typedef std::unordered_map<uint32_t, Book_ptr> BookMap;  // 账本映射
typedef std::unordered_map<uint32_t, state<Quote>> QuoteMap;  // 行情缓存

class Bookkeeper {
private:
  QuoteMap quotes_;                          // 行情数据
  BookMap books_;                            // 账本映射
  BookMap books_replica_;                    // 账本副本（用于同步）
  AccountingMethodMap accounting_methods_;   // 核算方法映射
  CommissionMap commissions_;                // 佣金配置
  InstrumentMap instruments_;                // 工具信息
};
```

### 4.3 账本更新流程

```cpp
template <typename TradingData, typename ApplyMethod>
void update_book(int64_t update_time, uint32_t source, uint32_t dest, 
                 const TradingData &data, ApplyMethod method) {
  std::lock_guard<std::mutex> lock(update_book_mutex_);  // 线程安全

  // 查找核算方法
  if (accounting_methods_.find(data.instrument_type) == accounting_methods_.end()) {
    SPDLOG_WARN("accounting method not found");
    return;
  }
  
  AccountingMethod &accounting_method = *accounting_methods_.at(data.instrument_type);
  
  auto apply_and_update = [&](uint32_t book_uid) {
    auto book = get_book(book_uid);
    auto &position = book->get_position_for(data);
    (accounting_method.*method)(book, data);  // 应用核算方法
    position.update_time = update_time;
    book->replace(data);
    book->update(update_time);
  };
  
  apply_and_update(source);  // 更新源账本
  if (dest != location::PUBLIC) {
    apply_and_update(dest);  // 更新目标账本
  }
}
```

---

## 五、事件处理架构

### 5.1 事件订阅列表

| 事件类型 | 处理函数 | 说明 |
|----------|----------|------|
| `BrokerStateUpdate` | `update_broker_state_map()` | 更新经纪状态 |
| `Deregister` | `update_broker_state_map()` | 移除经纪状态 |
| `OrderInput` | `update_order_stat()` | 订单输入 |
| `Order` | `update_order_stat()` | 订单状态更新 |
| `Trade` | `update_order_stat()` | 成交信息 |
| `Channel` | `inspect_channel()` | 通道变更 |
| `KeepPositionsRequest` | `keep_positions()` | 保存持仓 |
| `RebuildPositionsRequest` | `rebuild_positions()` | 重建持仓 |
| `MirrorPositionsRequest` | `bookkeeper_.mirror_positions()` | 镜像持仓 |
| `BrokerStateRequest` | `write_broker_state()` | 查询经纪状态 |
| `AssetRequest` | `write_book_reset()` | 查询资产 |
| `PositionRequest` | `write_strategy_data()` | 查询持仓 |
| `PositionEnd` | `update_account_book()` | 持仓同步完成 |

### 5.2 事件处理流程图

```
OrderInput ──┐
             ├──> update_order_stat() ──> write_book() ──> Bookkeeper.update_book()
Order ───────┤                                              │
             │                                              ▼
Trade ───────┘                                      更新持仓/资产
                                                      │
                                                      ▼
                                              写入目标通道
```

---

## 六、启动方式

### 命令行启动

```bash
# 直接启动
kfc run -m live -c system -g service -n ledger

# 快捷命令
kfc run ledger

# 重放模式
kfc run ledger -r -i <session_id>
```

### 启动流程

```
1. kfc CLI 解析命令参数
       │
       ▼
2. 创建 Wingchun Ledger 实例
       │
       ▼
3. 初始化 BrokerClient 和 Bookkeeper
       │
       ▼
4. 恢复缓存中的持仓状态
       │
       ▼
5. 注册事件处理回调
       │
       ▼
6. 设置定时同步任务
       │
       ▼
7. 刷新所有账本并开始事件循环
```

---

## 七、关键方法说明

| 方法 | 说明 |
|------|------|
| `on_start()` | 启动初始化，注册事件处理 |
| `write_book()` | 写入持仓和资产信息 |
| `update_order_stat()` | 更新订单统计信息 |
| `refresh_books()` | 刷新所有账本 |
| `refresh_account_book()` | 刷新指定账户账本 |
| `keep_positions()` | 保存策略持仓 |
| `rebuild_positions()` | 重建策略持仓 |
| `write_broker_state()` | 写入经纪状态 |
| `write_strategy_data()` | 写入策略数据 |
| `request_asset_sync()` | 请求资产同步 |
| `request_position_sync()` | 请求持仓同步 |

---

## 八、总结

| 特性 | 说明 |
|------|------|
| **核心职责** | 资产管理、持仓管理、订单统计、经纪状态维护 |
| **架构层次** | 基于 Yijinjing apprentice 框架 |
| **核心组件** | Bookkeeper（账本管理）、BrokerClient（经纪通信） |
| **数据同步** | 每分钟定时同步资产和持仓 |
| **线程安全** | 使用 mutex 保护账本更新 |
| **容错机制** | 支持持仓保护和重建 |

Ledger 是 Kungfu Trader 的交易数据中心，通过 Bookkeeper 管理所有账户和策略的账本，实时追踪交易状态变化，并提供查询接口供其他组件使用。

---

**文档生成时间**：2026-05-20
