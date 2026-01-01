"""Services for Oelo Lights integration.

Services: capture_effect, apply_effect, rename_effect, delete_effect,
list_effects, on_and_apply_effect.

Workflow: Create pattern in Oelo app → capture_effect (zone must be ON) →
rename_effect (optional) → apply_effect to any zone.

Uses "effect" terminology (backward compatible with "pattern_name"/"pattern_id").
Patterns shared across all zones.
"""

from __future__ import annotations
import logging
from typing import Any
import aiohttp
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import aiohttp_client
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    SERVICE_CAPTURE_EFFECT,
    SERVICE_APPLY_EFFECT,
    SERVICE_ON_AND_APPLY_EFFECT,
    SERVICE_RENAME_EFFECT,
    SERVICE_DELETE_EFFECT,
    SERVICE_LIST_EFFECTS,
    DEFAULT_SPOTLIGHT_PLAN_LIGHTS,
    DEFAULT_MAX_LEDS,
)
from .pattern_storage import PatternStorage
from .pattern_utils import (
    extract_pattern_from_zone_data,
    build_pattern_url,
    normalize_led_indices,
)

_LOGGER = logging.getLogger(__name__)


def get_entry_id_from_entity_id(hass: HomeAssistant, entity_id: str) -> str | None:
    """Get config entry ID from entity ID."""
    registry = er.async_get(hass)
    entity = registry.async_get(entity_id)
    if entity and entity.config_entry_id:
        return entity.config_entry_id
    return None


def get_zone_from_entity_id(entity_id: str) -> int | None:
    """Extract zone number from entity ID."""
    try:
        # Format: light.oelo_lights_zone_1
        parts = entity_id.split("_")
        if len(parts) >= 3 and parts[-1].isdigit():
            return int(parts[-1])
    except (ValueError, AttributeError):
        pass
    return None


async def async_capture_pattern(hass: HomeAssistant, call: ServiceCall) -> None:
    """Capture current effect from controller."""
    entity_id = call.data.get("entity_id")
    pattern_name = call.data.get("effect_name") or call.data.get("pattern_name")  # Support both for backward compat
    
    if not entity_id:
        raise HomeAssistantError("entity_id is required")
    
    # Get entry ID and zone
    entry_id = get_entry_id_from_entity_id(hass, entity_id)
    if not entry_id:
        raise HomeAssistantError(f"Could not find config entry for entity {entity_id}")
    
    zone = get_zone_from_entity_id(entity_id)
    if not zone:
        raise HomeAssistantError(f"Could not extract zone from entity_id {entity_id}")
    
    # Get config entry
    config_entry = hass.config_entries.async_get_entry(entry_id)
    if not config_entry:
        raise HomeAssistantError(f"Config entry {entry_id} not found")
    
    ip_address = config_entry.data.get("ip_address")
    if not ip_address:
        raise HomeAssistantError("Controller IP address not configured")
    
    # Fetch current zone data
    session = aiohttp_client.async_get_clientsession(hass)
    url = f"http://{ip_address}/getController"
    
    try:
        async with aiohttp.ClientTimeout(total=10):
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
                
                if not isinstance(data, list):
                    raise HomeAssistantError("Controller did not return valid zone data")
                
                # Find zone data
                zone_data = None
                for item in data:
                    if isinstance(item, dict) and item.get("num") == zone:
                        zone_data = item
                        break
                
                if not zone_data:
                    raise HomeAssistantError(f"Zone {zone} data not found in controller response")
                
                # Extract pattern
                pattern = extract_pattern_from_zone_data(zone_data, zone)
                if not pattern:
                    raise HomeAssistantError(f"Zone {zone} is off or has no pattern to capture")
                
                # For spotlight plans, normalize LED indices before storing
                if pattern.get("plan_type") == "spotlight":
                    max_leds = config_entry.options.get("max_leds", DEFAULT_MAX_LEDS)
                    spotlight_plan_lights_raw = config_entry.options.get("spotlight_plan_lights", DEFAULT_SPOTLIGHT_PLAN_LIGHTS)
                    spotlight_plan_lights = normalize_led_indices(spotlight_plan_lights_raw, max_leds)
                    # Store normalized value (will be used when applying)
                    # Original colors are already stored separately
                
                # Set custom name if provided
                if pattern_name:
                    pattern["name"] = pattern_name.strip()
                
                # Store pattern
                storage = PatternStorage(hass, entry_id)
                success = await storage.async_add_pattern(pattern)
                
                if success:
                    _LOGGER.info("Captured pattern '%s' (ID: %s) from zone %d", pattern["name"], pattern["id"], zone)
                    # Trigger entity update to refresh effect list
                    hass.bus.async_fire(f"{DOMAIN}_pattern_updated", {"entry_id": entry_id})
                else:
                    raise HomeAssistantError(f"Failed to save pattern (may already exist or limit reached)")
                    
    except aiohttp.ClientError as err:
        raise HomeAssistantError(f"Failed to connect to controller: {err}") from err
    except Exception as err:
        _LOGGER.exception("Error capturing pattern")
        raise HomeAssistantError(f"Error capturing pattern: {err}") from err


