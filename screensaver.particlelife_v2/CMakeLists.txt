cmake_minimum_required(VERSION 3.10)
project(screensaver.particlelife_v2 CXX)

# A Kodi screensaver written for Kodi's binary add-on API. Build it against the
# Kodi 21 "Omega" dev kit:
#
#   cmake -S . -B build -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
#   cmake --build build
#
# That writes build/addon/screensaver.particlelife_v2/ (library, addon.xml,
# icon, settings and strings), ready to copy into Kodi's addons folder.
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

set(ADDON_ID screensaver.particlelife_v2)

add_library(${ADDON_ID} MODULE src/ScreensaverParticleLife.cpp)
target_include_directories(${ADDON_ID} PRIVATE ${KODI_DEVKIT_INCLUDE} ${PROJECT_SOURCE_DIR}/src)
set_target_properties(${ADDON_ID} PROPERTIES PREFIX "" POSITION_INDEPENDENT_CODE ON)

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

# Assemble a ready-to-copy add-on folder next to the library.
set(OUT ${CMAKE_BINARY_DIR}/addon/${ADDON_ID})
add_custom_command(TARGET ${ADDON_ID} POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory ${OUT}/resources
  COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:${ADDON_ID}> ${OUT}/
  COMMAND ${CMAKE_COMMAND} -E copy
          ${PROJECT_SOURCE_DIR}/addon.xml
          ${PROJECT_SOURCE_DIR}/icon.png
          ${PROJECT_SOURCE_DIR}/LICENSE.txt
          ${OUT}/
  COMMAND ${CMAKE_COMMAND} -E copy ${PROJECT_SOURCE_DIR}/resources/settings.xml ${OUT}/resources/
  COMMAND ${CMAKE_COMMAND} -E copy_directory ${PROJECT_SOURCE_DIR}/resources/language
          ${OUT}/resources/language)
