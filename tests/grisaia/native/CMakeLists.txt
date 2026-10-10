cmake_minimum_required(VERSION 3.16)
project(GrisaiaWindowStateTests LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_executable(GrisaiaWindowStateTests window_state.cpp)
target_include_directories(GrisaiaWindowStateTests PRIVATE
  ../../../src/NativeImpl/LunaHook/LunaHook/engine32)
enable_testing()
add_test(NAME GrisaiaWindowState COMMAND GrisaiaWindowStateTests)
