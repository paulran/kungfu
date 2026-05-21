# Strategy (策略引擎) 程序实现分析

---

## 一、概述

**Strategy**（策略引擎）是 Kungfu Trader 交易系统的核心业务组件之一，负责执行用户编写的交易策略。它提供了完整的策略生命周期管理、事件驱动回调机制以及交易操作接口。

**核心职责**：
1. **策略生命周期管理** - 启动前、启动后、停止前、停止后回调
2. **事件驱动回调** - 行情、订单、成交等事件的处理
3. **交易操作接口** - 下单、撤单、查询等操作
4. **账户管理** - 添加账户、获取账户账本
5. **定时任务** - 单次定时器和周期定时器

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Strategy Engine                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Strategy                         │   │
│  │  (策略接口：回调函数定义)                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                     Context                         │   │
│  │  (运行上下文：下单、撤单、订阅、定时任务)           │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Python Wrapper                     │   │
│  │  (动态加载策略脚本，异步支持)                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │   MD    │    │   TD    │    │ Ledger  │
        │ (行情)   │    │ (交易)   │    │ (账本)   │
        └─────────┘    └─────────┘    └─────────┘
```

### 2.2 类关系图

```
Strategy (C++ 接口)
    │
    │  ┌─────────────────────────────┐
    │  │  定义回调接口               │
    │  │  on_quote, on_bar, ...     │
    │  └─────────────────────────────┘
    │
    ▼ (继承/实现)
Strategy (Python Wrapper)
    │
    │  ┌─────────────────────────────┐
    │  │  动态加载策略脚本           │
    │  │  支持同步/异步回调          │
    │  └─────────────────────────────┘
    │
    ▼ (持有)
Context
    │
    │  ┌─────────────────────────────┐
    │  │  提供操作接口               │
    │  │  insert_order, subscribe,  │
    │  │  add_timer, ...            │
    │  └─────────────────────────────┘
```

### 2.3 核心数据结构

| 数据结构 | 类型 | 说明 |
|----------|------|------|
| `books_` | `map<uint32_t, Book_ptr>` | 账户账本映射 |
| `book_` | `Book_ptr` | 当前策略账本 |
| `basketorder_engine_` | `BasketOrderEngine_ptr` | 篮子订单引擎 |
| `book_held_` | `bool` | 是否持有账本 |
| `positions_mirrored_` | `bool` | 是否镜像持仓 |
| `bypass_accounting_` | `bool` | 是否跳过核算 |

---

## 三、核心实现

### 3.1 Strategy C++ 接口

```cpp
class Strategy {
public:
  // 生命周期回调
  virtual void pre_start(Context_ptr &context){};
  virtual void post_start(Context_ptr &context){};
  virtual void pre_stop(Context_ptr &context){};
  virtual void post_stop(Context_ptr &context){};
  
  // 交易日回调
  virtual void on_trading_day(Context_ptr &context, int64_t daytime){};
  
  // 行情数据回调
  virtual void on_quote(Context_ptr &context, const Quote &quote, const location_ptr &location){};
  virtual void on_tree(Context_ptr &context, const Tree &tree, const location_ptr &location){};
  virtual void on_bar(Context_ptr &context, const Bar &bar, const location_ptr &location){};
  virtual void on_entrust(Context_ptr &context, const Entrust &entrust, const location_ptr &location){};
  virtual void on_transaction(Context_ptr &context, const Transaction &transaction, const location_ptr &location){};
  
  // 订单/成交回调
  virtual void on_order(Context_ptr &context, const Order &order, const location_ptr &location){};
  virtual void on_trade(Context_ptr &context, const Trade &trade, const location_ptr &location){};
  
  // 历史数据回调
  virtual void on_history_order(Context_ptr &context, const HistoryOrder &history_order, const location_ptr &location){};
  virtual void on_history_trade(Context_ptr &context, const HistoryTrade &history_trade, const location_ptr &location){};
  
  // 同步重置回调
  virtual void on_position_sync_reset(Context_ptr &context, const Book &old_book, const Book &new_book){};
  virtual void on_asset_sync_reset(Context_ptr &context, const Asset &old_asset, const Asset &new_asset){};
  
  // 状态变化回调
  virtual void on_broker_state_change(Context_ptr &context, const BrokerStateUpdate &broker_state_update, const location_ptr &location){};
  
