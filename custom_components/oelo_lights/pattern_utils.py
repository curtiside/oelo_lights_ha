"""Pattern utility functions for Oelo Lights integration.

Utilities: pattern ID generation (Hubitat-compatible), LED normalization,
spotlight plan color reconstruction, URL building, pattern extraction.

Spotlight Plan (CRITICAL): Controller returns only 40 LEDs, zones up to 500.
Capture: store original colors separately. Apply: reconstruct full array using
Spotlight Plan Lights config (only specified LEDs lit, others off).
"""

from __future__ import annotations
import logging
import urllib.parse
from typing import Any
from .const import DEFAULT_SPOTLIGHT_PLAN_LIGHTS

_LOGGER = logging.getLogger(__name__)


def generate_pattern_id(url_params: dict[str, Any], plan_type: str = "non-spotlight") -> str:
    """Generate a stable pattern ID from URL parameters.
    
    Matches Hubitat driver algorithm exactly for compatibility.
    Format: {patternType}_dir{direction}_spd{speed}_{num_colors}colors_rgb{r}-{g}-{b}
    
    Args:
        url_params: Pattern URL parameters
        plan_type: "spotlight" or "non-spotlight" (affects ID generation)
    
    Returns:
        Stable pattern identifier string
    """
    pattern_type = url_params.get("patternType", "unknown")
    direction = url_params.get("direction", "F")
    speed = url_params.get("speed", "0")
    num_colors = url_params.get("num_colors", "1")
    
    # Build suffix parts
    suffix_parts = []
    
    # Add direction if not default
    if direction and direction != "0" and direction != "F":
        suffix_parts.append(f"dir{direction}")
    
    # Add speed if not zero
    if speed and speed != "0":
        try:
            speed_int = int(speed)
            if speed_int != 0:
                suffix_parts.append(f"spd{speed_int}")
        except (ValueError, TypeError):
            pass
    
    # Add number of colors for non-spotlight patterns only
    if plan_type != "spotlight" and num_colors:
        try:
            num_colors_int = int(num_colors)
            if num_colors_int > 1:
                suffix_parts.append(f"{num_colors_int}colors")
        except (ValueError, TypeError):
            pass
    
    # Extract first non-zero RGB color for ID
    colors_str = url_params.get("colors", "")
    rgb_part = ""
    if colors_str:
        color_parts = colors_str.split(",")
        # Find first non-zero RGB triplet
        for i in range(0, len(color_parts) - 2, 3):
            try:
                r = int(color_parts[i].strip())
                g = int(color_parts[i + 1].strip())
                b = int(color_parts[i + 2].strip())
                # Check if this is a non-zero color
                if r != 0 or g != 0 or b != 0:
                    rgb_part = f"_rgb{r}-{g}-{b}"
                    break
            except (ValueError, IndexError, TypeError):
                continue
    
    # Build pattern ID
    if suffix_parts:
        suffix = "_" + "_".join(suffix_parts)
    else:
        suffix = ""
    
    pattern_id = f"{pattern_type}{suffix}{rgb_part}"
    return pattern_id


def normalize_led_indices(led_indices_str: str, max_leds: int = 500) -> str:
    """Normalize LED indices string (remove duplicates, sort, validate)."""
    if not led_indices_str or not led_indices_str.strip():
        return ""
    
    try:
        # Parse indices
        indices = []
        for part in led_indices_str.split(","):
            part = part.strip()
            if part:
                idx = int(part)
                if 1 <= idx <= max_leds:
                    indices.append(idx)
        
        # Remove duplicates and sort
        indices = sorted(set(indices))
        
        return ",".join(str(i) for i in indices)
    except (ValueError, TypeError):
        _LOGGER.warning("Invalid LED indices format: %s", led_indices_str)
        return ""


def modify_spotlight_plan_colors(
    original_colors: str,
    led_indices_str: str,
    num_colors: int,
    max_leds: int = 500
) -> str:
    """Modify spotlight plan colors based on LED indices.
    
    **CRITICAL**: This function handles the controller's 40-LED limitation.
    The controller only returns 40 LEDs worth of color data, but zones can have
    up to 500 LEDs. This function reconstructs the full LED array.
    
    Process:
    1. Extract base color from original_colors (first non-zero RGB triplet)
    2. Parse LED indices from configuration
    3. Generate full LED array (up to max_leds):
       - Specified LEDs: Use base color
       - All other LEDs: Set to (0,0,0)
    
    Args:
        original_colors: Original color string from controller (limited to 40 LEDs)
        led_indices_str: Comma-delimited list of LED indices to turn on (e.g., "1,2,3,4")
        num_colors: Number of color triplets in original colors
        max_leds: Maximum number of LEDs in zone (default: 500)
    
    Returns:
        Modified color string with full LED array (max_leds * 3 values)
    """
    # Parse original colors
    original_rgb = []
    color_parts = original_colors.split(",")
    for i in range(0, len(color_parts), 3):
        if i + 2 < len(color_parts):
            try:
                r = max(0, min(255, int(color_parts[i].strip())))
                g = max(0, min(255, int(color_parts[i + 1].strip())))
                b = max(0, min(255, int(color_parts[i + 2].strip())))
                original_rgb.append((r, g, b))
            except (ValueError, IndexError):
                pass
    
    if not original_rgb:
        _LOGGER.warning("No valid colors found in original_colors: %s", original_colors)
        return original_colors
    
    # Get first color (or use first available)
    base_color = original_rgb[0] if original_rgb else (255, 255, 255)
    
    # Parse LED indices
    led_indices = []
    for part in led_indices_str.split(","):
        part = part.strip()
        if part:
            try:
                idx = int(part)
                if 1 <= idx <= max_leds:
                    led_indices.append(idx)
            except ValueError:
                pass
    
    if not led_indices:
        _LOGGER.warning("No valid LED indices found: %s", led_indices_str)
        return original_colors
    
    # Generate full LED array
    modified_colors = []
    for led_num in range(1, max_leds + 1):
        if led_num in led_indices:
            # Use base color for specified LEDs
            modified_colors.extend(base_color)
        else:
            # All other LEDs off
            modified_colors.extend((0, 0, 0))
    
    return ",".join(str(c) for c in modified_colors)


