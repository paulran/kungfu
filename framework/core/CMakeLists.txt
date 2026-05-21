# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.15)
project(kungfu)

##########################################################################

include(.cmake/editor.cmake)
include(.cmake/compiler.cmake)
include(.cmake/libnode.cmake)

# Conan 2.x compatibility
list(APPEND CMAKE_PREFIX_PATH "${CMAKE_BINARY_DIR}/build")
include(${CMAKE_BINARY_DIR}/build/conan_toolchain.cmake)
find_package(fmt REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(nng REQUIRED)
find_package(rxcpp REQUIRED)
find_package(spdlog REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(tabulate REQUIRED)

# pybind11 - using local source
add_subdirectory(.deps/pybind11-2.9.0)

##########################################################################

add_compile_definitions(HAVE_USLEEP=1)

add_compile_definitions(SPDLOG_ACTIVE_LEVEL=${SPDLOG_LOG_LEVEL_COMPILE})
add_compile_definitions(SPDLOG_NO_NAME)
add_compile_definitions(SPDLOG_NO_ATOMIC_LEVELS)

##########################################################################

option(NNG_TESTS "" OFF)
option(NNG_TOOLS "" OFF)
option(NNG_ENABLE_NNGCAT "" OFF)

##########################################################################

include_directories(.deps/hana-1.80.0/include)
include_directories(.deps/sqlite_orm-1.7.1/include)
include_directories(src/include)

##########################################################################

set(KUNGFU_BUILD_DIR ${CMAKE_BINARY_DIR})
set(KUNGFU_BUILD_LIBRARY_DIR ${KUNGFU_BUILD_DIR}/${CMAKE_BUILD_TYPE})

link_directories(${KUNGFU_BUILD_LIBRARY_DIR})

##########################################################################

if(DEFINED ENV{LIBKUNGFU_NAME})
  set(LIBKUNGFU_NAME $ENV{LIBKUNGFU_NAME})
else()
  set(LIBKUNGFU_NAME kungfu)
endif()

##########################################################################

if (NOT DEFINED ENV{KUNGFU_BUILD_SKIP_LIBKUNGFU} OR NOT $ENV{KUNGFU_BUILD_SKIP_LIBKUNGFU})
  message(STATUS "Enabled libkungfu")
  add_subdirectory(src/libkungfu)
endif()

if (NOT DEFINED ENV{KUNGFU_BUILD_SKIP_KUNGFU_NODE} OR NOT $ENV{KUNGFU_BUILD_SKIP_KUNGFU_NODE})
  message(STATUS "Enabled kungfu_node")
  add_subdirectory(src/bindings/node)
endif()

if (NOT DEFINED ENV{KUNGFU_BUILD_SKIP_PYKUNGFU} OR NOT $ENV{KUNGFU_BUILD_SKIP_PYKUNGFU})
  message(STATUS "Enabled pykungfu")
  add_subdirectory(src/bindings/python)
endif()
