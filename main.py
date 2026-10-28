import json
import time

import network
from machine import Pin
from umqtt.simple import MQTTClient

import config
from player import Player
from util import parse_command

TOPIC_CMD = "talepuff/{}/cmd".format(config.DEVICE_ID).encode()
TOPIC_STATUS = "talepuff/{}/status".format(config.DEVICE_ID).encode()
TOPIC_ONLINE = "talepuff/{}/online".format(config.DEVICE_ID).encode()

led = Pin("LED", Pin.OUT)
pending = []


def on_message(topic, raw):
    cmd = parse_command(raw, config.MAX_VOLUME, config.ALLOWED_AUDIO_HOST)
    if cmd is None:
        print("Perintah diabaikan:", raw[:80])
    elif len(pending) < 8:
        pending.append(cmd)


def connect_wifi(wlan):
    wlan.active(True)
    if wlan.isconnected():
        return
    print("Menyambung ke Wi-Fi", config.WIFI_SSID)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    for _ in range(40):  # maksimal 20 detik
        if wlan.isconnected():
            print("Wi-Fi tersambung, IP Pico:", wlan.ifconfig()[0])
            return
        led.toggle()
        time.sleep_ms(500)
    raise RuntimeError("wifi")


def connect_mqtt():
    client = MQTTClient(
        config.DEVICE_ID,
        config.BROKER_IP,
        port=config.BROKER_PORT,
        user=config.MQTT_USER,
        password=config.MQTT_PASSWORD,
        keepalive=config.KEEPALIVE,
    )
    client.set_last_will(TOPIC_ONLINE, b"0", retain=True)
    client.set_callback(on_message)
    client.connect()
    client.subscribe(TOPIC_CMD, 1)
    client.publish(TOPIC_ONLINE, b"1", retain=True)
    print("MQTT tersambung, mendengarkan", TOPIC_CMD)
    return client


def run(player, cmd):
    action = cmd["action"]
    if action == "play":
        if cmd["volume"] is not None:
            player.set_volume(cmd["volume"])
        player.start(cmd["url"], cmd["story_id"])
    elif action == "pause":
        player.pause()
    elif action == "resume":
        player.resume()
    elif action == "stop":
        player.stop()
    elif action == "volume":
        player.set_volume(cmd["volume"])


def status_payload(player):
    return json.dumps({
        "state": player.state,
        "reason": player.reason,
        "story_id": player.story_id,
        "position": player.position,
        "duration": player.duration,
        "volume": player.volume,
    }).encode()


def main():
    wlan = network.WLAN(network.STA_IF)
    player = Player(min(config.DEFAULT_VOLUME, config.MAX_VOLUME))
    client = None
    last_ping = last_status = time.ticks_ms()
    sent = None

    while True:
        try:
            if not wlan.isconnected():
                player.stop("wifi_lost")
                client = None
                connect_wifi(wlan)
            if client is None:
                client = connect_mqtt()
                sent = None
                led.on()

            client.check_msg()
            while pending:
                run(player, pending.pop(0))
            busy = player.step()

            now = time.ticks_ms()
            if time.ticks_diff(now, last_ping) > config.KEEPALIVE * 500:
                client.ping()
                last_ping = now
            snapshot = (player.state, player.reason, player.story_id, player.volume)
            if snapshot != sent or (
                player.state == "playing" and time.ticks_diff(now, last_status) >= 1000
            ):
                client.publish(TOPIC_STATUS, status_payload(player), retain=True)
                sent = snapshot
                last_status = now
            if not busy:
                time.sleep_ms(30)
        except Exception as e:
            print("Koneksi bermasalah:", e)
            led.off()
            player.stop("connection_lost")
            client = None
            time.sleep(config.RECONNECT_DELAY)


main()
