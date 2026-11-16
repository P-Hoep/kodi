cmake_minimum_required(VERSION 3.10)
project(screensaver.aiarcade C CXX)

# AI Arcade: a Kodi screensaver that teaches itself to play NES ROMs.
#
#   cmake -S . -B build -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
#   cmake --build build
#
# ARCADE_KODI=OFF builds only the Kodi-free parts (the Nestopia core, the
# trainer and the command-line tools in tests/), which need no dev kit.
# build_all.sh builds every platform and copies the libraries into the add-on.

option(ARCADE_KODI "Build the Kodi screensaver module" ON)
option(ARCADE_TOOLS "Build the command-line tests and tools" OFF)
set(KODI_DEVKIT_INCLUDE "" CACHE PATH "xbmc/addons/kodi-dev-kit/include")

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ---- Nestopia core (GPL-2.0-or-later), compiled in --------------------------
set(NST ${PROJECT_SOURCE_DIR}/third_party/nestopia/src)
file(GLOB NST_SOURCES ${NST}/*.cpp ${NST}/api/*.cpp ${NST}/board/*.cpp ${NST}/input/*.cpp ${NST}/vssystem/*.cpp)
add_library(nestopia_core STATIC ${NST_SOURCES})
set_target_properties(nestopia_core PROPERTIES CXX_STANDARD 11 CXX_STANDARD_REQUIRED ON)
target_compile_definitions(nestopia_core PRIVATE NST_NO_ZLIB)
target_include_directories(nestopia_core PUBLIC ${NST})
target_compile_options(nestopia_core PRIVATE -O2 -w -fno-strict-aliasing)

# ---- the trainer: emulator wrapper, Go-Explore, objectives, NEAT ------------
find_package(ZLIB REQUIRED)
set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)

add_library(arcade_core STATIC src/Emu.cpp src/Store.cpp src/Neat.cpp src/Objectives.cpp src/Trainer.cpp)
set_target_properties(arcade_core PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_include_directories(arcade_core PUBLIC ${PROJECT_SOURCE_DIR}/src ${PROJECT_SOURCE_DIR}/third_party)
target_compile_options(arcade_core PRIVATE -O3 -Wall)
target_link_libraries(arcade_core PUBLIC nestopia_core ZLIB::ZLIB Threads::Threads)

if(ARCADE_TOOLS)
  foreach(t emu_test arcade_test)
    add_executable(${t} tests/${t}.cpp)
    set_target_properties(${t} PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
    target_compile_options(${t} PRIVATE -O2)
    target_link_libraries(${t} PRIVATE arcade_core)
  endforeach()
endif()

if(NOT ARCADE_KODI)
  return()
endif()

if(NOT KODI_DEVKIT_INCLUDE)
  find_package(Kodi QUIET)
  if(KODI_INCLUDE_DIR)
    set(KODI_DEVKIT_INCLUDE ${KODI_INCLUDE_DIR}/..)
  else()
    message(FATAL_ERROR "Set -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include")
  endif()
endif()

set(ADDON_ID screensaver.aiarcade)
add_library(${ADDON_ID} MODULE src/ScreensaverAIArcade.cpp)
set_target_properties(${ADDON_ID} PROPERTIES PREFIX "" CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_include_directories(${ADDON_ID} PRIVATE ${KODI_DEVKIT_INCLUDE})
target_compile_options(${ADDON_ID} PRIVATE -O2)
target_link_libraries(${ADDON_ID} PRIVATE arcade_core)

if(ANDROID)
  target_compile_definitions(${ADDON_ID} PRIVATE TARGET_ANDROID TARGET_LINUX HAS_GLES=2)
  target_link_libraries(${ADDON_ID} PRIVATE GLESv2 log)
  set_target_properties(${ADDON_ID} PROPERTIES SUFFIX ".so")
elseif(APPLE)
  find_package(OpenGL REQUIRED)
  target_compile_definitions(${ADDON_ID} PRIVATE TARGET_DARWIN HAS_GL GL_SILENCE_DEPRECATION)
  target_link_libraries(${ADDON_ID} PRIVATE OpenGL::GL)
  set_target_properties(${ADDON_ID} PROPERTIES SUFFIX ".dylib")
  target_link_options(${ADDON_ID} PRIVATE -undefined dynamic_lookup) # kodi:: symbols live in Kodi
elseif(WIN32)
  message(FATAL_ERROR "Kodi on Windows uses ANGLE (GLES); build with Kodi's cmake addons tree")
else()
  find_package(OpenGL REQUIRED)
  target_compile_definitions(${ADDON_ID} PRIVATE TARGET_LINUX HAS_GL)
  target_link_libraries(${ADDON_ID} PRIVATE OpenGL::GL)
  set_target_properties(${ADDON_ID} PROPERTIES SUFFIX ".so")
  # keep the static C++ runtime pieces and Nestopia's symbols private
  target_link_options(${ADDON_ID} PRIVATE -Wl,--exclude-libs,ALL)
endif()