async def async_apply_pattern(hass: HomeAssistant, call: ServiceCall) -> None:
    """Apply a saved effect to a zone."""
    entity_id = call.data.get("entity_id")
    pattern_id = call.data.get("effect_id") or call.data.get("pattern_id")  # Support both
    pattern_name = call.data.get("effect_name") or call.data.get("pattern_name")  # Support both
    
    if not entity_id:
        raise HomeAssistantError("entity_id is required")
    
    if not pattern_id and not pattern_name:
        raise HomeAssistantError("pattern_id or pattern_name is required")
    
    # Get entry ID and zone
    entry_id = get_entry_id_from_entity_id(hass, entity_id)
    if not entry_id:
        raise HomeAssistantError(f"Could not find config entry for entity {entity_id}")
    
    zone = get_zone_from_entity_id(entity_id)
    if not zone:
        raise HomeAssistantError(f"Could not extract zone from entity_id {entity_id}")
    
    # Get config entry
    config_entry = hass.config_entries.async_get_entry(entry_id)
    if not config_entry:
        raise HomeAssistantError(f"Config entry {entry_id} not found")
    
    ip_address = config_entry.data.get("ip_address")
    if not ip_address:
        raise HomeAssistantError("Controller IP address not configured")
    
    # Get pattern from storage
    storage = PatternStorage(hass, entry_id)
    pattern = await storage.async_get_pattern(pattern_id, pattern_name)
    
    if not pattern:
        raise HomeAssistantError(f"Pattern not found (ID: {pattern_id or 'N/A'}, Name: {pattern_name or 'N/A'})")
    
    # Get spotlight plan settings and normalize LED indices
    spotlight_plan_lights_raw = config_entry.options.get("spotlight_plan_lights", DEFAULT_SPOTLIGHT_PLAN_LIGHTS)
    max_leds = config_entry.options.get("max_leds", DEFAULT_MAX_LEDS)
    if spotlight_plan_lights_raw:
        spotlight_plan_lights = normalize_led_indices(spotlight_plan_lights_raw, max_leds)
    else:
        spotlight_plan_lights = normalize_led_indices(DEFAULT_SPOTLIGHT_PLAN_LIGHTS, max_leds)
    
    # Build URL
    url = build_pattern_url(pattern, zone, ip_address, spotlight_plan_lights, max_leds)
    
    # Send to controller
    session = aiohttp_client.async_get_clientsession(hass)
    timeout = config_entry.options.get("command_timeout", 10)
    
    try:
        async with aiohttp.ClientTimeout(total=timeout):
            async with session.get(url) as response:
                response.raise_for_status()
                text = await response.text()
                if "Command Received" not in text:
                    _LOGGER.warning("Unexpected response from controller: %s", text[:100])
                
                _LOGGER.info("Applied pattern '%s' to zone %d", pattern.get("name", "Unknown"), zone)
                
    except aiohttp.ClientError as err:
        raise HomeAssistantError(f"Failed to apply pattern: {err}") from err


async def async_on_and_apply_pattern(hass: HomeAssistant, call: ServiceCall) -> None:
    """Turn on and apply effect in one action."""
    # Apply effect (this will turn it on)
    await async_apply_pattern(hass, call)


