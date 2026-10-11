"""Drive a local Kodi for testing: install (symlink), run, send keys, screenshot.

  python3 tools/kodi.py install     # symlink the add-on into Kodi, rescan, enable
  python3 tools/kodi.py select      # make it Kodi's screensaver (prints the previous one)
  python3 tools/kodi.py run         # start the screensaver now
  python3 tools/kodi.py set zoom=3 basemap=4 layer_clouds=true   # change its settings
  python3 tools/kodi.py action Left # send a Kodi action (Left, Right, Select, Back, ContextMenu, Rewind...)
  python3 tools/kodi.py shot out.png
  python3 tools/kodi.py log         # tail Kodi's log for this add-on

Uses JSON-RPC on TCP 9090 and the EventServer on UDP 9777 (both on by default for local apps).
"""

import json
import os
import socket
import struct
import sys
import time

ADDON_ID = 'screensaver.godseye.map'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
if sys.platform == 'darwin':
    KODI_HOME = os.path.expanduser('~/Library/Application Support/Kodi')
else:
    KODI_HOME = os.path.expanduser('~/.kodi')


def rpc(method, params=None, timeout=10):
    s = socket.create_connection(('127.0.0.1', 9090), timeout=timeout)
    msg = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        msg['params'] = params
    s.sendall(json.dumps(msg).encode())
    buf = b''
    while True:
        buf += s.recv(65536)
        try:
            reply = json.loads(buf.decode())
        except ValueError:
            continue
        if isinstance(reply, dict) and reply.get('id') == 1:
            s.close()
            return reply
        buf = b''  # a notification; wait for our reply


def builtin(command):
    """Run a Kodi builtin through the EventServer (what kodi-send --action does)."""
    payload = struct.pack('!B', 1) + command.encode() + b'\0'  # ACTION_EXECBUILTIN
    header = b'XBMC' + struct.pack('!BBHIIHIII', 2, 0, 0x0A, 1, 1, len(payload), 0, int(time.time()), 0)
    header += b'\0' * (32 - len(header))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(header + payload, ('127.0.0.1', 9777))
    sock.close()


def install():
    target = os.path.join(KODI_HOME, 'addons', ADDON_ID)
    if os.path.islink(target):
        os.remove(target)
    elif os.path.exists(target):
        sys.exit('%s exists and is not a symlink; remove it first' % target)
    os.symlink(SRC, target)
    builtin('UpdateLocalAddons')
    time.sleep(3)
    print(rpc('Addons.SetAddonEnabled', {'addonid': ADDON_ID, 'enabled': True}))
    print(rpc('Addons.GetAddonDetails', {'addonid': ADDON_ID, 'properties': ['enabled', 'version']}))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'help'
    if cmd == 'install':
        install()
    elif cmd == 'select':
        before = rpc('Settings.GetSettingValue', {'setting': 'screensaver.mode'}).get('result', {}).get('value')
        print('previous screensaver:', before)
        print(rpc('Settings.SetSettingValue', {'setting': 'screensaver.mode', 'value': ADDON_ID}))
    elif cmd == 'set':
        builtin('RunScript(%s,%s)' % (os.path.join(HERE, 'kodi_set.py'), ','.join(sys.argv[2:])))
        time.sleep(1.5)
    elif cmd == 'run':
        builtin('ActivateScreensaver')
    elif cmd == 'action':
        for name in sys.argv[2:]:
            print(name, rpc('Input.ExecuteAction', {'action': name.lower()}).get('result'))
            time.sleep(0.4)
    elif cmd == 'builtin':
        builtin(sys.argv[2])
    elif cmd == 'shot':
        out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else 'kodi.png')
        if os.path.exists(out):
            os.remove(out)
        builtin('TakeScreenshot(%s,sync)' % out)
        for _ in range(20):
            time.sleep(0.25)
            if os.path.exists(out):
                break
        print(out if os.path.exists(out) else 'no screenshot')
    elif cmd == 'log':
        path = os.path.expanduser('~/Library/Logs/kodi.log') if sys.platform == 'darwin' \
            else os.path.join(KODI_HOME, 'temp', 'kodi.log')
        lines = open(path, errors='replace').read().splitlines()
        hits = [l for l in lines if ADDON_ID in l or 'Traceback' in l or 'Error' in l and 'python' in l.lower()]
        print('\n'.join(hits[-int(sys.argv[2]) if len(sys.argv) > 2 else -40:]))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
