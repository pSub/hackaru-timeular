"""
A simple linkage between a Timular cube and Hackaru.
"""

import asyncio
import os
from datetime import datetime
from functools import partial
from typing import Optional

import appdirs  # type: ignore
import requests
import yaml
from bleak import BleakClient  # type: ignore
from recordclass import RecordClass  # type: ignore

MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
MANUFACTURER_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
SOFTWARE_REVISION_UUID = "00002a28-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
ORIENTATION_UUID = "c7e70012-c847-11e6-8175-8c89a55d403c"


class State(RecordClass):
    """Application state"""

    # pylint: disable=too-few-public-methods
    current_task: Optional[dict]
    config: dict


def now():
    """Returns the current time as a formatted string"""
    return datetime.utcnow().strftime("%a %B %d %Y %H:%M:%S")


def headers(config):
    """Returns the authenticated headers for Hackaru"""
    return {
        "cookie": f"auth_token_id={config['authid']}; auth_token_raw={config['authtoken']}",
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest",
    }


def callback_with_state(
    state: State, sender: int, data: bytearray  # pylint: disable=unused-argument
):
    """Callback for orientation changes of the Timeular cube"""
    assert len(data) == 1
    orientation = data[0]
    print(f"Orientation: {orientation}")

    if orientation not in range(1, 9):
        stop_current_task(state)
        return

    stop_current_task(state)
    task = get_task(state, orientation)
    start_task(state, **task)


def get_task(state: State, orientation: int):
    """Retrieve a task for an orientation from the config file"""
    task = state.config["mapping"][orientation]
    return {
        "project_id": state.config["tasks"][task]["id"],
        "description": state.config["tasks"][task]["description"],
    }


def start_task(state: State, project_id: int, description: str):
    """Start a task in Hackaru"""
    data = f'{{"activity":{{"description":"{description or ""}","project_id":{project_id},"started_at":"{now()}"}}}}'

    resp = requests.post(
        state.config["endpoint"], data=data, headers=headers(state.config)
    )

    state.current_task = resp.json()


def stop_current_task(state: State):
    """Stop a task in Hackaru"""
    if state.current_task is None:
        return

    data = f'{{"activity":{{"id":{state.current_task["id"]},"stopped_at":"{now()}"}}}}'

    requests.put(
        state.config["endpoint"] + "/" + str(state.current_task["id"]),
        data=data,
        headers=headers(state.config),
    )

    state.current_task = None


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


async def main_loop(state: State):
    """Main loop listening for orientation changes"""
    async with BleakClient(state.config["address"]) as client:
        await print_device_information(client)

        callback = partial(callback_with_state, state)

        await client.start_notify(ORIENTATION_UUID, callback)

        while 1:
            await asyncio.sleep(1)


def main():
    """ "Console script entry point"""
    config_dir = appdirs.user_config_dir(appname="hackaru-timeular")
    with open(os.path.join(config_dir, "config.yml"), "r", encoding="utf-8") as f:

        config = yaml.safe_load(f)
        current_task = requests.get(
            config["endpoint"] + "/working", headers=headers(config)
        ).json()
        asyncio.run(main_loop(State(config=config, current_task=current_task)))
