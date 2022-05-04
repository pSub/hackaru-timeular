import asyncio
from datetime import datetime

import requests
import yaml
from bleak import BleakClient

MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
ORIENTATION_UUID = "c7e70012-c847-11e6-8175-8c89a55d403c"

currentTask = None


def callback(sender: int, data: bytearray):
    assert len(data) == 1
    orientation = data[0]
    print(f"Orientation: {orientation}")

    if orientation not in range(1, 9):
        stopCurrentTask()
        return

    if currentTask != None:
        stopCurrentTask()
    task = getTask(orientation)
    startTask(**task)


def getTask(orientation: int):
    task = config['mapping'][orientation]
    return {
        'projectId': config['tasks'][task]['id'],
        'description': config['tasks'][task]['description']}


def startTask(projectId: int, description: str):
    global currentTask
    time = datetime.utcnow().strftime('%a %B %d %Y %H:%M:%S')
    data = f'{{"activity":{{"description":"{description or ""}","project_id":{projectId},"started_at":"{time}"}}}}'
    headers = {
        "cookie": f"auth_token_id={config['authid']}; auth_token_raw={config['authtoken']}",
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest"
    }

    resp = requests.post(config['endpoint'], data=data, headers=headers)

    currentTask = resp.json()


def stopCurrentTask():
    global currentTask
    time = datetime.utcnow().strftime('%a %B %d %Y %H:%M:%S')
    data = f'{{"activity":{{"id":{currentTask["id"]},"stopped_at":"{time}"}}}}'

    headers = {
        "cookie": f"auth_token_id={config['authid']}; auth_token_raw={config['authtoken']}",
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest"
    }

    resp = requests.put(config['endpoint'] + "/" +
                        str(currentTask['id']), data=data, headers=headers)

    currentTask = None


def initCurrentTask():
    global currentTask
    headers = {
        "cookie": f"auth_token_id={config['authid']}; auth_token_raw={config['authtoken']}",
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest"
    }

    resp = requests.get(config['endpoint'] + '/working', headers=headers)

    currentTask = resp.json()


async def main(address):
    async with BleakClient(address) as client:

        model_number = await client.read_gatt_char(MODEL_NUMBER_UUID)
        print("Model Number: {0}".format("".join(map(chr, model_number))))

        await client.start_notify(ORIENTATION_UUID, callback)

        while 1:
            await asyncio.sleep(1)

with open('config.yml', 'r') as f:
    config = yaml.safe_load(f)
    initCurrentTask()
    asyncio.run(main(config['address']))