  // 自定义数据回调
  virtual void on_custom_data(Context_ptr &context, uint32_t msg_type, const std::vector<uint8_t> &data, uint32_t length, const location_ptr &location){};
};
```

### 3.2 Context 接口

```cpp
class Context {
public:
  // 时间获取
  virtual int64_t now() const = 0;
  
  // 定时任务
  virtual void add_timer(int64_t nanotime, const std::function<void(event_ptr)> &callback) = 0;
  virtual void add_time_interval(int64_t duration, const std::function<void(event_ptr)> &callback) = 0;
  
  // 账户管理
  virtual void add_account(const std::string &source, const std::string &account) = 0;
  
  // 行情订阅
  virtual void subscribe(const std::string &source, const std::vector<std::string> &instrument_ids, const std::string &exchange_ids) = 0;
  virtual void subscribe_all(const std::string &source, uint8_t market_type = 0, uint64_t instrument_type = 0, uint64_t data_type = 0) = 0;
  
  // 下单操作
  virtual uint64_t insert_order(const std::string &instrument_id, const std::string &exchange_id,
                                const std::string &source, const std::string &account, 
                                double limit_price, int64_t volume, PriceType type, Side side,
                                Offset offset, HedgeFlag hedge_flag = HedgeFlag::Speculation,
                                bool is_swap = false, uint64_t block_id = 0, uint64_t parent_id = 0) = 0;
  
  virtual uint64_t insert_basket_order(uint64_t basket_id, const std::string &source, const std::string &account,
                                       Side side, PriceType price_type, PriceLevel price_level, 
                                       double price_offset = 0, int64_t volume = 0) = 0;
  
  virtual std::vector<uint64_t> insert_batch_orders(const std::string &source, const std::string &account,
                                                    const std::vector<std::string> &instrument_ids, 
                                                    const std::vector<std::string> &exchange_ids,
                                                    std::vector<double> limit_prices, std::vector<int64_t> volumes,
                                                    std::vector<PriceType> types, std::vector<Side> sides,
                                                    std::vector<Offset> offsets, std::vector<HedgeFlag> hedge_flags,
                                                    std::vector<bool> is_swaps) = 0;
  
  // 撤单操作
  virtual uint64_t cancel_order(uint64_t order_id) = 0;
  
  // 查询操作
  virtual void req_history_order(const std::string &source, const std::string &account, uint32_t query_num = 0) = 0;
  virtual void req_history_trade(const std::string &source, const std::string &account, uint32_t query_num = 0) = 0;
  
  // 账本状态
  bool is_book_held() const;
  bool is_positions_mirrored() const;
  void hold_book();
  void hold_positions();
  void bypass_accounting();
};
```

### 3.3 Python Strategy 实现

```python
class Strategy(wc.Strategy):
    def __init__(self, ctx):
        wc.Strategy.__init__(self)
        self.ctx = ctx
        self.ctx.books = {}
        self.__init_strategy(ctx.path)  # 动态加载策略脚本
    
    def __init_strategy(self, path):
        # 加载策略模块
        strategy_dir = os.path.dirname(path)
        sys.path.append(os.path.relpath(strategy_dir))
        self._module = importlib.import_module(os.path.splitext(os.path.basename(path))[0])
        
        # 动态获取回调函数，默认为空函数
        self._pre_start = getattr(self._module, "pre_start", lambda ctx: None)
        self._on_quote = getattr(self._module, "on_quote", lambda ctx, quote, location: None)
        self._on_bar = getattr(self._module, "on_bar", lambda ctx, bar, location: None)
        self._on_order = getattr(self._module, "on_order", lambda ctx, order, location: None)
        self._on_trade = getattr(self._module, "on_trade", lambda ctx, trade, location: None)
        # ... 其他回调函数
    
    def __call_proxy(self, func, *args):
        # 支持同步和异步回调
        if inspect.iscoroutinefunction(func):
            async def wrap():
                await func(*args)
                self.ctx.loop._current = None
            asyncio.ensure_future(wrap())
        else:
            func(*args)
    
    def pre_start(self, wc_context):
        # 初始化上下文接口
        self.ctx.wc_context = wc_context
        self.ctx.now = wc_context.now
        self.ctx.add_timer = self.__add_timer
        self.ctx.add_time_interval = self.__add_time_interval
        self.ctx.subscribe = wc_context.subscribe
        self.ctx.insert_order = wc_context.insert_order
        self.ctx.cancel_order = wc_context.cancel_order
        # ... 其他接口
        
        # 初始化账本
        self.__init_book()
        
        # 调用策略的 pre_start
        self.__call_proxy(self._pre_start, self.ctx)
    
    def on_quote(self, wc_context, quote, location):
        self.__call_proxy(self._on_quote, self.ctx, quote, location)
    
    def on_bar(self, wc_context, bar, location):
        self.__call_proxy(self._on_bar, self.ctx, bar, location)
