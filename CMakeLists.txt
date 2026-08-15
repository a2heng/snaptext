cmake_minimum_required(VERSION 3.21)
project(snaptext VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# ── 依赖发现 ────────────────────────────────────────────────────────────────
find_package(OpenCV REQUIRED)
find_package(X11 REQUIRED)
find_package(Qt6 6.4 REQUIRED COMPONENTS Widgets DBus Network)

# onnxruntime：优先用 -DONNXRUNTIME_ROOT 指定，否则找项目内 third_party/onnxruntime/
set(ONNXRUNTIME_ROOT "" CACHE PATH "path to unpacked onnxruntime-linux-x64 release")
if(NOT ONNXRUNTIME_ROOT)
  file(GLOB _ort_candidates
    "${CMAKE_SOURCE_DIR}/third_party/onnxruntime/onnxruntime-linux-x64-*")
  list(SORT _ort_candidates)
  list(REVERSE _ort_candidates)
  list(GET _ort_candidates 0 ONNXRUNTIME_ROOT)
endif()
if(NOT EXISTS "${ONNXRUNTIME_ROOT}/include/onnxruntime_cxx_api.h")
  message(FATAL_ERROR "onnxruntime 头文件未找到，请先跑 scripts/fetch-onnxruntime.sh 或用 -DONNXRUNTIME_ROOT 指定")
endif()
if(NOT EXISTS "${ONNXRUNTIME_ROOT}/lib/libonnxruntime.so")
  message(FATAL_ERROR "libonnxruntime.so 未找到于 ${ONNXRUNTIME_ROOT}/lib")
endif()
message(STATUS "onnxruntime root: ${ONNXRUNTIME_ROOT}")

# ── OCR 核心：vendor 的 RapidOCR C++（MIT，改自 lwtw123456/RapidOCR-dll）────
set(RAPIDOCR_DIR ${CMAKE_SOURCE_DIR}/vendor/rapidocr)
add_library(snaptext_ocr STATIC
  ${RAPIDOCR_DIR}/src/ocr_common.cpp
  ${RAPIDOCR_DIR}/src/ocr_engine.cpp
  ${RAPIDOCR_DIR}/src/classifier.cpp
  ${RAPIDOCR_DIR}/src/detector.cpp
  ${RAPIDOCR_DIR}/src/recognizer.cpp
  ${RAPIDOCR_DIR}/third_party/clipper/clipper.cpp
)
target_include_directories(snaptext_ocr PUBLIC
  ${CMAKE_SOURCE_DIR}/third_party/onnxruntime-compat
  ${RAPIDOCR_DIR}/include
  ${RAPIDOCR_DIR}/third_party/clipper
  ${RAPIDOCR_DIR}/third_party/stb
  ${ONNXRUNTIME_ROOT}/include
)
target_link_libraries(snaptext_ocr PUBLIC
  ${ONNXRUNTIME_ROOT}/lib/libonnxruntime.so
  opencv_core opencv_imgproc opencv_imgcodecs
)
target_compile_definitions(snaptext_ocr PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)

# ── 主程序 ──────────────────────────────────────────────────────────────────
set(SNAPTEXT_SRC
  src/ocr.cpp
  src/config.cpp
  src/hotkey.cpp
  src/globalshortcut.cpp
  src/ui.cpp
  src/portal.cpp
  src/tray.cpp
  src/ipc.cpp
  src/app.cpp
  src/main.cpp
)
add_executable(snaptext ${SNAPTEXT_SRC})
target_include_directories(snaptext PRIVATE src)
target_compile_definitions(snaptext PRIVATE
  SNAPTEXT_VERSION="${PROJECT_VERSION}"
  QT_NO_CAST_FROM_ASCII
  QT_NO_CAST_TO_ASCII
)
target_link_libraries(snaptext PRIVATE
  snaptext_ocr
  Qt6::Widgets
  Qt6::DBus
  Qt6::Network
  ${X11_LIBRARIES}
  Threads::Threads
)

# ── OCR 命令行单跑（对应旧 ocr.py 的 CLI）──────────────────────────────────
add_executable(snaptext-ocr src/ocr.cpp src/ocrcli.cpp)
target_include_directories(snaptext-ocr PRIVATE src)
target_link_libraries(snaptext-ocr PRIVATE snaptext_ocr Threads::Threads)

# 部署：models/icons 打进 build 目录，便于直接运行
add_custom_command(TARGET snaptext POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory
    ${CMAKE_SOURCE_DIR}/models ${CMAKE_BINARY_DIR}/models)
add_custom_command(TARGET snaptext POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory
    ${CMAKE_SOURCE_DIR}/icons ${CMAKE_BINARY_DIR}/icons)
