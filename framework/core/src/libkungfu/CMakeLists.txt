project(${LIBKUNGFU_NAME})

enable_windows_export_all_symbols()

file(GLOB_RECURSE KUNGFU_OPTIM_SOURCE_FILES ${PROJECT_SOURCE_DIR}/*.cpp)
file(GLOB_RECURSE KUNGFU_CACHE_SOURCE_FILES ${PROJECT_SOURCE_DIR}/yijinjing/cache/*.cpp)
list(REMOVE_ITEM KUNGFU_OPTIM_SOURCE_FILES ${KUNGFU_CACHE_SOURCE_FILES})

add_library_object(kungfu_cache "${KUNGFU_CACHE_SOURCE_FILES}" "${COMPILER_OPTIMIZE_OFF_OPTIONS}" "${KUNGFU_BUILD_DIR}")
add_library_object(kungfu_optim "${KUNGFU_OPTIM_SOURCE_FILES}" "${COMPILER_OPTIMIZE_ON_OPTIONS}" "${KUNGFU_BUILD_DIR}")

# Link Conan targets to object libraries to get include directories
target_link_libraries(kungfu_cache PRIVATE fmt::fmt-header-only nlohmann_json::nlohmann_json nng::nng rxcpp::rxcpp spdlog::spdlog_header_only SQLite::SQLite3 tabulate::tabulate)
target_link_libraries(kungfu_optim PRIVATE fmt::fmt-header-only nlohmann_json::nlohmann_json nng::nng rxcpp::rxcpp spdlog::spdlog_header_only SQLite::SQLite3 tabulate::tabulate)

add_library(${LIBKUNGFU_NAME} SHARED $<TARGET_OBJECTS:kungfu_optim> $<TARGET_OBJECTS:kungfu_cache>)
set_target_properties(${LIBKUNGFU_NAME} PROPERTIES LINKER_LANGUAGE CXX)
set_target_properties(${LIBKUNGFU_NAME} PROPERTIES ARCHIVE_OUTPUT_DIRECTORY ${KUNGFU_BUILD_DIR})
target_compile_options(${LIBKUNGFU_NAME} PRIVATE "$<$<CONFIG:Release>:${COMPILER_OPTIMIZE_ON_OPTIONS}>")
target_link_libraries(${LIBKUNGFU_NAME} 
    fmt::fmt-header-only
    nlohmann_json::nlohmann_json
    nng::nng
    rxcpp::rxcpp
    spdlog::spdlog_header_only
    SQLite::SQLite3
    tabulate::tabulate
)
