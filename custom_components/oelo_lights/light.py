"""Light platform for the Oelo Lights integration.

Provides light entities for each Oelo Lights zone.

**Key Features:**
- Dynamic effect list (shows only captured patterns from controller)
- Pattern application via effect attribute (Home Assistant native)
- RGB color and brightness control
- Automatic pattern updates when patterns are captured/renamed/deleted
- Spotlight plan support (handles 40-LED controller limitation)

**Pattern Workflow:**
- Patterns are created in Oelo app, then captured in Home Assistant
- Captured patterns appear in effect list for all zones
- Apply patterns via effect dropdown or service calls

**Refresh:**
- Use standard `homeassistant.update_entity` service
- Entity implements `async_update()` for coordinator refresh
"""

from __future__ import annotations
import logging
import asyncio
import aiohttp
import async_timeout
import urllib.parse
from typing import Any
from homeassistant.const import CONF_IP_ADDRESS, STATE_ON
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
from homeassistant.components.light import (
    ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGB_COLOR, ColorMode, LightEntity, LightEntityFeature
)
from datetime import timedelta

from .const import (
    DOMAIN,
    DEFAULT_SPOTLIGHT_PLAN_LIGHTS,
    DEFAULT_MAX_LEDS,
    DEFAULT_ZONES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_COMMAND_TIMEOUT,
    CONF_ZONES,
    CONF_POLL_INTERVAL,
    CONF_AUTO_POLL,
    CONF_COMMAND_TIMEOUT,
)
from .pattern_storage import PatternStorage
from .pattern_utils import build_pattern_url, normalize_led_indices

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_BASE = f"{DOMAIN}_entity_data"
STORAGE_VERSION = 1

class OeloDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, ip: str, poll_interval: int = 300, command_timeout: int = 10) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Oelo Controller {ip}",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.session = session
        self.ip = ip
        self.timeout = command_timeout

    async def _async_update_data(self):
        url = f"http://{self.ip}/getController"
        timeout_seconds = getattr(self, "timeout", 10)
        try:
            async with async_timeout.timeout(timeout_seconds):
                async with self.session.get(url) as response:
                    response.raise_for_status()
                    data = await response.json(content_type=None)
                    if not isinstance(data, list):
                        raise UpdateFailed("Controller did not return a list")
                    return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Oelo controller: {err}")

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    ip_address = entry.data[CONF_IP_ADDRESS]
    session = aiohttp_client.async_get_clientsession(hass)
    
    # Get poll interval and timeout from options
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    command_timeout = entry.options.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT)
    auto_poll = entry.options.get(CONF_AUTO_POLL, True)

    coordinator = OeloDataUpdateCoordinator(hass, session, ip_address, poll_interval, command_timeout)
    
    # Only do initial refresh if auto polling is enabled
    if auto_poll:
        await coordinator.async_config_entry_first_refresh()

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    storage_key_for_entry = f"{STORAGE_KEY_BASE}_{entry.entry_id}"
    store = Store(hass, STORAGE_VERSION, storage_key_for_entry)
    stored_entity_data = await store.async_load() or {}

    # Initialize pattern storage
    pattern_storage = PatternStorage(hass, entry.entry_id)
    
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "store": store,
        "stored_entity_data": stored_entity_data,
        "pattern_storage": pattern_storage,
    }

    # Get zones to create from options
    zones = entry.options.get(CONF_ZONES, DEFAULT_ZONES)
    if isinstance(zones, list):
        zones = [int(z) for z in zones if isinstance(z, (int, str)) and str(z).isdigit()]
    else:
        zones = DEFAULT_ZONES
    
    light_entities = []
    for zone in zones:
        if 1 <= zone <= 6:
            entity_store_key = f"zone_{zone}_last_command"
            restored_last_command = stored_entity_data.get(entity_store_key)
            light_entity = OeloLight(coordinator, zone, entry, restored_last_command)
            light_entities.append(light_entity)
    
    async_add_entities(light_entities, True)

