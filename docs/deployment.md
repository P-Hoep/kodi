# Deployment guide

How an add-on gets from this repository onto a TV: build it, package it, publish the Kodi
repository, install it, and verify it. This guide covers the Python add-ons and the native
OpenGL add-ons, the local test loop, GitHub Pages, and Fire TV / Android sideloading.

For how to write and test the add-ons themselves, see
[development.md](development.md). For the per-add-on design notes, see the add-on sections in
the [README](../README.md) and the files in this `docs/` folder.

---

## 1. How delivery works

Everything is published as one Kodi repository, **P-Hoep Add-ons**, served by GitHub Pages at
**https://p-hoep.github.io/kodi/**. Kodi adds that URL as a file source, installs
`repository.phoep-<version>.zip`, and from then on checks the repository for new versions and
updates installed add-ons itself.

The pipeline has three pieces:

| Piece | File | What it does |
|---|---|---|
| Zip builder | `tools/build_zip.py` | Packages one add-on folder as `dist/<id>-<version>.zip` |
| Repository builder | `tools/make_repo.py` | Packages every top-level add-on folder, writes `addons.xml`, `.md5`, `.sha256` files, assets and the repository zip |
| CI | `.github/workflows/kodi-repo.yml` | Runs `make_repo.py --out _site` on every push to `main` and deploys `_site` to GitHub Pages |

A top-level folder is an add-on if it contains `addon.xml`. There is no list to maintain: a new
folder with a valid `addon.xml` is picked up automatically.

The generated repository looks like this:

```
addons.xml                 the index Kodi polls
addons.xml.md5             its checksum
<id>/<id>-<version>.zip    one zip per add-on
<id>/<id>-<version>.zip.sha256
<id>/icon.png, fanart.jpg  the assets named in addon.xml
repository.phoep-<version>.zip
index.html
.nojekyll                  stops GitHub Pages running Jekyll
```

`dist/` and `_site/` are build output and are gitignored. Do not edit them by hand.

---

## 2. One-time setup

### On the publishing side

1. Push the repository to GitHub.
2. Open **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
   The workflow cannot deploy without this.
3. Make sure Actions are enabled. The workflow asks for `pages: write` and `id-token: write`,
   so no extra secrets are needed.
4. Confirm that `repository.phoep/addon.xml` exists and that its `dir` entries point at the
   Pages URL:

   ```xml
   <info compressed="false">https://p-hoep.github.io/kodi/addons.xml</info>
   <checksum>https://p-hoep.github.io/kodi/addons.xml.md5</checksum>
   <datadir zip="true">https://p-hoep.github.io/kodi/</datadir>
   <hashes>sha256</hashes>
   ```

   If the repository moves to another URL, update this file and bump its version.

### On the development machine

- Python 3.9 or newer (the tools use only the standard library).
- Kodi installed and running, with **JSON-RPC** (TCP 9090) and the **EventServer** (UDP 9777)
  enabled. Both are on by default for local applications.
- For native add-ons: CMake, a C/C++ toolchain, GLFW for the test window, and the Android NDK
  and Kodi dev-kit headers described in section 7.

---

## 3. Build one add-on

```bash
cd /Users/patrickhoepner/Documents/GitHub/kodi

python3 tools/build_zip.py screensaver.jeopkodi
# -> dist/screensaver.jeopkodi-1.1.0.zip
```

- The version comes from `version="..."` in the add-on's `addon.xml`; the output name is always
  `dist/<id>-<version>.zip`.
- With no argument the tool builds `screensaver.godseye.map`.
- For a native add-on, `build_zip.py` packages the library that is already in the folder. It
  does **not** compile anything.
- `build_zip.py` leaves `src/`, `tests/`, `build*` folders, `CMakeLists.txt` and `README.md`
  out of a native add-on's zip. It ships the built library, `addon.xml`, settings, resources
  and licence files.

Use this zip for a one-off install (**Install from zip file**) or for a quick local test.

---

## 4. Build and preview the repository locally

```bash
python3 tools/make_repo.py                 # -> dist/repo (deleted and rebuilt)
cd dist/repo && python3 -m http.server 8000
```

Browse **http://localhost:8000/** to see the index, or add that URL to Kodi as a file source
(`http://<your-computer-ip>:8000` from another device on the LAN).

Two warnings:

- `make_repo.py` deletes and recreates its output directory. Never point `--out` at anything
  you need to keep.
- The repository build stops with an error if any file named in an add-on's `<assets>` block is
  missing. It is safer to fail than to publish an add-on with a broken icon.

### Which add-ons are included

`make_repo.py` includes every top-level folder with an `addon.xml`, with one rule for native
add-ons:

