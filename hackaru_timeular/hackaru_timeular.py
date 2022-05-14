"""
A simple linkage between a Timular cube and Hackaru.
"""

import asyncio
from getpass import getpass
import logging
import os
import signal
from datetime import datetime
from functools import partial
from typing import Optional

import appdirs  # type: ignore
import requests
from requests import Session
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

HEADERS = {
    "content-type": "application/json",
    "x-requested-with": "XMLHttpRequest",
}

logging.basicConfig()
logger = logging.getLogger("hackaru_timular")
logger.setLevel(logging.INFO)


class State(RecordClass):
    """Application state"""

    # pylint: disable=too-few-public-methods
    current_task: Optional[dict]
    config: dict
    session: Session


class GracefulKiller:
    kill_now = False

    def __init__(self, state: State):
        signal.signal(signal.SIGINT, partial(self.exit_gracefully, state))
        signal.signal(signal.SIGTERM, partial(self.exit_gracefully, state))

    def exit_gracefully(self, state, *args):
        stop_current_task(state)
        self.kill_now = True


def now():
    """Returns the current time as a formatted string"""
    return datetime.utcnow().strftime("%a %B %d %Y %H:%M:%S")


def login(session, config):
    data = f'{{"user":{{"email":"{config["email"]}","password":"{getpass()}"}}}}'
    session.post(
        "https://hackaru-api.pascal-wittmann.de/auth/auth_tokens",
        data=data,
        headers=HEADERS,
    )


def callback_with_state(
    state: State, sender: int, data: bytearray  # pylint: disable=unused-argument
):
    """Callback for orientation changes of the Timeular cube"""
    assert len(data) == 1
    orientation = data[0]
    logger.info("Orientation: %i", orientation)

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

    resp = state.session.post(state.config["endpoint"], data=data, headers=HEADERS)

    state.current_task = resp.json()


def stop_current_task(state: State):
    """Stop a task in Hackaru"""
    if state.current_task is None:
        return

    data = f'{{"activity":{{"id":{state.current_task["id"]},"stopped_at":"{now()}"}}}}'

    state.session.put(
        state.config["endpoint"] + "/" + str(state.current_task["id"]),
        data=data,
        headers=HEADERS,
    )

    state.current_task = None


async def print_device_information(client):
    """Print device information about the connected Timular cube"""

    model_number = await client.read_gatt_char(MODEL_NUMBER_UUID)
    logger.info("Model Number: %s", "".join(map(chr, model_number)))

    manufacturer = await client.read_gatt_char(MANUFACTURER_UUID)
    logger.info("Manufacturer: %s", "".join(map(chr, manufacturer)))

    serial_number = await client.read_gatt_char(SERIAL_NUMBER_UUID)
    logger.info("Serial Number: %s", "".join(map(chr, serial_number)))

    hardware_revision = await client.read_gatt_char(HARDWARE_REVISION_UUID)
    logger.info("Hardware Revision: %s", "".join(map(chr, hardware_revision)))

    software_revision = await client.read_gatt_char(SOFTWARE_REVISION_UUID)
    logger.info("Software Revision: %s", "".join(map(chr, software_revision)))

    firmware_revision = await client.read_gatt_char(FIRMWARE_REVISION_UUID)
    logger.info("Firmware Revision: %s", "".join(map(chr, firmware_revision)))


async def main_loop(state: State):
    """Main loop listening for orientation changes"""
    async with BleakClient(state.config["address"]) as client:
        await print_device_information(client)

        callback = partial(callback_with_state, state)

        await client.start_notify(ORIENTATION_UUID, callback)

        killer = GracefulKiller(state)
        while not killer.kill_now:
            await asyncio.sleep(1)


def main():
    """ "Console script entry point"""
    config_dir = appdirs.user_config_dir(appname="hackaru-timeular")
    with open(os.path.join(config_dir, "config.yml"), "r", encoding="utf-8") as f:

        config = yaml.safe_load(f)
        session = requests.Session()

        login(session, config)

        current_task = session.get(
            config["endpoint"] + "/working", headers=HEADERS
        ).json()

        asyncio.run(
            main_loop(State(config=config, current_task=current_task, session=session))
        )
