cmake_minimum_required(VERSION 3.10)
project(screensaver.dancingboids CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# A Kodi screensaver written for Kodi's binary add-on API. Build it against the
# Kodi 21 "Omega" dev kit:
#
#   cmake -S . -B build -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
#   cmake --build build
#
# build_all.sh builds every platform and copies the libraries into the add-on
# folders.
#
# Android uses the NDK toolchain and one ABI per build:
#
#   cmake -S . -B build-android \
#     -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
#     -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
#     -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include

set(KODI_DEVKIT_INCLUDE "" CACHE PATH "xbmc/addons/kodi-dev-kit/include")

if(NOT KODI_DEVKIT_INCLUDE)
  find_package(Kodi QUIET)
  if(KODI_INCLUDE_DIR)
    set(KODI_DEVKIT_INCLUDE ${KODI_INCLUDE_DIR}/..)
  else()
    message(FATAL_ERROR "Set -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include")
  endif()
endif()

set(ADDON_ID screensaver.dancingboids)

add_library(${ADDON_ID} MODULE src/ScreensaverDancingBoids.cpp)
target_include_directories(${ADDON_ID} PRIVATE ${KODI_DEVKIT_INCLUDE} ${PROJECT_SOURCE_DIR}/src)
set_target_properties(${ADDON_ID} PROPERTIES PREFIX "" POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
# The neighbour loop is the hot path; -O3 lets it vectorise. armeabi-v7a NDK
# builds already target ARMv7-A with NEON.
target_compile_options(${ADDON_ID} PRIVATE $<$<CONFIG:Release>:-O3>)
# Worker threads for the simulation (part of libc on Android and macOS).
set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)
target_link_libraries(${ADDON_ID} PRIVATE Threads::Threads)

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
endif()

