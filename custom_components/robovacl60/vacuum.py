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

"""Eufy Robovac vacuum platform.

This module provides the vacuum entity integration for Eufy Robovac devices.
"""
from __future__ import annotations
import ast
import base64
from datetime import timedelta
from enum import StrEnum
import json
import logging
import time
from typing import Any, Optional

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_MODEL,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_VACS, DOMAIN, PING_RATE, REFRESH_RATE, TIMEOUT
from .errors import getErrorMessage
from .vacuums.base import RobovacCommand, RoboVacEntityFeature, TuyaCodes, TUYA_CONSUMABLES_CODES
from .robovac import ModelNotSupportedException, RoboVac
from .tuyalocalapi import TuyaException

ATTR_BATTERY_ICON = "battery_icon"
ATTR_ERROR = "error"
ATTR_FAN_SPEED = "fan_speed"
ATTR_FAN_SPEED_LIST = "fan_speed_list"
ATTR_STATUS = "status"
ATTR_ERROR_CODE = "error_code"
ATTR_MODEL_CODE = "model_code"
ATTR_CLEANING_AREA = "cleaning_area"
ATTR_CLEANING_TIME = "cleaning_time"
ATTR_AUTO_RETURN = "auto_return"
ATTR_DO_NOT_DISTURB = "do_not_disturb"
ATTR_BOOST_IQ = "boost_iq"
ATTR_CONSUMABLES = "consumables"
ATTR_MODE = "mode"

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=REFRESH_RATE)
UPDATE_RETRIES = 3

def decode_mode_string(mode_raw: str) -> str:
    lookup = {
         "BBoCCAE=": "auto",
         "AggN": "pause",
         "AA==": "auto",
         "AggG": "home",
         "AggO": "auto",
         "AggB": "room",
         "AggC": "zone",
         "AggM": "auto",
    }
    return lookup.get(mode_raw, f"unknown ({mode_raw})")

