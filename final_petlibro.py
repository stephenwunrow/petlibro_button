import asyncio
import aiohttp
import hashlib
import uuid
from dotenv import load_dotenv

BASE_URL = "https://api.us.petlibro.com"


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
            print("✅ Logged in")

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

    async def open_tray(self, device_id, tray):
        print("🍽 Opening tray")
        data = await self.request(
            "/device/wetFeedingPlan/manualFeedNow",
            {
                "deviceSn": device_id,
                "plate": tray
            }
        )
        feed_id = data.get("feedId") if data else 0
        return feed_id
    
    def plate_position(self) -> int:
        return self.current_plate

    async def set_plate_position(self, device_sn: str, target: int) -> None:
        print(f"[DEBUG] set_plate_position called with target={target}")
        """Rotate to requested plate (1-3)."""
        curr = self.current_plate
        steps = (target - curr) % 3

        for _ in range(steps):
            print("setting plate position")
            await self.set_rotate_food_bowl(device_sn)
            await asyncio.sleep(0.6)

        self.current_plate = target

    async def set_rotate_food_bowl(self, device_sn: str) -> int:
        """Rotate the food bowl for a specific device by one plate."""
        print(f"Triggering rotate food bowl for device: {device_sn}")
        try:
            url = f"{BASE_URL}/device/wetFeedingPlan/platePositionChange"
            headers = self.headers.copy()
            headers["token"] = self.token

            async with self.session.post(url, json={"deviceSn": device_sn, "plate": 1}, headers=headers) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    print(f"API error rotating plate: {data}")
                else:
                    print(f"Rotate food bowl successful: {data}")
                return data
        except aiohttp.ClientError as err:
            print(f"Failed to rotate food bowl for device {device_sn}: {err}")

    async def stop_feed_now(self, device_sn, feed_id):
        """Close the tray using the API stopFeedNow endpoint."""
        print(f"⏹ Closing tray (feedId={feed_id})")
        await self.request(
            "/device/wetFeedingPlan/stopFeedNow",
            {"deviceSn": device_sn, "feedId": feed_id}
        )

# ----------------------------
# RUN LOOP WITH TRAY CYCLING
# ----------------------------
async def main():
    import os
    load_dotenv()

    EMAIL = os.getenv("PETLIBRO_USERNAME")
    PASSWORD = os.getenv("PETLIBRO_PASSWORD")
    DEVICE_ID = os.getenv("DEVICE_ID")

    async def auto_close(feed_id):
        await asyncio.sleep(15)  # 15 minutes
        await client.stop_feed_now(DEVICE_ID, feed_id)

    async with aiohttp.ClientSession() as session:
        client = PetlibroClient(EMAIL, PASSWORD)
        client.session = session

        await client.login()

        devices = await client.list_devices()
        for d in devices:
            print(d["name"], "online:", d["online"], "deviceSn:", d["deviceSn"])

        while True:
            cmd = await asyncio.to_thread(input, "Command: ")
            cmd = cmd.strip().lower()

            if cmd == "open":
                print("[DEBUG] Rotating once")

                # Rotate exactly once
                await client.set_rotate_food_bowl(DEVICE_ID)

                # Give device time to move
                await asyncio.sleep(2)

                # Open tray (plate number doesn't matter)
                feed_id = await client.open_tray(DEVICE_ID, 1)

                asyncio.create_task(auto_close(feed_id))

            elif cmd == "exit":
                # Optionally close the tray before exiting
                try:
                    await client.stop_feed_now(DEVICE_ID, feed_id)
                except Exception:
                    pass
                break

            else:
                print("Use 'open' or 'exit'")

if __name__ == "__main__":
    asyncio.run(main())