# Kungfu Trader 架构分析文档

---

## 一、整体架构概览

Kungfu Trader 是一个分布式交易系统，采用 **Electron + PM2 + C++ 核心** 的架构模式：

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron 桌面应用                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   UI 界面    │  │   主进程     │  │      渲染进程        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                        PM2 进程管理                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Master    │  │   Ledger    │  │      Cached         │  │
│  │   (核心)     │  │  (账本)      │  │    (缓存)           │  │
│  └─────────────┘  └─────────────┘  └─────────────┘        │  │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│     MD      │    │     TD      │    │  Strategy   │
│ (行情数据)   │    │  (交易)      │    │  (策略引擎)  │
└─────────────┘    └─────────────┘    └─────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  交易所接口  │    │  券商接口    │    │  策略代码    │
│ (CTP/XTP/SIM)│   │ (CTP/XTP)   │    │ (C++/Python) │
└─────────────┘    └─────────────┘    └─────────────┘
```

---

## 二、核心系统服务

### 1. 基础系统服务（必须启动）

| 服务名称 | 进程名 | 启动函数 | 作用说明 |
|---------|--------|---------|---------|
| **Master** | `master` | `startMaster()` | 系统核心进程，负责协调其他服务 |
| **Ledger** | `ledger` | `startLedger()` | 账本服务，处理交易数据持久化 |
| **Cached** | `cached` | `startCacheD()` | 缓存服务，提供高速数据访问 |

#### 核心服务启动代码分析

**Master 服务启动**：

```typescript
export const startMaster = async (force = false): Promise<void> => {
  const processName = 'master';
  try {
    await preStartProcess(processName, force);
    if (force) await killKfc();
    const args = buildArgs('run -c system -g master -n master');
    await startProcess({
      name: processName,
      args,
      force,
      env: {
        KF_NO_EXT: 'on',  // 禁用扩展加载
      },
    });
  } catch (err: unknown) {
    kfLogger.error((<Error>err).message);
  }
};
```

**Ledger 服务启动**：

```typescript
export const startLedger = async (force = false): Promise<void> => {
  const processName = 'ledger';
  try {
    await preStartProcess(processName, force);
    const args = buildArgs('run -c system -g service -n ledger');
    await startProcess({
      name: processName,
      args,
      force,
    });
  } catch (err: unknown) {
    kfLogger.error((<Error>err).message);
  }
};
```

**Cached 服务启动**：

```typescript
export const startCacheD = async (force = false): Promise<void> => {
  const processName = 'cached';
  try {
    await preStartProcess(processName, force);
    const args = buildArgs('run -c system -g service -n cached');
    await startProcess({
      name: processName,
      args,
      force,
    });
  } catch (err: unknown) {
    kfLogger.error((<Error>err).message);
  }
};
```

**服务状态检查**：

```typescript
export async function isAllMainProcessRunning() {
  const { processStatus } = await listProcessStatus();
  return (
    getIfProcessRunning(processStatus, 'master') &&
    getIfProcessRunning(processStatus, 'ledger') &&
    getIfProcessRunning(processStatus, 'cached')
  );
}
```

### 2. 可选系统任务

| 任务名称 | 进程名 | 启动函数 | 作用说明 |
|---------|--------|---------|---------|
| **Archive** | `archive` | `startArchiveMakeTask()` | 归档任务，定期清理历史数据 |

```typescript
export function startArchiveMakeTask(
  cb?: (processStatus: Pm2ProcessStatusTypes) => void,
) {
  const globalSetting = getKfGlobalSettingsValue();
  const bypassArchive = globalSetting?.system?.bypassArchive ?? false;
  return startProcessGetStatusUntilStop(
    {
      name: 'archive',
      args: buildArgs(`journal archive ${bypassArchive ? '-m delete' : ''}`),
    },
    cb,
  );
}
```

---

## 三、业务服务

### 1. 行情数据服务（MD）

**启动代码**：

```typescript
export const startMd = async (
  sourceId: string,
  kfConfig: KungfuApi.DerivedKfLocation,
): Promise<Proc | void> => {
  const extDirs = await flattenExtensionModuleDirs(EXTENSION_DIRS);
  const args = buildArgs(
    `-X "${extDirs
      .map((dir) => dealSpaceInPath(path.dirname(dir)))
      .join(path.delimiter)}" run -c md -g "${sourceId}" -n "${sourceId}"`,
  );
  const cwd = dealSpaceInPath(
    path.join(KF_RUNTIME_DIR, 'md', sourceId, sourceId),
  );
  await fse.ensureDir(cwd);
  const options =
    await globalThis.HookKeeper.getHooks().resolveStartOptions.trigger(
      kfConfig,
      {
        name: `md_${sourceId}`,
        cwd,
        script: `${dealSpaceInPath(path.join(KFC_DIR, kfcName))}`,
        args,
        max_restarts: 3,
        autorestart: true,
        force: true,
      },
    );
  return startProcess(options).catch((err) => {
    kfLogger.error(err);
  });
};
```

**关键参数**：
- `-c md`：指定为行情服务
- `-g "${sourceId}"`：数据源组名（如 ctp、xtp、sim）
- `-n "${sourceId}"`：进程名
- `-X`：扩展目录路径

### 2. 交易服务（TD）

**启动代码**：

```typescript
export const startTd = async (
  accountId: string,
  kfConfig: KungfuApi.DerivedKfLocation,
): Promise<Proc | void> => {
  const globalSetting = getKfGlobalSettingsValue();
  const autorestart = globalSetting?.system?.autoRestartTd ?? true;
  const extDirs = await flattenExtensionModuleDirs(EXTENSION_DIRS);
  const { source, id } = (accountId || '').parseSourceAccountId();
  const args = buildArgs(
    `-X "${extDirs
      .map((dir) => dealSpaceInPath(path.dirname(dir)))
      .join(path.delimiter)}" run -c td -g "${source}" -n "${id}"`,
  );
  const cwd = dealSpaceInPath(path.join(KF_RUNTIME_DIR, 'td', source, id));
  await fse.ensureDir(cwd);
  const fullProcessId = `td_${accountId}`;
  const options =
    await globalThis.HookKeeper.getHooks().resolveStartOptions.trigger(
      kfConfig,
      {
        name: fullProcessId,
        cwd,
        script: `${dealSpaceInPath(path.join(KFC_DIR, kfcName))}`,
        args,
        ...(autorestart
          ? {
              max_restarts: 4, // pm2 在进程退出时对重启次数进行 +1
              autorestart: true,
            }
          : {}),
        force: true,
      },
    );
  return startProcess(options).catch((err) => {
    kfLogger.error(err);
  });
};
```

**关键参数**：
- `-c td`：指定为交易服务
- `-g "${source}"`：券商/交易所类型
- `-n "${id}"`：账户ID

### 3. 策略引擎

**启动代码**：

```typescript
export const startStrategy = async (
  strategyId: string,
  strategyPath: string,
): Promise<Proc | void> => {
  strategyPath = dealSpaceInPath(strategyPath);
  const globalSetting = getKfGlobalSettingsValue();
  const ifLocalPython = globalSetting?.strategy?.python ?? false;
  const pythonPath = globalSetting?.strategy?.pythonPath ?? '';
  const strategyIdResolved = `strategy_${strategyId}`;

  // 清理已存在的策略进程
  try {
    const { processStatus } = await listProcessStatus();
    if (!getIfProcessDeleted(processStatus, strategyIdResolved)) {
      await deleteProcess(strategyIdResolved);
    }
  } catch (err) {
    kfLogger.warn(err);
  }

  // 根据配置选择启动方式
  if (ifLocalPython && strategyPath.endsWith('.py')) {
    return startStrategyByLocalPython(strategyId, strategyPath, pythonPath);
  } else {
    const args = buildArgs(
      `run -c strategy -g default -n '${strategyId}' '${strategyPath}'`,
    );
    return startProcess({
      name: strategyIdResolved,
      args,
      force: true,
    }).catch((err) => {
      kfLogger.error(err);
    });
  }
};
```

**本地 Python 策略启动**：

```typescript
export const startStrategyByLocalPython = async (
  name: string,
  strategyPath: string,
  pythonPath: string,
): Promise<Proc | void> => {
  const baseArgs = [
    'run',
    '-c',
    'strategy',
    '-g',
    'default',
    '-n',
    name,
    `'${strategyPath}'`,
  ].join(' ');
  const baseArgsResolved = buildArgs(baseArgs);
  const args = ['-m', 'kungfu', baseArgsResolved].join(' ');

  if (!pythonPath.trim()) {
    return Promise.reject(new Error('No local python path!'));
  }

  const fullPythonPathList = pythonPath.replace(/\\/g, '/').split('/');
  const pythonFolder = fullPythonPathList
    .slice(0, fullPythonPathList.length - 1)
    .join('/');
  const pythonFile = fullPythonPathList
    .slice(fullPythonPathList.length - 1)
    .join('/');

  return startProcess({
    name: `strategy_${name}`,
    args,
    cwd: `${dealSpaceInPath(pythonFolder)}`,
    script: `${pythonFile}`,
    force: true,
  }).catch((err) => {
    kfLogger.error(err);
  });
};
```

**支持的策略类型**：
- C++ 策略（编译为 `.so` 或 `.pyd`）
- Python 策略（`.py` 文件）

---

## 四、扩展服务

### 扩展守护进程

```typescript
export const startExtDaemon = (name: string, cwd: string, script: string) => {
  return startProcess({
    name,
    args: '',
    cwd,
    script,
    interpreter: path.join(KFC_DIR, kfcName),
    force: true,
    watch: process.env.NODE_ENV === 'production' ? false : true,
    env: {
      KFC_AS_VARIANT: 'node',
    },
    kill_timeout: 500,
  }).catch((err) => {
    kfLogger.error(err);
  });
};
```

**内置扩展**：
- **sim**：模拟交易扩展（Python）
- **xtp**：XTP 交易所接口（C++）

---

## 五、进程管理核心机制

### 1. PM2 进程启动配置

```typescript
export const startProcess = async (
  options: Pm2StartOptions,
): Promise<Proc | void> => {
  const extDirs = await flattenExtensionModuleDirs(EXTENSION_DIRS);
  const optionsResolved: Pm2StartOptions = {
    name: options.name,
    args: options.args,
    cwd: options.cwd || path.join(KFC_DIR),
    script: options.script || kfcName,
    interpreter: options.interpreter || 'none',
    output: buildProcessLogPath(options.name),
    error: buildProcessLogPath(options.name),
    merge_logs: true,
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    autorestart: options.autorestart || false,
    max_restarts: options.max_restarts || 1,
    min_uptime: 3600000, // 1小时内最大重启次数限制
    restart_delay: 1000,
    watch: options.watch || false,
    force: options.force || false,
    exec_mode: 'fork',
    kill_timeout: options.kill_timeout || 16000,
    env: {
      RELOAD_AFTER_CRASHED: process.env.RELOAD_AFTER_CRASHED || 'false',
      EXTENSION_DIRS: extDirs
        .map((dir) => dealSpaceInPath(path.dirname(dir)))
        .join(path.delimiter),
      KFC_DIR: process.env.KFC_DIR || '',
      CLI_DIR: process.env.CLI_DIR || '',
      KF_HOME: dealSpaceInPath(KF_HOME),
      KF_RUNTIME_DIR: dealSpaceInPath(KF_RUNTIME_DIR),
      LANG: `${locale}.UTF-8`,
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf8',
      KFC_AS_VARIANT: '',
      ...options.env,
      // 覆盖父进程环境变量
      APP_TYPE: '',
      APP_ID: '',
      UI_EXT_TYPE: '',
      BY_PASS_ACCOUNTING: '',
      BY_PASS_TRADINGDATA: '',
      BY_PASS_RESTORE: '',
    },
  };
  return pm2Start(optionsResolved).catch((err) => {
    kfLogger.error(err);
  });
};
```

### 2. PM2 核心操作封装

```typescript
// PM2 连接
export const pm2Connect = (): Promise<void> => {
  return new Promise((resolve, reject) => {
    pm2.connect((err: Error) => {
      if (err) {
        kfLogger.error(err);
        reject(err);
        return;
      }
      resolve();
    });
  });
};