> If the add-on declares `library_osx`, `library_android`, `library_linux` or
> `library_windows`, at least one of the declared library files must exist in the folder.
> Otherwise the add-on is skipped **silently**.

The check is `any`, not `all`: an add-on that declares both a macOS `.dylib` and an Android
`.so` is published even if only one of them exists. Check the `addons.xml` and the zip
contents when a platform-specific build seems missing.

There is no separate 32-bit attribute. A 32-bit Android build is a separate add-on with its own
id (`<base-id>.armv7`) and its own `addon.xml`; see section 7.

---

## 5. Publish a release

### Checklist

1. **Test locally** (section 3 or 6). For native code, also run the harness and `ctest`.
2. **Bump the version** in every changed add-on's `addon.xml`:

   ```xml
   <addon id="screensaver.jeopkodi" name="Jeopkodi" version="1.1.0" ...>
   ```

   Without a bump, Kodi sees no update. A native add-on and its `.armv7` companion are
   separate add-ons with separate versions; bump each one that changed.
3. **Publish the built libraries** for native add-ons: copy the new `.dylib` / `.so` into the
   add-on folder and commit it (section 7).
4. **Check the metadata**: every path in `<assets>` exists, and `addon.xml` still parses.
5. **Build the repository locally** and inspect it:

   ```bash
   python3 tools/make_repo.py
   grep '<addon id="screensaver.jeopkodi"' dist/repo/addons.xml
   ls dist/repo/screensaver.jeopkodi/
   ```

   The version in `addons.xml` must be the new one.
6. **Commit and push to `main`**:

   ```bash
   git add -A
   git commit -m "Jeopkodi 1.1.0: <what changed>"
   git push origin main
   ```

   The workflow runs `make_repo.py --out _site` and deploys it. You can also run it by hand
   with **Actions → Kodi repository → Run workflow**, or `gh workflow run kodi-repo.yml`.
7. **Verify the live repository**:

   ```bash
   curl -s https://p-hoep.github.io/kodi/addons.xml | grep 'screensaver.jeopkodi'
   curl -I https://p-hoep.github.io/kodi/screensaver.jeopkodi/screensaver.jeopkodi-1.1.0.zip
   ```

8. **Bump the repository add-on** only when the repository URL or metadata changes, not for
   every add-on release. Installed copies of `repository.phoep` only update themselves when
   `repository.phoep/addon.xml`'s version changes.

### Rolling back

Kodi always installs the newest version in `addons.xml`. To roll back an add-on, publish a new
version number that contains the older code (for example `1.1.1` with the previous behaviour).
Deleting a zip from the site does not downgrade installed copies; Kodi keeps what it has until
a newer version appears.

---

## 6. Install on a Kodi device

### From the published repository

1. **Settings → System → Add-ons → Unknown sources → On.**
2. **Settings → File manager → Add source →** `https://p-hoep.github.io/kodi/`, named `phoep`.
3. **Settings → Add-ons → Install from zip file → phoep →**
   `repository.phoep-<version>.zip`.
