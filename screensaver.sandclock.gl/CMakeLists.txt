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

add_library(sandclock_core STATIC src/sand.cpp src/engine.cpp)
target_include_directories(sandclock_core PUBLIC src)
target_compile_options(sandclock_core PRIVATE -Wall -Wextra)

enable_testing()
add_executable(test_sand tests/test_sand.cpp)
target_link_libraries(test_sand sandclock_core)
add_test(NAME sand COMMAND test_sand ${CMAKE_SOURCE_DIR}/../screensaver.sandclock/resources/media/fonts/fonts.json)

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

  if(APPLE)
    # The same thing with the 3.2 core profile Kodi runs on macOS, to test that shader dialect.
    add_library(sandclock_render_core STATIC src/renderer.cpp)
    target_link_libraries(sandclock_render_core PUBLIC sandclock_core OpenGL::GL)
    target_compile_definitions(sandclock_render_core PUBLIC SANDCLOCK_CORE)
    add_executable(sandclock_glfw_core src/main_glfw.cpp)
    target_link_libraries(sandclock_glfw_core sandclock_render_core ${GLFW_TARGET})
  endif()
endif()

# ---- Kodi add-on: cmake -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<.../kodi-dev-kit/include>
# Produces build/addon/screensaver.sandclock.gl/, ready to copy into Kodi's addons folder.
if(SANDCLOCK_KODI)
  set(ADDON_ID screensaver.sandclock.gl)
  if(NOT KODI_DEVKIT_INCLUDE)
    find_package(Kodi QUIET)
    if(KODI_INCLUDE_DIR)
      set(KODI_DEVKIT_INCLUDE ${KODI_INCLUDE_DIR}/..)
    else()
      message(FATAL_ERROR "Set -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include")
    endif()
  endif()
  find_package(OpenGL REQUIRED)

  add_library(${ADDON_ID} MODULE src/kodi_addon.cpp src/renderer.cpp)
  target_include_directories(${ADDON_ID} PRIVATE ${KODI_DEVKIT_INCLUDE})
  target_link_libraries(${ADDON_ID} PRIVATE sandclock_core)
  target_compile_definitions(${ADDON_ID} PRIVATE SANDCLOCK_KODI)
  set_target_properties(${ADDON_ID} PROPERTIES PREFIX "" POSITION_INDEPENDENT_CODE ON)
  set_target_properties(sandclock_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
  if(APPLE)
    target_compile_definitions(${ADDON_ID} PRIVATE TARGET_DARWIN HAS_GL SANDCLOCK_CORE GL_SILENCE_DEPRECATION)
    set_target_properties(${ADDON_ID} PROPERTIES SUFFIX ".dylib")
    target_link_options(${ADDON_ID} PRIVATE -undefined dynamic_lookup)  # kodi:: symbols live in Kodi
    target_link_libraries(${ADDON_ID} PRIVATE OpenGL::GL)
  elseif(WIN32)
    message(FATAL_ERROR "Kodi on Windows uses ANGLE (GLES); build with the kodi-addons cmake there")
  else()
    target_compile_definitions(${ADDON_ID} PRIVATE TARGET_LINUX)
    if(SANDCLOCK_GLES)
      target_compile_definitions(${ADDON_ID} PRIVATE HAS_GLES=2)
    else()
      target_compile_definitions(${ADDON_ID} PRIVATE HAS_GL)
      target_link_libraries(${ADDON_ID} PRIVATE OpenGL::GL)
    endif()
  endif()

  set(OUT ${CMAKE_BINARY_DIR}/addon/${ADDON_ID})
  set(FONTS ${CMAKE_SOURCE_DIR}/../screensaver.sandclock/resources/media/fonts/fonts.json)
  add_custom_command(TARGET ${ADDON_ID} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory ${OUT}/resources
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:${ADDON_ID}> ${OUT}/
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/addon.xml ${CMAKE_SOURCE_DIR}/icon.png
            ${CMAKE_SOURCE_DIR}/fanart.jpg ${CMAKE_SOURCE_DIR}/LICENSE.txt ${OUT}/
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/resources/settings.xml ${FONTS} ${OUT}/resources/
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_SOURCE_DIR}/resources/language ${OUT}/resources/language)
endif()
