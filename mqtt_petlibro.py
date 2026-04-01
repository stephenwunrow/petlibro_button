#!/usr/bin/env python3
import asyncio
import aiohttp
import hashlib
import uuid
from dotenv import load_dotenv
import os
import paho.mqtt.client as mqtt
from datetime import datetime

BASE_URL = "https://api.us.petlibro.com"

MQTT_BROKER = "localhost"
MQTT_TOPIC = "final_petlibro/command"

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

class PetlibroClient:
    def __init__(self, email, password, region="US", timezone="America/Chicago"):
        self.email = email
        self.password = password
        self.region = region
        self.timezone = timezone
        self.token = None
        self.session = None
        self.current_plate = 0

        self.headers = {
            "source": "ANDROID",
            "language": "EN",
            "timezone": timezone,
            "version": "1.3.45",
            "Content-Type": "application/json",
        }

    def hash_password(self):
        return hashlib.md5(self.password.encode()).hexdigest()

    async def login(self):
        url = f"{BASE_URL}/member/auth/login"

        payload = {
            "appId": 1,
            "appSn": "c35772530d1041699c87fe62348507a8",
            "country": self.region,
            "email": self.email,
            "password": self.hash_password(),
            "timezone": self.timezone,
        }

        async with self.session.post(url, json=payload, headers=self.headers) as resp:
            data = await resp.json()
            self.token = data["data"]["token"]
            log("✅ Logged in")

    async def request(self, path, payload=None):
        url = f"{BASE_URL}{path}"

        headers = self.headers.copy()
        headers["token"] = self.token

        async with self.session.post(url, json=payload or {}, headers=headers) as resp:
            data = await resp.json()

            if data.get("code") != 0:
                raise Exception(f"API error: {data}")

            return data.get("data")

    async def list_devices(self):
        return await self.request("/device/device/list")

    async def is_device_online(self, device_id):
        devices = await self.list_devices()
        for d in devices:
            if d["deviceSn"] == device_id:
                return d.get("online", False)
        return False

    async def rotation_loop(self, device_id):
        while True:
            await asyncio.sleep(60)
            log("[AUTO] Rotating tray")
            try:
                await self.set_rotate_food_bowl(device_id)
            except Exception as e:
                log(f"[AUTO] Rotation failed: {e}")

    async def open_tray(self, device_id, tray):
        log("🍽 Opening tray")
        data = await self.request(
            "/device/wetFeedingPlan/manualFeedNow",
            {"deviceSn": device_id, "plate": tray}
        )
        return data.get("feedId") if data else 0

    async def set_rotate_food_bowl(self, device_sn):
        url = f"{BASE_URL}/device/wetFeedingPlan/platePositionChange"
        headers = self.headers.copy()
        headers["token"] = self.token

        async with self.session.post(url, json={"deviceSn": device_sn, "plate": 1}, headers=headers) as resp:
            data = await resp.json()
            log(f"Rotate result: {data}")
            return data

    async def stop_feed_now(self, device_sn, feed_id):
        log(f"⏹ Closing tray (feedId={feed_id})")
        await self.request(
            "/device/wetFeedingPlan/stopFeedNow",
            {"deviceSn": device_sn, "feedId": feed_id}
        )


# ----------------------------
# MQTT → ASYNC BRIDGE
# ----------------------------
class MQTTListener:
    def __init__(self, loop):
        self.loop = loop
        self.queue = asyncio.Queue()

        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        log("📡 Connected to MQTT")
        client.subscribe(MQTT_TOPIC)

    def on_message(self, client, userdata, msg):
        command = msg.payload.decode().strip()
        log(f"📨 MQTT received: {command}")
        asyncio.run_coroutine_threadsafe(self.queue.put(command), self.loop)

    def start(self):
        self.client.connect(MQTT_BROKER, 1883, 60)
        self.client.loop_start()


# ----------------------------
# MAIN
# ----------------------------
async def main():
    load_dotenv()

    EMAIL = os.getenv("PETLIBRO_USERNAME")
    PASSWORD = os.getenv("PETLIBRO_PASSWORD")
    DEVICE_ID = os.getenv("DEVICE_ID")

    async with aiohttp.ClientSession() as session:
        client = PetlibroClient(EMAIL, PASSWORD)
        client.session = session

        await client.login()

        loop = asyncio.get_running_loop()
        mqtt_listener = MQTTListener(loop)
        mqtt_listener.start()

        rotation_task = asyncio.create_task(client.rotation_loop(DEVICE_ID))
        feed_id = None

        async def auto_close(fid):
            await asyncio.sleep(15)
            await client.stop_feed_now(DEVICE_ID, fid)

        log("🚀 Ready for MQTT commands...")

        while True:
            cmd = await mqtt_listener.queue.get()

            if cmd == "open":
                if not await client.is_device_online(DEVICE_ID):
                    log("⚠️ Device offline")
                    continue

                if rotation_task:
                    rotation_task.cancel()
                    try:
                        await rotation_task
                    except asyncio.CancelledError:
                        pass

                await client.set_rotate_food_bowl(DEVICE_ID)
                await asyncio.sleep(2)

                feed_id = await client.open_tray(DEVICE_ID, 1)
                asyncio.create_task(auto_close(feed_id))

                rotation_task = asyncio.create_task(client.rotation_loop(DEVICE_ID))

            elif cmd == "exit":
                if feed_id:
                    await client.stop_feed_now(DEVICE_ID, feed_id)
                break


if __name__ == "__main__":
    asyncio.run(main())