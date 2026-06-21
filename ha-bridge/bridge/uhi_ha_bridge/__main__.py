"""Entry point: connects UHI <-> Home Assistant via MQTT."""

from __future__ import annotations

import signal
import threading
import time

from . import device_keys
from .config import load_config
from .entities import ENTITIES, Entity
from .logger import setup_logging
from .mqtt_bridge import MqttBridge
from .uhi_client import UhiClient

logger = setup_logging()


class Bridge:
    def __init__(self) -> None:
        self._cfg = load_config()
        # Curated entities (with write access / nice names) first,
        # then all other known monitor keys from deviceKeys.json.
        curated = [
            device_keys.enrich(e, self._cfg.device_keys_path) for e in ENTITIES
        ]
        curated_keys = {e.key for e in curated}
        generated = device_keys.generate_sensor_entities(
            self._cfg.device_keys_path, exclude_keys=curated_keys
        )
        self._entities = curated + generated
        self._by_id = {e.id: e for e in self._entities}
        self._by_key = {e.key: e for e in self._entities}

        # Operation mode mapping (id <-> name), filled at runtime.
        self._mode_id_to_name: dict[int, str] = {}
        self._mode_name_to_id: dict[str, int] = {}
        self._device_info: dict = {}

        self._uhi = UhiClient(self._cfg)
        self._mqtt = MqttBridge(self._cfg)
        self._stop = threading.Event()

    # ---------------- Helpers ----------------
    @staticmethod
    def _scale(entity, raw):
        try:
            num = float(raw)
        except (TypeError, ValueError):
            return raw
        scale = entity.scale if entity.scale and entity.scale > 1 else 1
        return num if scale == 1 else num / scale

    def _load_operation_modes(self) -> list[str]:
        modes = self._uhi.get_operation_mode_list()
        self._mode_id_to_name = {}
        self._mode_name_to_id = {}
        for item in modes:
            try:
                mode_id = int(item["id"])
            except (KeyError, ValueError, TypeError):
                continue
            self._mode_id_to_name[mode_id] = item.get("name")
            self._mode_name_to_id[item.get("name")] = mode_id
        return [m.get("name") for m in modes if m.get("name")]

    def _current_mode_name(self, data: dict | None):
        if not data:
            return None
        if data.get("name"):
            return data["name"]
        op = data.get("operationMode") or {}
        if op.get("name"):
            return op["name"]
        mode_id = data.get("id", op.get("id"))
        if mode_id is not None:
            try:
                return self._mode_id_to_name.get(int(mode_id))
            except (ValueError, TypeError):
                return None
        return None

    # ---------------- Publishing ----------------
    def _publish_version(self) -> dict | None:
        try:
            version = self._uhi.get_version()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Version could not be read: %s", exc)
            return None
        uhi = version.get("uhi") or {}
        self._mqtt.publish_state("version_uhi", uhi.get("version"))
        self._mqtt.publish_state("version_heatpump", version.get("heatpump"))
        self._mqtt.publish_state("version_kkr", version.get("kkr"))
        self._mqtt.publish_state("version_wqif", version.get("wqif"))
        self._mqtt.publish_state("version_zlm", version.get("zlm"))
        return version

    def _publish_operation_mode_state(self) -> None:
        mode_entity = next(
            (e for e in self._entities if e.write_via == "operationmode"), None
        )
        if not mode_entity:
            return
        try:
            data = self._uhi.get_operation_mode()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Operation mode status not readable: %s", exc)
            return
        name = self._current_mode_name(data)
        if name:
            self._mqtt.publish_state(mode_entity.id, name)

    # ---------------- Live data ----------------
    def _initial_snapshot(self) -> None:
        """Fetch all current values once via REST (groups endpoint).

        UHI sends only changes over the socket; so that HA sees values
        immediately, all groups are queried once at startup and pushed
        through the same processing as live data.
        """
        groups = self._cfg.uhi.snapshot_groups
        try:
            data = self._uhi.get_function_data_groups(groups)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Initial snapshot failed: %s", exc)
            return
        values: dict = {}
        for items in data.values():
            if not isinstance(items, list):
                continue
            for item in items:
                key = item.get("key")
                if key is not None:
                    values[key] = item.get("value")
        if values:
            logger.info("Initial snapshot: %d values from %d groups", len(values), len(data))
            self._handle_operationdata(values)
        else:
            logger.warning("Initial snapshot returned no values")

    def _handle_operationdata(self, values: dict) -> None:
        for key, raw in values.items():
            entity = self._by_key.get(key)
            if entity is None:
                # Key not yet known -> create as sensor at runtime.
                entity = self._register_runtime_entity(key, raw)
            if entity.write_via == "operationmode":
                try:
                    name = self._mode_id_to_name.get(int(raw))
                except (ValueError, TypeError):
                    name = None
                if name:
                    self._mqtt.publish_state(entity.id, name)
                continue
            self._mqtt.publish_state(entity.id, self._scale(entity, raw))

    def _register_runtime_entity(self, key: str, sample) -> Entity:
        """Register an unknown broadcast key as a full sensor.

        The key is treated like any other entity (discovery + state).
        It is additionally noted once in the unknown log file.
        """
        entity = device_keys.build_entity_for_key(key, self._cfg.device_keys_path)
        # Avoid id collision (very rare, if two keys normalize equally).
        if entity.id in self._by_id:
            entity.id = f"{entity.id}_{abs(hash(key)) % 10000}"
        self._entities.append(entity)
        self._by_key[key] = entity
        self._by_id[entity.id] = entity
        self._mqtt.note_unknown(key, sample)
        self._mqtt.publish_discovery([entity], self._device_info, None)
        logger.info("New entity registered at runtime: %s (key=%s)", entity.id, key)
        return entity

    # ---------------- Commands ----------------
    def _handle_command(self, entity_id: str, payload: str) -> None:
        entity = self._by_id.get(entity_id)
        if not entity:
            logger.warning("Command for unknown entity: %s", entity_id)
            return
        try:
            if entity.write_via == "operationmode":
                mode_id = self._mode_name_to_id.get(payload)
                if mode_id is None:
                    logger.warning("Unknown operation mode: %s", payload)
                    return
                self._uhi.set_operation_mode(mode_id)
                self._mqtt.publish_state(entity.id, payload)  # optimistic
                logger.info("Operation mode set: %s (id=%s)", payload, mode_id)
            elif entity.write_via == "functiondata":
                try:
                    value = float(payload)
                    if value.is_integer():
                        value = int(value)
                except ValueError:
                    value = payload
                self._uhi.set_function_data(entity.key, value)
                self._mqtt.publish_state(entity.id, value)  # optimistic
                logger.info("Function data set: %s = %s", entity.key, value)
            else:
                logger.warning("Entity %s is not writable", entity_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("Write failed (%s): %s", entity_id, exc)

    # ---------------- Lifecycle ----------------
    def run(self) -> None:
        logger.info("UHI -> Home Assistant Bridge startet")
        logger.info("  UHI:    %s", self._cfg.uhi.base_url)
        logger.info("  Socket: %s", self._cfg.uhi.socket_url)
        logger.info("  MQTT:   %s", self._cfg.mqtt.url)

        self._mqtt.connect()
        self._mqtt.set_command_handler(self._handle_command)

        select_options: list[str] = []
        try:
            select_options = self._load_operation_modes()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Operation mode list not available: %s", exc)

        version = self._publish_version()
        device_info: dict = {}
        if version and version.get("uhi"):
            uhi = version["uhi"]
            device_info["sw_version"] = uhi.get("version")
            if uhi.get("mac"):
                device_info["mac"] = uhi["mac"]
                device_info["connections"] = [["mac", uhi["mac"]]]
        self._device_info = device_info

        self._mqtt.publish_discovery(self._entities, device_info, select_options)
        self._mqtt.publish_version_discovery(device_info)

        self._publish_operation_mode_state()

        self._uhi.on_operationdata(self._handle_operationdata)
        self._uhi.connect_socket()

        if self._cfg.uhi.initial_snapshot:
            self._initial_snapshot()

        logger.info("Bridge running. %d entities registered.", len(self._entities))

        last_version = 0.0
        last_state = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_version >= self._cfg.intervals.version_poll_s:
                self._publish_version()
                last_version = now
            if now - last_state >= self._cfg.intervals.state_poll_s:
                self._publish_operation_mode_state()
                last_state = now
            self._stop.wait(1.0)

    def shutdown(self, *_args) -> None:
        logger.info("Bridge shutting down...")
        self._stop.set()
        self._mqtt.close()
        self._uhi.close()


def main() -> None:
    bridge = Bridge()
    signal.signal(signal.SIGINT, bridge.shutdown)
    signal.signal(signal.SIGTERM, bridge.shutdown)
    try:
        bridge.run()
    except KeyboardInterrupt:
        bridge.shutdown()


if __name__ == "__main__":
    main()
