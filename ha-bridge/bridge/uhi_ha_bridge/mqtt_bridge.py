"""MQTT connection: HA discovery, state publishing, command reception.

Uses paho-mqtt. Commands from HA are forwarded to the main logic
via a callback (set_command_handler).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from .config import Config
from .entities import Entity

logger = logging.getLogger("uhi-ha-bridge.mqtt")


class MqttBridge:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._enabled = config.mqtt.enabled
        self._prefix = config.ha.discovery_prefix
        self._node = config.ha.node_id
        self._base = f"uhi/{self._node}"
        self._availability_topic = f"{self._base}/status"
        self._command_handler: Callable[[str, str], None] | None = None
        self._set_re = re.compile(rf"^{re.escape(self._base)}/([^/]+)/set$")
        self._client = None
        self._device_info: dict | None = None
        self._unknown_seen: set[str] = set()
        self._unknown_log_path = config.unknown_log_path
        self._load_unknown_seen()

        if not self._enabled:
            logger.warning(
                "MQTT disabled (MQTT_ENABLED=false) - test mode: "
                "state/discovery are only logged, no broker needed."
            )
            return

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"uhi-ha-bridge-{self._node}"
        )
        if config.mqtt.username:
            self._client.username_pw_set(config.mqtt.username, config.mqtt.password)
        self._client.will_set(self._availability_topic, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    # ---------------- Connection ----------------
    def connect(self) -> None:
        if not self._enabled:
            return
        parsed = urlparse(self._cfg.mqtt.url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 1883
        logger.info("Connecting MQTT to %s:%s", host, port)
        self._client.connect(host, port)
        self._client.loop_start()

    def set_command_handler(self, handler: Callable[[str, str], None]) -> None:
        self._command_handler = handler

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        logger.info("MQTT connected (rc=%s)", reason_code)
        self.publish_availability(True)

    def _on_message(self, client, userdata, msg) -> None:
        text = msg.payload.decode("utf-8", errors="replace")
        match = self._set_re.match(msg.topic)
        if match and self._command_handler:
            entity_id = match.group(1)
            logger.info("Command received: %s = %s", entity_id, text)
            self._command_handler(entity_id, text)

    # ---------------- Topics ----------------
    def _state_topic(self, entity_id: str) -> str:
        return f"{self._base}/{entity_id}/state"

    def _command_topic(self, entity_id: str) -> str:
        return f"{self._base}/{entity_id}/set"

    def _discovery_topic(self, component: str, entity_id: str) -> str:
        return f"{self._prefix}/{component}/{self._node}/{entity_id}/config"

    # ---------------- Publishing ----------------
    def publish_availability(self, online: bool) -> None:
        if not self._enabled:
            return
        self._client.publish(
            self._availability_topic, "online" if online else "offline", qos=1, retain=True
        )

    def publish_state(self, entity_id: str, value) -> None:
        payload = "" if value is None else str(value)
        if not self._enabled:
            logger.info("[TEST] State %s = %s", entity_id, payload)
            return
        self._client.publish(self._state_topic(entity_id), payload, retain=True)
        logger.debug("State %s = %s", entity_id, payload)

    def note_unknown(self, key: str, value) -> bool:
        """Log a key unknown to the bridge once.

        Writes key + sample value, deduplicated, to the unknown log file
        (also across restarts). Returns True if the key was seen for the
        first time.
        """
        payload = "" if value is None else str(value)
        if key in self._unknown_seen:
            return False
        self._unknown_seen.add(key)
        logger.info("Unknown entity detected: %s = %s", key, payload)
        self._record_unknown(key, payload)
        return True

    def _load_unknown_seen(self) -> None:
        """Read already-logged keys to avoid duplicates."""
        if not self._unknown_log_path or not os.path.exists(self._unknown_log_path):
            return
        try:
            with open(self._unknown_log_path, encoding="utf-8") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 2 and parts[1]:
                        self._unknown_seen.add(parts[1])
            logger.info(
                "%d already-known unknown keys loaded from %s",
                len(self._unknown_seen),
                self._unknown_log_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unknown log not readable (%s): %s", self._unknown_log_path, exc)

    def _record_unknown(self, key: str, example_value: str) -> None:
        """Write an unknown key to the log file once."""
        if not self._unknown_log_path:
            return
        try:
            new_file = not os.path.exists(self._unknown_log_path)
            directory = os.path.dirname(self._unknown_log_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self._unknown_log_path, "a", encoding="utf-8") as fh:
                if new_file:
                    fh.write("# timestamp\tkey\texample_value\n")
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                fh.write(f"{ts}\t{key}\t{example_value}\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unknown log not writable (%s): %s", self._unknown_log_path, exc
            )

    def _device_block(self, device_info: dict | None) -> dict:
        identifiers = []
        if device_info and device_info.get("mac"):
            identifiers.append(device_info["mac"])
        identifiers.append(f"uhi_{self._node}")
        device = {
            "identifiers": identifiers,
            "name": "UHI Heat Pump",
            "manufacturer": "UHI",
            "model": "Heat Pump Controller",
        }
        if device_info and device_info.get("sw_version"):
            device["sw_version"] = device_info["sw_version"]
        if device_info and device_info.get("connections"):
            device["connections"] = device_info["connections"]
        return device

    def _base_config(self, entity: Entity, device_info: dict | None) -> dict:
        return {
            "name": entity.name or entity.key,
            "unique_id": f"uhi_{self._node}_{entity.id}",
            "object_id": f"uhi_{entity.id}",
            "availability_topic": self._availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "state_topic": self._state_topic(entity.id),
            "device": self._device_block(device_info),
        }

    def publish_discovery(
        self,
        entities: list[Entity],
        device_info: dict | None,
        select_options: list[str] | None,
    ) -> None:
        self._device_info = device_info
        if not self._enabled:
            logger.info(
                "[TEST] Discovery skipped for %d entities (options: %s)",
                len(entities),
                select_options,
            )
            return
        for entity in entities:
            cfg = self._base_config(entity, device_info)
            if entity.type == "sensor":
                component = "sensor"
                if entity.unit:
                    cfg["unit_of_measurement"] = entity.unit
                if entity.device_class:
                    cfg["device_class"] = entity.device_class
                cfg["state_class"] = "measurement"
            elif entity.type == "number":
                component = "number"
                cfg["command_topic"] = self._command_topic(entity.id)
                if entity.unit:
                    cfg["unit_of_measurement"] = entity.unit
                if entity.device_class:
                    cfg["device_class"] = entity.device_class
                if entity.min is not None:
                    cfg["min"] = entity.min
                if entity.max is not None:
                    cfg["max"] = entity.max
                if entity.step is not None:
                    cfg["step"] = entity.step
                cfg["mode"] = "box"
            elif entity.type == "select":
                component = "select"
                cfg["command_topic"] = self._command_topic(entity.id)
                cfg["options"] = select_options if select_options else ["unknown"]
            else:
                logger.warning("Unknown entity type: %s", entity.type)
                continue

            topic = self._discovery_topic(component, entity.id)
            self._client.publish(topic, json.dumps(cfg), qos=1, retain=True)
            logger.info("Discovery published: %s (%s)", entity.id, component)

            if cfg.get("command_topic"):
                self._client.subscribe(cfg["command_topic"], qos=1)

    def publish_version_discovery(self, device_info: dict | None) -> None:
        if not self._enabled:
            return
        fields = [
            ("version_uhi", "UHI Version"),
            ("version_heatpump", "Heatpump Firmware"),
            ("version_kkr", "KKR Firmware"),
            ("version_wqif", "WQIF Firmware"),
            ("version_zlm", "ZLM Firmware"),
        ]
        for field_id, name in fields:
            cfg = {
                "name": name,
                "unique_id": f"uhi_{self._node}_{field_id}",
                "object_id": f"uhi_{field_id}",
                "state_topic": self._state_topic(field_id),
                "availability_topic": self._availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
                "entity_category": "diagnostic",
                "device": self._device_block(device_info),
            }
            topic = self._discovery_topic("sensor", field_id)
            self._client.publish(topic, json.dumps(cfg), qos=1, retain=True)
        logger.info("Version diagnostic sensors published")

    def close(self) -> None:
        if not self._enabled or self._client is None:
            return
        try:
            self.publish_availability(False)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass
