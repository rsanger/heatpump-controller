# Copyright (c) 2017 Richard Sanger
#
# Licensed under MIT
#
# A simple flask based web interface for controlling a heatpump and receiving
# current state using IR.
# 
# 
# * /api/set accepts a JSON object that can be posted with the settings to change
#   and 'apply' indicating this state should be sent to the heatpump. This
#   returns the previous state and the new state.
# * /api/status returns the current state
# 
# * Also handles IR messages received, if the remote is used to control the heat
#   pump the internal state will be updated with the new state information so
#   it is not overwritten the next time we send a message.

from flask import Flask, request, jsonify, abort
from heatpump import HeatPump
import sys
import os
import threading
import select
import json
import struct
try:
   import urllib2
except:
   import urllib.request as urllib2
try:
   import cPickle as pickle
except:
   import pickle

class default_config:
    LIRC_PATH = "/dev/lirc0"
    SAVE_STATE_PATH = None  # If set save current state and load when reloaded

app = Flask(__name__)
app.config.from_object(default_config)

try:
    app.config.from_envvar('SERVER_SETTINGS')
except:
    pass


PULSE_BIT = 0x01000000
PULSE_MASK = 0x00FFFFFF

f = os.open(app.config['LIRC_PATH'], os.O_RDWR)
assert f > 0


def decode(values):
    cur = None
    try:
        cur = HeatPump.decode(values)
    except:
        return
    # Send an update back to ourself
    req = urllib2.Request("http://localhost/api/update")
    req.add_header('Content-Type', 'application/json')
    try:
        response = urllib2.urlopen(req, json.dumps({'data': cur}))
        _ = json.load(response)
    except:
        pass


def receiver():
    global f
    grabbed = []
    while True:
        s_res = select.select([f], [], [], 0.1)
        if len(s_res[0]) and s_res[0][0] == f:
            # Have data
            bytes = os.read(f, 4)
            assert len(bytes) == 4
            as_int = struct.unpack('i', bytes)[0]
            as_int = as_int & PULSE_MASK
            if as_int > 1000000:
                continue
            grabbed.append(as_int)
            if len(grabbed) == 583:
                decode(grabbed)

                grabbed = []
        else:  # timeout
            if len(grabbed) >= 291:
                decode(grabbed)
            grabbed = []

t = threading.Thread(target=receiver)
t.daemon = True
t.start()

try:
    with open(app.config['SAVE_STATE_PATH'], 'rb') as fstate:
        pump = pickle.load(fstate)
except:
    pump = HeatPump()


def save_state():
    if app.config['SAVE_STATE_PATH']:
        try:
            with open(app.config['SAVE_STATE_PATH'], 'wb') as fstate:
                pickle.dump(pump, fstate)
        except:
            pass


def program_heatpump():
    """ Send current state as IR message """
    global f
    global pump
    request = pump.encode()
    written = os.write(f, request)
    save_state()
    assert len(request) == written


@app.route('/')
def hello_world():
    return 'Hello, World!'


@app.route('/api/update', methods=['POST'])
def update():
    if not request.json or 'data' not in request.json:
        abort(400)
    previous_state = pump.get_json_state()
    pump.load_bytes(request.json['data'])
    save_state()
    return jsonify({})


@app.route('/api/set', methods=['POST'])
def set():
    if not request.json or not 'apply' in request.json:
        abort(400)
    data = request.json
    previous_state = pump.get_json_state()
    if 'on' in data:
        pump.on = bool(data['on'])
    if 'hvac_mode' in data:
        pump.hvac_mode = data['hvac_mode']
    if 'temp' in data:
        if isinstance(data['temp'], list):
            if data['temp'][0] == '+':
                pump.set_temperature(pump.temp+data['temp'][1])
            else:
                assert data['temp'][0] == '-'
                pump.set_temperature(pump.temp-data['temp'][1])
        else:
            pump.set_temperature(data['temp'])
    if 'wide_vane' in data:
        pump.wide_vane = data['wide_vane']
    if 'fan_speed' in data:
        pump.set_fan(data['fan_speed'])
    if 'vane' in data:
        pump.vane = data['vane']
    if 'clock' in data:
        pump.clock = data['clock']
    if 'end_time' in data:
        pump.end_time = data['end_time']
    if 'start_time' in data:
        pump.end_time = data['start_time']
    if 'prog' in data:
        pump.end_time = data['prog']
    if 'econo_cool' in data:
        pump.end_time = bool(data['econo_cool'])
    if 'long_mode' in data:
        pump.end_time = bool(data['long_mode'])
    if 'apply' in data:
        if data['apply']:
            program_heatpump()
    return jsonify({"prev": previous_state, "new": pump.get_json_state()})


@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(pump.get_json_state())
