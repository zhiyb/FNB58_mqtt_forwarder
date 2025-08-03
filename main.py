#!/usr/bin/env python3
import os
import asyncio
import binascii
import traceback

from bleak import BleakClient
import paho.mqtt.client as mqtt

# Import configurations from file
if not os.path.isfile("config.py"):
    raise RuntimeError("Missing config.py file, please create from config_template.py")
from config import *

# Bluetooth address of your FNRISI FNB58 device
#FNB58_BLUETOOTH_ADDRESS = "98:DA:B0:0A:07:76"

# UUIDs for the characteristics
NOTIFY_CHAR_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"


def u16(b):
    return int.from_bytes(b, "little")

def u32(b):
    return int.from_bytes(b, "little")


class Dev:
    mqttc = None
    topic = None

    def __init__(self, mqttc):
        self.mqttc = mqttc

    def notification(self, sender, data):
        msgs = []   # MQTT messages
        while data:
            if data[0] != 0xaa:
                print(f"Corrupted header: {data[0]}")
                data = data[1:]
                continue

            typ = data[1]
            plen = data[2]
            if len(data) < 3 + plen + 1:
                print("Short read: {typ}, {plen}")
                continue

            pld = data[3:3+plen]
            cks = data[3+plen]
            seg = binascii.hexlify(pld, ' ').decode("utf-8")
            data = data[3+plen+1:]

            if typ == 0x03:
                if plen != 14:
                    print(f"Unexpected length: {seg}")
                    continue

                # Device information
                model = u16(pld[0:2])
                fw_ver = u16(pld[2:4])
                sn = u32(pld[4:8])
                boot_cnt = u32(pld[8:12])
                unknown0 = u16(pld[12:14])
                print(f"model = {model}, fw_ver = {fw_ver}, sn = {sn}, boot_cnt = {boot_cnt}, unknown0 = {unknown0}")

                self.topic = f"FNIRSI/FNB{model}_{sn}"
                msgs.append(("fw_version", f"{fw_ver}"))
                msgs.append(("boot", f"{boot_cnt}"))
                msgs.append(("unknown/3", f"{unknown0}"))

            elif typ == 0x04:
                if plen != 12:
                    print(f"Unexpected length: {seg}")
                    continue

                # Higher precision measurements
                volt = u32(pld[0:4]) / 10000.0
                amp = u32(pld[4:8]) / 10000.0
                power = u32(pld[8:12]) / 10000.0
                print(f"V = {volt}, I = {amp}, power = {power}")

                msgs.append(("voltage", f"{volt:.4f}"))
                msgs.append(("current", f"{amp:.4f}"))
                msgs.append(("power", f"{power:.4f}"))

            elif typ == 0x05:
                if plen != 7:
                    print(f"Unexpected length: {seg}")
                    continue

                # Cable resistance etc.
                res = u32(pld[0:4]) / 10000.0
                unknown0 = pld[5]   # probably temperature unit
                temp = u16(pld[5:7]) / 10.0
                print(f"res = {res}, T = {temp}, unknown0 = {unknown0}")

                msgs.append(("resistance", f"{res:.4f}"))
                msgs.append(("temperature", f"{temp:.1f}"))
                msgs.append(("unknown/5", f"{unknown0}"))

            elif typ == 0x06:
                if plen != 6:
                    print(f"Unexpected length: {seg}")
                    continue

                # D+/D- and protocol status
                dp = u16(pld[0:2]) / 1000.0
                dm = u16(pld[2:4]) / 1000.0
                unknown0 = u16(pld[4:6])
                print(f"D+ = {dp}, D- = {dm}, unknwon0 = {unknown0}")

                msgs.append(("dp_voltage", f"{dp:.3f}"))
                msgs.append(("dm_voltage", f"{dm:.3f}"))
                msgs.append(("unknown/6", f"{unknown0}"))

            elif typ == 0x07:
                if plen != 4:
                    print(f"Unexpected length: {seg}")
                    continue

                # Lower precision measurements
                volt = u16(pld[0:2])
                amp = u16(pld[2:4])
                print(f"V = {volt/1000.0}, I = {amp/1000.0}")

            elif typ == 0x08:
                if plen != 17:
                    print(f"Unexpected length: {seg}")
                    continue

                # Battery charging statistics
                group = pld[0]
                nrg = u32(pld[1:5]) / 100000.0
                cap = u32(pld[5:9]) / 100000.0
                t = u32(pld[9:13])
                t_s = t % 60
                t_m = (t // 60) % 60
                t_h = t // 3600
                rt = u32(pld[13:17])
                rt_s = rt % 60
                rt_m = (rt // 60) % 60
                rt_h = (rt // 3600) % 24
                rt_d = rt // 3600 // 24
                print(f"charging group {group}, NRG = {nrg}, CAP = {cap}, "
                      f"TIM = {t_h:02}:{t_m:02}:{t_s:02}, runtime = {rt_h:02}:{rt_m:02}:{rt_s:02}")

                msgs.append((f"battery/{group}/NRG", f"{nrg:.5f}"))
                msgs.append((f"battery/{group}/CAP", f"{cap:.5f}"))
                msgs.append((f"battery/{group}/time", f"{t}"))
                msgs.append(("runtime", f"{rt}"))

            else:
                print(f"Unknown type {typ}, plen {plen}: {seg}")

        if not self.topic:
            raise RuntimeError("Unknown device name")
        for topic, value in msgs:
            self.mqttc.publish(f"{self.topic}/{topic}", value, retain=False)


async def loop(mqttc):
    print(f"Connecting to device {FNB58_BLUETOOTH_ADDRESS}...")
    async with BleakClient(FNB58_BLUETOOTH_ADDRESS) as client:
        dev = Dev(mqttc)

        # Start receiving notifications
        await client.start_notify(NOTIFY_CHAR_UUID, dev.notification)

        # Send initial command \xaa\x81\x00\xf4
        command = bytearray([0xaa, 0x81, 0x00, 0xf4])
        await client.write_gatt_char(WRITE_CHAR_UUID, command)

        # Send second command \xaa8200a7 to start data streaming
        command = bytearray([0xaa, 0x82, 0x00, 0xa7])
        await client.write_gatt_char(WRITE_CHAR_UUID, command)

        # Keep connection open to receive streaming data
        while client.is_connected:
            await asyncio.sleep(1)
        # Disconnected
        return

        # Stop notifications when done
        command = bytearray([0xaa, 0x84, 0x00, 0x01])
        await client.write_gatt_char(WRITE_CHAR_UUID, command)
        await client.write_gatt_char(WRITE_CHAR_UUID, command)
        await client.stop_notify(NOTIFY_CHAR_UUID)
        await client.disconnect()


async def run(mqttc):
    while True:
        try:
            await loop(mqttc)
        except:
            traceback.print_exc()
        await asyncio.sleep(2)


mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
#mqttc.on_connect = on_connect
#mqttc.on_message = on_message

mqttc.username_pw_set(mqtt_user, mqtt_password)
mqttc.connect(mqtt_server, mqtt_port, 60)

mqttc.loop_start()

asyncio.run(run(mqttc))

mqttc.loop_stop()