```

### 3.4 异步下单支持

```python
class AsyncOrderAction:
    def __init__(self, ctx, order_id, status_set):
        self.ctx = ctx
        self.order_id = order_id
        self.status_set = status_set  # 等待的订单状态集合
        self.future = ctx.loop.create_future()
    
    def __await__(self):
        return AsyncOrderActionIter(self.ctx, self)

class AsyncOrderActionIter:
    def __init__(self, ctx, action):
        self.ctx = ctx
        self.action = action
        self.book = ctx.book
    
    def __next__(self):
        # 检查订单是否达到目标状态
        if self.action.order_id in self.book.orders:
            order = self.book.orders[self.action.order_id]
            if order.status in self.action.status_set:
                raise StopIteration  # 完成等待
        return next(iter(self.action.future))  # 继续等待

async def __async_insert_order(self, side, instrument_id, exchange_id, 
                               source_id, account_id, price, volume, 
                               price_type=PriceType.Any, status_set=None):
    # 默认等待状态
    if status_set is None:
        status_set = [OrderStatus.Filled, OrderStatus.PartialFilledActive, 
                      OrderStatus.Cancelled, OrderStatus.Error]
    
    # 下单
    order_id = self.ctx.insert_order(instrument_id, exchange_id, source_id, 
                                     account_id, price, volume, price_type, side)
    
    # 等待订单状态变化
    await AsyncOrderAction(self.ctx, order_id, status_set)
    
    # 返回订单信息
    return self.ctx.book.orders[order_id]

# 提供便捷的 buy/sell 方法
self.ctx.buy = functools.partial(self.__async_insert_order, Side.Buy)
self.ctx.sell = functools.partial(self.__async_insert_order, Side.Sell)
```

---

## 四、策略生命周期

### 4.1 生命周期流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                      策略生命周期                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│   │   pre_start  │───>│  post_start  │───>│   运行中      │     │
│   │   (启动前)    │    │   (启动后)    │    │  (事件循环)   │     │
│   └──────────────┘    └──────────────┘    └───────┬──────┘     │
│                                                     │          │
│                                                     │          │
│   ┌──────────────┐    ┌──────────────┐              │          │
│   │   pre_stop   │<───│   post_stop  │<─────────────┘          │
│   │   (停止前)    │    │   (停止后)    │                       │
│   └──────────────┘    └──────────────┘                       │
│                                                                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 生命周期回调说明

| 回调函数 | 调用时机 | 用途 |
|----------|----------|------|
| `pre_start` | 策略启动前 | 初始化变量、订阅行情、添加账户 |
| `post_start` | 策略启动后 | 启动定时任务、发送初始请求 |
| `pre_stop` | 策略停止前 | 清理资源、保存状态 |
| `post_stop` | 策略停止后 | 最终清理 |

---

## 五、事件回调体系

### 5.1 回调类型分类

| 类别 | 回调函数 | 说明 |
|------|----------|------|
| **行情数据** | `on_quote` | 行情报价 |
| | `on_tree` | Level2 行情 |
| | `on_bar` | K线数据 |
| | `on_entrust` | 逐笔委托 |
| | `on_transaction` | 逐笔成交 |
| **订单管理** | `on_order` | 订单状态更新 |
| | `on_trade` | 成交回报 |
| | `on_order_action_error` | 撤单错误 |
| **历史数据** | `on_history_order` | 历史订单 |
| | `on_history_trade` | 历史成交 |
| **同步重置** | `on_position_sync_reset` | 持仓同步重置 |
| | `on_asset_sync_reset` | 资产同步重置 |
| **状态变化** | `on_trading_day` | 交易日切换 |
| | `on_broker_state_change` | 经纪状态变化 |
| | `on_deregister` | 进程注销 |

### 5.2 事件处理流程

```
事件到达 ──> Strategy.on_xxx() ──> __call_proxy()
                                          │
                                    ┌─────┴─────┐
                                    ▼           ▼
                               同步函数      异步协程
                                    │           │
                                    ▼           ▼
                              直接执行    asyncio.ensure_future()
