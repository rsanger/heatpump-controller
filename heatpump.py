# Copyright (c) 2017 Richard Sanger
#
# Licensed under MIT
# 
# Handles the LIRC encode and decode of Mitsubishi heat pump IR protocol
# and maintain the current state. I.e. decodes and encodes to and from /dev/lircX/
#
# Based on the protocol decode work by analysir:
# https://www.analysir.com/blog/2015/01/06/reverse-engineering-mitsubishi-ac-infrared-protocol/
# https://github.com/r45635/HVAC-IR-Control
# 
# However, modified for the MSZ-GA60VA which has some minor differences/feature set.
# 
# decode() takes input read from /dev/lircX in MODE2 mode.
# encode() creates bytes to send to /dev/lircX in PULSE mode.
# 
# All timings are in microseconds, like lirc uses.


import struct
import time

HVAC_MISTSUBISHI_HDR_MARK   = 3400
HVAC_MISTSUBISHI_HDR_SPACE  = 1750
HVAC_MISTSUBISHI_BIT_MARK   = 450
HVAC_MISTSUBISHI_ONE_SPACE  = 1300
HVAC_MISTSUBISHI_ZERO_SPACE = 420
HVAC_MISTSUBISHI_RPT_MARK   = 440
HVAC_MISTSUBISHI_RPT_SPACE  = 17100


