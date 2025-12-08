"""Support for Oelo Lights.

Oelo Lights Home Assistant Integration

This integration provides control for Oelo Lights controllers via HTTP REST API.
Supports multi-zone control, effect capture, storage, and management.

## Protocol

**Base URL:** `http://{IP_ADDRESS}/`

**Endpoints:**
- `GET /getController` - Returns JSON array of zone statuses
- `GET /setPattern?patternType={type}&zones={zone}&...` - Sets pattern/color for zones

**Key Features:**
- Pattern capture from controller (patterns created in Oelo app first)
- Pattern storage (shared across all zones, up to 200 patterns)
- Pattern renaming and management
- Spotlight plan support (handles 40-LED controller limitation)
- Effect list integration (Home Assistant native)

**Pattern Workflow:**
1. Create/set pattern in Oelo app
2. Capture pattern in Home Assistant (stores for reuse)
3. Rename pattern (optional)
4. Apply pattern to any zone

**Storage:**
- Patterns stored per controller (shared across zones)
- Storage location: `{DOMAIN}_patterns_{entry_id}.json`
- Pattern structure includes: id, name, url_params, plan_type, original_colors
"""

from __future__ import annotations
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .services import async_register_services

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Oelo Lights integration."""
    # Register services
    async_register_services(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Oelo Lights integration from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, ["light"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_forward_entry_unload(entry, "light")
