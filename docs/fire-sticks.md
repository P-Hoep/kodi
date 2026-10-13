# Fire TV Sticks: adb connection reference

How to find, connect to and deploy Kodi add-ons to the Fire TV Sticks on the
home network. Last updated **2026-10-11**.

---

## Devices

Home LAN: `192.168.1.0/24`, gateway `192.168.1.1`. The Mac was `192.168.1.29`
at the time. IPs come from DHCP and can change, so the **MAC address** is the
reliable identifier. Consider DHCP reservations on the router.

| IP | MAC | Model | Fire OS / Android | Kodi | adb | God's Eye Map | God's World Map | Math Clock |
|---|---|---|---|---|---|---|---|---|
| **192.168.1.78** | `48:78:5e:42:d6:da` | AFTKA: Fire TV Stick 4K Max (2nd gen) | Fire OS 7.7.1.3 / Android 9 | 21.3 | ✅ authorized | ✅ v0.2.1 (TomTom key entered in its settings 2026-10-12) | ✅ v0.1.0 + centre lat/lon settings, updated 2026-10-11; alternates with God's Eye by day via Screensaver Switcher (installed 2026-10-12) | ✅ v0.1.0 (Algebra 2 build), installed 2026-10-11; previewed from the TV, not the active screensaver |
| **192.168.1.15** | `2c:71:ff:8c:40:bd` | AFTMM: Fire TV Stick 4K (1st gen) | Fire OS 6.7.1.1 / Android 7.1.2 | 21.2 | ✅ authorized | ⚠️ v0.2.0, installed 2026-10-10, replaced `screensaver.rsxs.lorenz`; v0.2.1 pending: it has the built-in TomTom key, and after updating, the key must be entered in its settings | ⚠️ v0.1.0, installed 2026-10-11, active screensaver (was God's Eye); centre lat/lon update pending, the stick was offline | ⚠️ v0.1.0 first build (classic sets only), installed 2026-10-11; update pending, the stick was offline |
| **192.168.1.128** | `60:6d:3c:23:10:df` | unknown (Fire TV, by its adb port) | ? | ? | ❌ **unauthorized**: approve the prompt on its TV | not installed | not installed | not installed |
| 192.168.1.254 | `bc:5f:f4:1d:d0:3f` | probably the ISP gateway (also has 8080 open) | - | - | goes offline at once | n/a, ignore | n/a | n/a |

Notes:
- **.15** also has Kodi repositories `repository.jenrepo` and
  `repository.universalscrapers`. Kodi 21 logs errors about their old schema at
  startup. That's harmless and unrelated to the screensaver.
- Both sticks already had `script.module.certifi`, the screensaver's only
  non-built-in dependency.
- Kodi's JSON-RPC TCP port 9090 was on by default on both sticks.

---

## Turning on adb on a new stick

1. **Settings → My Fire TV → About** and click the device name **7 times** until
   "You are now a developer" appears.
2. **Settings → My Fire TV → Developer options → ADB debugging → On**. Fire OS 6
   sticks also have **Apps from Unknown Sources**. Turn that on if you'll
   install Kodi itself by sideloading.
3. From the Mac, run `adb connect <ip>:5555`. The TV shows **"Allow USB
   debugging?"**. Tick **Always allow from this computer** and press **OK**.
   Until that is done, `adb devices` lists the stick as `unauthorized`.

Don't run a loop that disconnects and reconnects while waiting. Each reconnect
dismisses the prompt and shows a new one. Connect once, then just poll `adb devices`.

The Mac's adb key is `~/.android/adbkey`. If it is ever regenerated, every stick
has to be approved again.

---

## Finding sticks on the network

```bash
# adb (5555) and Kodi web/JSON-RPC (8080/9090) ports across the LAN
nmap -Pn -n -p 5555,8080,9090 --open -T4 192.168.1.0/24 -oG - | grep Ports:

# MAC addresses of everything seen recently
arp -an | grep -v incomplete

# try each candidate, then see which answered
adb connect 192.168.1.<n>:5555
adb devices -l      # "device" = ok, "unauthorized" = approve on TV, "offline" = not a stick / gone

# identify a connected device
adb -s <ip>:5555 shell 'getprop ro.product.manufacturer; getprop ro.product.model; \
  getprop ro.build.version.name; pm list packages | grep -i kodi'
```

Amazon model codes: `AFTKA` = 4K Max (2nd gen), `AFTMM` = 4K (1st gen),
`AFTSS` = HD (2020), `AFTKM` = 4K (2nd gen), `AFTKRT` = 4K Max (1st gen).

macOS has no `timeout` command. Use `perl -e 'alarm 10; exec @ARGV' <cmd>` or a
background kill if a connect hangs.

---

## Before touching Kodi: is someone watching?

**Always check this before stopping or restarting Kodi on a stick.** Someone
may be watching TV on it.

```bash
export ANDROID_SERIAL=192.168.1.15:5555
adb shell pidof org.xbmc.kodi                                   # empty = Kodi not running
adb shell dumpsys activity activities | grep -m1 mResumedActivity # what's on screen
adb shell dumpsys media_session | grep -E "package=|state=PlaybackState"
adb shell cat /proc/uptime                                       # seconds since boot
```

- `state=3` is "playing". Compare its `updated=` value (ms since boot) with
  `/proc/uptime`. A YouTube session last updated days ago is stale and can be
  ignored.
- If Kodi is running, also ask Kodi directly (see JSON-RPC below):
  `Player.GetActivePlayers` must return `[]`.
- If anything is genuinely playing, wait.

---

## Kodi on the sticks

| What | Path |
|---|---|
| Kodi package | `org.xbmc.kodi` |
| Kodi home (`special://home`) | `/sdcard/Android/data/org.xbmc.kodi/files/.kodi/` |
| Add-ons | `…/.kodi/addons/` |
| Add-on settings + tile cache | `…/.kodi/userdata/addon_data/screensaver.godseye.map/` |
| Log | `…/.kodi/temp/kodi.log` |

Useful commands:

```bash
K=/sdcard/Android/data/org.xbmc.kodi/files/.kodi
adb shell am force-stop org.xbmc.kodi                                  # quit Kodi (check first!)
adb shell monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1 # start Kodi
adb pull $K/temp/kodi.log stick.log && grep -a -i godseye stick.log    # log
adb exec-out screencap -p > screen.png                                 # screenshot (works on Kodi too)
```

### JSON-RPC over adb

Kodi listens for JSON-RPC on TCP 9090 on the stick. Forward a local port to it
(use a different local port per stick):

```bash
adb -s 192.168.1.15:5555 forward tcp:9092 tcp:9090
adb -s 192.168.1.15:5555 forward --remove tcp:9092   # when done
```

A minimal client (save as `rpc.py`):

```python
import json, socket, sys

def rpc(method, params=None, port=9092):
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    msg = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        msg['params'] = params
    s.sendall(json.dumps(msg).encode())
    buf = b''
    while True:                      # skip notifications until our reply arrives
        chunk = s.recv(65536)
        if not chunk:
            raise SystemExit('closed')
        buf += chunk
        try:
            r = json.loads(buf.decode())
        except ValueError:
            continue
        if r.get('id') == 1:
            return r
        buf = b''

if __name__ == '__main__':
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 9092
    print(rpc(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else None, port))
```

```bash
python3 rpc.py Player.GetActivePlayers
python3 rpc.py Application.GetProperties '{"properties":["version"]}'
python3 rpc.py Settings.GetSettingValue '{"setting":"screensaver.mode"}'
python3 rpc.py XBMC.GetInfoBooleans '{"booleans":["System.ScreenSaverActive"]}'
```

---

## Deploying God's Eye Map to a stick

From the repo root, with the stick checked as idle (see above):

```bash
export ANDROID_SERIAL=192.168.1.15:5555
K=/sdcard/Android/data/org.xbmc.kodi/files/.kodi
find screensaver.godseye.map -name __pycache__ -prune -exec rm -rf {} +

# 1. copy the add-on while Kodi is closed
adb shell am force-stop org.xbmc.kodi
adb shell rm -rf $K/addons/screensaver.godseye.map
adb push screensaver.godseye.map $K/addons/

# 2. start Kodi and connect JSON-RPC (Kodi takes ~10-20 s to answer)
adb shell monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1
adb forward tcp:9092 tcp:9090

# 3. first install only: enable it and make it the screensaver
python3 rpc.py Addons.SetAddonEnabled '{"addonid":"screensaver.godseye.map","enabled":true}'
python3 rpc.py Settings.GetSettingValue '{"setting":"screensaver.mode"}'      # note the old one
python3 rpc.py Settings.SetSettingValue '{"setting":"screensaver.mode","value":"screensaver.godseye.map"}'

# 4. verify: wait for the idle timeout (screensaver.time, 3 min on .15), then
python3 rpc.py XBMC.GetInfoBooleans '{"booleans":["System.ScreenSaverActive"]}'
adb exec-out screencap -p > screen.png
adb pull $K/temp/kodi.log && grep -a -iE "godseye|Traceback" kodi.log | tail

adb forward --remove tcp:9092
```

Notes:
- **Updating** an existing install only needs step 1 plus a Kodi restart.
  Settings live in `addon_data` and survive. Python code is reloaded every time
  the screensaver starts, so if Kodi can't be restarted, the new code still
  takes effect on the next screensaver run. Only `addon.xml`, `settings.xml`
  and `strings.po` need a restart.
- A freshly copied add-on is **disabled** until `Addons.SetAddonEnabled`.
- If a stick lacks `script.module.certifi`, install the zip through the Kodi UI
  instead (see the screensaver doc), which pulls dependencies automatically.
- To check that a stick runs the same build as the repo:
  ```bash
  f=resources/lib/screensaver.py
  md5 -q screensaver.godseye.map/$f
  adb shell md5sum $K/addons/screensaver.godseye.map/$f
  ```

### Deploying God's World Map

The same steps with `screensaver.godsworld.map` in place of `screensaver.godseye.map`
(both add-ons can be installed side by side; `screensaver.mode` picks one). Notes:

- It needs no extra dependencies beyond `script.module.certifi`.
- The first time each projection is shown, a stick spends 15-40 s building its lookup
  table (cached in `addon_data/screensaver.godsworld.map/lut`); later scenes are prepared
  in the background while the current one is on screen.
- Measured 2026-10-11 on .78 (4K Max): about 0.6 s per spinning-globe frame, 3-5 s per
  full-screen flat map, Kodi process 40-55 % of a core on a still scene. The log prints a
  CPU summary once a minute (`last minute: Kodi process CPU ...`).
- `adb exec-out screencap` does not wake the screensaver (Kodi's own TakeScreenshot via
  the EventServer, as `tools/kodi.py shot` uses on the Mac, does).

### Deploying Math Clock

The same steps with `screensaver.math.clock`. It has no dependencies at all. Notes:

- Kodi refuses `Addons.ExecuteAddon` for a screensaver add-on, so to see it without
  waiting for the idle timeout use **Settings → Interface → Screensaver → Preview** on
  the TV.
- An older, unrelated `screensaver.mathclock` (2024, v1.0.0) is installed in the Mac's
  Kodi; the new add-on's id is different so both can coexist.

### Deploying Couchstronomy

The same steps with `screensaver.couchstronomy`. It needs only `script.module.certifi`.
Notes:

- Installed on **.78** and **.15** 2026-10-11 (v0.1.0). On 2026-10-12 it is .78's saved
  screensaver; .15 runs Kodi 21.2, keeps Math Clock, and has not run it yet (it was asleep
  with adb offline).
- The Milky Way layer was removed 2026-10-12 (it looked glitchy on the TV). Only the
  ground mask is left under the stars.
- v0.1.2 (2026-10-12, adds Fred Espenak's Messier photos) is on .78; v0.1.1 came before it. Kodi keeps an add-on's strings in memory until the
  version changes or Kodi restarts. After v0.1.0's settings were renumbered in place, the
  stick showed shifted labels ("Show the Milky Way", "2"). When settings change, bump the
  version, then quit and relaunch Kodi.
- Measured on .78 (4K Max), without the Milky Way: ready 1.3 s after the screensaver
  starts (6.4-6.7 s with it); each star frame takes 330-610 ms, depending on how many
  objects are in view, and is redrawn every 4.1 s at a 60° field. The Kodi process uses
  33-87 % of a core; the high end comes with many objects and satellites in view, and was
  the same before the removal. The log prints
  `last minute: ... star frames, ... ms each` once a minute.
- The stick sleeps about 4 minutes after the last key press, so a key sent over adb
  to stop the screensaver can put it to sleep before Kodi's 3-minute timer starts
  the screensaver again. Bring Kodi back with
  `adb shell monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1`.
- To test at night by day, put a time offset in
  `addon_data/screensaver.couchstronomy/settings.xml` while Kodi is closed, e.g.
  `<settings version="2"><setting id="time_offset">8</setting></settings>`, and delete
  the file afterwards.

**Settings are only saved when Kodi exits cleanly.** `am force-stop` discards anything
changed since the last clean exit, including `screensaver.mode` set over JSON-RPC (that
is how .78 lost God's World Map as its screensaver: guisettings.xml still said Math
Clock). After changing settings, quit with `python3 rpc.py Application.Quit` rather than
`force-stop`, then relaunch.

### Deploying Screensaver Switcher

`service.screensaver.switcher` is a service add-on, not a screensaver: it sets
`screensaver.mode` on a schedule. No dependencies. Steps as above (copy while Kodi is
closed, start Kodi, `Addons.SetAddonEnabled`), then **quit with `Application.Quit` and
relaunch once**: Kodi loads an add-on's strings only at start-up, so the settings show
blank labels until then.

- Installed on **.78** 2026-10-12 (v0.1.0). Schedule: window 1, 07:30-19:00, God's Eye Map
  alternating with God's World Map every 5 minutes (changed from 30 the same day; God's
  Eye at :00, :10, :20..., God's World at :05, :15...); window 2, 19:00-07:30,
  Couchstronomy; no default. Not on .15 yet. After each swap God's World takes about 17 s
  on .78 to show its first scene (6 s to load the world, then the first frame).
- The schedule can be written as `addon_data/service.screensaver.switcher/settings.xml`
  while Kodi is closed, e.g.
  `<settings version="2"><setting id="w1_on">true</setting><setting id="w1_start">07:30</setting>...</settings>`
  (ids in `resources/lib/config.py`).
- Since the service owns `screensaver.mode`, set a different screensaver through the
  schedule; a hand-picked one is replaced at the next switch (at most 5 minutes with the current schedule).
- `Addons.ExecuteAddon {"addonid":"service.screensaver.switcher","params":["preview"]}`
  starts the screensaver over JSON-RPC (Kodi refuses that for screensaver add-ons
  themselves); `"params":["apply"]` applies the schedule now.
- Tested on .78: with a screensaver running, each switch wakes it and starts the new one
  within 1-2 s (`adb exec-out screencap` confirmed God's Eye -> Math Clock -> God's Eye,
  and God's World -> God's Eye at a 30-minute alternation).
- Waking God's Eye Map can keep a JSON-RPC `Input.ExecuteAction` call from answering for
  over 10 s while it shuts down (seen on the Mac and on .78). The screensaver still closes;
  the switcher just waits for it.
- Remove: `Addons.SetAddonEnabled` false, or with Kodi closed
  `rm -rf $K/addons/service.screensaver.switcher $K/userdata/addon_data/service.screensaver.switcher`.

### Deploying SkyWatch

The same steps with `screensaver.skywatch`. It needs only `script.module.certifi`, and it also
has a background service (`service.py`) that warms data before the screensaver starts.
Notes:

- Installed on **.78** 2026-10-12 (v1.0.0). Location was written before the first start as
  `addon_data/screensaver.skywatch/settings.xml` (`lat`, `lon`, `location_name`,
  `nws_email`), the same home point as God's Eye. Set as `screensaver.mode` over JSON-RPC
  for testing. The Screensaver Switcher still owns that setting and will put its own
  schedule back at the next switch; add SkyWatch to a switcher window to keep it.
- Kodi on Android reports `System.Platform.Linux.RaspberryPi` as true, so the profile
  check now tests `System.Platform.Android` first: sticks get the Balanced profile (radar
  frames 960x540, up to 36 frames). The log line `built N controls ... (profile ...)`
  shows which one ran.
- Measured on .78 (4K Max): 1454 controls built in 0.56 s, splash 2.5-4.6 s, Kodi process
  about 220 MB resident; 35-100 % of a core once the frames are cached, up to 155 % for
  the first minute while about 90 frames download and decode.
- Interactive mode reopens SkyWatch as a script window when it is woken; Kodi otherwise
  kills a Python screensaver 5 s after a key press.

### Loading splash (all four screensavers)

Since 2026-10-12 (God's Eye 0.2.2, God's World 0.1.1, Math Clock 0.1.1, Couchstronomy
0.1.3) each screensaver opens on its own art on black, with pulsing dots, instead of a line
of loading text. It fades out once the first real frame is up: at least 2.5 s, at most
25 s (God's Eye), 60 s (God's World), 15 s (Math Clock) or 30 s (Couchstronomy). The log
says `splash: shown for N s`. Measured on .78:

- God's Eye with cached tiles, Math Clock: the 2.5 s minimum. Kodi loads the art image
  asynchronously, so the first ~1 s on the stick is black with just the dots.
- Couchstronomy: about 3 s, and Kodi takes about 1 s to open its window before that.
- God's World: 12 s for an already-built projection. A projection's first run builds its
  lookup table and can take over 30 s.

Installed on **.78** 2026-10-12; **.15 still pending** (offline). Updating .15 also brings
God's Eye 0.2.1+, whose TomTom key must then be entered in its settings.

### Reverting a stick

```bash
python3 rpc.py Settings.SetSettingValue '{"setting":"screensaver.mode","value":"screensaver.rsxs.lorenz"}'  # .15's original
python3 rpc.py Addons.SetAddonEnabled '{"addonid":"screensaver.godseye.map","enabled":false}'
# or remove it entirely (Kodi closed):
adb shell rm -rf $K/addons/screensaver.godseye.map $K/userdata/addon_data/screensaver.godseye.map
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `unauthorized` | Approve the prompt on the TV. If the prompt is gone, `adb disconnect <ip>:5555` then `adb connect` once. |
| `offline` | Stick asleep or rebooting: wake it with the remote, or `adb disconnect` + `connect`. |
| `failed to connect` / connection refused | ADB debugging got turned off (Fire OS updates sometimes do this), or the IP changed. Rescan. |
| `failed to authenticate` on connect | Normal on first contact; it means the prompt is showing. |
| JSON-RPC connection refused | Kodi not running yet, or the forward is missing. Check `adb forward --list`. |
| "Could not connect to repository" right after installing `repository.phoep`; log shows `CRepository: failed read 'https://p-hoep.github.io/kodi/addons.xml.md5'` | Seen on .78 on 2026-10-12. The site and repo config were fine: the same file loaded from a Mac, and over plain HTTP from a local copy. Restarting Kodi (`am force-stop` + launch) cleared it. If it persists after a restart, stop Kodi, delete the `repository.phoep` rows from `repo` and `addonlinkrepo` in `userdata/Database/Addons33.db`, and start Kodi again to force a fresh fetch. |
| `adb` hangs | `adb kill-server && adb start-server`, then reconnect each stick. |
| Screensaver never starts | `screensaver.mode` not set, add-on disabled, or something is playing (Kodi doesn't run screensavers during playback by default). |
