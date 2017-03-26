# Copyright (c) 2017 Richard Sanger
#
# Licensed under MIT
#
# A simple debugging script to record and decode mode2 messages LIRC
# and decodes them

import os
import struct
import select
from heatpump import HeatPump

PULSE_BIT = 0x01000000
PULSE_MASK = 0x00FFFFFF

f = os.open("/dev/lirc0", os.O_RDONLY)
assert f > 0
grabbed = []
wait_pulse = True

last = None
cur = None

def decode(values):
        global cur
        global last
        hp = HeatPump()
        last = cur
        try:
                print(len(values))
                cur = HeatPump.decode(values)
        except:
                return
        print("Done it!!!!!!!!!")
        print(cur)
        try:
                hp.load_bytes(cur)
        except Exception as e:
                print(e)
                print("Failed decode")
        print(str(hp))

while True:
        s_res = select.select([f], [], [], 0.1)
        if len(s_res[0]) and s_res[0][0] == f:
                # Have data
                bytes = os.read(f, 4)
                assert len(bytes) == 4
                as_int = struct.unpack('i', bytes)[0]
                as_int = as_int & PULSE_MASK
                if as_int > 1000000:
                        print("biff")
                        continue
                #print(as_int, len(grabbed))
                grabbed.append(as_int)
                if len(grabbed) == 583:
                        print("good good")
                        decode(grabbed)
                        grabbed = []
        else: # timeout
                if len(grabbed) >= 291:
                        decode(grabbed)
                grabbed = []
