# TD (交易) 程序实现分析

---

## 一、概述

**TD**（Trading，交易服务）是 Kungfu Trader 交易系统的核心业务服务之一，负责处理订单的提交、撤销、查询以及获取账户和持仓信息。它是整个系统的**交易执行入口**，提供统一的交易接口和订单生命周期管理。

**核心职责**：
1. **订单管理** - 订单提交、撤销、状态更新
2. **账户管理** - 获取账户资产信息
3. **持仓管理** - 获取持仓信息
4. **自成交检测** - 防止同一账户内的自成交
5. **数据恢复** - 重启后恢复订单状态

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         TD Service                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TraderVendor                           │   │
│  │  (事件循环、消息路由、连接管理)                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   Trader                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ insert_order│  │cancel_order│  │ req_account │ │   │
│  │  │  (下单)      │  │ (撤单)      │  │  (查账户)    │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │req_position │  │req_order   │  │self_deal    │ │   │
│  │  │  (查持仓)    │  │  (查订单)    │  │  (自成交检测) │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│        ┌─────────────────┼─────────────────┐              │
│        ▼                 ▼                 ▼              │
│  ┌─────────┐      ┌─────────┐      ┌─────────┐          │
│  │   XTP   │      │   CTP   │      │   SIM   │          │
│  │ (实盘)   │      │ (实盘)   │      │ (模拟)   │          │
│  └─────────┘      └─────────┘      └─────────┘          │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
        ┌─────────┐                     ┌─────────┐
        │Strategy │                     │  Ledger │
        │ (策略)    │                     │ (账本)   │
        └─────────┘                     └─────────┘
```

### 2.2 类继承关系

```
apprentice (Yijinjing 子进程基类)
    │
    ▼
BrokerVendor (经纪供应商基类)
    │
    ▼
TraderVendor (交易供应商)
    │
    │  ┌─────────────────────────────┐
    │  │  持有 Trader 服务实例       │
    │  └─────────────────────────────┘
    │
    ▼ (通过模板/扩展实现)
Trader (交易服务接口)
    │
    ├── TraderXTP (XTP 实现)
    ├── TraderCTP (CTP 实现)
    └── TraderSim (模拟实现)
```

### 2.3 核心数据结构

| 数据结构 | 类型 | 说明 |
|----------|------|------|
| `orders_` | `OrderMap` | 当前订单状态映射 |
| `actions_` | `OrderActionMap` | 撤单操作映射 |
| `trades_` | `TradeMap` | 成交记录映射 |
| `order_inputs_` | `map<uint64_t, vector<OrderInput>>` | 批量订单输入缓存 |
| `batch_status_` | `map<uint64_t, bool>` | 策略批量模式状态 |
| `self_deal_detect_` | `bool` | 是否启用自成交检测 |

---

## 三、核心实现

### 3.1 TraderVendor 启动流程

```cpp
void TraderVendor::on_start() {
  BrokerVendor::on_start();

  // 注册订单相关事件
  events_ | is(BlockMessage::tag) | $$(service_->insert_block_message(event));
  events_ | is(OrderAction::tag) | $$(service_->cancel_order(event));
  
  // 注册查询相关事件
  events_ | is(AssetRequest::tag) | $$(service_->req_account());
  events_ | is(OrderTradeRequest::tag) | $$(service_->req_order_trade());
  events_ | is(PositionRequest::tag) | $$(service_->req_position());
  
  // 注册历史查询事件
  events_ | is(RequestHistoryOrder::tag) | $$(service_->req_history_order(event));
  events_ | is(RequestHistoryTrade::tag) | $$(service_->req_history_trade(event));
  
  // 注册同步事件
  events_ | is(AssetSync::tag) | $$(service_->handle_asset_sync());
  events_ | is(PositionSync::tag) | $$(service_->handle_position_sync());
  
  // 注册批量订单事件
  events_ | is(BatchOrderBegin::tag, BatchOrderEnd::tag) | $$(service_->handle_batch_order_tag(event));
  
  // 注册策略退出事件
  events_ | is(Deregister::tag) | $$(service_->on_strategy_exit(event));

  // 恢复订单状态
  service_->recover();
  service_->on_recover();
  
  // 启动具体服务
  service_->on_start();
}
```

### 3.2 Trader 核心接口

```cpp
class Trader : public BrokerService {
public:
  // 账户类型（纯虚函数）
  virtual longfist::enums::AccountType get_account_type() const = 0;
  
  // 订单操作（纯虚函数）
  virtual bool insert_order(const event_ptr &event) = 0;
  virtual bool cancel_order(const event_ptr &event) = 0;
  
