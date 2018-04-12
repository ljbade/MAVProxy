#!/usr/bin/env python
'''
support for connecting a Piksi Multi to Skylark
'''

import time, math
from pymavlink import mavutil
import requests
from collections import deque
from MAVProxy.modules.lib import mp_module
from MAVProxy.modules.lib.mp_settings import MPSettings
from sbp.navigation import SBP_MSG_POS_LLH, MsgPosLLH
from sbp.client.handler import Handler

SKYLARK_URL = "https://broker.skylark2.swiftnav.com"
BROKER_SBP_TYPE = 'application/vnd.swiftnav.broker.v1+sbp2'

DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_READ_TIMEOUT = 120
DEFAULT_TIMEOUT = (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)
MAX_CONNECT_RETRIES = 5
MAX_READ_RETRIES = 3
DEFAULT_RETRIES = (MAX_CONNECT_RETRIES, MAX_READ_RETRIES)
MAX_REDIRECTS = 0
DEFAULT_BACKOFF_FACTOR = 0.2

AP_MSEC_PER_SEC = 1000
AP_SEC_PER_WEEK = 7 * 86400
AP_MSEC_PER_WEEK = AP_SEC_PER_WEEK * AP_MSEC_PER_SEC

GPS_LEAPSECONDS_MILLIS = 18000
UNIX_OFFSET_MSEC = 17000 * 86400 + 52 * 10 * AP_MSEC_PER_WEEK - GPS_LEAPSECONDS_MILLIS

GPS_FIX_TYPE_NO_GPS = 0
GPS_FIX_TYPE_NO_FIX = 1
GPS_FIX_TYPE_2D_FIX = 2
GPS_FIX_TYPE_3D_FIX = 3
GPS_FIX_TYPE_DGPS = 4
GPS_FIX_TYPE_RTK_FLOAT = 5
GPS_FIX_TYPE_RTK_FIXED = 6
GPS_FIX_TYPE_STATIC = 7
GPS_FIX_TYPE_PPP = 8

def mav_status_to_sbp(status):
    if status == GPS_FIX_TYPE_NO_GPS:
        return 0
    elif status == GPS_FIX_TYPE_NO_FIX:
        return 0
    elif status == GPS_FIX_TYPE_2D_FIX:
        return 1
    elif status == GPS_FIX_TYPE_3D_FIX:
        return 1
    elif status == GPS_FIX_TYPE_DGPS:
        return 2
    elif status == GPS_FIX_TYPE_RTK_FLOAT:
        return 3
    elif status == GPS_FIX_TYPE_RTK_FIXED:
        return 4
    elif status == GPS_FIX_TYPE_STATIC:
        return 4
    elif status == GPS_FIX_TYPE_PPP:
        return 3
    else:
        return 0

def read_deque(deque_in):
    while True:
        deq

class SkylarkModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super(SkylarkModule, self).__init__(mpstate, "skylark", "Connect a Piksi Multi to Skylark")
        '''initialisation code'''
        self.skylark_settings = MPSettings([("url", str, SKYLARK_URL)])
        self.started = False
        self.put_r = None
        self.get_r = None
        self.positions = None
        self.add_command('skylark', self.cmd_skylark, "skylark control", ['start (DEVICEUUID)', 'stop', 'set (SKYLARKSETTING)'])

    def usage(self):
        '''show help on command line options'''
        return "Usage: skylark <start|stop|set>"

    def cmd_skylark(self, args):
        '''control behaviour of the module'''
        if len(args) == 0:
            print(self.usage())
        elif args[0] == "start":
            if len(args) == 2:
                self.start(args[1])
            else:
                print("Usage: skylark start (DEVICEUUID)")
        elif args[0] == "stop":
            self.stop()
        elif args[0] == "set":
            self.skylark_settings.command(args[1:])
        else:
            print(self.usage())

    def start(self, device_uuid):
        '''connect to Skylark'''
        self.positions = Handler._SBPQueueIterator(0)
        gen = (msg.pack() for msg in self.positions)

        # TODO add retries?

        put_headers = {
            'Device-Uid': device_uuid,
            'Content-Type': BROKER_SBP_TYPE
        }

        try:
            self.put_r = requests.put(
                self.skylark_settings.url,
                headers=put_headers,
                stream=True,
                timeout=DEFAULT_TIMEOUT,
                data=gen
            )
            self.put_r.raise_for_status()
        except Exception as e:
            print("Skylark: Upload connect failed: ", e)
            self.stop()
            return

        print "Upload connected"

        time.sleep(1)

        get_headers = {
            'Device-Uid': device_uuid,
            'Accept': BROKER_SBP_TYPE
        }

        try:
            import pdb; pdb.set_trace()
            self.get_r = requests.get(
                self.skylark_settings.url,
                headers=get_headers,
                stream=True,
                timeout=DEFAULT_TIMEOUT
            )
            self.get_r.raise_for_status()
        except Exception as e:
            print("Skylark: Download connect failed: ", e)
            self.stop()
            return

        print "Connected to Skylark"
        self.started = True

    def stop(self):
        '''disconnect from Skylark'''
        if self.put_r is not None:
            self.put_r.close()
        self.put_r = None
        if self.get_r is not None:
            self.get_r.close()
        self.get_r = None
        self.positions = None
        self.started = False
        print "Disconnected from Skylark"

    # copied from DGPS module
    def send_rtcm_msg(self, data):
        msglen = 180;

        if (len(data) > msglen * 4):
            print("DGPS: Message too large", len(data))
            return

        # How many messages will we send?
        msgs = 0
        if (len(data) % msglen == 0):
            msgs = len(data) / msglen
        else:
            msgs = (len(data) / msglen) + 1

        for a in range(0, msgs):

            flags = 0

            # Set the fragment flag if we're sending more than 1 packet.
            if (msgs) > 1:
                flags = 1

            # Set the ID of this fragment
            flags |= (a & 0x3) << 1

            # Set an overall sequence number
            flags |= (self.inject_seq_nr & 0x1f) << 3


            amount = min(len(data) - a * msglen, msglen)
            datachunk = data[a*msglen : a*msglen + amount]

            self.master.mav.gps_rtcm_data_send(
                flags,
                len(datachunk),
                bytearray(datachunk.ljust(180, '\0')))

        # Send a terminal 0-length message if we sent 2 or 3 exactly-full messages.
        if (msgs < 4) and (len(data) % msglen == 0) and (len(data) > msglen):
            flags = 1 | (msgs & 0x3)  << 1 | (self.inject_seq_nr & 0x1f) << 3
            self.master.mav.gps_rtcm_data_send(
                flags,
                0,
                bytearray("".ljust(180, '\0')))

        self.inject_seq_nr += 1

    def mavlink_packet(self, m):
        '''convert mavlink to sbp'''
        if not self.started:
            return

        if m.get_type() == 'GPS_RAW_INT':
            print m
            msg = MsgPosLLH(
                tow=((m.time_usec / 1000) - UNIX_OFFSET_MSEC) % AP_MSEC_PER_WEEK,
                lat=m.lat / 1e7,
                lon=m.lon / 1e7,
                height=m.alt / 1000,
                h_accuracy=0,
                v_accuracy=0,
                n_sats=m.satellites_visible,
                flags=mav_status_to_sbp(m.fix_type)
            )
            self.positions(msg)
            try:
                self.put_r.iter_content()
            except Exception as e:
                print("Skylark: Upload failed: ", e)
                self.stop()

    def idle_task(self):
        '''called in idle time'''
        if not self.started:
            return

        try:
            data = self.get_r.iter_content()
        except Exception as e:
            print("Skylark: Download failed: ", e)
            self.stop()
            return

        try:
            self.send_rtcm_msg(data)
        except Exception as e:
            print("Skylark: GPS inject failed: ", e)
            self.stop()

def init(mpstate):
    '''initialise module'''
    return SkylarkModule(mpstate)
