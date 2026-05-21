# MD (行情数据) 程序实现分析

---

## 一、概述

**MD**（Market Data，行情数据服务）是 Kungfu Trader 交易系统的核心业务服务之一，负责从交易所获取实时行情数据并分发给策略和其他组件。它是整个系统的**行情数据入口**，提供统一的行情订阅和分发机制。

**核心职责**：
1. **行情订阅** - 订阅指定合约的实时行情
2. **行情分发** - 将行情数据广播到公共通道
3. **合约管理** - 维护合约信息（Instrument）
4. **连接管理** - 维护与交易所的连接状态

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        MD Service                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MarketDataVendor                       │   │
│  │  (事件循环、消息路由、连接管理)                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MarketData (接口)                       │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │  subscribe  │  │unsubscribe │  │ instruments │ │   │
│  │  │  (订阅)      │  │ (取消订阅)   │  │  (合约管理)  │ │   │
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
                              ▼
                    ┌─────────────────┐
                    │   策略 / Ledger │
                    └─────────────────┘
```

### 2.2 类继承关系

```
apprentice (Yijinjing 子进程基类)
    │
    ▼
BrokerVendor (经纪供应商基类)
    │
    ▼
MarketDataVendor (行情供应商)
    │
    │  ┌─────────────────────────────────────┐
    │  │  持有 MarketData 服务实例          │
    │  └─────────────────────────────────────┘
    │
    ▼ (通过模板/扩展实现)
MarketData (行情服务接口)
    │
    ├── MarketDataXTP (XTP 实现)
    ├── MarketDataCTP (CTP 实现)
    └── MarketDataSim (模拟实现)
```

### 2.3 核心数据结构

| 数据结构 | 类型 | 说明 |
|----------|------|------|
| `instruments_` | `map<string, Instrument>` | 合约信息映射 |
| `instruments_to_subscribe_` | `vector<InstrumentKey>` | 待订阅的合约列表 |
| `service_` | `MarketData_ptr` | 具体的行情服务实现 |

---

## 三、核心实现

### 3.1 BrokerVendor 基类

```cpp
class BrokerVendor : public yijinjing::practice::apprentice {
public:
  BrokerVendor(location_ptr location, bool low_latency);
  
  void on_exit() override;
  
protected:
  virtual BrokerService_ptr get_service() = 0;
  void on_start() override;
  
private:
  void notify_broker_state();  // 通知经纪状态
};
```

**核心职责**：
- 继承自 apprentice，提供与 Master 的通信能力
- 管理连接状态并通知其他组件
- 定义服务获取接口（由子类实现）

### 3.2 MarketDataVendor 实现

```cpp
MarketDataVendor::MarketDataVendor(locator_ptr locator, const std::string &group, 
                                   const std::string &name, bool low_latency)
    : BrokerVendor(location::make_shared(mode::LIVE, category::MD, group, name, 
                                         std::move(locator)), low_latency) {}

void MarketDataVendor::on_react() {
  BrokerVendor::on_react();
  // 处理 Instrument 事件，更新合约信息
  events_ | is(Instrument::tag) | $$(service_->update_instrument(event->data<Instrument>()));
}

void MarketDataVendor::on_start() {
  BrokerVendor::on_start();
  
  // 订阅自定义订阅请求
  events_ | is(CustomSubscribe::tag) | $$(service_->subscribe_custom(event->data<CustomSubscribe>()));
  
  // 订阅合约 Key 添加请求
  events_ | is(InstrumentKey::tag) | $$(service_->add_instrument_key(event->data<InstrumentKey>()));
  
  // 处理自定义事件
  events_ | is_custom() | $$(service_->on_custom_event(event));
  
  // 启动具体服务
  service_->on_start();

  // 每秒尝试订阅（处理待订阅列表）
  add_time_interval(time_unit::NANOSECONDS_PER_SECOND, 
                    [&](auto e) { service_->try_subscribe(); });
}
```

### 3.3 MarketData 接口定义

```cpp
class MarketData : public BrokerService {
public:
  explicit MarketData(BrokerVendor &vendor) : BrokerService(vendor){};

  // 核心接口 - 订阅合约
  virtual bool subscribe(const std::vector<longfist::types::InstrumentKey> &instrument_keys) = 0;
  
  // 订阅所有合约（可选）
  virtual bool subscribe_all() { return false; };
  
  // 自定义订阅（可选）
  virtual bool subscribe_custom(const longfist::types::CustomSubscribe &custom_sub) { 
    return subscribe_all(); 
  };
  
  // 取消订阅
  virtual bool unsubscribe(const std::vector<longfist::types::InstrumentKey> &instrument_keys) = 0;
  
