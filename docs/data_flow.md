# Kungfu Trader 数据流分析

---

## 一、概述

Kungfu Trader 采用基于共享内存（mmap）和 nanomsg 的高性能数据传输架构。数据流核心基于 **Yijinjing** 事件总线框架，通过 Journal（日志）机制实现进程间通信。

---

## 二、核心数据传输机制

### 2.1 Yijinjing 架构

Yijinjing 是整个框架的事件总线，提供三种核心机制：

```
┌─────────────────────────────────────────────────────────────────┐
│                      Yijinjing 事件总线                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Journal   │  │   Publisher │  │       Observer          │  │
│  │  (共享内存)  │  │  (发布者)    │  │      (观察者)           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    nanomsg socket                          │  │
│  │              (PUBLISH/PULL/SUBSCRIBE/PUSH)                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Journal 机制

Journal 是数据存储和传输的核心，基于内存映射文件（mmap）：

```cpp
// journal.h - Journal 类定义
class journal {
public:
    journal(data::location_ptr location, uint32_t dest_id, bool is_writing, bool lazy);
    
    void next();                    // 移动到下一帧
    void seek_to_time(int64_t nanotime);  // 定位到指定时间
    
private:
    const data::location_ptr location_;  // 数据位置
    const uint32_t dest_id_;             // 目标 ID
    page_ptr page_;                      // 当前页
    frame_ptr frame_;                    // 当前帧
};
```

**数据层级结构**：

```
Journal（日志）
    │
    ├── Page（页）- 固定大小的内存映射文件
    │       │
    │       └── Frame（帧）- 单个数据单元
    │               ├── frame_header（帧头）
    │               │       ├── gen_time（生成时间）
    │               │       ├── trigger_time（触发时间）
    │               │       ├── msg_type（消息类型）
    │               │       ├── source（来源）
    │               │       └── dest（目标）
    │               └── data（数据体）
    │
    └── Reader/Writer（读写器）
```

### 2.3 Writer 写入流程

```cpp
// writer.h - 数据写入
class writer {
public:
    // 打开帧
    frame_ptr open_frame(int64_t trigger_time, int32_t msg_type, uint32_t length);
    
    // 关闭帧
    void close_frame(size_t data_length, int64_t gen_time = time::now_in_nano());
    
    // 写入数据（模板方法）
    template <typename T>
    void write(int64_t trigger_time, const T &data, int32_t msg_type = T::tag) {
        auto frame = open_frame(trigger_time, msg_type, sizeof(T));
        auto size = frame->copy_data(data);
        close_frame(size);
    }
};
```

### 2.4 Reader 读取流程

```cpp
// journal.h - 数据读取
class reader {
public:
    // 加入日志
    void join(const data::location_ptr &location, uint32_t dest_id, int64_t from_time);
    
    // 检查数据可用性
    bool data_available();
    
    // 移动到下一帧
    void next();
    
    // 按时间排序
    void sort();
};
```

### 2.5 nanomsg 通信

nanomsg 用于进程间通知和消息传递：

```cpp
// io.cpp - nanomsg 通信实现
class nanomsg_publisher : public publisher {
    int publish(const std::string &json_message, int flags = NN_DONTWAIT) {
        return socket_.send(json_message, flags);
    }
};

class nanomsg_observer : public observer {
    bool wait() override { return socket_.recv(recv_flags_) > 0; }
    const std::string &get_notice() override { return socket_.last_message(); }
};
```

**通信模式**：

| 角色 | Publisher | Observer |
|------|-----------|----------|
| Master | PUBLISH (bind) | PULL (bind) |
| Client | PUSH (connect) | SUBSCRIBE (connect) |

---

## 三、订单数据流

### 3.1 完整订单生命周期

```
┌─────────────────────────────────────────────────────────────────────┐
│                        订单数据流完整路径                             │
└─────────────────────────────────────────────────────────────────────┘