def decode_status_string(status_raw: str) -> str:
    lookup = {
        "BgoAEAUyAA==": "cleaning", # auto_cleaning
        "BgoAEAVSAA==": "position", # auto_positioning
        "CAoAEAUyAggB": "paused", # auto_paused
        "CAoCCAEQBTIA": "cleaning", # room_cleaning
        "CAoCCAEQBVIA": "position", # room_positioning
        "CgoCCAEQBTICCAE=": "paused", # room_paused
        "CAoCCAIQBTIA": "cleaning", # zone_cleaning
        "CAoCCAIQBVIA": "position", # zone_positioning
        "CgoCCAIQBTICCAE=": "paused", # zone_paused
        "BAoAEAY=": "start_manual",
        "BBAHQgA=": "returning",
        "BBADGgA=": "charging",
        "BhADGgIIAQ==": "idle",
        "AA==": "standby",
        "AhAB": "sleeping",
    }
    return lookup.get(status_raw, f"unknown ({status_raw})")

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eufy RoboVac vacuum entities for this config entry."""
    # Pull your filtered list out of hass.data instead of entry.data
    vacuums_data = hass.data[DOMAIN][entry.entry_id][CONF_VACS]
    entities: list[RoboVacEntity] = []

    for vac_id, vac_cfg in vacuums_data.items():
        entity = RoboVacEntity(vac_cfg)
        entities.append(entity)
        # Replace the raw dict with your entity so sensors can find it later
        hass.data[DOMAIN][entry.entry_id][CONF_VACS][vac_id] = entity

    # Register all vacuums at once, polling immediately before the first interval
    async_add_entities(entities, update_before_add=True)


class RoboVacEntity(StateVacuumEntity):
    """Eufy Robovac vacuum entity.

    This class represents a Eufy Robovac vacuum cleaner in Home Assistant.
    It handles the communication with the vacuum via the Tuya local API and
    provides the necessary functionality to control and monitor the vacuum.
    """

    _attr_should_poll = True

    _attr_access_token: str | None = None
    # _attr_mac_address: str | None = None
    _attr_ip_address: str | None = None
    _attr_model_code: str | None = None
    _attr_cleaning_area: str | None = None
    _attr_cleaning_time: str | None = None
    _attr_auto_return: str | None = None
    _attr_do_not_disturb: str | None = None
    _attr_boost_iq: str | None = None
    _attr_consumables: str | None = None
    _attr_mode: str | None = None
    _attr_cmd_dps_raw: str | None = None
    _attr_mode_raw: str | None = None
    _attr_stat_dps_raw: str | None = None
    _attr_tuya_state_raw: str | None = None
    _attr_robovac_supported: int | None = None
    _attr_error_code: int | str | None = None
    _attr_tuya_state: int | str | None = None

    @property
    def robovac_supported(self) -> int | None:
        """Return the supported features of the vacuum cleaner."""
        return self._attr_robovac_supported

    @property
    def mode(self) -> str | None:
        """Return the cleaning mode of the vacuum cleaner."""
        return self._attr_mode
        
    @property
    def mode_raw(self) -> str | None:
        return self._attr_mode_raw

    @property
    def cmd_dps_raw(self) -> str | None:
        return self._attr_cmd_dps_raw

    @property
    def stat_dps_raw(self) -> str | None:
        return self._attr_stat_dps_raw

    @property
    def tuya_state_raw(self) -> str | None:
        return self._attr_tuya_state_raw

    @property
    def consumables(self) -> str | None:
        """Return the consumables status of the vacuum cleaner."""
        return self._attr_consumables

    @property
    def cleaning_area(self) -> str | None:
        """Return the cleaning area of the vacuum cleaner."""
        return self._attr_cleaning_area

    @property
    def cleaning_time(self) -> str | None:
        """Return the cleaning time of the vacuum cleaner."""
        return self._attr_cleaning_time

    @property
    def auto_return(self) -> str | None:
        """Return the auto_return mode of the vacuum cleaner."""
        return self._attr_auto_return

    @property
    def do_not_disturb(self) -> str | None:
        """Return the do_not_disturb mode of the vacuum cleaner."""
        return self._attr_do_not_disturb

    @property
    def boost_iq(self) -> str | None:
        """Return the boost_iq mode of the vacuum cleaner."""
        return self._attr_boost_iq

    @property
    def tuya_state(self) -> str | int | None:
        """Return the state of the vacuum cleaner.

        This property is for backward compatibility with tests.
        """
        return self._attr_tuya_state

    @tuya_state.setter
    def tuya_state(self, value: str | int | None) -> None:
        """Set the state of the vacuum cleaner.

        This setter is for backward compatibility with tests.
        """
        self._attr_tuya_state = value

    @property
    def error_code(self) -> int | str | None:
        """Return the error code of the vacuum cleaner.

        This property is for backward compatibility with tests.
        """
        return self._attr_error_code

    @error_code.setter
    def error_code(self, value: int | str | None) -> None:
        """Set the error code of the vacuum cleaner.

        This setter is for backward compatibility with tests.
        """
        self._attr_error_code = value

    @property
    def model_code(self) -> str | None:
        """Return the model code of the vacuum cleaner."""
        return self._attr_model_code

    @property
    def access_token(self) -> str | None:
        """Return the fan speed of the vacuum cleaner."""
        return self._attr_access_token

    @property
    def ip_address(self) -> str | None:
        """Return the ip address of the vacuum cleaner."""
        return self._attr_ip_address

    def _is_value_true(self, value: Any) -> bool:
        """Check if a value is considered 'true', either as a boolean or string.

        Args:
            value: The value to check.

        Returns:
            bool: True if the value is considered 'true', False otherwise.
        """
        if value is True:
            return True
        if isinstance(value, str):
            return value == "True" or value.lower() == "true"
        return False

    @property
    def activity(self) -> str:
        """Return current vacuum activity."""
        decoded_status = decode_status_string(self.tuya_state_raw or "")

        if (
            isinstance(self.error_code, (int, str))
            and str(self.error_code) not in [0, "no_error", None]
            and "unknown" in decoded_status.lower()
        ):
            _LOGGER.debug(
                "State changed to error. Error message: {}".format(
                    getErrorMessage(self.error_code)
                )
            )
            return VacuumActivity.ERROR

        if decoded_status:
            return decoded_status.lower()

        return VacuumActivity.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the device-specific state attributes of this vacuum."""
        data: dict[str, Any] = {}

        # Error attribute seems to generate a non-repeatable string for error conditions. Maybe token based?
        error_message = getErrorMessage(self._attr_error_code)

        # Filter out messages that just echo the raw code (no translation)
        if (
            error_message == self._attr_error_code
            or error_message in ["", None, "no_error", "Unknown error", "0"]
        ):
            data[ATTR_ERROR] = "None"
        else:
            data[ATTR_ERROR] = error_message


        data["id"] = self._attr_unique_id
        data["model"] = self._attr_model_code
        # data["mac_address"] = self._attr_mac_address
        data["ip_address"] = self._attr_ip_address

        if (
            self.robovac_supported is not None
            and self.robovac_supported & RoboVacEntityFeature.CLEANING_AREA
            and self.cleaning_area
        ):
            data[ATTR_CLEANING_AREA] = self.cleaning_area
        if (
            self.robovac_supported is not None
            and self.robovac_supported & RoboVacEntityFeature.CLEANING_TIME
            and self.cleaning_time
        ):
            data[ATTR_CLEANING_TIME] = self.cleaning_time
        if (
            self.robovac_supported is not None
            and self.robovac_supported & RoboVacEntityFeature.AUTO_RETURN
            and self.auto_return
        ):
            data[ATTR_AUTO_RETURN] = self.auto_return
        if (
            self.robovac_supported is not None
            and self.robovac_supported & RoboVacEntityFeature.DO_NOT_DISTURB
            and self.do_not_disturb
        ):
            data[ATTR_DO_NOT_DISTURB] = self.do_not_disturb
        if (
            self.robovac_supported is not None
            and self.robovac_supported & RoboVacEntityFeature.BOOST_IQ
            and self.boost_iq
        ):
            data[ATTR_BOOST_IQ] = self.boost_iq
        if (
            self.robovac_supported is not None
            and self.robovac_supported & RoboVacEntityFeature.CONSUMABLES
            and self.consumables
        ):
            data[ATTR_CONSUMABLES] = self.consumables

        if self._attr_battery_level is not None:
            data["battery_level"] = self._attr_battery_level
            data["battery_icon"] = "mdi:battery-alert" if self._attr_battery_level <= 10 else "mdi:battery"

        if self.fan_speed:
            data[ATTR_FAN_SPEED] = self.fan_speed

        if self.mode:
            data[ATTR_MODE] = self.mode
        else:
            data[ATTR_MODE] = "Unavailable"

        if self.cmd_dps_raw is not None:
            data["cmd_dps_raw"] = self.cmd_dps_raw

        if self.mode_raw:
            data["mode_raw"] = self.mode_raw
        else:
            data["mode_raw"] = "Unavailable"

        if self.stat_dps_raw is not None:
            data["stat_dps_raw"] = self.stat_dps_raw

        if self.tuya_state:
            data[ATTR_STATUS] = self.tuya_state
        else:
            data[ATTR_STATUS] = "Unknown"

        if self.tuya_state_raw:
            data["status_raw"] = self.tuya_state_raw
        else:
            data["status_raw"] = "Unavailable"

        return data

    def __init__(self, item: dict[str, Any]) -> None:
        """Initialize Eufy Robovac entity.

        This method initializes the vacuum entity with the configuration provided
        and establishes a connection to the physical device via the Tuya local API.

        Args:
            item: Dictionary containing vacuum configuration including name, ID,
                  model, IP address, access token, and other required parameters.
        """
        super().__init__()

        # Initialize basic attributes
        self._attr_battery_level = 0
        self._attr_name = item[CONF_NAME]
        self._attr_unique_id = item[CONF_ID]
        self._attr_model_code = item[CONF_MODEL]
        self._attr_ip_address = item[CONF_IP_ADDRESS]
        self._attr_access_token = item[CONF_ACCESS_TOKEN]
        self.vacuum: Optional[RoboVac] = None
        self.update_failures = 0
        self._attr_stat_dps_raw = None
        self.tuyastatus: dict[str, Any] | None = None

        # Initialize the RoboVac connection
        try:
            # Extract model code prefix for device identification
            model_code_prefix = ""
            if self.model_code is not None:
                model_code_prefix = self.model_code[0:5]

            # Create the RoboVac instance
            self.vacuum = RoboVac(
                device_id=self.unique_id,
                host=self.ip_address,
                local_key=self.access_token,
                timeout=TIMEOUT,
                ping_interval=PING_RATE,
                model_code=model_code_prefix,
                update_entity_state=self.pushed_update_handler,
            )
            _LOGGER.debug(
                "Initialized RoboVac connection for %s (model: %s)",
                self._attr_name,
                self._attr_model_code
            )
        except ModelNotSupportedException:
            _LOGGER.error(
                "Model %s is not supported",
                self._attr_model_code
            )
            self._attr_error_code = "UNSUPPORTED_MODEL"

        # Set supported features if vacuum was initialized successfully
        if self.vacuum is not None:
            # Get the supported features from the vacuum
            features = int(self.vacuum.getHomeAssistantFeatures())
            self._attr_supported_features = VacuumEntityFeature(features)
            self._attr_robovac_supported = self.vacuum.getRoboVacFeatures()
            self._attr_fan_speed_list = self.vacuum.getFanSpeeds()

            _LOGGER.debug(
                "Vacuum %s supports features: %s",
                self._attr_name,
                self._attr_supported_features
            )
        else:
            # Set default values if vacuum initialization failed
            self._attr_supported_features = VacuumEntityFeature(0)
            self._attr_robovac_supported = 0
            self._attr_fan_speed_list = []
            _LOGGER.warning(
                "Vacuum %s initialization failed, features not available",
                self._attr_name
            )

        # Initialize additional attributes
        self._attr_mode = None
        self._attr_consumables = None

        # Set up device info for Home Assistant device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item[CONF_ID])},
            name=item[CONF_NAME],
            manufacturer="Eufy",
            model=item[CONF_DESCRIPTION],
            connections={
                (CONNECTION_NETWORK_MAC, item[CONF_MAC]),
            },
        )

    async def async_update(self) -> None:
        """Synchronize state from the vacuum.

        This method is called periodically by Home Assistant to update the entity state.
        It retrieves the current state from the vacuum via the Tuya API and updates
        the entity attributes accordingly.

        If the vacuum is not supported or the IP address is not set, the method returns
        early. If the update fails, it increments a failure counter and sets an error
        code after a certain number of retries.
        """
        # Skip update if the model is not supported
        if self._attr_error_code == "UNSUPPORTED_MODEL":
            _LOGGER.debug("Skipping update for unsupported model: %s", self._attr_model_code)
            return

        # Skip update if the IP address is not set
        if not self.ip_address:
            _LOGGER.warning("Cannot update vacuum %s: IP address not set", self._attr_name)
            self._attr_error_code = "IP_ADDRESS"
            return

        # Skip update if vacuum object is not initialized
        if self.vacuum is None:
            _LOGGER.warning("Cannot update %s: vacuum not initialized", self._attr_name)
            self._attr_error_code = "INITIALIZATION_FAILED"
            return

        # Try to update the vacuum state
        try:
            await self.vacuum.async_get()
            self.update_failures = 0
            self.update_entity_values()
            _LOGGER.debug("Successfully updated vacuum %s", self._attr_name)
        except TuyaException as e:
            self.update_failures += 1
            _LOGGER.warning(
                "Failed to update vacuum %s. Failure count: %d/%d. Error: %s",
                self._attr_name,
                self.update_failures,
                UPDATE_RETRIES,
                str(e)
            )

            # Set error code after maximum retries
            if self.update_failures >= UPDATE_RETRIES:
                self._attr_error_code = "CONNECTION_FAILED"
                _LOGGER.error(
                    "Maximum update retries reached for vacuum %s. Marking as unavailable",
                    self._attr_name
                )

    async def pushed_update_handler(self) -> None:
        """Handle updates pushed from the vacuum.

        This method is called when the vacuum sends an update via the Tuya API.
        It updates the entity values and writes the state to Home Assistant.
        """
        self.update_entity_values()
        self.async_write_ha_state()

    def update_entity_values(self) -> None:
        """Update entity values from the vacuum's data points.

        This method updates all the entity attributes based on the current
        state of the vacuum's data points (DPS). It handles different vacuum models
        and ensures that all values are properly typed and formatted.

        The method is called both during periodic updates and when pushed updates
        are received from the vacuum.
        """
        # Skip if vacuum is not initialized
        if self.vacuum is None:
            _LOGGER.warning("Cannot update entity values: vacuum not initialized")
            return

        # Get the current data points from the vacuum
        self.tuyastatus = self.vacuum._dps

        if self.tuyastatus is None:
            _LOGGER.warning("Cannot update entity values: no data points available")
            return

        _LOGGER.debug("Updating entity values from data points: %s", self.tuyastatus)

        # Preserve cmd_dps_raw if 152 is present
        if "152" in self.tuyastatus:
            self._attr_cmd_dps_raw = "152"

        # Update common attributes for all models
        self._update_battery_level()
        self._update_state_and_error()
        self._update_mode_and_fan_speed()

        # Update model-specific attributes
        self._update_cleaning_stats()

    def _get_dps_code(self, code_name: str) -> str:
        """Get the DPS code for a specific function.

        First checks for model-specific DPS codes, then falls back to defaults.

        Args:
            code_name: The name of the code to retrieve, e.g., "BATTERY_LEVEL"

        Returns:
            The DPS code as a string
        """
        if self.vacuum is None:
            enum_value = getattr(TuyaCodes, code_name, None)
            return enum_value.value if enum_value else ""

        model_dps_codes = self.vacuum.getDpsCodes()
        if code_name in model_dps_codes:
            return model_dps_codes[code_name]

        enum_value = getattr(TuyaCodes, code_name, None)
        return enum_value.value if enum_value else ""

    def _get_consumables_codes(self) -> list[str]:
        """Get the consumables DPS codes.

        First checks for model-specific codes, then falls back to defaults.

        Returns:
            A list of DPS codes for consumables
        """
        if self.vacuum is None:
            return TUYA_CONSUMABLES_CODES

        # Get model-specific DPS codes
        model_dps_codes = self.vacuum.getDpsCodes()

        # Return model-specific code if available, otherwise use default
        if "CONSUMABLES" in model_dps_codes:
            # Model-specific consumables can be a list or comma-separated string
            consumables = model_dps_codes["CONSUMABLES"]
            if isinstance(consumables, str):
                return [code.strip() for code in consumables.split(",")]
            return consumables

        # Fall back to default codes
        return TUYA_CONSUMABLES_CODES

    def _update_battery_level(self) -> None:
        """Update the battery level attribute."""
        if self.tuyastatus is None:
            _LOGGER.warning("No tuyastatus available during battery DPS [163] update")
            return

        if "163" not in self.tuyastatus:
            _LOGGER.debug("DPS [163] key absent from tuyastatus: %s", self.tuyastatus)
            self._attr_battery_level = 0
            return

        battery_level = self.tuyastatus.get("163")

        if battery_level is not None:
            try:
                new_battery_level = max(0, min(100, int(battery_level)))
                if new_battery_level != self._attr_battery_level:
                    _LOGGER.debug("Battery level changed from %s to %s", self._attr_battery_level, new_battery_level)
                self._attr_battery_level = new_battery_level
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid battery level DPS [163] value: %s", battery_level)
                self._attr_battery_level = 0
        else:
            _LOGGER.warning("Battery DPS [163] was missing or None")
            self._attr_battery_level = 0

    def _update_state_and_error(self) -> None:
        """Update the state and error code attributes."""
        status_raw = self.tuyastatus.get("153")
        _LOGGER.debug("Raw DPS [153] status: %s", status_raw)

        self._attr_tuya_state_raw = status_raw if status_raw is not None else ""
        self._attr_stat_dps_raw = "153" if status_raw is not None else None

        if status_raw:
            self._attr_tuya_state = decode_status_string(status_raw)
        else:
            self._attr_tuya_state = "Unknown"

        _LOGGER.debug("Decoded DPS [153] status: %s", self._attr_tuya_state)

        error_code = self.tuyastatus.get("177")
        self._attr_error_code = error_code if error_code is not None else 0

    def _update_mode_and_fan_speed(self) -> None:
        """Update the mode and fan speed attributes."""
        if self.tuyastatus is None:
            _LOGGER.warning("No tuyastatus available in _update_mode_and_fan_speed")
            return

        # Get mode and fan speed from data points using hardcoded DPS
        mode = self.tuyastatus.get("152")
        fan_speed = self.tuyastatus.get("158")

        _LOGGER.debug("Raw DPS [152] mode: %s", mode)
        _LOGGER.debug("Raw DPS [158] fan speed: %s", fan_speed)

        # Preserve raw mode for traceability
        self._attr_mode_raw = mode if mode is not None else ""

        # Decode L60 SES mode payload if present
        if mode:
            self._attr_mode = decode_mode_string(mode)
        else:
            self._attr_mode = "N/A"


        # Update fan speed attribute
        self._attr_fan_speed = fan_speed if fan_speed is not None else ""

        # Format fan speed for display consistency
        if isinstance(self.fan_speed, str):
            if self.fan_speed == "No_suction":
                self._attr_fan_speed = "No Suction"
            elif self.fan_speed == "Boost_IQ":
                self._attr_fan_speed = "Boost IQ"
            elif self.fan_speed == "Quiet":
                self._attr_fan_speed = "Pure"

        if not self.fan_speed:
            _LOGGER.debug("Final fan speed DPS [158] attribute is empty or unknown")
        else:
            _LOGGER.debug("Final fan speed DPS [158] attribute set to: %s", self.fan_speed)

    def _update_cleaning_stats(self) -> None:
        """Update cleaning statistics (area and time)."""
        if self.tuyastatus is None:
            return
            
        self._log_all_dps_codes()  # Logs all DPS codes received from the vacuum

        # Keep dynamic lookup for unknown codes
        cleaning_area = self.tuyastatus.get(self._get_dps_code("CLEANING_AREA"))
        if cleaning_area is not None:
            self._attr_cleaning_area = str(cleaning_area)

        cleaning_time = self.tuyastatus.get(self._get_dps_code("CLEANING_TIME"))
        if cleaning_time is not None:
            self._attr_cleaning_time = str(cleaning_time)

            # Use hardcoded DPS for known attributes
            auto_return = self.tuyastatus.get(self._get_dps_code("AUTO_RETURN"))  # Still unknown
            self._attr_auto_return = str(auto_return) if auto_return is not None else None

            do_not_disturb = self.tuyastatus.get(157)
            self._attr_do_not_disturb = str(do_not_disturb) if do_not_disturb is not None else None

            boost_iq = self.tuyastatus.get(159)
            self._attr_boost_iq = str(boost_iq) if boost_iq is not None else None

        # Handle consumables with hardcoded DPS
        if (
            isinstance(self.robovac_supported, int)
            and self.robovac_supported & RoboVacEntityFeature.CONSUMABLES
            and self.tuyastatus is not None
        ):
            for CONSUMABLE_CODE in ["168"]:
                if (
                    CONSUMABLE_CODE in self.tuyastatus
                    and self.tuyastatus.get(CONSUMABLE_CODE) is not None
                ):
                    consumable_data = self.tuyastatus.get(CONSUMABLE_CODE)
                    if isinstance(consumable_data, str):
                        try:
                            consumables = ast.literal_eval(
                                base64.b64decode(consumable_data).decode("ascii")
                            )
                            if (
                                "consumable" in consumables
                                and "duration" in consumables["consumable"]
                            ):
                                self._attr_consumables = consumables["consumable"]["duration"]
                        except Exception as e:
                            _LOGGER.warning("Failed to decode consumable data: %s", str(e))
                            
    def _log_all_dps_codes(self) -> None:
        """Log all DPS codes and values for inspection."""
        if self.tuyastatus is None:
            _LOGGER.warning("No tuyastatus available to log.")
            return

        for dps_code, value in self.tuyastatus.items():
            _LOGGER.debug(f"DPS code {dps_code}: {value}")

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner.

        Args:
            **kwargs: Additional arguments passed from Home Assistant.
        """
        _LOGGER.info("Locate Pressed")
        if self.vacuum is None:
            _LOGGER.error("Cannot locate vacuum: vacuum not initialized")
            return

        if self.tuyastatus is not None and self.tuyastatus.get(160):
            await self.vacuum.async_set({160: False})
        else:
            await self.vacuum.async_set({160: True})

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock.

        Args:
            **kwargs: Additional arguments passed from Home Assistant.
        """
        _LOGGER.info("Return home Pressed")
        if self.vacuum is None:
            _LOGGER.error("Cannot return to base: vacuum not initialized")
            return

        await self.vacuum.async_set({
            152: "AggG"  # Send 'return to dock' as a MODE command
        })

    async def async_start(self, **kwargs: Any) -> None:
        """Start the vacuum cleaner in auto mode."""
        self._attr_mode = "auto"

        if self.vacuum is None:
            _LOGGER.error("Cannot start vacuum: vacuum not initialized")
            return

        dps_key = self._get_dps_code("MODE")
        self._attr_cmd_dps_raw = dps_key

        _LOGGER.debug("Sending hardcoded L60 SES start command")
        await self.vacuum.async_set({
            dps_key: "BBoCCAE="
        })

    async def async_pause(self, **kwargs: Any) -> None:
        """Pause the vacuum cleaner using direct payload for L60 SES."""
        if self.vacuum is None:
            _LOGGER.error("Cannot pause vacuum: vacuum not initialized")
            return

        _LOGGER.debug("Sending pause command to vacuum")
        await self.vacuum.async_set({
            "152": "AggN"
        })

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the vacuum cleaner using direct payload for L60 SES."""
        _LOGGER.info("Stop command issued")
        if self.vacuum is None:
            _LOGGER.error("Cannot stop vacuum: vacuum not initialized")
            return

        _LOGGER.debug("Sending stop command to vacuum")
        await self.vacuum.async_set({
           "152": "AggN"
        })

    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean using direct payload for L60 SES."""
        _LOGGER.info("Spot Clean Pressed")
        if self.vacuum is None:
            _LOGGER.error("Cannot clean spot: vacuum not initialized")
            return

        _LOGGER.debug("Sending spot clean command to vacuum")
        await self.vacuum.async_set({
            "152": "AA=="
        })

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed using direct payload for L60 SES."""
        _LOGGER.info("Fan Speed Selected")

        if self.vacuum is None:
            _LOGGER.error("Cannot set fan speed: vacuum not initialized")
            return

        # Normalize fan speed input to match T2277 values
        normalized_fan_speed = fan_speed.lower().replace(" ", "_")
        value_map = {
            "quiet": "Quiet",
            "standard": "Standard",
            "turbo": "Turbo",
            "max": "Max",
            "boost_iq": "Boost_IQ"
        }

        command_value = value_map.get(normalized_fan_speed)
        if command_value is None:
            _LOGGER.warning("Unsupported fan speed: %s", fan_speed)
            return

        _LOGGER.debug("Sending fan speed '%s' with payload '%s'", normalized_fan_speed, command_value)
        await self.vacuum.async_set({
            "158": command_value
        })

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list | None = None,
        **kwargs: Any
    ) -> None:
        """Send a command to a vacuum cleaner.

        Args:
            command: The command to send.
            params: Optional parameters for the command.
            **kwargs: Additional arguments passed from Home Assistant.
        """
        _LOGGER.info("Send Command %s Pressed", command)
        if self.vacuum is None:
            _LOGGER.error("Cannot send command: vacuum not initialized")
            return

        if command == "edgeClean":
            await self.vacuum.async_set({
                self._get_dps_code("MODE"): self.vacuum.getRoboVacCommandValue(RobovacCommand.MODE, "edge")
            })
        elif command == "smallRoomClean":
            await self.vacuum.async_set({
                self._get_dps_code("MODE"): self.vacuum.getRoboVacCommandValue(RobovacCommand.MODE, "small_room")
            })
        elif command == "autoClean":
            await self.vacuum.async_set({
                self._get_dps_code("MODE"): self.vacuum.getRoboVacCommandValue(RobovacCommand.MODE, "auto")
            })
        elif command == "autoReturn":
            await self.vacuum.async_set({
                self._get_dps_code("AUTO_RETURN"): self._is_value_true(self.auto_return)
            })
        elif command == "doNotDisturb":
            await self.vacuum.async_set({
                self._get_dps_code("DO_NOT_DISTURB"): self._is_value_true(self.do_not_disturb)
            })
            if self._is_value_true(self.do_not_disturb):
                await self.vacuum.async_set({
                    self._get_dps_code("DO_NOT_DISTURB"): False
                })
            else:
                await self.vacuum.async_set({
                    self._get_dps_code("DO_NOT_DISTURB"): True
                })
        elif command == "boostIQ":
            await self.vacuum.async_set({
                self._get_dps_code("BOOST_IQ"): self._is_value_true(self.boost_iq)
            })
        elif command == "roomClean" and params is not None and isinstance(params, dict):
            room_ids = params.get("roomIds", [1])
            count = params.get("count", 1)
            clean_request = {"roomIds": room_ids, "cleanTimes": count}
            method_call = {
                "method": "selectRoomsClean",
                "data": clean_request,
                "timestamp": round(time.time() * 1000),
            }
            json_str = json.dumps(method_call, separators=(",", ":"))
            base64_str = base64.b64encode(json_str.encode("utf8")).decode("utf8")
            _LOGGER.info("roomClean call %s", json_str)
            await self.vacuum.async_set({TuyaCodes.ROOM_CLEAN: base64_str})

    async def async_will_remove_from_hass(self) -> None:
        """Handle removal from Home Assistant."""
        if self.vacuum is None:
            _LOGGER.debug("Cannot disable vacuum: vacuum not initialized")
            return

        await self.vacuum.async_disable()