```

---

## 六、启动方式

### 命令行启动

```bash
# 启动 Python 策略
kfc run -m live -c strategy -g default -n my_strategy /path/to/strategy.py

# 启动编译后的 C++ 策略
kfc run -m live -c strategy -g default -n my_strategy /path/to/strategy.so

# 带参数启动
kfc run -m live -c strategy -g default -n my_strategy -a "param1=value1;param2=value2" /path/to/strategy.py
```

### 启动流程

```
1. kfc CLI 解析命令参数
       │
       ▼
2. 创建 Strategy Runner
       │
       ▼
3. 动态加载策略脚本/模块
       │
       ▼
4. 创建 Strategy 实例
       │
       ▼
5. 调用 pre_start() 初始化
       │
       ▼
6. 调用 post_start() 完成启动
       │
       ▼
7. 进入事件循环，处理回调
```

---

## 七、策略开发示例

### 7.1 简单策略示例

```python
# strategy.py
def pre_start(ctx):
    ctx.subscribe('sim', ['000001.SZ', '600000.SH'], '')
    ctx.add_account('sim', 'sim001')
    ctx.add_time_interval(1000000000, on_timer)

def on_quote(ctx, quote, location):
    ctx.log.info(f"收到行情: {quote.instrument_id} {quote.last_price}")

def on_bar(ctx, bar, location):
    ctx.log.info(f"收到K线: {bar.instrument_id} {bar.open} {bar.high} {bar.low} {bar.close}")
    
    # 简单策略：收盘价高于开盘价则买入
    if bar.close > bar.open:
        ctx.buy('000001.SZ', 'SZSE', 'sim', 'sim001', bar.close, 100)

def on_order(ctx, order, location):
    ctx.log.info(f"订单状态更新: {order.order_id} {order.status}")

def on_trade(ctx, trade, location):
    ctx.log.info(f"成交: {trade.instrument_id} {trade.price} {trade.volume}")

def on_timer(ctx, event):
    ctx.log.info(f"定时任务: {ctx.now()}")
```

### 7.2 异步策略示例

```python
async def on_bar(ctx, bar, location):
    # 异步下单并等待成交
    order = await ctx.buy('000001.SZ', 'SZSE', 'sim', 'sim001', bar.close, 100)
    ctx.log.info(f"订单完成: {order.order_id} {order.status}")
```

---

## 八、关键功能说明

### 8.1 账本管理

| 方法 | 说明 |
|------|------|
| `hold_book()` | 持有账本，重启后从 ledger 恢复持仓 |
| `hold_positions()` | 持有持仓，不镜像账户持仓 |
| `bypass_accounting()` | 跳过账本核算 |
| `is_book_held()` | 检查是否持有账本 |
| `is_positions_mirrored()` | 检查是否镜像持仓 |

### 8.2 定时任务

| 方法 | 说明 |
|------|------|
| `add_timer(nanotime, callback)` | 添加单次定时器 |
| `add_time_interval(duration, callback)` | 添加周期定时器 |

### 8.3 交易操作

| 方法 | 说明 |
|------|------|
| `insert_order()` | 插入单个订单 |
| `insert_batch_orders()` | 插入批量订单 |
| `insert_basket_order()` | 插入篮子订单 |
| `cancel_order(order_id)` | 撤销订单 |
| `buy()` | 便捷买入方法（异步） |
| `sell()` | 便捷卖出方法（异步） |

---

## 九、总结

| 特性 | 说明 |
|------|------|
| **核心职责** | 策略生命周期管理、事件回调、交易操作 |
| **架构层次** | C++ 接口 + Python 包装层 |
| **开发方式** | Python 脚本动态加载 |
| **异步支持** | 支持 async/await 异步回调 |
| **扩展性** | 支持 C++ 和 Python 两种策略开发 |

Strategy 是 Kungfu Trader 的策略执行引擎，通过事件驱动的方式执行用户编写的交易策略，提供完整的生命周期管理和交易操作接口。

---

**文档生成时间**：2026-05-20
