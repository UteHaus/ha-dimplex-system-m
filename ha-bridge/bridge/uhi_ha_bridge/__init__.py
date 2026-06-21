"""UHI -> Home Assistant bridge (test setup).

Reads heat pump data from UHI via existing endpoints/socket and
publishes it to Home Assistant through MQTT discovery. Writes HA
commands back via existing UHI REST endpoints.

NO changes are made to UHI.
"""

__version__ = "0.1.0"