// PM2 进程列表
export const pm2List = (): Promise<ProcessDescription[]> => {
  return new Promise((resolve, reject) => {
    pm2.list((err: Error, pList: ProcessDescription[]) => {
      if (err) {
        kfLogger.error(err);
        reject(err);
        return;
      }
      resolve(pList);
    });
  });
};

// PM2 进程启动
const pm2Start = (options: Pm2StartOptions): Promise<Proc> => {
  return new Promise((resolve, reject) => {
    pm2Connect()
      .then(() => {
        pm2.start(options, (err: Error, proc: Proc) => {
          if (err) {
            kfLogger.error(err);
            reject(err);
            return;
          }
          resolve(proc);
        });
      })
      .catch((err: Error) => {
        kfLogger.error(err);
        reject(err);
      });
  });
};
```

### 3. 优雅停止机制

```typescript
export const graceStopProcess = async (
  watcher: KungfuApi.Watcher | null,
  kfLocation: KungfuApi.KfConfig | KungfuApi.KfLocation,
  processStatusData?: Pm2ProcessStatusData,
): Promise<void> => {
  if (!processStatusData) {
    const { processStatus } = await listProcessStatus();
    processStatusData = processStatus;
  }

  const processId = getProcessIdByKfLocation(kfLocation);

  if (!watcher) {
    return Promise.reject(new Error('Watcher is NULL'));
  }

  if (getIfProcessRunning(processStatusData, processId)) {
    // 检查进程是否就绪
    if (
      watcher &&
      !watcher.isReadyToInteract(kfLocation) &&
      isTdMdStrategy(kfLocation.category)
    ) {
      return Promise.reject(new Error(t('未就绪', { processId })));
    }

    // 先请求停止，再强制停止
    return requestStop(watcher, kfLocation)
      .then(() => delayMilliSeconds(200))
      .then(() => stopProcess(processId));
  }

  return Promise.resolve();
};
```

### 4. 进程状态管理

```typescript
export const listProcessStatus = (): Promise<{
  processStatus: Pm2ProcessStatusData;
  processStatusWithDetail: Pm2ProcessStatusDetailData;
}> => {
  return pm2List().then((pList: ProcessDescription[]) => {
    const processStatus = buildProcessStatus(pList);
    const processStatusWithDetail = buildProcessStatusWidthDetail(pList);
    return { processStatus, processStatusWithDetail };
  });
};

