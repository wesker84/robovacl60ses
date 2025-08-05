import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, CONF_NAME, CONF_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_VACS, DOMAIN, REFRESH_RATE
from .vacuums.base import TuyaCodes

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=REFRESH_RATE)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up battery sensors for each valid RoboVac."""
    vacuums = hass.data[DOMAIN][config_entry.entry_id][CONF_VACS]
    entities: list[RobovacBatterySensor] = []

    for vac_id, vac_data in vacuums.items():
        entities.append(RobovacBatterySensor(config_entry.entry_id, vac_data))

    # Tell HA to poll right away before first update()
    async_add_entities(entities, update_before_add=True)


class RobovacBatterySensor(SensorEntity):
    """Representation of a Eufy RoboVac Battery Sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_should_poll = True

    def __init__(self, entry_id: str, item: dict) -> None:
        """Initialize the sensor with its entry ID and config dict."""
        self.entry_id = entry_id
        self.robovac_id = item[CONF_ID]
        # e.g. “abc123_battery”
        self._attr_unique_id = f"{self.robovac_id}_battery"
        # This will show up as “RoboVac L60 Battery” (or whatever you named it)
        self._attr_name = f"{item[CONF_NAME]} Battery"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.robovac_id)},
            name=item[CONF_NAME],
            manufacturer="Eufy",
            model=item.get("model"),
        )

    @property
    def scan_interval(self) -> timedelta:
        """Force HA to poll at our REFRESH_RATE interval."""
        return SCAN_INTERVAL

    async def async_update(self) -> None:
        """Fetch the latest battery level from the saved vacuum client."""
        try:
            vac_client = self.hass.data[DOMAIN][self.entry_id][CONF_VACS].get(self.robovac_id)
            if vac_client and vac_client.tuyastatus:
                level = vac_client.tuyastatus.get(TuyaCodes.BATTERY_LEVEL)
                self._attr_native_value = level
                self._attr_available = True
            else:
                _LOGGER.debug("No status available for %s", self.robovac_id)
                self._attr_available = False
        except Exception as exc:
            _LOGGER.error("Error updating battery sensor %s: %s", self.robovac_id, exc)
            self._attr_available = False