  // 查询操作（纯虚函数）
  virtual bool req_position() = 0;
  virtual bool req_account() = 0;
  virtual bool req_order_trade() = 0;
  
  // 可选操作
  virtual bool insert_batch_orders(const event_ptr &event) { return true; }
  virtual bool req_history_order(const event_ptr &event) { return true; }
  virtual bool req_history_trade(const event_ptr &event) { return true; }
};
```

### 3.3 订单输入处理

```cpp
void Trader::handle_order_input(const event_ptr &event) {
  // 1. 自成交风险检测
  if (has_self_deal_risk(event)) {
    Order &order = get_writer(event->source())->open_data<Order>();
    order_from_input(event->data<OrderInput>(), order);
    order.status = OrderStatus::Error;
    strncpy(order.error_msg, "该委托存在自成交风险,已拒绝下单", ERROR_MSG_LEN);
    order.insert_time = event->gen_time();
    order.update_time = event->gen_time();
    get_writer(event->source())->close_data();
    return;
  }

  // 2. 判断是否批量模式
  if (batch_status_.try_emplace(event->source()).first->second) {
    // 批量模式：缓存订单输入
    const OrderInput &input = event->data<OrderInput>();
    order_inputs_.try_emplace(event->source()).first->second.push_back(input);
  } else {
    // 非批量模式：立即下单
    insert_order(event);
  }
}
```

### 3.4 自成交检测机制

```cpp
bool Trader::has_self_deal_risk(const event_ptr &event) {
  if (not self_deal_detect_) {
    return false;
  }
  
  const OrderInput &input = event->data<OrderInput>();
  std::string str_ex_instrument = input.exchange_id.to_string() + input.instrument_id.to_string();
  
  auto risk_check = [&]() -> bool {
    auto iter = map_ex_instrument_to_order_ids_.find(str_ex_instrument);
    
    // 没有相同标的，无风险
    if (iter == map_ex_instrument_to_order_ids_.end()) {
      return false;
    }
    
    // 存在相同标的，遍历判断
    return std::any_of(iter->second.begin(), iter->second.end(), [&](const auto order_id) -> bool {
      const auto order_iter = orders_.find(order_id);
      if (order_iter == orders_.end()) return false;
      
      const Order &order = order_iter->second.data;
      
      // 方向相同或委托完结，无风险
      if (order.side == input.side or is_final_status(order.status)) {
        return false;
      }
      
      // 市价委托 + 反方向未完成委托，有风险
      if (input.price_type != PriceType::Limit) {
        return true;
      }
      
      // 限价委托，判断价格
      if (input.side == Side::Buy and input.limit_price < order.limit_price) {
        return false; // 买价低于卖价，无风险
      } else if (input.side == Side::Sell and input.limit_price > order.limit_price) {
        return false; // 卖价高于买价，无风险
      } else {
        return true; // 存在自成交风险
      }
    });
  };

  if (risk_check()) {
    return true;
  }
  // 记录订单到风险检测映射
  map_ex_instrument_to_order_ids_.try_emplace(str_ex_instrument).first->second.emplace(input.order_id);
  return false;
}
```

**自成交检测逻辑**：
1. **方向相同**：无风险（都是买或都是卖）
2. **订单完结**：无风险（已成交或已撤销）
3. **市价委托**：有风险（可能立即成交）
4. **限价委托**：比较价格判断是否可能成交

### 3.5 批量订单处理

```cpp
void Trader::handle_batch_order_tag(const event_ptr &event) {
  if (event->msg_type() == BatchOrderBegin::tag) {
    // 开始批量模式
    batch_status_.insert_or_assign(event->source(), true);
  } else if (event->msg_type() == BatchOrderEnd::tag) {
    // 结束批量模式
    batch_status_.insert_or_assign(event->source(), false);
    insert_batch_orders(event);  // 批量下单
    clear_order_inputs(event->source());  // 清理缓存
  }
}
```

### 3.6 订单状态恢复

```cpp
void Trader::recover() {
  if (disable_recover_) {
    return;
  }
  deal_write_frame();  // 从写入帧恢复
  deal_read_frame();   // 从读取帧恢复
}

