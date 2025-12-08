"""Pattern storage for Oelo Lights integration.

Manages persistent storage using Home Assistant Store. Patterns shared across
all zones per controller. Storage: {DOMAIN}_patterns_{entry_id}.json (max 200).
Pattern structure: id, name, url_params, plan_type, original_colors.
"""

from __future__ import annotations
import logging
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from .const import (
    STORAGE_VERSION,
    STORAGE_KEY_PATTERNS,
    MAX_PATTERNS,
    DEFAULT_SPOTLIGHT_PLAN_LIGHTS,
)

_LOGGER = logging.getLogger(__name__)


class PatternStorage:
    """Manages pattern storage for Oelo Lights.
    
    Patterns are stored per controller (shared across all zones).
    Storage uses Home Assistant's Store class for persistence.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize pattern storage.
        
        Args:
            hass: Home Assistant instance
            entry_id: Config entry ID (used for storage key)
        """
        self.hass = hass
        self.entry_id = entry_id
        self.store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PATTERNS}_{entry_id}")
        self._patterns: list[dict[str, Any]] = []

    async def async_load(self) -> list[dict[str, Any]]:
        """Load patterns from storage."""
        if not self._patterns:
            data = await self.store.async_load()
            if data and isinstance(data, dict) and "patterns" in data:
                self._patterns = data["patterns"] or []
            else:
                self._patterns = []
        return self._patterns.copy()

    async def async_save(self) -> None:
        """Save patterns to storage."""
        await self.store.async_save({"patterns": self._patterns})

    async def async_add_pattern(self, pattern: dict[str, Any]) -> bool:
        """Add a pattern to storage."""
        patterns = await self.async_load()
        
        # Check if pattern already exists (by ID)
        pattern_id = pattern.get("id")
        if pattern_id:
            for existing in patterns:
                if existing.get("id") == pattern_id:
                    _LOGGER.debug("Pattern with ID %s already exists, updating name if different", pattern_id)
                    # Update name if provided and different
                    if pattern.get("name") and pattern.get("name") != existing.get("name"):
                        existing["name"] = pattern.get("name")
                        self._patterns = patterns
                        await self.async_save()
                        return True
                    return False
        
        # Check pattern limit
        if len(patterns) >= MAX_PATTERNS:
            _LOGGER.warning("Pattern limit reached (%d), cannot add more patterns", MAX_PATTERNS)
            return False
        
        patterns.append(pattern)
        self._patterns = patterns
        await self.async_save()
        return True

    async def async_get_pattern(self, pattern_id: str | None = None, pattern_name: str | None = None) -> dict[str, Any] | None:
        """Get a pattern by ID or name."""
        patterns = await self.async_load()
        
        if pattern_id:
            for pattern in patterns:
                if pattern.get("id") == pattern_id:
                    return pattern
        
        if pattern_name:
            for pattern in patterns:
                if pattern.get("name") == pattern_name:
                    return pattern
        
        return None

    async def async_rename_pattern(self, pattern_id: str | None = None, pattern_name: str | None = None, new_name: str = "") -> bool:
        """Rename a pattern."""
        pattern = await self.async_get_pattern(pattern_id, pattern_name)
        if not pattern:
            return False
        
        # Check if new name conflicts
        patterns = await self.async_load()
        for existing in patterns:
            if existing != pattern and existing.get("name") == new_name:
                _LOGGER.warning("Pattern name '%s' already exists", new_name)
                return False
        
        pattern["name"] = new_name
        await self.async_save()
        return True

    async def async_delete_pattern(self, pattern_id: str | None = None, pattern_name: str | None = None) -> bool:
        """Delete a pattern."""
        patterns = await self.async_load()
        
        pattern_to_delete = None
        if pattern_id:
            for pattern in patterns:
                if pattern.get("id") == pattern_id:
                    pattern_to_delete = pattern
                    break
        elif pattern_name:
            for pattern in patterns:
                if pattern.get("name") == pattern_name:
                    pattern_to_delete = pattern
                    break
        
        if pattern_to_delete:
            patterns.remove(pattern_to_delete)
            self._patterns = patterns
            await self.async_save()
            return True
        
        return False

    async def async_list_patterns(self) -> list[dict[str, Any]]:
        """List all patterns."""
        return await self.async_load()