  // 自定义事件处理
  virtual bool on_custom_event(const event_ptr &event) { return true; }

protected:
  // 合约管理
  bool has_instrument(const std::string &instrument_id) const;
  const longfist::types::Instrument &get_instrument(const std::string &instrument_id) const;
  void update_instrument(longfist::types::Instrument instrument);
  
  // 订阅逻辑
  void try_subscribe();
  void add_instrument_key(const longfist::types::InstrumentKey &key);

  std::unordered_map<std::string, longfist::types::Instrument> instruments_ = {};
  std::vector<longfist::types::InstrumentKey> instruments_to_subscribe_{};
};
```

### 3.4 订阅机制实现

```cpp
void MarketData::update_instrument(Instrument instrument) {
  instruments_.emplace(instrument.instrument_id, instrument);
}

void MarketData::add_instrument_key(const InstrumentKey &key) { 
  instruments_to_subscribe_.push_back(key); 
}

void MarketData::try_subscribe() {
  if (not instruments_to_subscribe_.empty()) {
    subscribe(instruments_to_subscribe_);  // 调用具体实现
  }
  instruments_to_subscribe_.clear();
}
```

**订阅流程**：
1. 收到 `InstrumentKey` 事件 → 添加到待订阅列表
2. 每秒定时器触发 → 调用 `try_subscribe()`
3. 如果有待订阅项 → 调用具体的 `subscribe()` 实现
4. 清空待订阅列表

---

## 四、具体实现示例

### 4.1 XTP 行情实现

```cpp
class MarketDataXTP : public XTP::API::QuoteSpi, public broker::MarketData {
public:
  explicit MarketDataXTP(broker::BrokerVendor &vendor);
  ~MarketDataXTP() override;

  bool subscribe(const std::vector<longfist::types::InstrumentKey> &instrument_keys) override;
  bool subscribe_all() override;
  bool subscribe_custom(const longfist::types::CustomSubscribe &custom_sub) override;
  
  // XTP API 回调
  void OnDisconnected(int reason) override;
  void OnError(XTPRI *error_info) override{};
  void OnSubMarketData(XTPST *ticker, XTPRI *error_info, bool is_last) override;
  void OnDepthMarketData(XTPMD *market_data, int64_t bid1_qty[], int32_t bid1_count, 
                         int32_t max_bid1_count, int64_t ask1_qty[], int32_t ask1_count, 
                         int32_t max_ask1_count) override;
  void OnTickByTick(XTPTBT *tbt_data) override;
  
private:
  XTP::API::QuoteApi *api_{};  // XTP 行情 API
  uint32_t level2_tick_band_uid_;
  yijinjing::journal::writer_ptr public_wirter_{};
};
```

**XTP 回调处理**：

| 回调方法 | 说明 |
|----------|------|
| `OnDisconnected()` | 连接断开时触发 |
| `OnSubMarketData()` | 订阅应答 |
| `OnDepthMarketData()` | 深度行情推送（Level2） |
| `OnTickByTick()` | 逐笔行情推送 |
| `OnQueryAllTickers()` | 查询合约列表应答 |

### 4.2 SIM 模拟行情实现

```python
class MarketDataSim(wc.MarketData):
    def __init__(self, vendor):
        wc.MarketData.__init__(self, vendor)
        self.config_obj = MakerConfig(
            base=200.0, bound=1000, samples=1000, variation=4, randseed=6
        )
        self.orderbooks = {}  # 模拟订单簿
        self.logger = find_logger(self.home)

    def on_start(self):
        # 每 500ms 更新一次订单簿
        self.add_time_interval(500 * 1000 * 1000, lambda e: self.update_orderbooks())
        self.update_broker_state(lf.enums.BrokerState.Ready)

    def init_order_book(self, instrument_id, exchange_id):
        """初始化模拟订单簿"""
        security = instrument_id + "." + exchange_id
        book = mdmaker.OrderBook(security=security)
        for i in range(mdmaker.MAX_DEPTH):
            delta = (i + 1) * 1.0
            # 添加买单
            book.order(mdmaker.Order(
                secid=book.security,
                side=mdmaker.Side.BUY,
                price=(self.config_obj.base - delta),
                qty=1,
            ))
            # 添加卖单
            book.order(mdmaker.Order(
                secid=book.security,
                side=mdmaker.Side.SELL,
                price=(self.config_obj.base + delta),
                qty=1,
            ))
        self.orderbooks[instrument_key] = book

    def update_orderbooks(self):
        """更新订单簿并生成行情"""
        for book in self.orderbooks.values():
            order_generator = book.gen_orders(self.config_obj)
            for orders, mid in order_generator:
                for order in orders:
                    instrument_id, exchange_id = order.secid.split(".")
                    trades = book.order(order)
            # 生成 Quote 并写入公共通道
            quote = self.quote_from_orderbook(book)
            self.get_writer(0).write(0, quote)

    def subscribe(self, instruments):
        """订阅合约"""
        for inst in instruments:
            instrument_key = wc.utils.hash_instrument(inst.instrument_id, inst.exchange_id)
            if instrument_key not in self.orderbooks:
                self.init_order_book(inst.instrument_id, inst.exchange_id)
        return True
