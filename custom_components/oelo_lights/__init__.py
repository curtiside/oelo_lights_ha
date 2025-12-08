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

from .const import DOMAIN, DEFAULT_ZONES, CONF_ZONES
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
    
    # Try to add card to dashboard automatically
    await _add_card_to_dashboard(hass, entry)
    
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
        
        # Copy card if source exists (use executor to avoid blocking I/O)
        card_installed = False
        if card_source.exists():
            def _copy_card():
                if not card_dest.exists():
                    shutil.copy2(card_source, card_dest)
                    return True
                elif card_source.stat().st_mtime > card_dest.stat().st_mtime:
                    shutil.copy2(card_source, card_dest)
                    return True
                return False
            
            card_installed = await hass.async_add_executor_job(_copy_card)
            if card_installed:
                _LOGGER.info("Lovelace card installed/updated at %s", card_dest)
        
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

async def _add_card_to_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Try to automatically add pattern management card to dashboard."""
    try:
        # Wait for Lovelace to be available
        max_attempts = 15
        for attempt in range(max_attempts):
            if "lovelace" in hass.config.components:
                break
            await asyncio.sleep(1)
        
        if "lovelace" not in hass.config.components:
            _LOGGER.warning("Lovelace not available after %d attempts - pattern management card not added", max_attempts)
            return
        
        # Get first zone entity ID
        zones = entry.options.get(CONF_ZONES, DEFAULT_ZONES)
        if not zones:
            zones = DEFAULT_ZONES
        first_zone = zones[0] if isinstance(zones, list) else DEFAULT_ZONES[0]
        entity_id = f"light.{DOMAIN}_zone_{first_zone}"
        
        _LOGGER.info("Attempting to add pattern management card to dashboard for entity %s", entity_id)
        
        # Try to access Lovelace config storage
        try:
            from homeassistant.components.lovelace.dashboard import LovelaceStorage
            
            # Try to get dashboard storage
            try:
                storage = LovelaceStorage(hass, None)
                config = await storage.async_load(force=False)
                
                if not config:
                    _LOGGER.warning("Dashboard config is None - cannot add pattern management card")
                    return
                
                if not isinstance(config, dict):
                    _LOGGER.warning("Dashboard config is not a dict (type: %s) - cannot add pattern management card", type(config))
                    return
                
                views = config.get("views", [])
                if not views:
                    _LOGGER.info("No views found, creating default view")
                    views = [{"title": "Home", "path": "home", "cards": []}]
                
                # Check if pattern card exists, or if there's an old zones card to replace
                pattern_card_exists = False
                zones_card_index = None
                zones_card_view = None
                
                for view_idx, view in enumerate(views):
                    cards = view.get("cards", [])
                    for card_idx, card in enumerate(cards):
                        if card.get("type") == "custom:oelo-patterns-card":
                            pattern_card_exists = True
                            _LOGGER.info("Pattern management card already exists in view %d", view_idx)
                            break
                        # Check for old zones card (entities card showing zones)
                        if card.get("type") == "entities":
                            entities = card.get("entities", [])
                            if isinstance(entities, list):
                                entity_ids = [str(e).lower() for e in entities]
                                if any("oleo" in eid or DOMAIN in eid for eid in entity_ids):
                                    zones_card_index = card_idx
                                    zones_card_view = view_idx
                                    _LOGGER.info("Found existing zones card at view %d, card %d", view_idx, card_idx)
                    if pattern_card_exists:
                        break
                
                if not pattern_card_exists:
                    card_config = {
                        "type": "custom:oelo-patterns-card",
                        "entity": entity_id,
                        "title": "Oelo Patterns"
                    }
                    
                    # Replace old zones card if found, otherwise add to first view
                    if zones_card_view is not None and zones_card_index is not None:
                        views[zones_card_view]["cards"][zones_card_index] = card_config
                        _LOGGER.info("✓ Pattern management card replaced old zones card in view %d", zones_card_view)
                    else:
                        # Add to first view (Overview)
                        if "cards" not in views[0]:
                            views[0]["cards"] = []
                        views[0]["cards"].append(card_config)
                        _LOGGER.info("✓ Pattern management card added to Overview dashboard (view 0)")
                    
                    config["views"] = views
                    await storage.async_save(config)
                    _LOGGER.info("✓ Dashboard config saved successfully - pattern management card should be visible")
                    return
                else:
                    _LOGGER.debug("Pattern management card already exists in dashboard")
                    return
            except Exception as e:
                _LOGGER.error("Failed to access dashboard storage: %s", e, exc_info=True)
                _LOGGER.warning("Pattern management card NOT added - check Home Assistant logs for details")
                return
        except ImportError as e:
            _LOGGER.error("Lovelace storage API not available: %s", e)
            _LOGGER.warning("Pattern management card NOT added - Lovelace storage API import failed")
            return
    except Exception as e:
        _LOGGER.error("Failed to add pattern management card to dashboard: %s", e, exc_info=True)
        _LOGGER.warning("Pattern management card NOT added - check Home Assistant logs for error details")

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_forward_entry_unload(entry, "light")