function buildProcessStatus(pList: ProcessDescription[]): Pm2ProcessStatusData {
  return pList.reduce((pre, p: ProcessDescription) => {
    const name: string | undefined = p?.name;
    const status: Pm2ProcessStatusTypes | undefined = p?.pm2_env?.status;
    if (name) {
      pre[name] = status;
    }
    return pre;
  }, {} as Pm2ProcessStatusData);
}
```

---

## 六、启动流程

### 完整启动顺序

```
1. 启动 Electron 应用
       │
       ▼
2. 启动核心系统服务（PM2 管理）
   ├── startMaster()     → master
   ├── startLedger()     → ledger
   └── startCacheD()     → cached
       │
       ▼
3. 启动业务服务（按需启动）
   ├── startMd()         → md_xxx (行情)
   ├── startTd()         → td_xxx (交易)
   └── startStrategy()   → strategy_xxx (策略)
       │
       ▼
4. 启动扩展服务（按需）
   └── startExtDaemon()  → 扩展守护进程
```

### 进程启动命令格式

所有服务均通过 `kfc` 可执行文件启动，格式如下：

```bash
# 核心服务
kfc run -c system -g master -n master
kfc run -c system -g service -n ledger
kfc run -c system -g service -n cached

# 行情服务
kfc -X "扩展目录" run -c md -g ctp -n ctp

