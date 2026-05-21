# Kungfu Trader 启动顺序分析

---

## 一、概述

Kungfu Trader 是一个分布式交易系统，由多个独立进程组成。这些进程之间存在明确的依赖关系，因此存在严格的**启动顺序要求**。

**核心原则**：先启动系统核心服务，再启动业务服务。

---

## 二、启动顺序层次图

```
┌─────────────────────────────────────────────────────────────────┐
│                    启动顺序层次图                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                │
│  第一层：核心系统服务（必须按顺序启动）                           │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                 │
│  │  Master  │───>│  Ledger  │───>│  Cached  │                 │
│  │  (核心协调) │    │  (账本)    │    │  (缓存)    │                 │
│  └──────────┘    └──────────┘    └──────────┘                 │
│         │                │                │                    │
│         ▼                ▼                ▼                    │
│  第二层：业务服务（可并行启动）                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐              │
│  │    MD    │    │    TD    │    │  Strategy   │              │
│  │ (行情)    │    │ (交易)    │    │  (策略引擎)   │              │
│  └──────────┘    └──────────┘    └──────────────┘              │
│                                                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、启动顺序详解

### 3.1 第一层：核心系统服务

| 顺序 | 服务 | 启动命令 | 作用 | 依赖 |
|------|------|----------|------|------|
| 1 | **Master** | `kfc run -c system -g master -n master` | 系统核心协调器 | 无 |
| 2 | **Ledger** | `kfc run -c system -g service -n ledger` | 账本服务 | Master |
| 3 | **Cached** | `kfc run -c system -g service -n cached` | 缓存服务 | Master, Ledger |

**服务间依赖关系**：

```
Master ──控制──> Ledger
Master ──控制──> Cached
Ledger ──数据──> Cached (缓存订单/成交数据)
```

### 3.2 第二层：业务服务

| 服务 | 启动命令 | 作用 | 依赖 |
|------|----------|------|------|
| **MD** | `kfc run -c md -g <source> -n <name>` | 行情数据服务 | Master, Cached |
| **TD** | `kfc run -c td -g <source> -n <account>` | 交易服务 | Master, Ledger, Cached |
| **Strategy** | `kfc run -c strategy -g <group> -n <name> <path>` | 策略引擎 | Master, MD, TD |

**业务服务依赖关系**：

```
MD ──行情──> Strategy
TD ──订单/成交──> Strategy
Strategy ──下单──> TD
MD/TD ──注册──> Master
Strategy ──注册──> Master
```

---

## 四、启动顺序的技术原因

### 4.1 Master 必须最先启动

```typescript
// processUtils.ts
export const startMaster = async (force = false): Promise<void> => {
  const processName = 'master';
  await preStartProcess(processName, force);
  if (force) await killKfc();  // 强制启动时先停止所有服务
  const args = buildArgs('run -c system -g master -n master');
  await startProcess({
    name: processName,
    args,
    force,
    env: { KF_NO_EXT: 'on' },
  });
};
```

**原因**：
1. Master 是系统的**进程注册中心**，所有其他进程都需要向 Master 注册
2. Master 管理进程间的**通信通道**
3. Master 负责**心跳检测**和**故障恢复**

### 4.2 Ledger 必须在 Master 之后启动

```typescript
// processUtils.ts
export const startLedger = async (force = false): Promise<void> => {
  const processName = 'ledger';
  await preStartProcess(processName, force);
  const args = buildArgs('run -c system -g service -n ledger');
  await startProcess({ name: processName, args, force });
};
```

**原因**：
1. Ledger 需要向 Master **注册**
2. Ledger 需要从 Master 获取**配置信息**
3. Ledger 的**状态变更**需要通知 Master

### 4.3 Cached 必须在 Master 和 Ledger 之后启动

```typescript
// processUtils.ts
export const startCacheD = async (force = false): Promise<void> => {
  const processName = 'cached';
  await preStartProcess(processName, force);
  const args = buildArgs('run -c system -g service -n cached');
  await startProcess({ name: processName, args, force });
};
```

**原因**：
1. Cached 需要向 Master **注册**
2. Cached 需要订阅 Ledger 的**状态数据**（订单、成交等）
3. Cached 需要为新进程提供**数据恢复**服务

### 4.4 业务服务的启动时机

**MD 启动条件**：
- Master 运行正常
- Cached 运行正常（用于缓存 Instrument 数据）

**TD 启动条件**：
- Master 运行正常
- Ledger 运行正常（用于更新资产/持仓）
- Cached 运行正常（用于恢复订单状态）

**Strategy 启动条件**：
- Master 运行正常
- 依赖的 MD 服务运行正常（订阅行情）
- 依赖的 TD 服务运行正常（提交订单）

---

## 五、核心服务启动检查

### 5.1 检查所有核心服务是否运行

```typescript
// processUtils.ts
export async function isAllMainProcessRunning() {
  const { processStatus } = await listProcessStatus();
  
  return (
    getIfProcessRunning(processStatus, 'master') &&
    getIfProcessRunning(processStatus, 'ledger') &&
    getIfProcessRunning(processStatus, 'cached')
  );
}
```

**返回值**：
- `true`：三个核心服务都在运行
- `false`：至少有一个核心服务未运行

### 5.2 业务服务启动前的检查

```typescript
// busiUtils.ts
switch (kfLocation.category) {
  case 'system':
    if (kfLocation.name === 'master') {
      return startMaster(isForce);
    } else if (kfLocation.name === 'ledger') {
      return startLedger(isForce);
    } else if (kfLocation.name === 'cached') {
      return startCacheD(isForce);
    }
    break;
  case 'td':
    return startTd(accountId, kfConfig);
  case 'md':
    return startMd(sourceId, kfConfig);
  case 'strategy':
    return startStrategy(strategyId, strategyPath, kfConfig);
}
```

---

## 六、推荐的启动顺序

### 6.1 手动启动顺序

```bash
# 第一步：启动 Master
kfc run -c system -g master -n master