1. 策略发起订单
   Strategy.insert_order()
         │
         ▼
   ┌─────────────────┐
   │  OrderInput     │  策略生成订单输入
   │  (订单输入)      │
   └─────────────────┘
         │
         │  write to Journal (策略 → TD)
         ▼
   ┌─────────────────┐
   │    Journal      │  共享内存传输
   └─────────────────┘
         │
         ▼
2. TD 服务处理
   TraderVendor.react()
         │
         ├─→ 自成交检测 (has_self_deal_risk)
         │         │
         │         └─→ 风险 → Order.status = Error
         │
         ├─→ 批量订单处理 (batch_status_)
         │         │
         │         └─→ 等待 BatchOrderEnd
         │
         └─→ insert_order(event)
                  │
                  ▼
            ┌─────────────────┐
            │     Order       │  TD 生成订单
            │   (订单状态)     │
            └─────────────────┘
                  │
                  │  write to Journal (TD → PUBLIC)
                  ▼
            ┌─────────────────┐
            │    Journal      │  广播到公共通道
            └─────────────────┘
                  │
                  ▼
3. Ledger 账本处理
   Ledger.on_order()
         │
         ├─→ 更新账户账本
         │
         └─→ 更新策略账本
                  │
                  ▼
            ┌─────────────────┐
            │   BookKeeper    │  账本管理
            │   update_book() │
            └─────────────────┘
                  │
                  ▼
4. 交易所回报
   Trader.on_order_report()
         │
         ▼
   ┌─────────────────┐
   │     Order       │  更新订单状态
   │  (状态更新)      │
   └─────────────────┘
         │
         ▼
5. 成交回报
   Trader.on_trade_report()
         │
         ▼
   ┌─────────────────┐
   │     Trade       │  成交信息
   │    (成交)        │
   └─────────────────┘
         │
         │  write to Journal (TD → PUBLIC)
         ▼
   ┌─────────────────┐
   │    Journal      │  广播成交
   └─────────────────┘
         │
         ▼
6. Ledger 成交处理
   Ledger.on_trade()
         │
         ├─→ 更新持仓
         │
         ├─→ 更新资产
         │
         └─→ 计算手续费
                  │
                  ▼
            ┌─────────────────┐
            │    Position     │  持仓更新
            └─────────────────┘
                  │
                  ▼
            ┌─────────────────┐
            │     Asset       │  资产更新
            └─────────────────┘
                  │
                  ▼
7. 策略接收回报
   Strategy.on_order()
   Strategy.on_trade()
```

### 3.2 订单输入处理代码

```cpp
// trader.cpp - 订单输入处理
void Trader::handle_order_input(const event_ptr &event) {
    // 1. 自成交风险检测
    if (has_self_deal_risk(event)) {
        Order &order = get_writer(event->source())->open_data<Order>();
        order_from_input(event->data<OrderInput>(), order);
        order.status = OrderStatus::Error;
        strncpy(order.error_msg, "该委托存在自成交风险,已拒绝下单", ERROR_MSG_LEN);
        get_writer(event->source())->close_data();
        return;
    }

    // 2. 批量订单处理
    if (batch_status_.try_emplace(event->source()).first->second) {
        const OrderInput &input = event->data<OrderInput>();
        order_inputs_.try_emplace(event->source()).first->second.push_back(input);
    } else {
        insert_order(event);
    }
}
```

### 3.3 自成交检测逻辑

```cpp
// trader.cpp - 自成交风险检测
bool Trader::has_self_deal_risk(const event_ptr &event) {
    const OrderInput &input = event->data<OrderInput>();
    auto risk_check = [&]() -> bool {
        // 查找相同标的的订单
        auto iter = map_ex_instrument_to_order_ids_.find(str_ex_instrument);
        if (iter == map_ex_instrument_to_order_ids_.end()) {
            return false;  // 没有相同标的
        }
        
        // 遍历检查是否存在反方向未完成订单
        return std::any_of(iter->second.begin(), iter->second.end(), [&](const auto order_id) {
            const Order &order = orders_.find(order_id)->second.data;
            
            // 方向相同或已完结，无风险
            if (order.side == input.side or is_final_status(order.status)) {
                return false;
            }
            
            // 市价单直接判定风险
            if (input.price_type != PriceType::Limit) {
                return true;
            }
            
            // 限价单价格判断
            if (input.side == Side::Buy and input.limit_price < order.limit_price) {
                return false;  // 买价低于卖价
            } else if (input.side == Side::Sell and input.limit_price > order.limit_price) {
                return false;  // 卖价高于买价
            }
            return true;  // 存在自成交风险
        });
    };
    
    return risk_check();
}
```

---

## 四、行情数据流

### 4.1 行情数据流路径

```
┌─────────────────────────────────────────────────────────────────────┐
│                        行情数据流完整路径                             │
└─────────────────────────────────────────────────────────────────────┘

