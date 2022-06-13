"""
A simple linkage between a Timular cube and Hackaru.
"""

import argparse
import asyncio
import http.cookiejar
import logging
import os
import signal
import tkinter as tk
from datetime import datetime
from functools import partial
from getpass import getpass
from threading import Lock
from tkinter import simpledialog
from typing import Optional

import appdirs  # type: ignore
import requests
import yamale  # type: ignore
import yaml
from bleak import BleakClient  # type: ignore
from recordclass import RecordClass  # type: ignore
from requests import Session
from tenacity import retry  # type: ignore

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

CONFIG_SCHEMA = yamale.make_schema(
    content="""
cli: bool(required=False)
timeular:
    device-address: regex('([0-9A-F]{2}):([0-9A-F]{2}):([0-9A-F]{2}):([0-9A-F]{2}):([0-9A-F]{2}):([0-9A-F]{2})')

hackaru:
    endpoint: str()
    email: str()

task_endpoint: str(required=False)

mapping: list(include('task-mapping'))

---

hackaru-task:
    name: str(required=False)
    id: int()
    description: str(required=False)

task-mapping:
    side: int(min=1, max=9)
    task: include('hackaru-task')
"""
)


logging.basicConfig()
logger = logging.getLogger("hackaru_timular")
logger.setLevel(logging.INFO)


state_lock = Lock()


class State(RecordClass):
    """Application state"""

    # pylint: disable=too-few-public-methods
    current_task: Optional[dict]
    config: dict
    session: Session


class GracefulKiller:
    kill_now = False

    def __init__(self, state: State):
        for sig in [signal.SIGINT, signal.SIGTERM]:
            signal.signal(sig, partial(self.exit_gracefully, state))

    def exit_gracefully(self, state, *_):
        """ "Stop the current task before exit"""
        stop_current_task(state)
        logger.info("Stopped current task, shutting down.")
        self.kill_now = True


def now():
    """Returns the current time as a formatted string"""
    return datetime.utcnow().strftime("%a %B %d %Y %H:%M:%S")


@retry
def login(session, config):
    """Login to Hackaru Server"""
    data = f'{{"user":{{"email":"{config["email"]}","password":"{getpass()}"}}}}'
    response = session.post(
        config["hackaru"]["endpoint"] + "/auth/auth_tokens",
        data=data,
        headers=HEADERS,
    )

    response.raise_for_status()
    session.cookies.save()


def prompt_for_password(cli: bool):
    if cli:
        return getpass()
    else:
        root = tk.Tk()
        root.overrideredirect(1)
        root.withdraw()

        return (
            simpledialog.askstring(
                title="Task Description", prompt="What are you working on?", show="*"
            )
            or ""
        )


def callback_with_state(
    state: State, sender: int, data: bytearray  # pylint: disable=unused-argument
):
    """Callback for orientation changes of the Timeular cube"""
    assert len(data) == 1
    orientation = data[0]
    logger.info("Orientation: %i", orientation)

    with state_lock:
        if orientation not in range(1, 9):
            stop_current_task(state)
            return

        stop_current_task(state)
        try:
            task = get_task(state, orientation)
            start_task(state, **task)
        except StopIteration:
            logger.error("There is no task assigned for side %i", orientation)


def get_task(state: State, orientation: int):
    """Retrieve a task for an orientation from the config file"""
    task = next(
        mapping["task"]
        for mapping in state.config["mapping"]
        if mapping["side"] == orientation
    )

    return {
        "project_id": task["id"],
        "description": task.get("description", ""),
    }


def start_task(state: State, project_id: int, description: str):
    """Start a task in Hackaru"""
    data = f'{{"activity":{{"description":"{description or prompt_for_description(state.config["cli"])}","project_id":{project_id},"started_at":"{now()}"}}}}'

    resp = state.session.post(state.config["task_endpoint"], data=data, headers=HEADERS)

    state.current_task = resp.json()


def prompt_for_description(cli: bool):
    if cli:
        return input("What are you working on? ")
    else:
        root = tk.Tk()
        root.overrideredirect(1)
        root.withdraw()

        return (
            simpledialog.askstring(
                title="Task Description", prompt="What are you working on?"
            )
            or ""
        )


