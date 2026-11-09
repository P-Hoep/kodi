// One place for the GL headers.
//  - Kodi build (PLANT_KODI): the dev kit's own header, which picks GL / GLES by HAS_GL / HAS_GLES.
//  - Harness: the system's. PLANT_CORE is the macOS 3.2 core profile (gl3.h).
#pragma once
#if defined(PLANT_KODI)
#include <kodi/gui/gl/GL.h>
#elif defined(PLANT_GLES)
#include <GLES2/gl2.h>
#elif defined(__APPLE__)
#define GL_SILENCE_DEPRECATION
#ifdef PLANT_CORE
#include <OpenGL/gl3.h>
#else
#include <OpenGL/gl.h>
#endif
#else
#include <GL/gl.h>
#endif