# 交易服务
kfc -X "扩展目录" run -c td -g ctp -n account001

# 策略引擎
kfc run -c strategy -g default -n my_strategy /path/to/strategy.so
```

---

## 七、关键配置与环境变量

### 环境变量

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `KF_HOME` | 用户数据目录 | `~/.kungfu` |
| `KF_RUNTIME_DIR` | 运行时目录 | `~/.kungfu/runtime` |
| `EXTENSION_DIRS` | 扩展模块路径 | `/path/to/extensions` |
| `KFC_DIR` | kfc 可执行文件目录 | `/kungfu/bin` |
| `KF_NO_EXT` | 是否禁用扩展 | `on` |
| `RELOAD_AFTER_CRASHED` | 崩溃后是否重载 | `false` |
| `PYTHONUTF8` | Python UTF-8 支持 | `1` |
| `PYTHONIOENCODING` | Python IO 编码 | `utf8` |

### 进程管理特性

- **PM2 管理**：所有服务通过 PM2 进行进程管理
- **自动重启**：TD 和 MD 服务支持自动重启（可配置）
- **日志记录**：每个进程有独立的日志文件
- **优雅停止**：支持请求停止 + 强制停止的两阶段停止机制

---

## 八、启动完整服务所需的程序清单

| 层级 | 程序/服务 | 状态 | 说明 |
|------|----------|------|------|
| **框架层** | Electron 应用 | 必须 | 桌面客户端入口 |
| **核心服务** | master | 必须 | 系统核心协调器 |
| **核心服务** | ledger | 必须 | 交易数据账本 |
| **核心服务** | cached | 必须 | 高速缓存服务 |
| **业务服务** | md_xxx | 按需 | 行情数据采集 |
| **业务服务** | td_xxx | 按需 | 交易执行服务 |
| **业务服务** | strategy_xxx | 按需 | 策略运行引擎 |
| **扩展服务** | sim/xtp 等 | 按需 | 交易所接口扩展 |

---

## 九、编译产物分析

### 项目概述

这是一个基于 Yarn Workspaces 的 monorepo 项目，主要包含以下模块：
- `framework/app` - Electron 桌面应用框架
- `framework/api` - JavaScript/TypeScript API
- `developer/sdk` - 开发工具包（kfs 命令行工具）
- `extensions/` - 扩展模块（如 sim、xtp）
- `examples/` - 示例策略项目

### Artifact 构建（`yarn build`）

执行根目录的 `yarn build` 命令后，会在 `artifact/dist` 目录下生成以下结构：

| 目录 | 来源 | 说明 |
|------|------|------|
| `dist/app/` | `kungfu-app/dist/app` | Electron 渲染进程代码 |
| `dist/public/` | `kungfu-app/public` | 静态资源文件 |
| `dist/cli/` | `kungfu-cli/dist/cli` | 命令行工具 |
| `dist/api/` | `kungfu-js-api/dist/api` | JS API 模块 |
| `dist/kfs/` | `kungfu-sdk/dist/sdk` | 开发工具包 |

### 应用打包（`yarn package:app`）

执行 Electron 打包后，会在 `artifact/build` 目录生成平台相关的安装包：

- **Windows**: `.exe` 安装程序
- **macOS**: `.dmg` 磁盘镜像或 `.app` 应用包
- **Linux**: `.deb` 或 `.rpm` 包

### 策略/扩展编译产物

编译目标类型由 `package.json` 中的 `kungfuBuild.cpp.target` 字段决定：

| 目标类型 | CMake 命令 | 产物类型 | 用途 |
|----------|-----------|----------|------|
| `exe` | `add_executable` | 独立可执行文件 | 独立运行的 C++ 策略 |
| `bind/python` | `pybind11_add_module` | Python 扩展模块 | Python 策略调用 C++ 代码 |
| `bind/node` | `add_library` | Node.js 扩展模块 | Node.js 调用 C++ 代码 |

### 编译产物位置

编译后的产物输出到 `dist/<extension_name>/` 目录：

```
dist/
└── <extension_name>/
    ├── package.json
    ├── README.md（可选）
    ├── <executable>.exe（exe 目标）
    ├── <module>.pyd（Python 绑定）
    ├── <module>.node（Node.js 绑定）
    ├── __kungfulibs/（依赖库）
    └── __pypackages__/（Python 依赖）