4. **Settings → Add-ons → Install from repository → P-Hoep Add-ons.** Screensavers are under
   **Look and feel → Screensaver**; the apps under **Program add-ons**; the Switcher under
   **Services**; Audioshelf under **Music add-ons**; the Physarum visualisation under
   **Music → Visualisation** (inside Kodi's player settings).
5. To choose a screensaver: **Settings → Interface → Screensaver → Screensaver mode**, then
   open **Settings** below it to configure it. **Preview** starts it immediately.

Kodi installs dependency modules such as `script.module.certifi` from its official repository
by itself.

### From a local zip

1. Serve `dist/` on the LAN: `cd dist && python3 -m http.server 8000`.
2. In Kodi: **Settings → File manager → Add source →** `http://<your-computer-ip>:8000`.
3. **Settings → System → Add-ons → Unknown sources → On.**
4. **Settings → Add-ons → Install from zip file →** the source → the zip.

### From a development symlink (no packaging)

The fastest loop while editing Python:

```bash
export KODI_ADDON=screensaver.jeopkodi
python3 tools/kodi.py install       # symlink into Kodi and enable
python3 tools/kodi.py select        # make it Kodi's screensaver
python3 tools/kodi.py run           # start it now
python3 tools/kodi.py set language=1
python3 tools/kodi.py action Left   # send a remote action
python3 tools/kodi.py shot /tmp/shot.png
python3 tools/kodi.py log           # tail the log for this add-on
```

`install` refuses to replace a real directory; remove an existing non-symlink first.
`tools/kodi.py` talks to JSON-RPC on port 9090 and the EventServer on UDP 9777, so Kodi must be
running and both must be enabled.

Restart Kodi after changing `addon.xml`, `settings.xml` or `strings.po`. Kodi caches an add-on's
strings, so labels show blank or shift until it reloads them.

---

## 7. Native add-ons: build and deploy per platform

The native add-ons draw with OpenGL / OpenGL ES (not WebGL). Their source lives in
`screensaver.sandclock.gl` (Sand Clock, Liquid Clock, Cellular Automata, Physarum, Tetris AI),
`screensaver.infworld.gl` (Endless World) and `screensaver.plant.gl` (Growing Plant). The
Kodi-facing folders at the top level contain `addon.xml`, resources AND the built library.

### What each add-on needs

| Add-on | macOS | Android 64-bit | Android 32-bit |
|---|---|---|---|
| `screensaver.sandclock.gl` | `.dylib` | `.so` | separate `.armv7` add-on |
| `screensaver.tetris.gl` | `.dylib` | `.so` | separate `.armv7` add-on |
| `screensaver.infworld.gl` | `.dylib` | `.so` | separate `.armv7` add-on |
| `screensaver.plant.gl` | `.dylib` | `.so` | separate `.armv7` add-on |
| `visualization.physarum.lite` | `.dylib` | `.so` | separate `.armv7` add-on |

Some GL add-ons exist **only** as 32-bit Android companions in this repository
(`screensaver.automata.armv7`, `screensaver.automata.lite.armv7`,
`screensaver.automata3d.armv7`, `screensaver.liquidclock.armv7`,
`screensaver.physarum.armv7`, `screensaver.physarum.lite.armv7`). Their `addon.xml` declares
`library_android` only, so they work on 32-bit Android Kodi and not on macOS or 64-bit Android.

The library filename must match the name declared in `addon.xml` exactly:

```bash
grep -n 'library_' screensaver.tetris.gl/addon.xml
# library_osx="screensaver.tetris.gl.dylib" library_android="screensaver.tetris.gl.so"
```

### Build commands

The full commands for each project are in its own README:

- [screensaver.sandclock.gl/README.md](../screensaver.sandclock.gl/README.md): Sand Clock,
  Liquid Clock, Cellular Automata / Lite / 3D, Physarum / Lite, Physarum Visualisation, Tetris AI
- [screensaver.infworld.gl/README.md](../screensaver.infworld.gl/README.md): Endless World
- [screensaver.plant.gl/README.md](../screensaver.plant.gl/README.md): Growing Plant

The shape of every build:

```bash
# macOS universal (Intel + Apple Silicon)
cmake -S . -B build-macos -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
cmake --build build-macos
# copy build-macos/<id>.dylib into the add-on folder

# Android 64-bit
cmake -S . -B build-android \
  -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
cmake --build build-android

# Android 32-bit (for the .armv7 companion)
cmake -S . -B build-android32 ... -DANDROID_ABI=armeabi-v7a ...
```

On a Homebrew NDK install `$ANDROID_NDK_HOME` is often unset. Point
`-DCMAKE_TOOLCHAIN_FILE` directly at the toolchain file, which may live inside a `.app`
bundle, for example
`/opt/homebrew/Caskroom/android-ndk/30/AndroidNDK16248370.app/Contents/NDK/build/cmake/android.toolchain.cmake`.
See [development.md](development.md) for the full prerequisites.

After building, copy the library into the correct add-on folder at the top level, then check:

```bash
file screensaver.tetris.gl/screensaver.tetris.gl.dylib
# Mach-O universal binary with 2 architectures: x86_64 arm64

file screensaver.tetris.gl/screensaver.tetris.gl.so
# ELF 64-bit LSB ... ARM aarch64

file screensaver.tetris.gl.armv7/screensaver.tetris.gl.armv7.so
# ELF 32-bit LSB ... ARM, EABI5
```

Commit the rebuilt library together with the code. `tools/make_repo.py` packages the file that
is in the folder; it never compiles.

### 32-bit and 64-bit are separate add-ons

Kodi on many Fire TV models, many Google TV boxes and the Chromecast with Google TV is a 32-bit
application. It cannot load an arm64 `.so`, and a 64-bit Kodi cannot load an armeabi-v7a `.so`.
That is why each native project has two add-on ids:

- `screensaver.tetris.gl` — macOS and 64-bit Android
- `screensaver.tetris.gl.armv7` — 32-bit Android

The 32-bit add-on's `addon.xml` names the same screensaver differently ("Tetris AI (OpenGL,
32-bit Android)") so users can tell them apart. Do not merge them into one zip: Kodi picks by
id, not by the architecture it finds inside.

---

## 8. Fire TV / Android sideload

Use this when testing a build before publishing, or when a device cannot reach the Pages site.
The full procedure is in [fire-sticks.md](fire-sticks.md); the short version below uses
`rpc.py`, the minimal JSON-RPC client whose source is in that document (it defaults to local
port 9092, matching the `adb forward`):

