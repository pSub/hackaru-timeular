"""
A simple linkage between a Timular cube and Hackaru.
"""

import asyncio
from datetime import datetime

import requests
import yaml
from bleak import BleakClient

MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
MANUFACTURER_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
SOFTWARE_REVISION_UUID = "00002a28-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
ORIENTATION_UUID = "c7e70012-c847-11e6-8175-8c89a55d403c"

CURRENT_TASK = None


def now():
    """Returns the current time as a formatted string"""
    return datetime.utcnow().strftime('%a %B %d %Y %H:%M:%S')


def headers():
    """Returns the authenticated headers for Hackaru"""
    return {
        "cookie": f"auth_token_id={config['authid']}; auth_token_raw={config['authtoken']}",
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest"
    }


def callback(sender: int, # pylint: disable=unused-argument
             data: bytearray):
    """Callback for orientation changes of the Timeular cube"""
    assert len(data) == 1
    orientation = data[0]
    print(f"Orientation: {orientation}")

    if orientation not in range(1, 9):
        stop_current_task()
        return

    stop_current_task()
    task = get_task(orientation)
    start_task(**task)


def get_task(orientation: int):
    """Retrieve a task for an orientation from the config file"""
    task = config['mapping'][orientation]
    return {
        'projectId': config['tasks'][task]['id'],
        'description': config['tasks'][task]['description']}


def start_task(projectId: int, description: str):
    """Start a task in Hackaru"""
    global CURRENT_TASK
    data = f'{{"activity":{{"description":"{description or ""}","project_id":{projectId},"started_at":"{now()}"}}}}'

    resp = requests.post(config['endpoint'], data=data, headers=headers())

    CURRENT_TASK = resp.json()


def stop_current_task():
    """Stop a task in Hackaru"""
    global CURRENT_TASK

    if CURRENT_TASK == None:
        return

    data = f'{{"activity":{{"id":{CURRENT_TASK["id"]},"stopped_at":"{now()}"}}}}'

    requests.put(config['endpoint'] + "/" +
                 str(CURRENT_TASK['id']), data=data, headers=headers())

    CURRENT_TASK = None


def init_current_task():
    """Initialize the current task with the task currently active in Hackaru"""
    global CURRENT_TASK

    resp = requests.get(config['endpoint'] + '/working', headers=headers())

    CURRENT_TASK = resp.json()


async def print_device_information(client):
    """Print device information about the connected Timular cube"""

    model_number = await client.read_gatt_char(MODEL_NUMBER_UUID)
    print(f"Model Number: {''.join(map(chr, model_number))}")

    manufacturer = await client.read_gatt_char(MANUFACTURER_UUID)
    print(f"Manufacturer: {''.join(map(chr, manufacturer))}")

    serial_number = await client.read_gatt_char(SERIAL_NUMBER_UUID)
    print(f"Serial Number: {''.join(map(chr, serial_number))}")

    hardware_revision = await client.read_gatt_char(HARDWARE_REVISION_UUID)
    print(f"Hardware Revision: {''.join(map(chr, hardware_revision))}")

    software_revision = await client.read_gatt_char(SOFTWARE_REVISION_UUID)
    print(f"Software Revision: {''.join(map(chr, software_revision))}")

    firmware_revision = await client.read_gatt_char(FIRMWARE_REVISION_UUID)
    print(f"Firmware Revision: {''.join(map(chr, firmware_revision))}")


async def main(address):
    """Main loop listening for orientation changes"""
    async with BleakClient(address) as client:
        await print_device_information(client)

        await client.start_notify(ORIENTATION_UUID, callback)

        while 1:
            await asyncio.sleep(1)

with open('config.yml', 'r') as f:
    config = yaml.safe_load(f)
    init_current_task()
    asyncio.run(main(config['address']))
