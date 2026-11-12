cmake_minimum_required(VERSION 3.5)
project(screensaver.particlelife_v2)

set(CMAKE_MODULE_PATH ${PROJECT_SOURCE_DIR})

find_package(Kodi REQUIRED)

if(NOT WIN32 AND (APP_RENDER_SYSTEM STREQUAL "gl" OR NOT APP_RENDER_SYSTEM))
  find_package(OpenGl REQUIRED)
  set(DEPLIBS ${OPENGL_LIBRARIES})
  set(INCLUDES ${OPENGL_INCLUDE_DIR})
  add_definitions(-DHAS_GL)
elseif(APP_RENDER_SYSTEM STREQUAL "gles")
  find_package(OpenGLES REQUIRED)
  set(DEPLIBS ${OPENGLES_LIBRARIES})
  set(INCLUDES ${OPENGLES_INCLUDE_DIR})
  add_definitions(-DHAS_GLES=2)
endif()

include_directories(${INCLUDES} ${KODI_INCLUDE_DIR}/.. ${PROJECT_SOURCE_DIR}/src)

set(PARTICLELIFE_SOURCES src/ScreensaverParticleLife.cpp)
set(PARTICLELIFE_HEADERS src/ParticleLife.h)

build_addon(screensaver.particlelife_v2 PARTICLELIFE DEPLIBS)

include(CPack)
