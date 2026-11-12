# ScreenMazer (OpenGL) - Kodi screensaver

Binary (C++) Kodi screensaver port of Alex Beals' macOS screensaver
[ScreenMazer](https://github.com/dado3212/ScreenMazer) (Swift / SpriteKit). It
builds a maze cell by cell around a block showing the time, traces the
solution, fades out and starts again. The original Swift source is kept in
`../ScreenMazer-master/` for reference.

## Layout
- `src/Maze.h`: the generator (`MazeGenerator.swift`): clock glyphs and frame
  (`timeToArray()`), randomised depth-first search, solution walk-back.
- `src/Mazer.h`: the animation (`MazeScene.update`): build, 1 s pause, solve,
  2 s pause, 1 s fade back to the wall colour, next maze. Each cell fades to its
  new colour over 0.5 s like `SKAction.colorize`. GL-free, so it is testable.
- `src/ScreensaverMazer.cpp`: the Kodi wrapper. One RGBA texel per cell,
  uploaded with `glTexSubImage2D` and drawn as one `GL_NEAREST` quad.
- `tests/maze_test.cpp`: maze validity checks and a full animation cycle.

## What changed vs. the original
- Grid orientation is the original's (row 0 at the bottom, entrance bottom
  left, exit on the right edge), which is also GL texture order.
- Reveal speed is time-based (cells per second = cells / build time) instead of
  "at least one cell per tick"; the pauses are the original's 60/120 ticks as
  1 s / 2 s.
- Fixed: the first carved cell (1,1) was never marked open, so it stayed dark
  until the solve and could be carved into twice. It is now lit and opened.
- Fixed: a maze too small for the clock skips the clock instead of trapping on
  an empty random range.
- Cell size is in pixels on a 1080-line screen, scaled and rounded to whole
  pixels; leftover margins take the wall colour.
- Added settings: wall colour, centred clock (the original had it commented
  out), clock on/off. Dropped: the preview-size scaling (Kodi has no
  System Settings thumbnail preview).

## Build (macOS, universal Intel + Apple Silicon)
    cmake -S . -B build-uni -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
      -DKODI_DEVKIT_INCLUDE=/tmp/kodi-src/xbmc/addons/kodi-dev-kit/include
    cmake --build build-uni
    cp build-uni/addon/screensaver.screenmazer/screensaver.screenmazer.dylib .

## Build (Android, 64-bit and 32-bit)
    NDK=/opt/homebrew/Caskroom/android-ndk/30/AndroidNDK16248370.app/Contents/NDK
    for abi in arm64-v8a armeabi-v7a; do
      cmake -S . -B build-android-$abi -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
        -DANDROID_ABI=$abi -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
        -DKODI_DEVKIT_INCLUDE=/tmp/kodi-src/xbmc/addons/kodi-dev-kit/include
      cmake --build build-android-$abi
    done
    STRIP=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip
    $STRIP --strip-unneeded -o screensaver.screenmazer.so \
      build-android-arm64-v8a/addon/screensaver.screenmazer/screensaver.screenmazer.so
    $STRIP --strip-unneeded -o ../screensaver.screenmazer.armv7/screensaver.screenmazer.armv7.so \
      build-android-armeabi-v7a/addon/screensaver.screenmazer/screensaver.screenmazer.so

## Test (no Kodi needed)
    c++ -O2 -std=c++17 -Isrc tests/maze_test.cpp -o /tmp/maze_test && /tmp/maze_test
    # snapshot of a solved maze: /tmp/maze_test out.ppm [cell_px rows cols seed]

`icon.png` (`out.ppm 8 32 32 5`) and `fanart.jpg` (`out.ppm 7 154 274 3`,
pasted on a 1920x1080 canvas) were made this way.

## Release
Bump `version="..."` in `addon.xml` and in `../screensaver.screenmazer.armv7`
when they change, commit the libraries with the code, and push to `main`; the
GitHub Actions workflow publishes the repository.
