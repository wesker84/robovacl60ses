# Copyright 2022 Brendan McCluskey
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The Eufy Robovac integration."""

from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform, CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant

from .const import CONF_VACS, CONF_MODEL, DOMAIN
from .tuyalocaldiscovery import TuyaLocalDiscovery
from .vacuum import async_setup_entry as vacuum_setup  # needed by HA forwarding
from .sensor import async_setup_entry as sensor_setup  # needed by HA forwarding

PLATFORMS = [Platform.VACUUM, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Eufy Robovac component."""
    hass.data.setdefault(DOMAIN, {CONF_VACS: {}})

    async def update_device(device: Dict[str, Any]) -> None:
        entry = async_get_config_entry_for_device(hass, device["gwId"])
        if entry is None or not entry.state.recoverable:
            return

        hass_data = entry.data.copy()
        if (
            device["gwId"] in hass_data[CONF_VACS]
            and device.get("ip") is not None
            and hass_data[CONF_VACS][device["gwId"]].get("autodiscovery", True)
        ):
            if hass_data[CONF_VACS][device["gwId"]][CONF_IP_ADDRESS] != device["ip"]:
                hass_data[CONF_VACS][device["gwId"]][CONF_IP_ADDRESS] = device["ip"]
                if device.get("mac"):
                    hass_data[CONF_VACS][device["gwId"]]["mac_address"] = device["mac"]

                hass.config_entries.async_update_entry(entry, data=hass_data)
                await hass.config_entries.async_reload(entry.entry_id)
                _LOGGER.debug(
                    "Updated ip address of %s to %s",
                    device["gwId"],
                    device["ip"],
                )

    tuyalocaldiscovery = TuyaLocalDiscovery(update_device)
    try:
        await tuyalocaldiscovery.start()
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, tuyalocaldiscovery.close
        )
    except Exception:
        _LOGGER.exception("Failed to set up discovery")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Eufy Robovac config entry (L60 SES only)."""
    SUPPORTED_MODEL_PREFIX = "T2277"  # L60 SES model series

    original_vacs = entry.data.get(CONF_VACS, {})
    valid_vacs: dict[str, Any] = {}

    for vac_id, vac_data in original_vacs.items():
        model = vac_data.get(CONF_MODEL, "")
        if model.startswith(SUPPORTED_MODEL_PREFIX):
            valid_vacs[vac_id] = vac_data
        else:
            _LOGGER.info("Skipping unsupported model for vac %s: %s", vac_id, model)

    if not valid_vacs:
        _LOGGER.warning("No supported L60 vacuums found in this config entry.")
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {CONF_VACS: valid_vacs}

    # Forward setup to each platform
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.VACUUM])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def async_get_config_entry_for_device(
    hass: HomeAssistant, device_id: str
) -> Optional[ConfigEntry]:
    """Find the config entry for a specific device ID."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if device_id in entry.data[CONF_VACS]:
            return entry
    return None