```

---

## 五、事件处理架构

### 5.1 事件订阅列表

| 事件类型 | 处理函数 | 说明 |
|----------|----------|------|
| `Instrument` | `MarketData.update_instrument()` | 更新合约信息 |
| `InstrumentKey` | `MarketData.add_instrument_key()` | 添加待订阅合约 |
| `CustomSubscribe` | `MarketData.subscribe_custom()` | 自定义订阅请求 |
| `Custom Event` | `MarketData.on_custom_event()` | 自定义事件 |

### 5.2 定时任务

```cpp
// 每秒检查待订阅列表
add_time_interval(time_unit::NANOSECONDS_PER_SECOND, 
                  [&](auto e) { service_->try_subscribe(); });
```

### 5.3 数据流图

```
InstrumentKey ──> add_instrument_key() ──> instruments_to_subscribe_
                                              │
                                              ▼
                                      try_subscribe() ──> subscribe()
                                              │
                                              ▼
                                    交易所 API 订阅
                                              │
                                              ▼
                                    行情数据回调 ──> 写入公共通道
```

---

## 六、启动方式

### 命令行启动

```bash
# 启动 XTP 行情
kfc run -m live -c md -g xtp -n xtp

# 启动 SIM 模拟行情
kfc run -m live -c md -g sim -n sim

# 完整参数
kfc -X "扩展目录" run -c md -g <source> -n <name>
```

### 启动流程

```
1. kfc CLI 解析命令参数
       │
       ▼
2. 创建 MarketDataVendor 实例
       │
       ▼
3. 加载对应的扩展模块（XTP/SIM/CTP）
       │
       ▼
4. 创建具体的 MarketData 服务实例
       │
       ▼
5. 注册事件处理回调
       │
       ▼
6. 启动事件循环，等待订阅请求
```

---

## 七、关键方法说明

| 方法 | 说明 | 所属类 |
|------|------|--------|
| `on_react()` | 注册事件处理 | MarketDataVendor |
| `on_start()` | 启动初始化 | MarketDataVendor |
| `subscribe()` | 订阅行情（纯虚函数） | MarketData |
| `unsubscribe()` | 取消订阅（纯虚函数） | MarketData |
| `update_instrument()` | 更新合约信息 | MarketData |
| `add_instrument_key()` | 添加待订阅合约 | MarketData |
| `try_subscribe()` | 尝试订阅待订阅列表 | MarketData |
| `OnDepthMarketData()` | XTP 深度行情回调 | MarketDataXTP |
| `update_orderbooks()` | 更新模拟订单簿 | MarketDataSim |

---

## 八、扩展机制

MD 服务通过**扩展模块**实现对不同交易所的支持：

### 扩展类型

| 扩展 | 类型 | 说明 |
|------|------|------|
| **xtp** | C++ | XTP 交易所接口 |
| **ctp** | C++ | CTP 期货接口 |
| **sim** | Python | 模拟行情 |

### 扩展加载流程

```
1. kfc 启动时通过 -X 参数指定扩展目录
       │
       ▼
2. 根据 -g 参数确定使用哪个扩展
       │
       ▼
3. 动态加载对应的 MarketData 实现
       │
       ▼
4. 通过 MarketDataVendor.set_service() 设置服务
```

---

## 九、总结

| 特性 | 说明 |
|------|------|
| **核心职责** | 行情订阅、行情分发、合约管理、连接管理 |
| **架构层次** | 基于 Yijinjing apprentice 框架 |
| **设计模式** | 模板方法模式（基类定义流程，子类实现细节） |
| **扩展机制** | 通过扩展模块支持不同交易所 |
| **订阅机制** | 异步订阅，待订阅列表 + 定时处理 |

MD 服务是 Kungfu Trader 的行情数据入口，通过统一的接口抽象，支持多种交易所的行情接入，并将行情数据广播到公共通道供策略和其他组件使用。

---

**文档生成时间**：2026-05-20