1. 交易所行情
   Exchange (CTP/XTP/SIM)
         │
         ▼
   ┌─────────────────┐
   │   MarketData    │  接收原始行情
   │   on_quote()    │
   └─────────────────┘
         │
         │  write to Journal (MD → PUBLIC)
         ▼
   ┌─────────────────┐
   │    Journal      │  共享内存广播
   └─────────────────┘
         │
         ├──────────────────┬──────────────────┐
         ▼                  ▼                  ▼
2. 多路分发
   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
   │   Strategy 1    │ │   Strategy 2    │ │    Ledger       │
   │  on_quote()     │ │  on_quote()     │ │  更新行情       │
   └─────────────────┘ └─────────────────┘ └─────────────────┘
         │
         ▼
3. 策略处理
   Strategy.on_quote(quote)
         │
         ├─→ 信号计算
         │
         └─→ 交易决策
                  │
                  ▼
            OrderInput (新订单)
```

### 4.2 行情订阅流程

```cpp
// marketdata.cpp - 行情订阅
void MarketData::try_subscribe() {
    if (not instruments_to_subscribe_.empty()) {
        subscribe(instruments_to_subscribe_);
    }
    instruments_to_subscribe_.clear();
}

void MarketData::add_instrument_key(const InstrumentKey &key) {
    instruments_to_subscribe_.push_back(key);
}
```

### 4.3 MarketDataVendor 事件处理

```cpp
// marketdata.cpp - 行情服务事件处理
void MarketDataVendor::on_react() {
    BrokerVendor::on_react();
    // 接收合约信息
    events_ | is(Instrument::tag) | 
        $$(service_->update_instrument(event->data<Instrument>()));
}

