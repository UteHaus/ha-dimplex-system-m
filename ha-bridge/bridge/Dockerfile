# UHI -> Home Assistant Bridge (Python + uv)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Abhaengigkeiten zuerst (besseres Layer-Caching)
COPY pyproject.toml ./
COPY uhi_ha_bridge ./uhi_ha_bridge

# Virtuelle Umgebung im Projekt erstellen und Paket installieren
RUN uv sync --no-dev || uv pip install --system .

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "python", "-m", "uhi_ha_bridge"]