class OeloLight(LightEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: OeloDataUpdateCoordinator, zone: int, entry: ConfigEntry,
                 restored_last_command: str | None = None) -> None:
        self.coordinator = coordinator
        self._zone = zone
        self._entry = entry
        self._state = False
        self._brightness: int | None = 255
        self._rgb_color: tuple[int, int, int] | None = (255, 255, 255)
        self._intended_effect: str | None = None
        self._last_successful_command: str | None = restored_last_command
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        self._attr_supported_features = LightEntityFeature.EFFECT
        self._attr_unique_id = f"{entry.entry_id}_zone_{self._zone}"
        self._attr_name = f"Zone {zone}"
        self._attr_available = True
        self._pending_command_url: str | None = None
        self._pending_command_future: asyncio.Future | None = None
        self._debounce_task: asyncio.Task | None = None
        self._debounce_interval = 1.0
        self._entity_store_key = f"zone_{self._zone}_last_command"
        self._pattern_storage: PatternStorage | None = None
        self._cached_patterns: list[dict[str, Any]] = []


    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Oelo",
            model="Light Controller",
            configuration_url=f"http://{self.coordinator.ip}/",
        )

    @property
    def available(self) -> bool:
        return self._attr_available

    @property
    def is_on(self) -> bool | None:
        return self._state if self.available else None

    @property
    def brightness(self) -> int | None:
        return self._brightness if self.available else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self._rgb_color if self.available else None

    @property
    def effect(self) -> str | None:
        if not self.available:
            return None
        return self._intended_effect if self.is_on else None

    @property
    def effect_list(self) -> list[str] | None:
        """Return list of available effects (captured patterns)."""
        if not self.available:
            return None
        
        # Return pattern names from cached patterns
        return [p.get("name", "") for p in self._cached_patterns if p.get("name")]
    
    async def _load_patterns(self) -> None:
        """Load patterns from storage."""
        if not self._pattern_storage:
            entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            self._pattern_storage = entry_data.get("pattern_storage")
        
        if self._pattern_storage:
            try:
                self._cached_patterns = await self._pattern_storage.async_load()
            except Exception as err:
                _LOGGER.error("Error loading patterns: %s", err)
                self._cached_patterns = []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.coordinator.async_add_listener(self._handle_coordinator_update)
        
        # Load patterns
        await self._load_patterns()
        
        # Listen for pattern updates
        @callback
        def _handle_pattern_update(event: Event) -> None:
            """Handle pattern update event."""
            if event.data.get("entry_id") == self._entry.entry_id:
                # Reload patterns and update state
                async def _reload_and_update():
                    await self._load_patterns()
                    self.async_write_ha_state()
                self.hass.async_create_task(_reload_and_update())
        
        self.hass.bus.async_listen(f"{DOMAIN}_pattern_updated", _handle_pattern_update)
        
        last_state = await self.async_get_last_state()
        log_prefix = self.entity_id or self._attr_name
        if last_state:
            self._state = last_state.state == STATE_ON
            self._brightness = last_state.attributes.get(ATTR_BRIGHTNESS, 255)
            self._intended_effect = last_state.attributes.get(ATTR_EFFECT)
            rgb_color_restored = last_state.attributes.get(ATTR_RGB_COLOR)
            if rgb_color_restored is not None and isinstance(rgb_color_restored, (list, tuple)) and len(rgb_color_restored) == 3:
                try:
                    self._rgb_color = tuple(int(c) for c in rgb_color_restored)
                except (ValueError, TypeError):
                    _LOGGER.warning("%s: Invalid RGB color %s restored, using default.", log_prefix, rgb_color_restored)
                    self._rgb_color = (255, 255, 255)
            else:
                _LOGGER.debug("%s: No valid RGB in restored state, using default or will derive.", log_prefix)
                self._rgb_color = (255,255,255)

            _LOGGER.debug("%s: Restored standard attrs: On=%s, Brightness=%s, Effect=%s, RGB=%s. LSC from Store: %s",
                        log_prefix, self._state, self._brightness, self._intended_effect, self._rgb_color, self._last_successful_command)
        else:
            _LOGGER.debug("%s: No previous state found for restore.", log_prefix)
            if self._rgb_color is None:
                self._rgb_color = (255, 255, 255)

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self) -> None:
        log_prefix = self.entity_id or self._attr_name
        if not self.coordinator.last_update_success:
            if self._attr_available:
                _LOGGER.warning("%s: Coordinator update failed, marking unavailable.", log_prefix)
                self._attr_available = False
                self.async_write_ha_state()
            return
        data = self.coordinator.data
        zone_data = None
        if data:
            for item in data:
                if isinstance(item, dict) and item.get("num") == self._zone:
                    zone_data = item
                    break
        if not zone_data:
            _LOGGER.warning("%s: Zone data not found in coordinator update.", log_prefix)
            self._attr_available = False
            self.async_write_ha_state()
            return
        current_pattern = zone_data.get("pattern")
        if current_pattern is None:
            _LOGGER.warning("%s: 'pattern' key missing in zone data: %s", log_prefix, zone_data)
            self._attr_available = False
            self.async_write_ha_state()
            return
        is_actually_on = current_pattern != "off"
        new_state = is_actually_on
        new_availability = True
        state_changed = self._state != new_state
        availability_changed = self._attr_available != new_availability
        if availability_changed:
            _LOGGER.info("%s: Availability changed via coordinator: %s -> %s",
                        log_prefix, self._attr_available, new_availability)
            self._attr_available = new_availability
        if self._attr_available and state_changed:
            _LOGGER.info("%s: State change via coordinator: %s -> %s (Pattern: '%s')",
                        log_prefix, "On" if self._state else "Off", "On" if new_state else "Off", current_pattern)
            self._state = new_state
            if not new_state:
                self._intended_effect = None
        self.async_write_ha_state()

    async def _save_last_command_to_store(self):
        log_prefix = self.entity_id or self._attr_name
        if self.hass and self._entry.entry_id in self.hass.data.get(DOMAIN, {}):
            entry_hass_data = self.hass.data[DOMAIN][self._entry.entry_id]
            store: Store = entry_hass_data.get("store")
            stored_entity_data: dict = entry_hass_data.get("stored_entity_data")

            if store and stored_entity_data is not None:
                if self._last_successful_command is None:
                    if self._entity_store_key in stored_entity_data:
                        del stored_entity_data[self._entity_store_key]
                        _LOGGER.debug("%s: Removed LSC from store for key %s", log_prefix, self._entity_store_key)
                else:
                    stored_entity_data[self._entity_store_key] = self._last_successful_command
                    _LOGGER.debug("%s: Updated LSC '%s' in store data for key %s",
                                  log_prefix, self._last_successful_command, self._entity_store_key)
                try:
                    await store.async_save(stored_entity_data)
                except Exception as e:
                    _LOGGER.error("%s: Failed to save last command to store: %s", log_prefix, e)
            else:
                _LOGGER.warning("%s: Store or stored_entity_data not found for saving LSC.", log_prefix)

    async def async_turn_on(self, **kwargs: Any) -> None:
        log_prefix = self.entity_id or self._attr_name
        _LOGGER.debug("%s: Turning on with kwargs: %s", log_prefix, kwargs)

        if not self._attr_available and not self._state:
             _LOGGER.warning("%s: Cannot turn on: Controller is unavailable and reported off.", log_prefix)
             return
        if not self._attr_available and self._state:
             _LOGGER.warning("%s: Controller unavailable, but attempting turn on/update as state is ON.", log_prefix)

        url_to_send: str | None = None
        effect_to_set: str | None = self._intended_effect
        rgb_to_set: tuple[int, int, int] | None = self._rgb_color
        brightness_to_set: int = self._brightness if self._brightness is not None else 255
        triggered_by_effect_kwarg = False
        base_command_for_lsc: str | None = None

        if ATTR_BRIGHTNESS in kwargs:
            try:
                brightness_to_set = int(kwargs[ATTR_BRIGHTNESS])
                _LOGGER.debug("%s: Brightness specified: %d", log_prefix, brightness_to_set)
            except (ValueError, TypeError):
                _LOGGER.warning("%s: Invalid brightness value: %s, using default", log_prefix, kwargs[ATTR_BRIGHTNESS])
                brightness_to_set = 255

        brightness_to_set = max(0, min(brightness_to_set, 255))
        brightness_factor = brightness_to_set / 255.0

        if ATTR_RGB_COLOR in kwargs:
            _LOGGER.debug("%s: RGB color specified: %s", log_prefix, kwargs[ATTR_RGB_COLOR])
            try:
                rgb_input = kwargs[ATTR_RGB_COLOR]
                if isinstance(rgb_input, (list, tuple)) and len(rgb_input) == 3:
                    rgb_to_set = tuple(max(0, min(int(c), 255)) for c in rgb_input)
                else:
                    _LOGGER.warning("%s: Invalid RGB color format: %s, using current color", log_prefix, rgb_input)
                    rgb_to_set = self._rgb_color or (255, 255, 255)
            except (ValueError, TypeError):
                _LOGGER.warning("%s: Invalid RGB color values: %s, using current color", log_prefix, kwargs[ATTR_RGB_COLOR])
                rgb_to_set = self._rgb_color or (255, 255, 255)
            effect_to_set = None
            
            scaled_color = tuple(max(0, min(int(round(c * brightness_factor)), 255)) for c in rgb_to_set)
            url_params_send = {
                 "patternType": "custom", "num_zones": 1, "zones": self._zone,
                 "num_colors": 1, "colors": ','.join(map(str, scaled_color)),
                 "direction": "F", "speed": 0, "gap": 0, "other": 0, "pause": 0
            }
            query_string_send = urllib.parse.urlencode(url_params_send)
            url_to_send = f"http://{self.coordinator.ip}/setPattern?{query_string_send}"

            url_params_lsc = url_params_send.copy()
            url_params_lsc["colors"] = ','.join(map(str, rgb_to_set))
            query_string_lsc = urllib.parse.urlencode(url_params_lsc)
            base_command_for_lsc = f"http://{self.coordinator.ip}/setPattern?{query_string_lsc}"

        elif ATTR_EFFECT in kwargs:
            selected_effect = kwargs[ATTR_EFFECT]
            triggered_by_effect_kwarg = True
            _LOGGER.debug("%s: Effect specified: %s", log_prefix, selected_effect)
            
            # Load patterns if not cached
            if not self._cached_patterns:
                await self._load_patterns()
            
            # Find pattern by name
            pattern = None
            for p in self._cached_patterns:
                if p.get("name") == selected_effect:
                    pattern = p
                    break
            
            if pattern:
                effect_to_set = selected_effect
                # Build URL from captured pattern
                spotlight_plan_lights_raw = self._entry.options.get("spotlight_plan_lights", DEFAULT_SPOTLIGHT_PLAN_LIGHTS)
                max_leds = self._entry.options.get("max_leds", DEFAULT_MAX_LEDS)
                spotlight_plan_lights = normalize_led_indices(spotlight_plan_lights_raw, max_leds) if spotlight_plan_lights_raw else None
                base_command_for_lsc = build_pattern_url(pattern, self._zone, self.coordinator.ip, spotlight_plan_lights, max_leds)
                
                # Extract RGB from pattern
                colors_str = pattern.get("url_params", {}).get("colors", "")
                if colors_str:
                    color_parts = colors_str.split(",")
                    if len(color_parts) >= 3:
                        try:
                            rgb_to_set = (int(color_parts[0]), int(color_parts[1]), int(color_parts[2]))
                        except (ValueError, IndexError):
                            rgb_to_set = (255, 255, 255)
                    else:
                        rgb_to_set = (255, 255, 255)
                else:
                    rgb_to_set = (255, 255, 255)
                
                url_to_send = self._adjust_colors_in_url(base_command_for_lsc, brightness_factor)
            else:
                _LOGGER.error("%s: Pattern '%s' not found. Available patterns: %s", 
                             log_prefix, selected_effect, [p.get("name") for p in self._cached_patterns])
                return

        elif not self._state or ATTR_BRIGHTNESS in kwargs:
            _LOGGER.debug("%s: Turning on from OFF or adjusting brightness only.", log_prefix)
            
            if effect_to_set and not triggered_by_effect_kwarg:
                _LOGGER.debug("%s: Replaying stored effect '%s'", log_prefix, effect_to_set)
                # Load patterns if not cached
                if not self._cached_patterns:
                    await self._load_patterns()
                
                # Find pattern by name
                pattern = None
                for p in self._cached_patterns:
                    if p.get("name") == effect_to_set:
                        pattern = p
                        break
                
                if pattern:
                    spotlight_plan_lights_raw = self._entry.options.get("spotlight_plan_lights", DEFAULT_SPOTLIGHT_PLAN_LIGHTS)
                    max_leds = self._entry.options.get("max_leds", DEFAULT_MAX_LEDS)
                    spotlight_plan_lights = normalize_led_indices(spotlight_plan_lights_raw, max_leds) if spotlight_plan_lights_raw else None
                    base_command_for_lsc = build_pattern_url(pattern, self._zone, self.coordinator.ip, spotlight_plan_lights, max_leds)
                    
                    # Extract RGB
                    colors_str = pattern.get("url_params", {}).get("colors", "")
                    if colors_str:
                        color_parts = colors_str.split(",")
                        if len(color_parts) >= 3:
                            try:
                                rgb_to_set = (int(color_parts[0]), int(color_parts[1]), int(color_parts[2]))
                            except (ValueError, IndexError):
                                rgb_to_set = (255, 255, 255)
                        else:
                            rgb_to_set = (255, 255, 255)
                    else:
                        rgb_to_set = (255, 255, 255)
                else:
                    effect_to_set = None
            
            if not base_command_for_lsc and self._last_successful_command:
                 _LOGGER.debug("%s: Replaying last successful command for ON.", log_prefix)
                 base_command_for_lsc = self._last_successful_command
                 parsed_lsc = urllib.parse.urlparse(base_command_for_lsc)
                 lsc_params = urllib.parse.parse_qs(parsed_lsc.query)
                 lsc_pattern_type = lsc_params.get("patternType", [""])[0]
                 
                 extracted_rgb_lsc = self._extract_first_color_from_url(base_command_for_lsc)
                 if extracted_rgb_lsc: 
                     rgb_to_set = extracted_rgb_lsc

                 if lsc_pattern_type == "custom": 
                     effect_to_set = None
                 elif lsc_pattern_type != "off":
                     # Try to find pattern name from captured patterns
                     if not self._cached_patterns:
                         await self._load_patterns()
                     
                     found_effect_name = False
                     for pattern in self._cached_patterns:
                         pattern_type = pattern.get("url_params", {}).get("patternType", "")
                         if pattern_type == lsc_pattern_type:
                             effect_to_set = pattern.get("name")
                             found_effect_name = True
                             break
                     
                     if not found_effect_name: 
                         effect_to_set = None

            if base_command_for_lsc:
                url_to_send = self._adjust_colors_in_url(base_command_for_lsc, brightness_factor)
            else:
                 _LOGGER.debug("%s: Fallback to Solid White.", log_prefix)
                 effect_to_set = None
                 rgb_to_set = (255, 255, 255)
                 scaled_color = tuple(max(0, min(int(round(c * brightness_factor)), 255)) for c in rgb_to_set)
                 url_params_send = {
                     "patternType": "custom", "num_zones": 1, "zones": self._zone,
                     "num_colors": 1, "colors": ','.join(map(str, scaled_color)),
                     "direction": "F", "speed": 0, "gap": 0, "other": 0, "pause": 0
                 }
                 url_to_send = f"http://{self.coordinator.ip}/setPattern?{urllib.parse.urlencode(url_params_send)}"
                 
                 url_params_lsc = url_params_send.copy()
                 url_params_lsc["colors"] = "255,255,255"
                 base_command_for_lsc = f"http://{self.coordinator.ip}/setPattern?{urllib.parse.urlencode(url_params_lsc)}"

        self._state = True
        self._brightness = brightness_to_set
        self._rgb_color = rgb_to_set
        self._intended_effect = effect_to_set
        self._attr_color_mode = ColorMode.RGB

        if base_command_for_lsc:
            if self._last_successful_command != base_command_for_lsc:
                self._last_successful_command = base_command_for_lsc
                await self._save_last_command_to_store()
        elif self._last_successful_command is not None: 
            self._last_successful_command = None
            await self._save_last_command_to_store()


        _LOGGER.debug("%s: Optimistic: On=%s, Bright=%s, Effect=%s, RGB=%s, LSC=%s",
                      log_prefix, self._state, self._brightness, self._intended_effect, self._rgb_color, self._last_successful_command)
        
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()

        if url_to_send:
            try:
                actual_send_success = await self._buffered_send_request(url_to_send)
                if actual_send_success:
                    _LOGGER.info("%s: Turn_on command sent successfully via buffer.", log_prefix)
                    if not self._attr_available:
                        _LOGGER.info("%s: Marking available after successful turn_on.", log_prefix)
                        self._attr_available = True
                        if self.hass is not None and self.entity_id is not None: 
                            self.async_write_ha_state()
                else:
                    _LOGGER.error("%s: Turn_on command failed via buffer.", log_prefix)
                    if self._attr_available:
                        _LOGGER.warning("%s: Marking unavailable after failed turn_on.", log_prefix)
                        self._attr_available = False
                        if self.hass is not None and self.entity_id is not None: 
                            self.async_write_ha_state()
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Turn_on command superseded. Optimistic state remains.", log_prefix)
            except Exception as e:
                _LOGGER.error("%s: Error during _buffered_send_request for turn_on: %s", log_prefix, e, exc_info=True)
                if self._attr_available:
                    self._attr_available = False
                    if self.hass is not None and self.entity_id is not None: 
                        self.async_write_ha_state()
        else:
             _LOGGER.debug("%s: Turn on called, no URL generated.", log_prefix)
             if not self._attr_available:
                 self._attr_available = True
                 if self.hass is not None and self.entity_id is not None: 
                     self.async_write_ha_state()


    async def async_turn_off(self, **kwargs: Any) -> None:
        log_prefix = self.entity_id or self._attr_name
        _LOGGER.debug("%s: Turning off", log_prefix)

        if not self._state and not self._attr_available:
            _LOGGER.debug("%s: Already off and unavailable.", log_prefix)
            return
        if not self._state and self._attr_available:
            _LOGGER.debug("%s: Already off.", log_prefix)
            return
        
        if not self._attr_available and self._state:
             _LOGGER.warning("%s: Unavailable but ON. Attempting turn off.", log_prefix)

        self._state = False
        _LOGGER.debug("%s: Optimistic: Off", log_prefix)
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()

        url_params = {
            "patternType": "off", "num_zones": 1, "zones": self._zone,
            "num_colors": 1, "colors": "0,0,0",
            "direction": "F", "speed": 0, "gap": 0, "other": 0, "pause": 0
        }
        url = f"http://{self.coordinator.ip}/setPattern?{urllib.parse.urlencode(url_params)}"

        try:
            actual_send_success = await self._buffered_send_request(url)
            if actual_send_success:
                _LOGGER.info("%s: Turn_off command sent successfully via buffer.", log_prefix)
                if not self._attr_available:
                    _LOGGER.info("%s: Marking available after successful turn_off.", log_prefix)
                    self._attr_available = True
                    if self.hass is not None and self.entity_id is not None: 
                        self.async_write_ha_state()
            else:
                _LOGGER.error("%s: Turn_off command failed via buffer.", log_prefix)
                if self._attr_available:
                    _LOGGER.warning("%s: Marking unavailable after failed turn_off.", log_prefix)
                    self._attr_available = False
                    if self.hass is not None and self.entity_id is not None: 
                        self.async_write_ha_state()
        except asyncio.CancelledError:
            _LOGGER.debug("%s: Turn_off command superseded. Optimistic state remains.", log_prefix)
        except Exception as e:
            _LOGGER.error("%s: Error during _buffered_send_request for turn_off: %s", log_prefix, e, exc_info=True)
            if self._attr_available:
                self._attr_available = False
                if self.hass is not None and self.entity_id is not None: 
                    self.async_write_ha_state()


    def _get_pattern_url(self, pattern_name: str) -> str | None:
        """Get pattern URL from captured patterns."""
        log_prefix = self.entity_id or self._attr_name
        
        # Find pattern by name
        pattern = None
        for p in self._cached_patterns:
            if p.get("name") == pattern_name:
                pattern = p
                break
        
        if not pattern:
            _LOGGER.error("%s: Pattern '%s' not found in captured patterns", log_prefix, pattern_name)
            return None
        
        try:
            spotlight_plan_lights_raw = self._entry.options.get("spotlight_plan_lights", DEFAULT_SPOTLIGHT_PLAN_LIGHTS)
            max_leds = self._entry.options.get("max_leds", DEFAULT_MAX_LEDS)
            spotlight_plan_lights = normalize_led_indices(spotlight_plan_lights_raw, max_leds) if spotlight_plan_lights_raw else None
            return build_pattern_url(pattern, self._zone, self.coordinator.ip, spotlight_plan_lights, max_leds)
        except Exception as e:
            _LOGGER.error("%s: Error building URL for pattern '%s': %s", log_prefix, pattern_name, e)
            return None


    def _extract_first_color_from_url(self, url: str) -> tuple[int, int, int] | None:
        log_prefix = self.entity_id or self._attr_name
        if not url: 
            return None
        try:
            query_params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if 'colors' in query_params and query_params['colors'] and query_params['colors'][0]:
                colors_str = query_params['colors'][0]
                color_parts = colors_str.split(',')
                if len(color_parts) >= 3:
                    try:
                        color_values = [max(0, min(int(c.strip()), 255)) for c in color_parts[:3]]
                        return tuple(color_values)
                    except (ValueError, TypeError):
                        _LOGGER.debug("%s: Invalid color values in '%s' from %s", log_prefix, colors_str, url)
                else:
                    _LOGGER.debug("%s: Not enough numeric values in colors='%s' from %s", log_prefix, colors_str, url)
            else:
                _LOGGER.debug("%s: No 'colors' param or empty in %s", log_prefix, url)
        except ValueError as e:
            _LOGGER.error("%s: Invalid color value parsing 'colors' from %s: %s", log_prefix, url, e)
        except Exception as e:
            _LOGGER.error("%s: Error parsing color from URL '%s': %s", log_prefix, url, e)
        return None


    async def _send_request(self, url: str) -> bool:
        log_prefix = self.entity_id or self._attr_name
        _LOGGER.debug("%s: Sending request: %s", log_prefix, url)
        timeout_seconds = getattr(self.coordinator, "timeout", 10)
        try:
            async with async_timeout.timeout(timeout_seconds):
                session = self.coordinator.session
                if session is None or session.closed:
                     _LOGGER.error("%s: HTTP session closed/invalid for send request.", log_prefix)
                     return False

                async with session.get(url) as response:
                    resp_text = await response.text()
                    response.raise_for_status()

                    if "Command Received" in resp_text:
                         _LOGGER.info("%s: Request OK (Status: %d, Resp: '%s')", log_prefix, response.status, resp_text.strip()[:50])
                         return True
                    else:
                         _LOGGER.warning("%s: Request OK (Status: %d), but unexpected response: '%s'", log_prefix, response.status, resp_text.strip()[:50])
                         return True
        except asyncio.TimeoutError:
            _LOGGER.error("%s: Request timed out: %s", log_prefix, url)
            return False
        except aiohttp.ClientResponseError as err:
            _LOGGER.error("%s: HTTP request failed: %s (%s)", log_prefix, err, url)
            return False
        except aiohttp.ClientConnectionError as err:
             _LOGGER.error("%s: HTTP connection failed: %s (%s)", log_prefix, err, url)
             return False
        except aiohttp.ClientError as err:
            _LOGGER.error("%s: HTTP client error: %s (%s)", log_prefix, err, url)
            return False
        except Exception as err:
            _LOGGER.exception("%s: Unexpected error during request: %s (%s)", log_prefix, err, url)
            return False


    def _adjust_colors_in_url(self, url: str, brightness_factor: float) -> str:
        log_prefix = self.entity_id or self._attr_name
        if not url:
            _LOGGER.warning("%s: Empty URL to adjust colors.", log_prefix)
            return ""
        brightness_factor = max(0.0, min(brightness_factor, 1.0))

        try:
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query, keep_blank_values=True)

            if 'colors' in query_params and query_params['colors'][0]:
                colors_str_list = query_params['colors'][0].split(',')
                original_colors_int = []
                for c_str in colors_str_list:
                    c_str_stripped = c_str.strip()
                    if c_str_stripped.isdigit():
                        original_colors_int.append(int(c_str_stripped))

                if not original_colors_int:
                    _LOGGER.warning("%s: No numeric colors in '%s' from %s", log_prefix, query_params['colors'][0], url)
                    return url

                if len(original_colors_int) % 3 != 0:
                    _LOGGER.warning("%s: Color count %d not multiple of 3 in %s", log_prefix, len(original_colors_int), url)

                adjusted_colors = [max(0, min(int(round(v * brightness_factor)), 255)) for v in original_colors_int]
                query_params['colors'] = [','.join(map(str, adjusted_colors))]
            else:
                _LOGGER.debug("%s: No 'colors' param to adjust in %s", log_prefix, url)
                return urllib.parse.urlunparse(parsed_url._replace(scheme='http', netloc=self.coordinator.ip))


            new_query = urllib.parse.urlencode(query_params, doseq=True)
            new_url = urllib.parse.urlunparse(
                parsed_url._replace(scheme='http', netloc=self.coordinator.ip, query=new_query)
            )
            _LOGGER.debug("%s: Adjusted URL (bright %.2f): %s", log_prefix, brightness_factor, new_url)
            return new_url

        except Exception as e:
            _LOGGER.exception("%s: Error adjusting colors in URL '%s': %s", log_prefix, url, e)
            try:
                 return urllib.parse.urlunparse(urllib.parse.urlparse(url)._replace(scheme='http', netloc=self.coordinator.ip))
            except Exception:
                 return url


    async def _buffered_send_request(self, url: str) -> bool:
        log_prefix = self.entity_id or self._attr_name
        loop = asyncio.get_running_loop()

        if self._debounce_task and not self._debounce_task.done():
            _LOGGER.debug("%s: Cancelling previous debounce task.", log_prefix)
            self._debounce_task.cancel()

        if self._pending_command_future and not self._pending_command_future.done():
            _LOGGER.debug("%s: Cancelling previous pending command future.", log_prefix)
            self._pending_command_future.cancel()

        self._pending_command_url = url
        current_call_future = loop.create_future()
        self._pending_command_future = current_call_future

        self._debounce_task = loop.create_task(self._debounce_and_send())

        try:
            result = await current_call_future
            return result
        except asyncio.CancelledError:
            _LOGGER.debug("%s: This buffered request call was cancelled (superseded).", log_prefix)
            raise


    async def _debounce_and_send(self):
        log_prefix = self.entity_id or self._attr_name
        try:
            await asyncio.sleep(self._debounce_interval)

            url_to_send_now = self._pending_command_url
            future_to_resolve_now = self._pending_command_future

            if url_to_send_now is None or future_to_resolve_now is None:
                _LOGGER.warning("%s: Debounce task woke up with no command/future.", log_prefix)
                return

            if future_to_resolve_now.cancelled():
                _LOGGER.debug("%s: Debounce task future was already cancelled before send.", log_prefix)
                return
            
            if future_to_resolve_now.done():
                _LOGGER.debug("%s: Debounce task future was already done before send (unexpected).", log_prefix)
                return

            _LOGGER.debug("%s: Debounce finished. Sending actual URL: %s", log_prefix, url_to_send_now)
            send_result = await self._send_request(url_to_send_now)

            if not future_to_resolve_now.done():
                future_to_resolve_now.set_result(send_result)
            else:
                _LOGGER.debug("%s: Future for URL %s was done/cancelled while send was in progress.", log_prefix, url_to_send_now)

        except asyncio.CancelledError:
            _LOGGER.debug("%s: Debounce task itself cancelled (new command came in).", log_prefix)
        except Exception as e:
            _LOGGER.error("%s: Error in _debounce_and_send: %s", log_prefix, e, exc_info=True)
            if self._pending_command_future and not self._pending_command_future.done():
                self._pending_command_future.set_result(False)


    async def async_will_remove_from_hass(self) -> None:
        """Clean up resources when entity is removed."""
        try:
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
                try:
                    await self._debounce_task
                except asyncio.CancelledError:
                    pass
            
            if self._pending_command_future and not self._pending_command_future.done():
                self._pending_command_future.cancel()
            
        except Exception as e:
            _LOGGER.debug("%s: Error during cleanup: %s", self.entity_id or self._attr_name, e)
        finally:
            await super().async_will_remove_from_hass()
            

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle unloading of a config entry."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        del hass.data[DOMAIN][entry.entry_id]
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
        _LOGGER.info("Unloaded Oelo Lights entry %s", entry.entry_id)

    return await hass.config_entries.async_unload_platforms(entry, ["light"])