void MarketDataVendor::on_start() {
    BrokerVendor::on_start();
    // 自定义订阅
    events_ | is(CustomSubscribe::tag) | 
        $$(service_->subscribe_custom(event->data<CustomSubscribe>()));
    // 添加合约键
    events_ | is(InstrumentKey::tag) | 
        $$(service_->add_instrument_key(event->data<InstrumentKey>()));
    
    service_->on_start();
    
    // 每秒尝试订阅
    add_time_interval(time_unit::NANOSECONDS_PER_SECOND, 
        [&](auto e) { service_->try_subscribe(); });
}
```

---

## 五、账本数据流

### 5.1 BookKeeper 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BookKeeper 架构                             │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                        Book (账本)                           │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │    │
│  │  │    Asset    │  │  Position   │  │    Order/Trade      │  │    │
│  │  │   (资产)    │  │   (持仓)    │  │    (订单/成交)       │  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Commission (手续费)                       │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Book 更新逻辑

```cpp
// book.cpp - 账本更新
void Book::update(int64_t update_time) {
    asset.update_time = update_time;
    asset.margin = 0;
    asset.market_value = 0;
    asset.unrealized_pnl = 0;
    asset.dynamic_equity = asset.avail;

    auto update_position = [&](Position &position) {
        // 计算持仓市值
        auto position_market_value = 
            position.volume * (position.last_price > 0 ? 
                position.last_price : position.avg_open_price) * db_exchage_rate;
        
        // 累加保证金
        margin += position.margin;
        
        // 更新资产
        asset.market_value += position_market_value;
        asset.unrealized_pnl += position.unrealized_pnl * db_exchage_rate;
        
        // 根据品种类型更新动态权益
        if (is_stock) {
            asset.dynamic_equity += position_market_value;
        } else if (is_future) {
            asset.dynamic_equity += position.margin + position.position_pnl * db_exchage_rate;
        }
    };

    for (auto &pair : long_positions) { update_position(pair.second); }
    for (auto &pair : short_positions) { update_position(pair.second); }
}
```

### 5.3 持仓管理

```cpp
// book.cpp - 持仓获取
Position &Book::get_position(Direction direction, const char *exchange_id, const char *instrument_id) {
    PositionMap &positions = direction == Direction::Long ? long_positions : short_positions;
    auto position_id = hash_instrument(exchange_id, instrument_id);
    auto pair = positions.try_emplace(position_id);
    auto &position = pair.first->second;
    
    if (pair.second) {  // 新建持仓
        position.trading_day = asset.trading_day;
        position.instrument_id = instrument_id;
        position.exchange_id = exchange_id;
        position.instrument_type = get_instrument_type(position.exchange_id, position.instrument_id);
        position.holder_uid = asset.holder_uid;
        position.ledger_category = asset.ledger_category;
        position.direction = direction;
    }
    return position;
}
```

---

## 六、策略数据流

### 6.1 策略事件订阅

```cpp
// runner.cpp - 策略事件订阅
void Runner::post_start() {
    // 行情事件
    events_ | is_own<Quote>(context_->get_broker_client()) |
        $$(invoke(&Strategy::on_quote, event->data<Quote>(), get_location(event->source())));
    
    events_ | is_own<Tree>(context_->get_broker_client()) |
        $$(invoke(&Strategy::on_tree, event->data<Tree>(), get_location(event->source())));
    
    // 订单事件
    events_ | is(Order::tag) | 
        $$(invoke(&Strategy::on_order, event->data<Order>(), get_location(event->source())));
    
    // 成交事件
    events_ | is(Trade::tag) | 
        $$(invoke(&Strategy::on_trade, event->data<Trade>(), get_location(event->source())));
    
    // 自定义事件
    events_ | is_custom() |
        $$(invoke(&Strategy::on_custom_data, event->msg_type(),
                  {event->data_as_bytes(), event->data_as_bytes() + event->data_length()}, 
                  event->data_length(), get_location(event->source())));
    
    // 经纪状态
    events_ | is_own<BrokerStateUpdate>(context_->get_broker_client()) |
        $$(invoke(&Strategy::on_broker_state_change, event->data<BrokerStateUpdate>(),
                  get_location(event->data<BrokerStateUpdate>().location_uid)));
}
```

### 6.2 策略准备流程

```cpp
// runner.cpp - 策略准备
void Runner::prepare(const event_ptr &event) {
    // 处理持仓事件
    if (event->msg_type() == Position::tag) {
        const Position &position = event->data<Position>();
        if (position.holder_uid == get_home_uid()) {
            context_->get_broker_client().subscribe(position.exchange_id, position.instrument_id);
        }
    }

    // 请求经纪状态
    if (not broker_states_requested_ and connected_test(context_->list_accounts())) {
        writer->mark(now(), BrokerStateRequest::tag);
        broker_states_requested_ = true;
    }

    // 请求持仓和资产
    if (not positions_requested_) {
        if (not context_->is_book_held()) {
            writer->mark(now(), KeepPositionsRequest::tag);
            writer->mark(now(), ResetBookRequest::tag);
        }
        
        if (context_->is_positions_mirrored()) {
            writer->mark(now(), MirrorPositionsRequest::tag);
        }
        
        if (not context_->is_book_held() and not context_->is_positions_mirrored()) {
            writer->mark(now(), RebuildPositionsRequest::tag);
        }
        
        writer->mark(now(), AssetRequest::tag);
        writer->mark(now(), PositionRequest::tag);
        positions_requested_ = true;
    }
}
```

---

## 七、Channel 通信机制

### 7.1 Channel 定义

Channel 定义了进程间的通信通道：

```cpp
// types.h - Channel 相关类型
KF_DEFINE_DATA_TYPE(                              //
    Channel, 10015, PK(source_id, dest_id), PERPETUAL(), //
    (uint32_t, source_id),                        // 源 ID
    (uint32_t, dest_id),                          // 目标 ID
    (uint8_t, has_writer),                        // 是否有写入器
    (uint8_t, has_reader)                         // 是否有读取器
);
```

### 7.2 Channel 建立流程

```
1. 进程注册
   Apprentice.on_register()
         │
         ▼
   Register 事件 → Master

