# Makefile fuer die UHI -> Home Assistant Bridge
# Aufruf z.B.:  make run-bridge

BRIDGE_DIR := bridge
UV         := uv

.DEFAULT_GOAL := help

.PHONY: help sync run-bridge run-bridge-mqtt compose-up compose-down logs clean-mqtt

help: ## Zeigt diese Hilfe
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

sync: ## Python-Abhaengigkeiten mit uv installieren
	cd $(BRIDGE_DIR) && $(UV) sync

run-bridge: sync ## Bridge im Test-Modus starten (ohne MQTT, Werte nur im Log)
	cd $(BRIDGE_DIR) && MQTT_ENABLED=false $(UV) run python -m uhi_ha_bridge

run-bridge-mqtt: sync ## Bridge mit MQTT-Broker starten
	cd $(BRIDGE_DIR) && MQTT_ENABLED=true $(UV) run python -m uhi_ha_bridge

compose-up: ## Mosquitto + Home Assistant + Bridge via Docker starten
	docker compose up -d --build

compose-down: ## Docker-Stack stoppen
	docker compose down

logs: ## Logs des Docker-Stacks anzeigen
	docker compose logs -f

clean-mqtt: ## Alte retained Discovery-/State-Topics aus Mosquitto loeschen
	@echo "Entferne retained Topics unter homeassistant/# und uhi/# ..."
	docker compose exec -T mosquitto \
		mosquitto_sub -t 'homeassistant/#' -t 'uhi/#' --remove-retained --retained-only -W 3 || true
	@echo "Fertig. Bridge neu starten, damit sie frisch publiziert."
