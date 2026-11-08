// One place for the GL headers.
//  - Kodi build (SANDCLOCK_KODI): the dev kit's own header, which picks GL / GLES by HAS_GL / HAS_GLES.
//  - Harness: the system's. SANDCLOCK_CORE is the macOS 3.2 core profile (gl3.h), which Kodi uses there.
#pragma once
#if defined(SANDCLOCK_KODI)
#include <kodi/gui/gl/GL.h>
#elif defined(SANDCLOCK_GLES)
#include <GLES2/gl2.h>
#elif defined(__APPLE__)
#define GL_SILENCE_DEPRECATION
#ifdef SANDCLOCK_CORE
#include <OpenGL/gl3.h>
#else
#include <OpenGL/gl.h>
#endif
#else
#include <GL/gl.h>
#endif
