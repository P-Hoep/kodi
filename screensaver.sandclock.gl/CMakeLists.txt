cmake_minimum_required(VERSION 3.16)
project(sandclock_gl CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

option(SANDCLOCK_GLES "Use OpenGL ES 2.0 shaders and headers" OFF)
option(SANDCLOCK_HARNESS "Build the GLFW test window (needs GLFW)" ON)
option(SANDCLOCK_FETCH_GLFW "Download GLFW instead of using an installed one" OFF)
option(SANDCLOCK_KODI "Build the Kodi add-on (needs the kodi-addon-dev-kit headers)" OFF)
set(KODI_DEVKIT_INCLUDE "" CACHE PATH "xbmc/addons/kodi-dev-kit/include, if Kodi's cmake package is not installed")

add_library(sandclock_core STATIC src/sand.cpp src/engine.cpp src/liquid.cpp src/automata.cpp src/physarum.cpp)
target_include_directories(sandclock_core PUBLIC src)
target_compile_options(sandclock_core PRIVATE -Wall -Wextra)

enable_testing()
add_executable(test_sand tests/test_sand.cpp)
target_link_libraries(test_sand sandclock_core)
add_test(NAME sand COMMAND test_sand ${CMAKE_SOURCE_DIR}/../screensaver.sandclock/resources/media/fonts/fonts.json)
add_executable(test_liquid tests/test_liquid.cpp)
target_link_libraries(test_liquid sandclock_core)
add_executable(test_automata tests/test_automata.cpp)
target_link_libraries(test_automata sandclock_core)
add_test(NAME automata COMMAND test_automata)
add_executable(test_physarum tests/test_physarum.cpp)
target_link_libraries(test_physarum sandclock_core)
add_test(NAME physarum COMMAND test_physarum)
add_test(NAME liquid COMMAND test_liquid ${CMAKE_SOURCE_DIR}/../screensaver.sandclock/resources/media/fonts/fonts.json)

if(SANDCLOCK_HARNESS)
  if(SANDCLOCK_FETCH_GLFW)
    include(FetchContent)
    set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(glfw GIT_REPOSITORY https://github.com/glfw/glfw.git GIT_TAG 3.4 GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(glfw)
    set(GLFW_TARGET glfw)
  else()
    find_package(glfw3 REQUIRED)
    set(GLFW_TARGET glfw)
  endif()
  find_package(OpenGL REQUIRED)

  add_library(sandclock_render STATIC src/renderer.cpp)
  target_link_libraries(sandclock_render PUBLIC sandclock_core OpenGL::GL)
  if(SANDCLOCK_GLES)
    target_compile_definitions(sandclock_render PUBLIC SANDCLOCK_GLES)
  endif()

  add_executable(sandclock_glfw src/main_glfw.cpp)
  target_link_libraries(sandclock_glfw sandclock_render ${GLFW_TARGET})

  add_library(liquid_render STATIC src/liquid_renderer.cpp)
  target_link_libraries(liquid_render PUBLIC sandclock_core OpenGL::GL)
  if(SANDCLOCK_GLES)
    target_compile_definitions(liquid_render PUBLIC SANDCLOCK_GLES)
  endif()
  add_executable(liquidclock_glfw src/main_glfw.cpp)
  target_compile_definitions(liquidclock_glfw PRIVATE SANDCLOCK_LIQUID)
  target_link_libraries(liquidclock_glfw liquid_render ${GLFW_TARGET})

  add_library(automata_render STATIC src/automata_app.cpp)
  target_link_libraries(automata_render PUBLIC sandclock_core OpenGL::GL)
  if(SANDCLOCK_GLES)
    target_compile_definitions(automata_render PUBLIC SANDCLOCK_GLES)
  endif()
  add_executable(automata_glfw src/main_automata_glfw.cpp)
  target_link_libraries(automata_glfw automata_render ${GLFW_TARGET})

  add_library(physarum_render STATIC src/physarum_app.cpp)
  target_link_libraries(physarum_render PUBLIC sandclock_core OpenGL::GL)
  if(SANDCLOCK_GLES)
    target_compile_definitions(physarum_render PUBLIC SANDCLOCK_GLES)
  endif()
  add_executable(physarum_glfw src/main_physarum_glfw.cpp)
  target_link_libraries(physarum_glfw physarum_render ${GLFW_TARGET})

  add_library(physarum_lite_render STATIC src/physarum_lite_app.cpp)
  target_link_libraries(physarum_lite_render PUBLIC sandclock_core OpenGL::GL)
  if(SANDCLOCK_GLES)
    target_compile_definitions(physarum_lite_render PUBLIC SANDCLOCK_GLES)
  endif()
  add_executable(physarum_lite_glfw src/main_physarum_lite_glfw.cpp)
  target_link_libraries(physarum_lite_glfw physarum_lite_render ${GLFW_TARGET})

  add_library(automata_lite_render STATIC src/automata_lite_app.cpp)
  target_link_libraries(automata_lite_render PUBLIC sandclock_core OpenGL::GL)
  if(SANDCLOCK_GLES)
    target_compile_definitions(automata_lite_render PUBLIC SANDCLOCK_GLES)
  endif()
  add_executable(automata_lite_glfw src/main_automata_lite_glfw.cpp)
  target_link_libraries(automata_lite_glfw automata_lite_render ${GLFW_TARGET})

  if(APPLE)
    add_library(physarum_render_core STATIC src/physarum_app.cpp)
    target_link_libraries(physarum_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(physarum_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(physarum_glfw_core src/main_physarum_glfw.cpp)
    target_link_libraries(physarum_glfw_core physarum_render_core ${GLFW_TARGET})

    add_library(physarum_lite_render_core STATIC src/physarum_lite_app.cpp)
    target_link_libraries(physarum_lite_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(physarum_lite_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(physarum_lite_glfw_core src/main_physarum_lite_glfw.cpp)
    target_link_libraries(physarum_lite_glfw_core physarum_lite_render_core ${GLFW_TARGET})

    # The same thing with the 3.2 core profile Kodi runs on macOS, to test that shader dialect.
    add_library(automata_render_core STATIC src/automata_app.cpp)
    target_link_libraries(automata_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(automata_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(automata_glfw_core src/main_automata_glfw.cpp)
    target_link_libraries(automata_glfw_core automata_render_core ${GLFW_TARGET})
    add_library(automata_lite_render_core STATIC src/automata_lite_app.cpp)
    target_link_libraries(automata_lite_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(automata_lite_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(automata_lite_glfw_core src/main_automata_lite_glfw.cpp)
    target_link_libraries(automata_lite_glfw_core automata_lite_render_core ${GLFW_TARGET})
    add_library(liquid_render_core STATIC src/liquid_renderer.cpp)
    target_link_libraries(liquid_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(liquid_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(liquidclock_glfw_core src/main_glfw.cpp)
    target_compile_definitions(liquidclock_glfw_core PRIVATE SANDCLOCK_LIQUID)
    target_link_libraries(liquidclock_glfw_core liquid_render_core ${GLFW_TARGET})

    add_library(sandclock_render_core STATIC src/renderer.cpp)
    target_link_libraries(sandclock_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(sandclock_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(sandclock_glfw_core src/main_glfw.cpp)
    target_link_libraries(sandclock_glfw_core sandclock_render_core ${GLFW_TARGET})
  endif()
endif()

# ---- Kodi add-ons: cmake -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<.../kodi-dev-kit/include>
# Sand Clock -> build/addon/screensaver.sandclock.gl/ ; Liquid Clock -> build/liquid/ (library only).
if(SANDCLOCK_KODI)
  if(NOT KODI_DEVKIT_INCLUDE)
    find_package(Kodi QUIET)
    if(KODI_INCLUDE_DIR)
      set(KODI_DEVKIT_INCLUDE ${KODI_INCLUDE_DIR}/..)
    else()
      message(FATAL_ERROR "Set -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include")
    endif()
  endif()
  if(NOT ANDROID)
    find_package(OpenGL REQUIRED)
  endif()
  set_target_properties(sandclock_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

  function(sandclock_kodi_module NAME)
    add_library(${NAME} MODULE ${ARGN})
    target_include_directories(${NAME} PRIVATE ${KODI_DEVKIT_INCLUDE})
    target_link_libraries(${NAME} PRIVATE sandclock_core)
    target_compile_definitions(${NAME} PRIVATE SANDCLOCK_KODI)
    set_target_properties(${NAME} PROPERTIES PREFIX "" POSITION_INDEPENDENT_CODE ON)
    if(ANDROID)
      # cmake -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake
      #       -DANDROID_ABI=arm64-v8a|armeabi-v7a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static
      target_compile_definitions(${NAME} PRIVATE TARGET_ANDROID TARGET_LINUX HAS_GLES=2 SANDCLOCK_GLES)
      target_link_libraries(${NAME} PRIVATE GLESv2 log)
      set_target_properties(${NAME} PROPERTIES SUFFIX ".so")
    elseif(APPLE)
      target_compile_definitions(${NAME} PRIVATE TARGET_DARWIN HAS_GL SANDCLOCK_CORE GL_SILENCE_DEPRECATION)
      set_target_properties(${NAME} PROPERTIES SUFFIX ".dylib")
      target_link_options(${NAME} PRIVATE -undefined dynamic_lookup)  # kodi:: symbols live in Kodi
      target_link_libraries(${NAME} PRIVATE OpenGL::GL)
    elseif(WIN32)
      message(FATAL_ERROR "Kodi on Windows uses ANGLE (GLES); build with the kodi-addons cmake there")
    else()
      target_compile_definitions(${NAME} PRIVATE TARGET_LINUX)
      if(SANDCLOCK_GLES)
        target_compile_definitions(${NAME} PRIVATE HAS_GLES=2)
      else()
        target_compile_definitions(${NAME} PRIVATE HAS_GL)
        target_link_libraries(${NAME} PRIVATE OpenGL::GL)
      endif()
    endif()
  endfunction()

  # Sand Clock: also assembles a ready-to-copy add-on folder.
  set(ADDON_ID screensaver.sandclock.gl)
  sandclock_kodi_module(${ADDON_ID} src/kodi_addon.cpp src/renderer.cpp)
  set(OUT ${CMAKE_BINARY_DIR}/addon/${ADDON_ID})
  set(FONTS ${CMAKE_SOURCE_DIR}/../screensaver.sandclock/resources/media/fonts/fonts.json)
  add_custom_command(TARGET ${ADDON_ID} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory ${OUT}/resources
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:${ADDON_ID}> ${OUT}/
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/addon.xml ${CMAKE_SOURCE_DIR}/icon.png
            ${CMAKE_SOURCE_DIR}/fanart.jpg ${CMAKE_SOURCE_DIR}/LICENSE.txt ${OUT}/
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/resources/settings.xml ${FONTS} ${OUT}/resources/
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_SOURCE_DIR}/resources/language ${OUT}/resources/language)

  # Liquid Clock: only the library; the add-on folder is ../screensaver.liquidclock.armv7.
  sandclock_kodi_module(screensaver.liquidclock src/kodi_liquid.cpp src/liquid_renderer.cpp)

  # Cellular Automata: only the library; the add-on folder is ../screensaver.automata.armv7.
  sandclock_kodi_module(screensaver.automata src/kodi_automata.cpp src/automata_app.cpp)

  # Physarum: only the library; the add-on folder is ../screensaver.physarum.armv7.
  sandclock_kodi_module(screensaver.physarum src/kodi_physarum.cpp src/physarum_app.cpp)

  # Physarum Lite: the same simulation with the timers removed and an optional clock (off by
  # default); the add-on folder is ../screensaver.physarum.lite.armv7.
  sandclock_kodi_module(screensaver.physarum_lite src/kodi_physarum_lite.cpp src/physarum_lite_app.cpp)

  # Cellular Automata Lite: the same automaton without the clock, with specialised shaders and a
  # capped draw resolution; the add-on folder is ../screensaver.automata.lite.armv7.
  sandclock_kodi_module(screensaver.automata_lite src/kodi_automata_lite.cpp src/automata_lite_app.cpp)
endif()
