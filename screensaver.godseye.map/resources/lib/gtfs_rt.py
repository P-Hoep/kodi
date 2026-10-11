"""Minimal GTFS-realtime VehiclePositions decoder (protobuf wire format, no dependencies).

Only the fields a map needs are read:
  FeedMessage.entity(2) -> FeedEntity.vehicle(4) -> VehiclePosition
    .trip(1)     TripDescriptor.route_id(5)
    .position(2) Position.latitude(1) longitude(2) bearing(3) speed(5)  (float32)
    .timestamp(5)
    .vehicle(8)  VehicleDescriptor.id(1) label(2)
"""

import struct


def _varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def fields(buf):
    """Yield (field_number, wire_type, value) for one message."""
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            value = buf[i:i + 8]
            i += 8
        elif wire == 2:
            length, i = _varint(buf, i)
            value = buf[i:i + length]
            i += length
        elif wire == 5:
            value = buf[i:i + 4]
            i += 4
        else:
            raise ValueError('unsupported wire type %d' % wire)
        yield number, wire, value


def _float(value):
    return struct.unpack('<f', value)[0]


def _text(value):
    return bytes(value).decode('utf-8', 'replace')


def vehicle_positions(buf):
    """[{'id', 'label', 'route', 'lat', 'lon', 'bearing', 'speed', 'timestamp'}]"""
    buf = memoryview(buf)
    out = []
    for number, wire, entity in fields(buf):
        if number != 2 or wire != 2:
            continue
        for en, ew, vehicle in fields(entity):
            if en != 4 or ew != 2:
                continue
            v = {'id': None, 'label': None, 'route': None, 'lat': None, 'lon': None,
                 'bearing': None, 'speed': None, 'timestamp': None}
            for vn, vw, value in fields(vehicle):
                if vn == 1 and vw == 2:
                    for tn, tw, tv in fields(value):
                        if tn == 5 and tw == 2:
                            v['route'] = _text(tv)
                elif vn == 2 and vw == 2:
                    for pn, pw, pv in fields(value):
                        if pw != 5:
                            continue
                        if pn == 1:
                            v['lat'] = _float(pv)
                        elif pn == 2:
                            v['lon'] = _float(pv)
                        elif pn == 3:
                            v['bearing'] = _float(pv)
                        elif pn == 5:
                            v['speed'] = _float(pv)
                elif vn == 5 and vw == 0:
                    v['timestamp'] = value
                elif vn == 8 and vw == 2:
                    for dn, dw, dv in fields(value):
                        if dn == 1 and dw == 2:
                            v['id'] = _text(dv)
                        elif dn == 2 and dw == 2:
                            v['label'] = _text(dv)
            if v['lat'] is not None and v['lon'] is not None and (v['lat'] or v['lon']):
                out.append(v)
    return out