def build_pattern_url(
    pattern: dict[str, Any],
    zone: int,
    ip_address: str,
    spotlight_plan_lights: str | None = None,
    max_leds: int = 500
) -> str:
    """Build pattern URL from stored pattern data.
    
    Handles spotlight plan reconstruction if needed:
    - For spotlight plans: Reconstructs full LED array from original_colors
    - For non-spotlight plans: Uses colors as-is
    
    Args:
        pattern: Stored pattern dictionary (id, name, url_params, plan_type, original_colors)
        zone: Zone number (1-6) to apply pattern to
        ip_address: Controller IP address
        spotlight_plan_lights: LED indices for spotlight plans (comma-delimited)
        max_leds: Maximum LEDs per zone
    
    Returns:
        Complete URL string for controller API call
    """
    url_params = pattern.get("url_params", {}).copy()
    
    # Update zone
    url_params["zones"] = str(zone)
    url_params["num_zones"] = "1"
    
    # Handle spotlight plans
    if pattern.get("plan_type") == "spotlight" and spotlight_plan_lights:
        original_colors = pattern.get("original_colors", "")
        num_colors = int(url_params.get("num_colors", "1"))
        modified_colors = modify_spotlight_plan_colors(
            original_colors,
            spotlight_plan_lights,
            num_colors,
            max_leds
        )
        url_params["colors"] = modified_colors
    
    # Build URL
    query_string = urllib.parse.urlencode(url_params)
    return f"http://{ip_address}/setPattern?{query_string}"


def extract_pattern_from_zone_data(zone_data: dict[str, Any], zone: int) -> dict[str, Any] | None:
    """Extract pattern information from zone data returned by controller."""
    if not zone_data:
        return None
    
    # Check if zone is on
    is_on = zone_data.get("isOn", False)
    pattern_type = zone_data.get("pattern") or zone_data.get("patternType", "off")
    
    if pattern_type == "off" or not is_on:
        _LOGGER.debug("Zone %d is off, cannot capture pattern", zone)
        return None
    
    # Build URL parameters from zone data
    url_params: dict[str, Any] = {
        "patternType": pattern_type,
        "zones": str(zone),
        "num_zones": "1",
    }
    
    # Extract other parameters from zone data
    url_params["speed"] = str(zone_data.get("speed", 0))
    url_params["gap"] = str(zone_data.get("gap", 0))
    url_params["direction"] = str(zone_data.get("direction", "F"))
    
    # Extract number of colors
    if "numberOfColors" in zone_data:
        url_params["num_colors"] = str(zone_data["numberOfColors"])
    elif "num_colors" in zone_data:
        url_params["num_colors"] = str(zone_data["num_colors"])
    else:
        url_params["num_colors"] = "1"
    
    # Extract colors - controller returns colorStr
    colors_str = zone_data.get("colorStr", "")
    if not colors_str and "colors" in zone_data:
        colors_str = str(zone_data["colors"])
    
    if colors_str:
        url_params["colors"] = colors_str
    else:
        # Fallback: generate default colors if missing
        url_params["colors"] = "255,255,255"
    
    # Set defaults for missing parameters
    url_params.setdefault("other", "0")
    url_params.setdefault("pause", "0")
    
    # Detect spotlight plan first
    plan_type = "spotlight" if pattern_type == "spotlight" else "non-spotlight"
    
    # Generate pattern ID (needs plan_type for correct generation)
    pattern_id = generate_pattern_id(url_params, plan_type)
    
    # Store original colors for spotlight plans (before any modification)
    original_colors = url_params.get("colors", "") if plan_type == "spotlight" else None
    
    return {
        "id": pattern_id,
        "name": pattern_id,  # Initial name same as ID, user can rename
        "url_params": url_params,
        "plan_type": plan_type,
        "original_colors": original_colors,
    }
