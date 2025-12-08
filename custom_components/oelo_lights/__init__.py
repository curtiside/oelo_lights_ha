"""Oelo Lights Home Assistant integration.

Controls Oelo Lights controllers via HTTP REST API. Supports multi-zone control,
effect capture/storage/management, spotlight plan handling (40-LED limitation).

Protocol:
    GET http://{IP}/getController - Returns zone statuses (JSON array)
    GET http://{IP}/setPattern?patternType={type}&zones={zone}&... - Sets pattern

Workflow:
    1. Create/set pattern in Oelo app
    2. Capture in HA (stores for reuse, shared across zones)
    3. Rename (optional)
    4. Apply to any zone

Storage: {DOMAIN}_patterns_{entry_id}.json (up to 200 patterns per controller)
"""

from __future__ import annotations
import shutil
import logging
import asyncio
from pathlib import Path
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Oelo Lights integration."""
    # Register services
    async_register_services(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Oelo Lights integration from a config entry."""
    # Copy Lovelace card and register resource when integration is added
    await _install_lovelace_card(hass)
    
    await hass.config_entries.async_forward_entry_setups(entry, ["light"])
    return True

async def _install_lovelace_card(hass: HomeAssistant) -> None:
    """Copy Lovelace card to www directory and register as resource."""
    try:
        # Get paths
        integration_dir = Path(__file__).parent
        card_source = integration_dir / "www" / "oelo-patterns-card-simple.js"
        www_dir = Path(hass.config.path("www"))
        card_dest = www_dir / "oelo-patterns-card-simple.js"
        
        # Create www directory if it doesn't exist
        www_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy card if source exists
        card_installed = False
        if card_source.exists():
            if not card_dest.exists():
                shutil.copy2(card_source, card_dest)
                card_installed = True
                _LOGGER.info("Lovelace card installed to %s", card_dest)
            elif card_source.stat().st_mtime > card_dest.stat().st_mtime:
                shutil.copy2(card_source, card_dest)
                card_installed = True
                _LOGGER.info("Lovelace card updated at %s", card_dest)
        
        # Try to register as Lovelace resource (always try if card exists)
        if card_dest.exists():
            _LOGGER.info("Card file exists, attempting to register Lovelace resource...")
            await _register_lovelace_resource(hass)
        elif card_installed:
            await _register_lovelace_resource(hass)
            
    except Exception as e:
        # Don't fail integration setup if card copy fails
        _LOGGER.warning("Could not install Lovelace card: %s", e)

async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register Lovelace card as a resource automatically."""
    try:
        # Wait for Lovelace to be available
        max_attempts = 10
        for attempt in range(max_attempts):
            if "lovelace" in hass.config.components:
                break
            await asyncio.sleep(1)
        
        if "lovelace" not in hass.config.components:
            _LOGGER.warning("Lovelace not available, card resource will need manual registration")
            return
        
        # Try multiple methods to register the resource
        resource_url = "/local/oelo-patterns-card-simple.js"
        resource_type = "module"
        
        # Method 1: Use ResourceStorage API
        try:
            from homeassistant.components.lovelace.resources import ResourceStorage
            resources = ResourceStorage(hass)
            
            # Check if resource already exists
            existing_resources = await resources.async_get_info()
            resource_exists = any(
                res.get("url") == resource_url for res in existing_resources
            )
            
            if not resource_exists:
                await resources.async_create_item({
                    "type": resource_type,
                    "url": resource_url,
                })
                _LOGGER.info("✓ Lovelace card resource registered automatically")
                return
            else:
                _LOGGER.debug("Lovelace card resource already registered")
                return
        except Exception as e:
            _LOGGER.debug("ResourceStorage method failed: %s", e)
        
        # Method 2: Use frontend component to load globally (works without resource registration)
        try:
            # This loads the JS globally, making the card available without manual resource addition
            from homeassistant.components.frontend import add_extra_js_url
            add_extra_js_url(hass, resource_url, es5=False)
            _LOGGER.info("✓ Lovelace card loaded automatically via frontend component")
            return
        except ImportError:
            # Frontend component not available
            pass
        except Exception as e:
            _LOGGER.debug("Frontend component method failed: %s", e)
        
        # If all methods fail, log instructions
        _LOGGER.warning("Could not auto-register Lovelace resource. Add manually: Settings → Dashboards → Resources → URL: %s, Type: %s", resource_url, resource_type)
            
    except ImportError as e:
        _LOGGER.warning("Lovelace API not available: %s. Add resource manually: Settings → Dashboards → Resources", e)
    except Exception as e:
        _LOGGER.warning("Could not register Lovelace resource: %s. Add manually: Settings → Dashboards → Resources", e)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_forward_entry_unload(entry, "light")
