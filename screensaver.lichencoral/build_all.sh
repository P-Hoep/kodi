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
codesign --force --sign - build-uni/screensaver.lichencoral.dylib
# Replace, never overwrite in place: macOS caches a signed file's code signature by inode, and a
# running Kodi that dlopens a rewritten file is killed with "Code Signature Invalid".
cp build-uni/screensaver.lichencoral.dylib screensaver.lichencoral.dylib.new
mv -f screensaver.lichencoral.dylib.new screensaver.lichencoral.dylib

for abi in arm64-v8a armeabi-v7a; do
  cmake -S . -B build-android-$abi -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" -DANDROID_ABI=$abi \
    -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static -DKODI_DEVKIT_INCLUDE="$DEVKIT" >/dev/null
  cmake --build build-android-$abi
done
"$STRIP" --strip-unneeded -o screensaver.lichencoral.so build-android-arm64-v8a/screensaver.lichencoral.so
"$STRIP" --strip-unneeded -o ../screensaver.lichencoral.armv7/screensaver.lichencoral.armv7.so \
  build-android-armeabi-v7a/screensaver.lichencoral.so