class HeatPump(object):
    # We don't have the MSZ-FD25
    on = False # The on/off status
    isee = False # MSZ-FD25 only
    hvac_mode = "auto" # string of auto/heat/dry/cool
    temp = 20 # A value between 16 and 31
    wide_vane = "middle" # string of "leftend/left/middle/right/rightend/sides/swing"
    fan_speed = 0 # An integer from 0 to 3, 0 is auto 1 - 3 are power levels 3 being highest
    vane = "auto" # A string of upend/up/middle/down/downend/swing/auto
    clock = "auto" # Time since midnight in 10 minute increments cannot exceed 143
                  # or auto to fill in the current time
    read_clock = None # Rather than overwriting time when read in, we store that here
    end_time = 0 # Time to end in 10 mins
    start_time = 0 # Time to start in 10 mins
    prog = "none" # Which programmed timers are enabled? A string of none/start/end/startend
    econo_cool = False # Economy cool
    clean_mode = False # Clean mode MSZ-FD25 only
    plasma = False # What is plasma? MSZ-FD25 only
    #install = "none" # Install position string of none/left/mid/right MSZ-FD25 only
    long_mode = False # Long mode
    """
    Note: When either long mode or econo cool are set vane is set to auto
          Only one of long mode and econo cool can be set at a time.
          When decoding these conditions are check strictly. When encoding
          if both are set long mode takes priority, and vane is always set to auto.
    """


    def to_bytes(self):
        """ Return the current instance state as a list of 18 integers,
            representing the 18 byte code """
        ret = []
        # The first 5 bytes (0-4) are constants
        ret.append(0x23)
        ret.append(0xCB)
        ret.append(0x26)
        ret.append(0x01)
        ret.append(0x00)
        # BYTE 5 Next ON/OFF
        ret.append(0x20 if self.on else 0x0)
        # BYTE 6 HVAC MODE and isee
        hvac = {"auto": 0x20, "heat": 0x08, "dry": 0x10, "cold": 0x18}[self.hvac_mode]
        ret.append((0x40 if self.isee else 0x0) | hvac)
        # BYTE 7 Temperature
        assert self.temp >= 16 and self.temp <= 31
        ret.append(self.temp-16)
        # BYTE 8 HVAC MODE round 2 and WIDE VANE
        # Difference auto is a 0x06 not 0x00 as listed
        hvac = {"auto": 0x06, "heat": 0x00, "dry": 0x2, "cold": 0x06}[self.hvac_mode]
        # For ours swing is 0xC0 and sides are 0x80
        wide_vane = {"leftend": 0x10, "left": 0x20, "middle": 0x30, "right": 0x40, "rightend": 0x50, "sides": 0x80, "swing": 0xC0}[self.wide_vane]
        ret.append(hvac|wide_vane)
        # BYTE 9 FAN/VANE(TODO)
        fan_speed = self.fan_speed
        assert fan_speed >= 0 and fan_speed <= 3
        # This is inconsistent on the remote sometimes the top bit is set
        # then change another setting and it is unset when looped to the
        # same state. The top bit seems to be set when to represent auto
        # vane, but also auto fan it is odd.
        # I'm assuming that it truly maps to the vane setting
        # Does not match with docs 100%
        vane = {"upend": 0x48, "up": 0x50, "middle": 0x58, "down": 0x60, "downend": 0x68, "swing": 0x78, "auto": 0x40}[self.vane]
        # Cannot have vane set in econo mode
        if (self.econo_cool and self.hvac_mode == "cool") or self.long_mode:
            vane = 0x40
        ret.append(fan_speed|vane)
        # BYTE 10 CLOCK
        if self.clock == "auto":
            t = time.localtime()
            ret.append(t.tm_hour*6+t.tm_min//10)
        else:
            assert self.clock >=0 and self.clock <= 143
            ret.append(self.clock)
        # BYTE 11 END TIME
        # TODO how do you set midnight? all zeros is listed as not set?
        assert self.end_time >=0 and self.end_time <= 143
        ret.append(self.end_time)
        # BYTE 12 START TIME
        assert self.start_time >=0 and self.start_time <= 143
        ret.append(self.start_time)
        # BYTE 13 TIMER + (AREA mode TODO)
        prog = {"none": 0x0, "start": 0x5, "end": 0x3, "startend": 0x7}
        ret.append(0x00)
        # BYTE 14 econo cool/clean mode
        econo = 0x20 if self.econo_cool and self.hvac_mode == "cool" and not self.long_mode else 0
        clean = 0x04 if self.clean_mode else 0
        ret.append(econo|clean)

        # BYTE 15 constant XXX We don't have this feature
        #install = {"none": 0x00, "left": 0x08, "mid": 0x10, "right": 0x18}[self.install]
        long_mode = 0x10 if self.long_mode else 0x00
        plasma = 0x04 if self.plasma else 0x00
        ret.append(long_mode|plasma)

        # BYTE 16 constant XXX We don't have this feature
        ret.append(0x00)
        # BYTE 17 CHECKSUM
        # Sum and truncate
        # Sample [0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x08, 0x05, 0x30, 0x45, 0x54,0x00,0x00,0x00,0x00,0x00,0x00] = 0x0b
        ret.append(sum(ret) & 0xFF)
        return ret

    def encode(self, req_bytes=None):
        """ Takes a sequence of 18 bytes and encodes these into pulses, ready for
            writing to /dev/lircX. The message is repeats twice.
            req_bytes: If supplied an 18 int list representing the bytes of the 
                       message to encode, otherwise if None uses the current
                       state of the instance.
        """
        ret = [] # A list of ints representing pulse, space, should be odd :)
        if req_bytes is None:
            req_bytes = self.to_bytes()
        assert len(req_bytes) == 18

        # HEADER
        ret.append(HVAC_MISTSUBISHI_HDR_MARK)
        ret.append(HVAC_MISTSUBISHI_HDR_SPACE)
        # Add bits
        for byte in req_bytes:
            for shift in range(8):
                mask = 0x1<<shift
                ret.append(HVAC_MISTSUBISHI_BIT_MARK)
                if (mask&byte) == 0:
                    ret.append(HVAC_MISTSUBISHI_ZERO_SPACE)
                else:
                    ret.append(HVAC_MISTSUBISHI_ONE_SPACE)
        # Finish
        ret.append(HVAC_MISTSUBISHI_RPT_MARK)
        ret.append(HVAC_MISTSUBISHI_RPT_SPACE)
        ret.append(HVAC_MISTSUBISHI_HDR_MARK)
        ret.append(HVAC_MISTSUBISHI_HDR_SPACE)
        for byte in req_bytes:
            for shift in range(8):
                mask = 0x1<<shift
                ret.append(HVAC_MISTSUBISHI_BIT_MARK)
                if (mask&byte) == 0:
                    ret.append(HVAC_MISTSUBISHI_ZERO_SPACE)
                else:
                    ret.append(HVAC_MISTSUBISHI_ONE_SPACE)
        ret.append(HVAC_MISTSUBISHI_RPT_MARK)

        assert len(ret) % 2 == 1

        return struct.pack('I'*len(ret), *ret)

    def do_pack(self, values):
        """ Packs a list of integers into C integers ready for /dev/lircX """
        return struct.pack('I'*len(values), *values)

    @staticmethod
    def _decode_bits(values, tol=300):
        """ Decodes the pulses of a 18 byte message and returns the bytes.

            values: A list of pulse space pauses of the bits. Should not include
                    the header or trailing repeat mark. Should be 288 integers.
            tol: The timing tolerance, defaults to 300us
            return: A list of integers representing the 18 bytes of protocol
                    Will raise an exception if invalid data is found, including AssertionError
        """
        assert len(values) == 288
        offset = 0
        mask = 1
        ret = []
        for x in range(18*8):
            if x % 8 == 0:
                if x != 0:
                    ret.append(value)
                value = 0
                mask = 1
            else:
                mask <<= 1
            assert abs(HVAC_MISTSUBISHI_BIT_MARK - values[offset]) < tol
            offset += 1
            if abs(HVAC_MISTSUBISHI_ZERO_SPACE - values[offset]) < tol:
                pass
            elif abs(HVAC_MISTSUBISHI_ONE_SPACE - values[offset]) < tol:
                value |= mask
            else:
                raise Exception("Bad value")
            offset += 1
        ret.append(value)
        assert len(ret) == 18
        # Check the checksum
        if sum(ret[0:17]) & 0xFF != ret[17]:
            raise Exception("Invalid checksum")
        return ret

    @staticmethod
    def decode(values, tol=300):
        """ Accepts a series of pulses+space timings as a list (from /dev/lircX)
            values: A list of timings, should be an odd number and at least 291
                     in length, representing a single header.
            tol: The timing tolerance, keeping it high seems to work best

            return: A list of integers representing the 18 bytes of protocol
                    Will raise an exception if invalid data is found, including AssertionError
        """
        # Check header
        if len(values) == 583:
            # Header1 + data1 + repeat pulse + space + Header2 + data2 + repeat pulse
            assert abs(HVAC_MISTSUBISHI_RPT_SPACE - values[291]) < tol*2
            mesg1 = None
            mesg2 = None
            try:
                mesg1 = HeatPump.decode(values[0:291], tol)
            except:
                pass
            try:
                mesg2 = HeatPump.decode(values[292:583], tol)
            except:
                pass 

            if mesg1 is not None and mesg2 is None:
                return mesg1
            elif mesg1 is None and mesg2 is not None:
                return mesg2
            elif mesg1 is not None and mesg2 is not None:
                assert tuple(mesg1) == tuple(mesg2)
                return mesg1
            else:
                raise Exception("No valid codes found")
        elif len(values) == 291:
            # Header + data + repeat pulse
            assert abs(HVAC_MISTSUBISHI_HDR_MARK - values[0]) < tol*2
            assert abs(HVAC_MISTSUBISHI_HDR_SPACE - values[1]) < tol*2
            assert abs(HVAC_MISTSUBISHI_RPT_MARK - values[290]) < tol*2
            return HeatPump._decode_bits(values[2:290])
        elif len(values) >= 291:
            # Try find a header pulse
            for i in range(len(values)-290):
                if abs(HVAC_MISTSUBISHI_HDR_MARK - values[i]) < tol*2:
                    try:
                        return HeatPump.decode(values[i:i+291], tol)
                    except:
                        pass
            raise Exception("Could not find valid starting pulse")
        else:
            raise Exception("Incorrect list size")

    def load_bytes(self, values):
        """ Loads the byte sequence into the current instance state.

            values: A list of integers representing the 18 bytes of protocol
            return: Nothing. Will raise exception if invalid data is found.
        """
        # The first 5 bytes (0-4) are constants
        assert values[0] == 0x23
        assert values[1] == 0xCB
        assert values[2] == 0x26
        assert values[3] == 0x01
        assert values[4] == 0x00

        # BYTE 5 - ON or OFF
        if values[5] == 0x20:
            self.on = True
        elif values[5] == 0x00:
            self.on = False
        else:
            raise Exception("Unexpected value for byte 5")

        # BYTE 6 - HVAC MODE/ I-SEE
        assert 0x78 & values[6] == values[6]
        self.isee = True if values[6] & 0x40 else False
        self.hvac_mode = {0x20: "auto", 0x08: "heat", 0x10: "dry", 0x18: "cold"}[values[6]&0x38]

        # BYTE 7 - TEMPERATURE
        assert 0x0f & values[7] == values[7]
        self.temp = values[7]+16

        # BYTE 8 HVAC MODE
        assert 0xf7 & values[8] == values[8]
        self.wide_vane = {0x10: "leftend", 0x20: "left", 0x30: "middle", 0x40: "right", 0x50: "rightend", 0x80: "sides", 0xC0: "swing"}[values[8]&0xF0]
        assert self.hvac_mode in {0x00: ("heat",), 0x2: ("dry",), 0x06: ("cold", "auto")}[values[8]&0x07]

        # BYTE 9
        fan_speed = values[9] & 0x07
        assert fan_speed >= 0 and fan_speed <= 3
        self.fan_speed = fan_speed
        # This is inconsistent on the remote sometimes the top bit is set
        # then change another setting and it is unset when looped to the
        # same state. The top bit seems to be set when to represent auto
        # vane, but also auto fan it is odd.
        # I'm assuming that it truly maps to the vane setting
        # Does not match with docs 100% , auto seems to be all zeros
        vane = {0x48: "upend", 0x50: "up", 0x58: "middle", 0x60: "down", 0x68: "downend", 0x78: "swing", 0x00: "auto", 0x40: "auto"}[values[9]&0x78]
        self.vane = vane

        # BYTE 10 TIME
        assert values[10] >= 0 and values[10] <= 143
        self.read_clock = values[10]

        # BYTE 11 END TIME
        assert values[11] >= 0 and values[11] <= 143
        self.end_time = values[11]

        # BYTE 12 START TIME
        assert values[12] >= 0 and values[12] <= 143
        self.start_time = values[12]

        # BYTE 13 TIMER Programmed?
        self.prog = {0x0: "none", 0x5: "start", 0x3: "end", 0x7: "startend"}[values[13]]

        # BYTE 14
        assert values[14] & 0x24 == values[14]
        self.econo_cool = True if values[14] & 0x20 else False
        self.clean_mode = True if values[14] & 0x04 else False
        if self.econo_cool:
            assert self.hvac_mode == "cool"
            assert self.vane == "auto"
        # Byte 15 plasma and install
        assert values[15] & 0x1C == values[15]
        self.plasma = True if values[15] & 0x04 else False
        #self.install =  {0x00: "none", 0x08: "left", 0x10: "mid", 0x18: "right"}[values[15]&0x18]
        self.long_mode = True if values[15] & 0x10 else False

        # Byte 16 all zero 17 already checked
        assert values[16] == 0

    @staticmethod
    def format_time(value):
        """ Converts the AC time to a human readable 24 hour time """
        if value is None:
            return ""
        if value == "auto":
            return value
        assert value >= 0 and value <= 143
        return str(value // 6) + ":" + str((value%6)*10)

    def __str__(self):
        ret = "Heat Pump on: " + str(self.on)
        ret += "\tMode: " + str(self.hvac_mode)
        ret += "\tTemp: " + str(self.temp)
        ret += "\tWide Vane: " + str(self.wide_vane)
        if self.fan_speed == 0:
            ret += "\tFan Speed: auto"
        else:
            ret += "\tFan Speed: " + str(self.fan_speed)
        ret += "\tVane: " + str(self.vane)
        ret += "\tTime: " + self.format_time(self.clock) + "[" + self.format_time(self.read_clock) + "]"
        ret += "\tStart Time: " + self.format_time(self.start_time)
        ret += "\tEnd Time: " + self.format_time(self.end_time)
        ret += "\tTimers Set: " + self.prog
        modes = []
        if self.econo_cool:
            modes.append("Econo Cool")
        if self.clean_mode:
            modes.append("Clean Mode")
        if self.plasma:
            modes.append("Plasma")
        if self.long_mode:
            modes.append("Long Mode")
        if self.isee:
            modes.append("I-See")
        ret += "\tModes: [" + ",".join(modes) + "]"
        #if self.install != "none":
        #    ret += "\tInstall Location: " + self.install
        return ret

    def __repr__(self):
        return str(self)

    def get_json_state(self):
        return {
            "on": self.on,
            #"isee": self.isee,
            "hvac_mode": self.hvac_mode,
            "temp": self.temp,
            "wide_vane": self.wide_vane,
            "fan_speed": self.fan_speed,
            "vane": self.vane,
            "clock": self.clock,
            "read_clock": self.read_clock,
            "end_time": self.end_time,
            "start_time": self.start_time,
            "prog": self.prog,
            "econo_cool": self.econo_cool,
            #"clean_mode": self.clean_mode,
            #"plasma": self.plasma,
            "long_mode": self.long_mode
        }

    def set_temperature(self, temp):
        """ The temperature target in C
            Range limited from 16-31, if set higher or lower it set to the closest
        """
        temp = int(temp)
        if temp > 31:
            temp = 31
        if temp < 16:
            temp = 16
        self.temp = temp

    def set_fan(self, fan):
        """ Set the fan to a value 0-3 or "auto". 0 is "auto" """
        if fan == "auto":
            self.fan_speed = 0
        else:
            assert fan >= 0 and fan <= 3
            self.fan_speed = fan