2. Master 处理注册
   Master.on_register()
         │
         ├─→ 创建 Location
         │
         ├─→ 订阅 Channel
         │
         └─→ 发布 Channel 事件

3. Channel 事件广播
   Channel 事件 → PUBLIC Journal
         │
         ▼
   所有进程接收 Channel 信息

4. 进程建立连接
   Apprentice.inspect_channel()
         │
         ├─→ 检查 source_id 和 dest_id
         │
         └─→ reader_->join() 建立读取连接
```

---

## 八、数据类型定义

### 8.1 核心数据类型

| 类型 | Tag | 说明 |
|------|-----|------|
| OrderInput | - | 订单输入 |
| Order | - | 订单状态 |
| Trade | - | 成交信息 |
| Quote | - | 行情快照 |
| Bar | - | K线数据 |
| Position | - | 持仓信息 |
| Asset | - | 资产信息 |
| Instrument | - | 合约信息 |
| Channel | 10015 | 通道信息 |
| Register | 10011 | 注册信息 |
| Deregister | 10012 | 注销信息 |

### 8.2 帧头结构

```cpp
// types.h - 帧头定义
KF_DEFINE_PACK_TYPE(                                    //
    frame_header, 0, PK(gen_time), TIMESTAMP(gen_time), //
    (volatile uint32_t, length),      // 总帧长度
    (uint32_t, header_length),        // 头长度
    (int64_t, gen_time),              // 生成时间
    (int64_t, trigger_time),          // 触发时间
    (volatile int32_t, msg_type),     // 消息类型
    (uint32_t, source),               // 来源
    (uint32_t, dest)                  // 目标
);
```

---

## 九、数据流总结图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Kungfu Trader 数据流总览                           │
└─────────────────────────────────────────────────────────────────────────────┘

                            ┌─────────────┐
                            │   Master    │
                            │  (协调器)    │
                            └─────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
             ┌───────────┐  ┌───────────┐  ┌───────────┐
             │  Ledger   │  │  Cached   │  │  Archive  │
             │  (账本)   │  │  (缓存)   │  │  (归档)   │
             └───────────┘  └───────────┘  └───────────┘
                    │              │
                    │              │
         ┌──────────┴──────────────┴──────────┐
         │                                     │
         ▼                                     ▼
  ┌─────────────┐                       ┌─────────────┐
  │     MD      │                       │     TD      │
  │   (行情)    │                       │   (交易)    │
  └─────────────┘                       └─────────────┘
         │                                     │
         │  Quote/Bar/Tree                     │  Order/Trade
         │                                     │
         └──────────────┬──────────────────────┘
                        │
                        ▼
                 ┌─────────────┐
                 │  Strategy   │
                 │   (策略)    │
                 └─────────────┘

数据传输方式：
├── Journal (共享内存 mmap) - 高性能数据传输
├── nanomsg (IPC socket) - 进程间通知
└── Channel - 通信通道管理

数据流向：
├── 行情: Exchange → MD → Journal → Strategy/Ledger
├── 订单: Strategy → Journal → TD → Exchange
├── 回报: Exchange → TD → Journal → Ledger → Strategy
└── 状态: Master → Journal → All Services
```

---

**文档生成时间**：2026-05-20
