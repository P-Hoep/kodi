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
| **192.168.1.78** | `48:78:5e:42:d6:da` | AFTKA: Fire TV Stick 4K Max (2nd gen) | Fire OS 7.7.1.3 / Android 9 | 21.3 | ✅ authorized | ✅ v0.2.0 | ✅ v0.1.0 + centre lat/lon settings, updated 2026-10-11, active screensaver | ✅ v0.1.0 (Algebra 2 build), installed 2026-10-11; previewed from the TV, not the active screensaver |
| **192.168.1.15** | `2c:71:ff:8c:40:bd` | AFTMM: Fire TV Stick 4K (1st gen) | Fire OS 6.7.1.1 / Android 7.1.2 | 21.2 | ✅ authorized | ✅ v0.2.0, installed 2026-10-10, replaced `screensaver.rsxs.lorenz` | ⚠️ v0.1.0, installed 2026-10-11, active screensaver (was God's Eye); centre lat/lon update pending, the stick was offline | ⚠️ v0.1.0 first build (classic sets only), installed 2026-10-11; update pending, the stick was offline |
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
| `adb` hangs | `adb kill-server && adb start-server`, then reconnect each stick. |
| Screensaver never starts | `screensaver.mode` not set, add-on disabled, or something is playing (Kodi doesn't run screensavers during playback by default). |