```

### Python 策略编译

对于 Python 策略，使用 **Nuitka** 编译器编译为二进制模块。

### 总结

| 构建命令 | 产物 | 位置 |
|----------|------|------|
| `yarn build` | 所有模块的编译产物 | `各模块/dist/` |
| `yarn package:app` | Electron 安装包 | `artifact/build/` |
| `kfs strategy build` | 策略/扩展二进制 | `dist/<name>/` |
| `kfs extension compile` | 扩展编译产物 | `dist/<name>/` |

**核心可执行文件类型**：
1. **Electron 主程序** - 桌面应用入口
2. **CLI 工具** - `kfs` 命令行工具
3. **C++ 策略可执行文件** - 独立运行的策略程序（`.exe`）
4. **Python 扩展模块** - `.pyd` 或 `.so` 文件
5. **Node.js 扩展模块** - `.node` 文件

---

## 十、代码文件参考

| 文件路径 | 说明 |
|----------|------|
| `framework/api/src/utils/processUtils.ts` | 进程管理核心逻辑 |
| `framework/api/src/utils/pm2Custom.ts` | PM2 自定义配置 |
| `framework/api/src/kungfu/watcher.ts` | 监控器初始化 |
| `framework/api/src/actions/tradingTask.ts` | 交易任务管理 |
| `developer/sdk/src/lib/craft.js` | 构建流程管理 |
| `developer/sdk/src/lib/extension.js` | 扩展编译逻辑 |

---

**文档生成时间**：2026-05-20