# 第二步：启动 Ledger
kfc run -c system -g service -n ledger

# 第三步：启动 Cached
kfc run -c system -g service -n cached

# 第四步：启动业务服务（可并行）
kfc run -c md -g sim -n sim &
kfc run -c td -g sim -n sim001 &

# 第五步：启动策略
kfc run -c strategy -g default -n my_strategy /path/to/strategy.py
```

### 6.2 检查核心服务状态

```bash
# 检查所有核心服务是否运行
kfc service status

# 或使用 API 检查
# isAllMainProcessRunning() 返回 true 表示就绪
```

---

## 七、启动顺序的架构意义

### 7.1 进程注册流程

```
新进程启动 ──> 向 Master 注册 ──> Master 创建通信通道 ──> 订阅数据 ──> 开始工作
```

### 7.2 数据流向

```
交易所 ──> MD ──> 公共通道 ──> Strategy
                                │
                                ▼
                            订单 ──> TD ──> 交易所
                                │
                                ▼
                           Ledger (更新账本)
                                │
                                ▼
                           Cached (缓存数据)
```

### 7.3 容错机制

| 服务 | 故障影响 | 恢复方式 |
|------|----------|----------|
| Master | 系统瘫痪 | 重启 Master，所有进程重新注册 |
| Ledger | 账本不同步 | 重启 Ledger，从 Cached 恢复数据 |
| Cached | 新进程无法恢复数据 | 重启 Cached，从日志重建缓存 |
| MD | 行情中断 | 重启 MD，重新订阅 |
| TD | 交易中断 | 重启 TD，恢复订单状态 |
| Strategy | 策略暂停 | 重启 Strategy，从 Cached 恢复状态 |

---

## 八、总结

### 启动顺序总结

| 阶段 | 服务 | 说明 |
|------|------|------|
| **阶段一** | Master | 必须最先启动，系统核心 |
| **阶段二** | Ledger | 必须在 Master 之后启动 |
| **阶段三** | Cached | 必须在 Master 和 Ledger 之后启动 |
| **阶段四** | MD | 核心服务就绪后启动 |
| **阶段五** | TD | 核心服务就绪后启动 |
| **阶段六** | Strategy | MD 和 TD 就绪后启动 |

### 关键依赖关系

```
Master (核心)
    │
    ├─> Ledger (账本)
    ├─> Cached (缓存)
    │
    ├─> MD (行情) ──> Strategy (策略)
    │
    └─> TD (交易) ──> Strategy (策略)
```

**核心原则**：核心系统服务必须按顺序启动，业务服务可以并行启动，但必须等待核心服务就绪。

---

**文档生成时间**：2026-05-20
