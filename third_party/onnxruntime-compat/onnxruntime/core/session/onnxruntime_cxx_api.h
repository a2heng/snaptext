#pragma once
// onnxruntime 1.29+ 预编译包把头文件放在 include/ 顶层（onnxruntime_cxx_api.h），
// 不再放在 include/onnxruntime/core/session/ 下。此 shim 让旧 include 路径可用。
#include <onnxruntime_cxx_api.h>
