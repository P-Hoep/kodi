cmake_minimum_required(VERSION 3.16)
project(screensaver_plant CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Growing Plant (OpenGL): a screensaver add-on for Kodi.
#   cmake -S . -B build -DPLANT_HARNESS=ON            # GLFW test window + tests
#   cmake -S . -B build -DPLANT_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>  # the add-on library
option(PLANT_GLES "Compile the renderer for OpenGL ES 2.0" OFF)
option(PLANT_HARNESS "Build the GLFW test window (needs GLFW)" ON)
option(PLANT_FETCH_GLFW "Download GLFW instead of using an installed one" OFF)
option(PLANT_KODI "Build the Kodi add-on (needs the kodi-addon-dev-kit headers)" OFF)
set(KODI_DEVKIT_INCLUDE "" CACHE PATH "xbmc/addons/kodi-dev-kit/include, if Kodi's cmake package is not installed")

add_library(plant_core STATIC
  src/plant_growth.cpp
  src/twol/generator.cpp
  src/twol/lsystem.cpp
  src/twol/math.cpp
  src/twol/mesh_builder.cpp
  src/twol/presets.cpp
  src/twol/random.cpp
)
target_include_directories(plant_core PUBLIC src)
if(NOT MSVC)
  target_compile_options(plant_core PRIVATE -Wall -Wextra)
endif()

enable_testing()
add_executable(test_plant_growth tests/test_plant_growth.cpp)
target_link_libraries(test_plant_growth plant_core)
if(NOT MSVC)
  target_compile_options(test_plant_growth PRIVATE -Wall -Wextra)
endif()
add_test(NAME plant_growth COMMAND test_plant_growth)

if(PLANT_HARNESS)
  if(PLANT_FETCH_GLFW)
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

  add_library(plant_render STATIC src/plant_app.cpp)
  target_link_libraries(plant_render PUBLIC plant_core OpenGL::GL)
  if(PLANT_GLES)
    target_compile_definitions(plant_render PUBLIC PLANT_GLES)
  endif()
  add_executable(plant_glfw src/main_plant_glfw.cpp)
  target_link_libraries(plant_glfw plant_render ${GLFW_TARGET})

  if(APPLE)
    # The same renderer with the 3.2 core profile Kodi runs on macOS.
    add_library(plant_render_core STATIC src/plant_app.cpp)
    target_link_libraries(plant_render_core PUBLIC plant_core OpenGL::GL)
    target_compile_definitions(plant_render_core PUBLIC PLANT_CORE)
    add_executable(plant_glfw_core src/main_plant_glfw.cpp)
    target_link_libraries(plant_glfw_core plant_render_core ${GLFW_TARGET})
  endif()
endif()

# ---- Kodi add-on -----------------------------------------------------------------
if(PLANT_KODI)
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

  add_library(screensaver.plant.gl MODULE src/kodi_plant.cpp src/plant_app.cpp)
  target_include_directories(screensaver.plant.gl PRIVATE ${KODI_DEVKIT_INCLUDE})
  target_link_libraries(screensaver.plant.gl PRIVATE plant_core)
  target_compile_definitions(screensaver.plant.gl PRIVATE PLANT_KODI)
  set_target_properties(screensaver.plant.gl PROPERTIES PREFIX "" POSITION_INDEPENDENT_CODE ON)
  if(NOT MSVC)
    target_compile_options(screensaver.plant.gl PRIVATE -Wall -Wextra)
  endif()
  if(ANDROID)
    # cmake -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake
    #       -DANDROID_ABI=arm64-v8a|armeabi-v7a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static
    target_compile_definitions(screensaver.plant.gl PRIVATE TARGET_ANDROID TARGET_LINUX
                                                             HAS_GLES=2 PLANT_GLES)
    target_link_libraries(screensaver.plant.gl PRIVATE GLESv2 log)
    set_target_properties(screensaver.plant.gl PROPERTIES SUFFIX ".so")
  elseif(APPLE)
    target_compile_definitions(screensaver.plant.gl PRIVATE TARGET_DARWIN HAS_GL PLANT_CORE
                                                             GL_SILENCE_DEPRECATION)
    set_target_properties(screensaver.plant.gl PROPERTIES SUFFIX ".dylib")
    target_link_options(screensaver.plant.gl PRIVATE -undefined dynamic_lookup)
    target_link_libraries(screensaver.plant.gl PRIVATE OpenGL::GL)
  elseif(WIN32)
    message(FATAL_ERROR "Kodi on Windows uses ANGLE (GLES); build with the kodi-addons cmake there")
  elseif(PLANT_GLES)
    target_compile_definitions(screensaver.plant.gl PRIVATE TARGET_LINUX HAS_GLES=2 PLANT_GLES)
    target_link_libraries(screensaver.plant.gl PRIVATE GLESv2)
  else()
    target_compile_definitions(screensaver.plant.gl PRIVATE TARGET_LINUX HAS_GL PLANT_CORE)
    target_link_libraries(screensaver.plant.gl PRIVATE OpenGL::GL)
  endif()
endif()
