"""
Support for water heaters connected to Bosch thermostat.

For more details about this platform, please refer to the documentation at...
"""
import logging
from homeassistant.helpers.dispatcher import async_dispatcher_send
from bosch_thermostat_client.const import GATEWAY, SETPOINT

from homeassistant.helpers import entity_platform
from homeassistant.helpers.config_validation import (  # noqa: F401
    PLATFORM_SCHEMA,
    PLATFORM_SCHEMA_BASE,
)

from homeassistant.components.water_heater import (
    STATE_OFF,
    SUPPORT_OPERATION_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    WaterHeaterEntity,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
)


from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS

from .const import (
    DOMAIN,
    SIGNAL_DHW_UPDATE_BOSCH,
    UNITS_CONVERTER,
    UUID,
    WATER_HEATER,
    SWITCHPOINT,
    SIGNAL_BOSCH,
    SERVICE_CHARGE_SCHEMA,
    SERVICE_CHARGE_START,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    CHARGE,
    BOSCH_STATE,
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS_HEATER = SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Bosch Water heater from a config entry."""
    uuid = config_entry.data[UUID]
    data = hass.data[DOMAIN][uuid]
    data[WATER_HEATER] = [
        BoschWaterHeater(hass, uuid, dhw, data[GATEWAY])
        for dhw in data[GATEWAY].dhw_circuits
    ]
    async_add_entities(data[WATER_HEATER])
    async_dispatcher_send(hass, SIGNAL_BOSCH)
    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
        SERVICE_CHARGE_START, SERVICE_CHARGE_SCHEMA, "service_charge"
    )
    return True


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Bosch Thermostat Platform."""
    pass


class BoschWaterHeater(WaterHeaterEntity):
    """Representation of an EcoNet water heater."""

    def __init__(self, hass, uuid, dhw, gateway):
        """Initialize the water heater."""
        self.hass = hass
        self._dhw = dhw
        self._name = self._dhw.name
        self._uuid = uuid
        self._unique_id = self._name + self._uuid
        self._gateway = gateway
        self._mode = None
        self._state = None
        self._target_temperature = None
        self._current_temperature = None
        self._current_setpoint = None
        self._temperature_units = TEMP_CELSIUS
        self._max_temp = DEFAULT_MAX_TEMP
        self._low_temp = DEFAULT_MIN_TEMP
        self._target_temp_off = 0
        self._operation_list = []

    async def async_added_to_hass(self):
        """Register callbacks."""
        self.hass.helpers.dispatcher.async_dispatcher_connect(
            SIGNAL_DHW_UPDATE_BOSCH, self.update
        )

    async def service_charge(self, value):
        """Set charge of DHW device. Upstream lib doesn't check if value is proper!"""
        _LOGGER.info("Setting %s %s with value %s", self._name, CHARGE, value)
        await self._dhw.set_service_call(CHARGE, value)

    @property
    def name(self):
        """Return the device name."""
        return self._name

    @property
    def bosch_object(self):
        """Return upstream component. Used for refreshing."""
        return self._dhw

    @property
    def unique_id(self):
        """Return unique ID for this device."""
        return self._unique_id

    @property
    def device_info(self):
        """Get attributes about the device."""
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "manufacturer": self._gateway.device_model,
            "model": self._gateway.device_type,
            "name": "Water heater " + self._name,
            "sw_version": self._gateway.firmware,
            "via_hub": (DOMAIN, self._uuid),
        }

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._temperature_units

    @property
    def state_attributes(self):
        data = super().state_attributes
        data.pop(ATTR_TARGET_TEMP_HIGH, None)
        data.pop(ATTR_TARGET_TEMP_LOW, None)
        data[SETPOINT] = self._dhw.setpoint
        data[SWITCHPOINT] = self._dhw.schedule.active_program
        data[BOSCH_STATE] = self._state
        return data

    @property
    def device_state_attributes(self):
        """Return the optional device state attributes."""
        data = {"target_temp_step": 1}
        return data

    @property
    def current_operation(self):
        """
        Return current operation as one of the following.
        ["eco", "heat_pump", "high_demand", "electric_only"]
        """
        return self._mode

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

    @property
    def supported_features(self):
        """Return the list of supported features."""
        if self._dhw.ha_mode == STATE_OFF or self._dhw.setpoint == STATE_OFF:
            return SUPPORT_OPERATION_MODE
        return SUPPORT_FLAGS_HEATER

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp and target_temp != self._target_temperature:
            await self._dhw.set_temperature(target_temp)
        else:
            _LOGGER.error("A target temperature must be provided")

    async def async_set_operation_mode(self, operation_mode):
        """Set operation mode."""
        _LOGGER.debug(f"Setting operation mode of {self._name} to {operation_mode}.")
        status = await self.bosch_object.set_ha_mode(operation_mode)
        if status > 0:
            return True
        return False

    def update(self):
        """Get the latest date."""
        _LOGGER.debug("Updating Bosch water_heater.")
        if not self._dhw or not self._dhw.update_initialized:
            return
        self._temperature_units = UNITS_CONVERTER.get(self._dhw.temp_units if self._dhw.temp_units else 'C')
        if (
            self._state != self._dhw.state
            or self._operation_list == self._dhw.ha_modes
            or self._current_temperature != self._dhw.current_temp
            or self._low_temp != self._dhw.min_temp
            or self._max_temp != self._dhw.max_temp
        ):
            self._state = self._dhw.state
            self._target_temperature = self._dhw.target_temperature
            self._current_temperature = self._dhw.current_temp
            self._operation_list = self._dhw.ha_modes
            self._mode = self._dhw.ha_mode
            self._low_temp = self._dhw.min_temp
            self._max_temp = self._dhw.max_temp
            self.async_schedule_update_ha_state()

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._low_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self._max_temp
