#!/bin/sh
# Rebuild the macOS universal dylib and both Android libraries, and copy them into the add-on
# folders. Needs the Kodi 21 dev-kit headers and the Android NDK (see docs/development.md).
set -e
cd "$(dirname "$0")"
DEVKIT=${KODI_DEVKIT_INCLUDE:-/tmp/kodi-src/xbmc/addons/kodi-dev-kit/include}
NDK=${NDK:-/opt/homebrew/Caskroom/android-ndk/30/AndroidNDK16248370.app/Contents/NDK}
STRIP=$(ls "$NDK"/toolchains/llvm/prebuilt/*/bin/llvm-strip | head -1)

cmake -S . -B build-uni -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
  -DKODI_DEVKIT_INCLUDE="$DEVKIT" >/dev/null
cmake --build build-uni
codesign --force --sign - build-uni/screensaver.physarum_v2.dylib
# Replace, never overwrite in place: macOS caches a signed file's code signature by inode, and a
# running Kodi that dlopens a rewritten file is killed with "Code Signature Invalid".
cp build-uni/screensaver.physarum_v2.dylib screensaver.physarum_v2.dylib.new
mv -f screensaver.physarum_v2.dylib.new screensaver.physarum_v2.dylib

for abi in arm64-v8a armeabi-v7a; do
  cmake -S . -B build-android-$abi -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" -DANDROID_ABI=$abi \
    -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static -DKODI_DEVKIT_INCLUDE="$DEVKIT" >/dev/null
  cmake --build build-android-$abi
done
"$STRIP" --strip-unneeded -o screensaver.physarum_v2.so build-android-arm64-v8a/screensaver.physarum_v2.so
"$STRIP" --strip-unneeded -o ../screensaver.physarum_v2.armv7/screensaver.physarum_v2.armv7.so \
  build-android-armeabi-v7a/screensaver.physarum_v2.so
