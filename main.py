import asyncio
import binascii
from bleak import BleakClient

# Bluetooth address of your FNRISI FNB58 device
FNB58_BLUETOOTH_ADDRESS = "98:DA:B0:0A:07:76"

# UUIDs for the characteristics
NOTIFY_CHAR_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"

def u16(b):
    return int.from_bytes(b, "little")

def u32(b):
    return int.from_bytes(b, "little")

def process_frame(data):
    "Process data frames"
    #print(f"frame: {data}")
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
        #seg = binascii.hexlify(data[0:3+plen+1], ' ').decode("utf-8")
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

        elif typ == 0x04:
            if plen != 12:
                print(f"Unexpected length: {seg}")
                continue

            # Higher precision measurements
            volt = u32(pld[0:4])
            amp = u32(pld[4:8])
            power = u32(pld[8:12])
            print(f"V = {volt/10000.0}, I = {amp/10000.0}, power = {power/10000.0}")

        elif typ == 0x05:
            if plen != 7:
                print(f"Unexpected length: {seg}")
                continue

            # Device stats
            res = u32(pld[0:4])
            unknown0 = pld[5]   # probably temperature unit
            temp = u16(pld[5:7])
            print(f"res = {res/10000.0}, T = {temp/10.0}, unknown0 = {unknown0}")

        elif typ == 0x06:
            if plen != 6:
                print(f"Unexpected length: {seg}")
                continue

            # D+/D- and protocol status
            dp = u16(pld[0:2])
            dm = u16(pld[2:4])
            unknown0 = u16(pld[4:6])
            print(f"D+ = {dp/1000.0}, D- = {dm/1000.0}, unknwon0 = {unknown0}")

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

            # Charging statistics
            group = pld[0]
            nrg = u32(pld[1:5])
            cap = u32(pld[5:9])
            t = u32(pld[9:13])
            t_s = t % 60
            t_m = (t // 60) % 60
            t_h = t // 3600
            rt = u32(pld[13:17])
            rt_s = rt % 60
            rt_m = (rt // 60) % 60
            rt_h = (rt // 3600) % 24
            rt_d = rt // 3600 // 24
            print(f"stat group {group}, NRG = {nrg/100000.0}, CAP = {cap/100000.0}, "
                  f"TIM = {t_h:02}:{t_m:02}:{t_s:02}, runtime = {rt_h:02}:{rt_m:02}:{rt_s:02}")

        else:
            print(f"Unknown type {typ}, plen {plen}: {seg}")

def notification_handler(sender, data):
    """Notification handler to receive data from the device."""
    process_frame(data)

async def run():
    print("Voltage (V), Current (A)")  # Data header
    print("-------------------------")

    print(f"Connecting to device {FNB58_BLUETOOTH_ADDRESS}...")
    async with BleakClient(FNB58_BLUETOOTH_ADDRESS) as client:
        print(f"Connected: {client.is_connected}")

        # Start receiving notifications
        await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        print("Notifications enabled...")

        # Step 1: Send initial command \xaa\x81\x00\xf4
        command_1 = bytearray([0xaa, 0x81, 0x00, 0xf4])
        await client.write_gatt_char(WRITE_CHAR_UUID, command_1)

        # Step 2: Wait for the device's response
        await asyncio.sleep(2)

        # Step 3: Send second command \xaa8200a7 to start data streaming
        command_2 = bytearray([0xaa, 0x82, 0x00, 0xa7])
        await client.write_gatt_char(WRITE_CHAR_UUID, command_2)

        # Keep connection open to receive streaming data
        await asyncio.sleep(3)

        # Stop notifications when done
        command = bytearray([0xaa, 0x84, 0x00, 0x01])
        await client.write_gatt_char(WRITE_CHAR_UUID, command)
        await client.write_gatt_char(WRITE_CHAR_UUID, command)

        await client.stop_notify(NOTIFY_CHAR_UUID)

loop = asyncio.get_event_loop()
loop.run_until_complete(run())