def stop_current_task(state: State):
    """Stop a task in Hackaru"""
    if state.current_task is None:
        return

    data = f'{{"activity":{{"id":{state.current_task["id"]},"stopped_at":"{now()}"}}}}'

    state.session.put(
        state.config["task_endpoint"] + "/" + str(state.current_task["id"]),
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


async def main_loop(state: State, killer: GracefulKiller):
    """Main loop listening for orientation changes"""
    async with BleakClient(state.config["timeular"]["device-address"]) as client:
        await print_device_information(client)

        callback = partial(callback_with_state, state)

        await client.start_notify(ORIENTATION_UUID, callback)

        while not killer.kill_now:
            await asyncio.sleep(1)


def hackaru_projects(state: State):
    return state.session.get(
        state.config["hackaru"]["endpoint"] + "/v1/projects", headers=HEADERS
    ).json()


def get_project_name(projects: dict, id: int):
    return next(project["name"] for project in projects if project["id"] == id) or ""


def get_project_id(projects: dict, name: str):
    return next(project["id"] for project in projects if project["name"] == name)


def to_mapping(project_names, projects, descriptions):
    mapping = []
    for side in range(1, 9):
        if project_names[side].get():
            project_name = project_names[side].get()
            mapping.append(
                {
                    "side": side,
                    "task": {
                        "name": project_name,
                        "id": get_project_id(projects, project_name),
                        "description": descriptions.get("side", ""),
                    },
                }
            )
    return mapping


def update_mapping(
    state: State, config_file_name, project_names, projects, descriptions
):
    state.config["mapping"] = to_mapping(project_names, projects, descriptions)
    with open(config_file_name, "w") as config_file:
        yaml.dump(state.config, config_file)


def mapping_editor(state: State, config_file_name):
    root = tk.Tk()
    root.geometry("900x900")
    root.columnconfigure(0, weight=1)
    root.columnconfigure(1, weight=3)

    for side in range(1, 9):
        side_label = tk.Label(root, text=str(side))
        side_label.grid(column=0, row=side, sticky=tk.W, padx=5, pady=5)

    projects = hackaru_projects(state)

    project_names = {}
    dropdown_dict = {}
    frames = {}
    descriptions = {}
    description_inputs = {}

    for side in range(1, 9):

        frames[side] = tk.Frame(root)

        project_names[side] = tk.StringVar()
        descriptions[side] = tk.StringVar()
        try:
            task = get_task(state, side)
            project_names[side].set(get_project_name(projects, task["project_id"]))
            descriptions[side].set(task["description"])
        except StopIteration:
            pass

        dropdown_dict[side] = tk.OptionMenu(
            frames[side],
            project_names[side],
            *list(map(lambda project: project["name"], projects)),
        )
        dropdown_dict[side].config(width=18)
        side_label = tk.Label(frames[side], text=str(side))
        description_inputs[side] = tk.Entry(
            frames[side], textvariable=descriptions[side]
        )

        frames[side].grid(column=1, row=side, sticky=tk.W, padx=5, pady=5)
        dropdown_dict[side].pack(anchor="w")
        description_inputs[side].pack(anchor="w")

    save_config_button = tk.Button(
        root,
        text="Save configuration",
        command=lambda: update_mapping(
            state, config_file_name, project_names, projects, descriptions
        ),
    )
    save_config_button.grid(column=1, row=9)
    root.mainloop()


def main(*args):
    """Console script entry point"""
    parser = argparse.ArgumentParser(
        description="hackaru-timeular",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-e", "--mapping-editor", action="store_true", help="mapping editor"
    )

    args = vars(parser.parse_args())

    config_dir = appdirs.user_config_dir(appname="hackaru-timeular")

    with open(
        os.path.join(config_dir, "config.yml"), "r+", encoding="utf-8"
    ) as config_file:

        config = yaml.safe_load(config_file)

        data = yamale.make_data(config_file.name)
        yamale.validate(CONFIG_SCHEMA, data)

    config["task_endpoint"] = config["hackaru"]["endpoint"] + "/v1/activities"

    if "cli" not in config:
        config["cli"] = False

    cookies_file = os.path.join(config_dir, "cookies.txt")
    session = requests.Session()
    session.cookies = http.cookiejar.LWPCookieJar(filename=cookies_file)
    try:
        session.cookies.load(ignore_discard=True)
        session.cookies.clear_expired_cookies()
    except FileNotFoundError:
        pass

    if not session.cookies:
        login(session, config)

    current_task = session.get(
        config["task_endpoint"] + "/working", headers=HEADERS
    ).json()

    state = State(config=config, current_task=current_task, session=session)
    killer = GracefulKiller(state)

    if args["mapping_editor"]:
        mapping_editor(
            state=state, config_file_name=os.path.join(config_dir, "config.yml")
        )
    else:
        asyncio.run(main_loop(state, killer))