```bash
# Find the stick and connect
adb connect 192.168.1.78:5555
adb devices -l

export ANDROID_SERIAL=192.168.1.78:5555
K=/sdcard/Android/data/org.xbmc.kodi/files/.kodi

# 1. Copy the add-on while Kodi is closed
find screensaver.jeopkodi -name __pycache__ -prune -exec rm -rf {} +
adb shell am force-stop org.xbmc.kodi
adb shell rm -rf $K/addons/screensaver.jeopkodi
adb push screensaver.jeopkodi $K/addons/

# 2. Start Kodi and forward JSON-RPC
adb shell monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1
adb forward tcp:9092 tcp:9090

# 3. Enable it (first install only)
python3 rpc.py Addons.SetAddonEnabled \
  '{"addonid":"screensaver.jeopkodi","enabled":true}'

# 4. Verify
adb exec-out screencap -p > screen.png
adb pull $K/temp/kodi.log && grep -a -iE 'jeopkodi|Traceback' kodi.log | tail
adb forward --remove tcp:9092
```

Rules that prevent lost work:

- **Never `am force-stop` after changing settings.** Kodi writes settings on a clean exit. Use
  `Application.Quit` through JSON-RPC, then relaunch.
- Only a first install needs `Addons.SetAddonEnabled`; an update reuses `addon_data`.
- A change to `addon.xml`, `settings.xml` or `strings.po` needs a Kodi restart; ordinary Python
  edits are picked up on the next start of the add-on.
- `adb exec-out screencap` does not wake a sleeping screensaver. Kodi's own `TakeScreenshot`
  (what `tools/kodi.py shot` uses) keeps a running one rendering; screen recording does not.
- On a 32-bit stick, install the `.armv7` build of a native add-on. The 64-bit library fails
  with "is 64-bit instead of 32-bit".

To revert: set `screensaver.mode` back to its previous value, disable the add-on, or remove the
add-on folder and its `addon_data` while Kodi is closed.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A native add-on is missing from `addons.xml` | No declared library file exists, so `make_repo.py` skipped it silently | `grep -n 'library_' <id>/addon.xml`; put the built library at the add-on root; rebuild |
| The add-on installs but Kodi cannot load its library | Wrong architecture, or the other platform's library was never built | `file <id>/*.so`; use the `.armv7` add-on on 32-bit Kodi |
| `make_repo.py` exits: `repository.phoep/addon.xml is missing` | The repository add-on folder was moved or renamed | Restore `repository.phoep/addon.xml` |
| `make_repo.py` exits: `<id>: asset <file> is missing` | `<assets>` names a file that is not in the add-on folder | Add the file or fix `addon.xml` |
| Kodi sees no update after a push | The add-on version was not bumped, or Kodi has not rechecked | Compare `curl -s .../addons.xml` with the installed version; bump and push; check for updates |
| Pages returns 404 | Pages source is not **GitHub Actions**, or the deploy failed | Check Settings → Pages and the Actions log; `curl -I https://p-hoep.github.io/kodi/addons.xml` |
| `tools/kodi.py` hangs or refuses connections | Kodi is not running, or JSON-RPC / EventServer are disabled | Start Kodi; `nc -z 127.0.0.1 9090`; enable remote control from local applications |
| `shot`, `run` or `set` does nothing but JSON-RPC works | The EventServer (UDP 9777) is not reachable | Enable it in Kodi; retry |
| Settings labels are blank or shifted | `strings.po` / `settings.xml` changed and Kodi cached the old strings | Bump the version, quit Kodi cleanly, relaunch |
| `adb` says unauthorized or offline | The stick slept, its IP changed, or debugging was turned off | `adb devices -l`; reconnect; rescan the LAN for port 5555 |
| Kodi reports a failed read of `addons.xml.md5` | Stale repository cache | Restart Kodi; if it persists, delete the `repository.phoep` rows from `Addons33.db` while Kodi is closed |

---

## 10. Release checklist (copy this into the pull request)

- [ ] The change is tested locally (unit tests and/or the add-on in Kodi).
- [ ] Native libraries are rebuilt, copied into their add-on folders and committed.
- [ ] `version="..."` is bumped in every changed `addon.xml` (base and `.armv7` separately).
- [ ] Every `<assets>` file exists.
- [ ] `python3 tools/make_repo.py` succeeds and `dist/repo/addons.xml` shows the new versions.
- [ ] The change is committed and pushed to `main`.
- [ ] The Actions run is green and the live `addons.xml` shows the new version.
- [ ] The README and the add-on's own documentation describe the new behaviour.
