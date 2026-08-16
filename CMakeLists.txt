cmake_minimum_required(VERSION 3.16)
project(tvc_harness CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "Linux-only: clock_nanosleep/SCHED_FIFO/sched_setaffinity. Build in the tvc-dev container on other hosts.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

# -O2 with frame pointers and symbols. Optimised, because measuring a debug
# build tells you nothing about the binary you would fly; frame pointers,
# because perf needs them to unwind and the cost is under one percent.
set(CMAKE_CXX_FLAGS_RELWITHDEBINFO "-O2 -g -fno-omit-frame-pointer -ffp-contract=off")

# -ffast-math is deliberately absent and -ffp-contract=off is set: both can
# change bit-level results across builds, which breaks replay goldens.

include(FetchContent)
set(HDR_HISTOGRAM_BUILD_PROGRAMS OFF CACHE BOOL "" FORCE)
set(HDR_HISTOGRAM_BUILD_SHARED   OFF CACHE BOOL "" FORCE)
set(HDR_LOG_REQUIRED             OFF CACHE BOOL "" FORCE)
FetchContent_Declare(
  hdr_histogram
  GIT_REPOSITORY https://github.com/HdrHistogram/HdrHistogram_c.git
  GIT_TAG        0.11.8
  GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(hdr_histogram)

add_executable(tvc_harness
  src/main.cpp
  src/alloc_guard.cpp
  src/rt_setup.cpp
  src/loop_stats.cpp
  src/telemetry.cpp
)

target_compile_definitions(tvc_harness PRIVATE _GNU_SOURCE)
target_include_directories(tvc_harness PRIVATE
  ${hdr_histogram_SOURCE_DIR}/include
)

if(TARGET hdr_histogram_static)
  target_link_libraries(tvc_harness PRIVATE hdr_histogram_static)
else()
  target_link_libraries(tvc_harness PRIVATE hdr_histogram)
endif()

find_package(Threads REQUIRED)
target_link_libraries(tvc_harness PRIVATE Threads::Threads m)

target_compile_options(tvc_harness PRIVATE -Wall -Wextra -Wpedantic)

add_executable(wire_tests tests/cpp/wire_tests.cpp src/telemetry.cpp)
target_compile_definitions(wire_tests PRIVATE _GNU_SOURCE)
target_compile_options(wire_tests PRIVATE -Wall -Wextra -Wpedantic)