void Trader::deal_write_frame() {
  assemble asb_write(get_home(), location::PUBLIC, AssembleMode::Write);
  asb_write.seek_to_time(time::today_start());  // 从今日开始恢复
  
  while (asb_write.data_available()) {
    const auto &frame = asb_write.current_frame();
    if (frame->msg_type() == Order::tag) {
      const Order &order = frame->data<Order>();
      orders_.insert_or_assign(order.order_id, 
          state<Order>(frame->source(), frame->dest(), frame->gen_time(), order));
      map_ex_instrument_to_order_ids_.try_emplace(
          order.exchange_id.to_string() + order.instrument_id.to_string())
          .first->second.emplace(order.order_id);
    } else if (frame->msg_type() == Trade::tag) {
      const Trade &trade = frame->data<Trade>();
      trades_.insert_or_assign(trade.trade_id, 
          state<Trade>(frame->source(), frame->dest(), frame->gen_time(), trade));
    }
    asb_write.next();
  }
  
  // 将无外部订单ID的订单标记为 Lost
  for (auto &pair : orders_) {
    Order &order = pair.second.data;
    if (not is_final_status(order.status) and 
        (order.external_order_id.to_string().empty() or disable_recover_)) {
      order.status = OrderStatus::Lost;
      order.update_time = time::now_in_nano();
      if (has_writer(pair.second.dest)) {
        write_to(order, pair.second.dest);
      }
    }
  }
}

void Trader::deal_read_frame() {
  assemble asb_read(get_home(), get_home_uid(), AssembleMode::Read);
  asb_read.disjoin(get_vendor().get_ledger_home_location()->location_uid);
  asb_read.disjoin(get_vendor().get_master_home_location()->location_uid);
  asb_read.seek_to_time(time::today_start());
  
  while (asb_read.data_available()) {
    const auto &frame = asb_read.current_frame();
    if (frame->msg_type() == OrderInput::tag) {
      const OrderInput &order_input = frame->data<OrderInput>();
      // 如果订单不在 orders_ 中，说明下单失败，标记为 Lost
      if (orders_.find(order_input.order_id) == orders_.end()) {
        if (has_writer(frame->source())) {
          Order &order = get_writer(frame->source())->open_data<Order>();
          order_from_input(order_input, order);
          order.status = OrderStatus::Lost;
          order.update_time = time::now_in_nano();
          get_writer(frame->source())->close_data();
        }
      }
    }
    asb_read.next();
  }
}
```

---

## 四、具体实现示例

### 4.1 XTP 交易实现

```cpp
class TraderXTP : public XTP::API::TraderSpi, public broker::Trader {
public:
  bool insert_order(const event_ptr &event) override {
    const OrderInput &input = event->data<OrderInput>();
    
    // 构造 XTP 订单结构
    XTPOrderInsertInfo xtp_order{};
    // ... 设置订单参数 ...
    
    // 调用 XTP API
    uint64_t xtp_order_id = api_->InsertOrder(&xtp_order, session_id_);
    
    // 维护订单ID映射
    map_kf_to_xtp_order_id_.emplace(input.order_id, xtp_order_id);
    map_xtp_to_kf_order_id_.emplace(xtp_order_id, input.order_id);
    
    return true;
  }

  void OnOrderEvent(XTPOrderInfo *order_info, XTPRI *error_info, uint64_t session_id) override {
    // 将 XTP 订单状态转换为内部格式
    Order order{};
    // ... 转换逻辑 ...
    
    // 更新订单状态
    orders_.insert_or_assign(order.order_id, 
        state<Order>(get_home_uid(), location::PUBLIC, now(), order));
    
    // 写入公共通道
    write_to(now(), order);
  }

  void OnTradeEvent(XTPTradeReport *trade_info, uint64_t session_id) override {
    // 将 XTP 成交信息转换为内部格式
    Trade trade{};
    // ... 转换逻辑 ...
    
    // 更新成交记录
    trades_.insert_or_assign(trade.trade_id, 
        state<Trade>(get_home_uid(), location::PUBLIC, now(), trade));
    
    // 写入公共通道
    write_to(now(), trade);
  }
};
```

### 4.2 SIM 模拟交易实现

```python
class TraderSim(wc.Trader):
    def __init__(self, vendor):
        wc.Trader.__init__(self, vendor)
        self.match_mode = None
        self.ctx.orders = {}
        self.enable_self_detect()  # 启用自成交检测

    def on_start(self):
        config = json.loads(self.config)
        self.match_mode = config.get("match_mode", MatchMode.Custom)
        
        if self.match_mode == MatchMode.Custom:
            # 加载自定义匹配器
            path = config.get("path")
            impl = importlib.import_module(path)
            self.ctx.insert_order = getattr(impl, "insert_order", lambda ctx, event: False)
            # ...
        
        self.update_broker_state(lf.enums.BrokerState.Ready)

    def insert_order(self, event):
        if self.match_mode == MatchMode.Custom:
            return self.ctx.insert_order(self.ctx, event)
        else:
            order_input = event.OrderInput()
            order = wc.utils.order_from_input(order_input)
            order.external_order_id = str(order.order_id)
            
            # 根据匹配模式设置订单状态
            if self.match_mode == MatchMode.Reject:
                order.status = lf.enums.OrderStatus.Error
            elif self.match_mode == MatchMode.Pend:
                order.status = lf.enums.OrderStatus.Pending
            elif self.match_mode == MatchMode.Fill:
                order.status = lf.enums.OrderStatus.Filled
                # 生成成交记录
                trade = lf.types.Trade()
                trade.trade_id = writer.current_frame_uid()
                trade.order_id = order.order_id
                trade.volume = order.volume
                trade.price = order.limit_price
                writer.write(event.gen_time, trade)
            
            self.ctx.orders[order.order_id] = order
            writer.write(event.gen_time, order)
            return True
