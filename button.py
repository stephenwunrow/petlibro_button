#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import subprocess
import json
import paho.mqtt.publish as publish

# --- CONFIGURATION ---
MQTT_BROKER = "localhost"           # Replace if your MQTT broker is on another host
MQTT_PORT = 1883
BUTTON_TOPIC = "zigbee2mqtt/Moes_IP55_Button"  # The topic of your button
SCRIPT_PATH = "/home/pi/open_script.py"        # Path to the script to trigger
COMMAND_ARG = "open"                           # Argument to send to the script

# --- MQTT CALLBACKS ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker")
        client.subscribe(BUTTON_TOPIC)
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
    except json.JSONDecodeError:
        print(f"Invalid JSON received: {msg.payload}")
        return

    action = data.get("action", "")
    if action in ["single", "double", "long"]:
        print(f"Button pressed ({action})! Running script...")
        publish.single("final_petlibro/command", COMMAND_ARG, hostname=MQTT_BROKER)
        print(f"Sent '{COMMAND_ARG}' command to final_petlibro.py")
    else:
        print(f"Ignored action: {action}")

# --- MAIN ---
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
print("Listening for button presses...")
client.loop_forever()