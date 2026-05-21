# Node.js 24.15.0 升级说明

## 概述

本项目已成功升级至 Node.js 24.15.0，并完成了相关依赖和构建系统的同步升级。

## 升级内容

### 1. Node.js 版本升级

**修改文件**: `framework/core/package.json`

- 将 `@kungfu-trader/libnode` 版本从 `16.15.0` 升级至 `24.15.0`
- 更新了 `conanfile.py` 中的默认 `node_version` 选项至 `24.15.0`

### 2. Conan 2.x 迁移

**修改文件**: `framework/core/conanfile.py`

- 迁移至 Conan 2.x API：
  - 使用 `CMakeToolchain` 和 `CMakeDeps` 替代旧版 generator
  - 修复选项定义格式，添加 `&:` 前缀（如 `&:log_level`, `&:arch`）
  - 更新 `requirements()` 方法，移除 `pybind11` 依赖（改用本地源码）

**修改文件**: `framework/core/.gyp/run-conan.js`

- 将 `-if` 参数改为 `-of`（Conan 2.x 语法）
- 添加必要选项（`vs_toolset`, `log_level` 等）

### 3. Python 3.13 兼容性修复

**修改文件**: `framework/core/conanfile.py`

- 修复 `distutils` 模块导入问题：
```python
try:
    from distutils import sysconfig
except ImportError:
    import sysconfig
```

**修改文件**: `framework/core/.deps/pybind11-2.9.0/tools/FindPythonLibsNew.cmake`

- 使用 `sysconfig` 替代已移除的 `distutils` 模块
- 添加兼容层函数 `get_python_inc` 和 `get_python_lib`

**修改文件**: `framework/core/.deps/pybind11-2.9.0/include/pybind11/detail/type_caster_base.h`

- 修复 Python 3.13 中 `_frame` 类型未定义的问题
- 使用 `PyFrame_GetBack()` API 替代直接访问 `frame->f_back`

### 4. CMake 兼容性修复

**修改文件**: `framework/core/.deps/pybind11-2.9.0/CMakeLists.txt`

- 更新最低 CMake 版本要求从 `3.4` 至 `3.5...3.22`

**修改文件**: `framework/core/CMakeLists.txt`

- 适配 Conan 2.x 目标名称（`fmt::fmt-header-only`, `spdlog::spdlog_header_only`）
- 使用本地 pybind11 源码：`add_subdirectory(.deps/pybind11-2.9.0)`

### 5. libnode 源码集成（通过本地 Git 仓库）

**目录**: `framework/core/.deps/libnode`

- 将 libnode 作为本地仓库添加到项目中
- 使用 cmake-js 预下载的 Node.js 24.15.0 头文件进行构建

**libnode 结构**:
```
framework/core/.deps/libnode/
├── package.json          # 包配置，版本 24.15.0
├── src/js/index.js       # 模块导出，自动使用 cmake-js 缓存
├── .gyp/
│   └── node-make.js      # 构建脚本
└── ...                   # 其他源文件
```

**设置步骤**:
```bash
# libnode 已克隆到本地
# framework/core/.deps/libnode/

# 修改 package.json 引用本地 libnode
# framework/core/package.json
# "devDependencies": { "@kungfu-trader/libnode": "file:.deps/libnode" }
```

**修改文件**: `framework/core/.deps/libnode/src/js/index.js`
- 修改以优先使用 cmake-js 缓存的 Node.js 24.15.0 头文件

**修改文件**: `framework/core/package.json`
```json
{
  "devDependencies": {
    "@kungfu-trader/libnode": "file:.deps/libnode"
  }
}
```

## 依赖版本汇总

| 依赖 | 版本 |
|------|------|
| Node.js | 24.15.0 |
| Electron | 32.0.0 |
| Conan | 2.28.1 |
| pybind11 | 2.9.0 (本地源码) |
| @kungfu-trader/libnode | 24.15.0 |

## 构建说明

### 前置条件

1. Node.js 24.15.0 已安装
2. Conan 2.x 已安装
3. Python 3.13 环境可用
4. Visual Studio 2022 (v143) 已安装
5. libnode submodule 已初始化（见 5.1 节）

### 构建命令

```bash
# 安装依赖（使用本地 libnode，跳过 npm 下载）
yarn install --ignore-engines --ignore-optional

# 配置 Conan
yarn configure

# 编译项目
yarn compile

# 完整构建
yarn build
```

### 使用本地 libnode 源码编译

**步骤 1**: 初始化 libnode submodule
```bash
git submodule add https://github.com/paulran/libnode.git framework/core/.deps/libnode
git submodule update --init --recursive
```

**步骤 2**: 编译 libnode（Windows）
```bash
cd framework/core/.deps/libnode
yarn install
yarn make
yarn dist
```

**步骤 3**: 更新 CMake 配置使用本地 libnode
```cmake
# framework/core/CMakeLists.txt
include_directories(.deps/libnode/dist/node/include)
link_directories(.deps/libnode/dist/node)
```

## 已知问题

### libnode 编译需要 Clang

**问题**: Node.js 24.x 编译需要 Clang 编译器

**解决方案**:
- 当前使用 cmake-js 预下载的 Node.js 头文件和库文件进行构建
- 如果需要从源码编译 libnode，需安装 Clang/LLVM toolset

### 编译器内存不足

**问题**: 在编译复杂模板代码时，MSVC 编译器可能出现 `C1060: 编译器的堆空间不足` 错误

**解决方案**:
1. 减少并行编译线程数（已设置为 1）
2. 增加系统可用内存
3. 在资源更充足的环境中运行构建

## 验证步骤

1. 确认 Node.js 版本：`node -v` → v24.15.0
2. 确认 Conan 版本：`conan --version` → 2.28.1+
3. 运行 `yarn compile` 验证编译成功
4. 运行 `yarn test` 验证功能正常

---

*文档创建日期: 2026-05-21*
*项目版本: kungfu-core v2.4.77*