```

**SIM 匹配模式**：

| 模式 | 说明 |
|------|------|
| `Reject` | 拒绝所有订单 |
| `Pend` | 订单挂起（等待成交） |
| `Cancel` | 立即取消 |
| `PartialFillAndCancel` | 部分成交后取消剩余 |
| `PartialFill` | 部分成交 |
| `Fill` | 完全成交 |
| `Custom` | 自定义匹配逻辑 |

---

## 五、事件处理架构

### 5.1 事件订阅列表

| 事件类型 | 处理函数 | 说明 |
|----------|----------|------|
| `OrderInput` | `handle_order_input()` | 订单输入 |
| `OrderAction` | `cancel_order()` | 撤单请求 |
| `BlockMessage` | `insert_block_message()` | 批量消息 |
| `AssetRequest` | `req_account()` | 查询账户 |
| `PositionRequest` | `req_position()` | 查询持仓 |
| `OrderTradeRequest` | `req_order_trade()` | 查询订单成交 |
| `AssetSync` | `handle_asset_sync()` | 资产同步 |
| `PositionSync` | `handle_position_sync()` | 持仓同步 |
| `BatchOrderBegin/BatchOrderEnd` | `handle_batch_order_tag()` | 批量订单标记 |
| `Deregister` | `on_strategy_exit()` | 策略退出 |

### 5.2 订单生命周期

```
OrderInput ──> handle_order_input()
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
  自成交检测            批量模式判断
        │                   │
        ▼                   ▼
    有风险              缓存订单
        │                   │
        ▼                   ▼
  返回错误            立即下单/批量下单
        │                   │
        ▼                   ▼
    Order(Error)         insert_order()
                              │
                              ▼
                       交易所API提交
                              │
                              ▼
                       Order状态更新
                              │
                              ▼
                       Trade(成交)
```

---

## 六、启动方式

### 命令行启动

```bash
# 启动 XTP 交易
kfc run -m live -c td -g xtp -n account001

# 启动 SIM 模拟交易
kfc run -m live -c td -g sim -n sim001

# 完整参数
kfc -X "扩展目录" run -c td -g <source> -n <account_id>
```

### 启动流程

```
1. kfc CLI 解析命令参数
       │
       ▼
2. 创建 TraderVendor 实例
       │
       ▼
3. 加载对应的扩展模块（XTP/SIM/CTP）
       │
       ▼
4. 创建具体的 Trader 服务实例
       │
       ▼
5. 注册事件处理回调
       │
       ▼
6. 恢复订单状态（recover）
       │
       ▼
7. 启动事件循环
```

---

## 七、关键方法说明

| 方法 | 说明 | 所属类 |
|------|------|--------|
| `on_start()` | 启动初始化 | TraderVendor |
| `handle_order_input()` | 处理订单输入 | Trader |
| `has_self_deal_risk()` | 自成交风险检测 | Trader |
| `insert_order()` | 提交订单（纯虚函数） | Trader |
| `cancel_order()` | 撤销订单（纯虚函数） | Trader |
| `req_account()` | 查询账户（纯虚函数） | Trader |
| `req_position()` | 查询持仓（纯虚函数） | Trader |
| `recover()` | 恢复订单状态 | Trader |
| `deal_write_frame()` | 从写入帧恢复 | Trader |
| `deal_read_frame()` | 从读取帧恢复 | Trader |

---

## 八、总结

| 特性 | 说明 |
|------|------|
| **核心职责** | 订单管理、账户管理、持仓管理、自成交检测 |
| **架构层次** | 基于 Yijinjing apprentice 框架 |
| **设计模式** | 模板方法模式（基类定义流程，子类实现细节） |
| **扩展机制** | 通过扩展模块支持不同交易所 |
| **容错机制** | 订单状态恢复、自成交检测、批量订单支持 |

TD 服务是 Kungfu Trader 的交易执行入口，通过统一的接口抽象，支持多种交易所的交易接入，并提供完整的订单生命周期管理和风险控制能力。

---

**文档生成时间**：2026-05-20