async def async_rename_pattern(hass: HomeAssistant, call: ServiceCall) -> None:
    """Rename a saved effect."""
    entity_id = call.data.get("entity_id")
    pattern_id = call.data.get("effect_id") or call.data.get("pattern_id")  # Support both
    pattern_name = call.data.get("effect_name") or call.data.get("pattern_name")  # Support both
    new_name = call.data.get("new_name", "").strip()
    
    if not entity_id:
        raise HomeAssistantError("entity_id is required")
    
    if not pattern_id and not pattern_name:
        raise HomeAssistantError("pattern_id or pattern_name is required")
    
    if not new_name:
        raise HomeAssistantError("new_name is required")
    
    # Get entry ID
    entry_id = get_entry_id_from_entity_id(hass, entity_id)
    if not entry_id:
        raise HomeAssistantError(f"Could not find config entry for entity {entity_id}")
    
    # Rename pattern
    storage = PatternStorage(hass, entry_id)
    success = await storage.async_rename_pattern(pattern_id, pattern_name, new_name)
    
    if success:
        _LOGGER.info("Renamed pattern to '%s'", new_name)
        # Trigger entity update
        hass.bus.async_fire(f"{DOMAIN}_pattern_updated", {"entry_id": entry_id})
    else:
        raise HomeAssistantError("Failed to rename pattern (pattern not found or name conflict)")


async def async_delete_pattern(hass: HomeAssistant, call: ServiceCall) -> None:
    """Delete a saved effect."""
    entity_id = call.data.get("entity_id")
    pattern_id = call.data.get("effect_id") or call.data.get("pattern_id")  # Support both
    pattern_name = call.data.get("effect_name") or call.data.get("pattern_name")  # Support both
    
    if not entity_id:
        raise HomeAssistantError("entity_id is required")
    
    if not pattern_id and not pattern_name:
        raise HomeAssistantError("pattern_id or pattern_name is required")
    
    # Get entry ID
    entry_id = get_entry_id_from_entity_id(hass, entity_id)
    if not entry_id:
        raise HomeAssistantError(f"Could not find config entry for entity {entity_id}")
    
    # Delete pattern
    storage = PatternStorage(hass, entry_id)
    success = await storage.async_delete_pattern(pattern_id, pattern_name)
    
    if success:
        _LOGGER.info("Deleted pattern (ID: %s, Name: %s)", pattern_id or "N/A", pattern_name or "N/A")
        # Trigger entity update
        hass.bus.async_fire(f"{DOMAIN}_pattern_updated", {"entry_id": entry_id})
    else:
        raise HomeAssistantError("Failed to delete pattern (pattern not found)")


async def async_list_patterns(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """List all saved effects."""
    entity_id = call.data.get("entity_id")
    
    if not entity_id:
        raise HomeAssistantError("entity_id is required")
    
    # Get entry ID
    entry_id = get_entry_id_from_entity_id(hass, entity_id)
    if not entry_id:
        raise HomeAssistantError(f"Could not find config entry for entity {entity_id}")
    
    # List patterns
    storage = PatternStorage(hass, entry_id)
    patterns = await storage.async_list_patterns()
    
    _LOGGER.info("Listed %d patterns for entry %s", len(patterns), entry_id)
    # Return patterns for frontend consumption
    return {"patterns": patterns}


def async_register_services(hass: HomeAssistant) -> None:
    """Register Oelo Lights services."""
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_CAPTURE_EFFECT,
        async_capture_pattern,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Optional("effect_name"): str,
            vol.Optional("pattern_name"): str,  # Backward compatibility
        }),
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_EFFECT,
        async_apply_pattern,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Exclusive("effect_id", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("effect_name", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("pattern_id", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
            vol.Exclusive("pattern_name", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
        }),
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_ON_AND_APPLY_EFFECT,
        async_on_and_apply_pattern,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Exclusive("effect_id", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("effect_name", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("pattern_id", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
            vol.Exclusive("pattern_name", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
        }),
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_RENAME_EFFECT,
        async_rename_pattern,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Required("new_name"): str,
            vol.Exclusive("effect_id", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("effect_name", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("pattern_id", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
            vol.Exclusive("pattern_name", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
        }),
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_EFFECT,
        async_delete_pattern,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Exclusive("effect_id", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("effect_name", "effect_identifier"): vol.Any(str, None),
            vol.Exclusive("pattern_id", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
            vol.Exclusive("pattern_name", "effect_identifier"): vol.Any(str, None),  # Backward compatibility
        }),
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_EFFECTS,
        async_list_patterns,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
        }),
    )
    
    # Register alias for backward compatibility (card uses list_patterns)
    hass.services.async_register(
        DOMAIN,
        "list_patterns",
        async_list_patterns,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
        }),
    )
    
    _LOGGER.info("Registered Oelo Lights services")
