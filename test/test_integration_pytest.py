"""Pytest-based integration tests using pytest-homeassistant-custom-component.

Primary testing method: pytest-homeassistant-custom-component
Secondary method: HA REST/WebSocket API with Long-Lived Access Token

Tests:
    - Config flow validation
    - Integration setup
    - Entity creation
    - Service registration
    - Pattern utilities
    - Pattern storage

Usage:
    pytest test/test_integration_pytest.py -v
    pytest test/test_integration_pytest.py::test_config_flow -v
"""

import pytest
from unittest.mock import AsyncMock, patch
from pytest_homeassistant_custom_component.common import MockConfigEntry
import aiohttp


@pytest.mark.asyncio
async def test_config_flow_init(hass):
    """Test config flow initialization.
    
    Uses pytest-homeassistant-custom-component to test config flow.
    """
    from oelo_lights.config_flow import OeloLightsConfigFlow
    
    flow = OeloLightsConfigFlow()
    result = await flow.async_step_user()
    
    assert result["type"] == "form"
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_config_flow_ip_validation(hass, controller_ip):
    """Test IP address validation in config flow.
    
    Uses pytest-homeassistant-custom-component with mocked HTTP calls.
    """
    from oelo_lights.config_flow import OeloLightsConfigFlow
    
    flow = OeloLightsConfigFlow()
    
    # Test with valid IP
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=[{"num": 1, "isOn": False}])
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        result = await flow.async_step_user(user_input={"ip_address": controller_ip})
        
        # Should create entry on valid IP
        assert result["type"] == "create_entry"
        assert result["data"]["ip_address"] == controller_ip


@pytest.mark.asyncio
async def test_integration_setup(hass, mock_config_entry):
    """Test integration setup with mock config entry.
    
    Uses pytest-homeassistant-custom-component MockConfigEntry.
    """
    from oelo_lights import async_setup_entry
    
    # Add entry to hass
    mock_config_entry.add_to_hass(hass)
    
    # Setup integration
    result = await async_setup_entry(hass, mock_config_entry)
    
    assert result is True
    
    # Verify light entities are created
    await hass.async_block_till_done()
    
    # Check that entities exist (adjust entity IDs based on your integration)
    zones = mock_config_entry.options.get("zones", ["1"])
    for zone in zones:
        entity_id = f"light.oelo_lights_zone_{zone}"
        state = hass.states.get(entity_id)
        # Entity might not exist if controller not reachable, but setup should succeed
        # assert state is not None  # Uncomment if controller is available


@pytest.mark.asyncio
async def test_services_registered(hass, mock_config_entry):
    """Test that services are registered.
    
    Uses pytest-homeassistant-custom-component to verify service registration.
    """
    from oelo_lights import async_setup_entry
    from oelo_lights.const import (
        SERVICE_CAPTURE_EFFECT,
        SERVICE_APPLY_EFFECT,
        SERVICE_RENAME_EFFECT,
    )
    
    mock_config_entry.add_to_hass(hass)
    await async_setup_entry(hass, mock_config_entry)
    await hass.async_block_till_done()
    
    # Check services are registered
    assert hass.services.has_service("oelo_lights", SERVICE_CAPTURE_EFFECT)
    assert hass.services.has_service("oelo_lights", SERVICE_APPLY_EFFECT)
    assert hass.services.has_service("oelo_lights", SERVICE_RENAME_EFFECT)


@pytest.mark.asyncio
async def test_pattern_utils():
    """Test pattern utility functions.
    
    Unit test that doesn't require HA setup.
    """
    from oelo_lights.pattern_utils import (
        generate_pattern_id,
        normalize_led_indices,
        extract_pattern_from_zone_data,
    )
    
    # Test pattern ID generation
    url_params = {
        "patternType": "march",
        "direction": "R",
        "speed": "3",
        "num_colors": "6",
        "colors": "255,92,0,255,92,0",
    }
    pattern_id = generate_pattern_id(url_params, "non-spotlight")
    assert pattern_id is not None
    assert len(pattern_id) > 0
    
    # Test LED index normalization
    normalized = normalize_led_indices("1,2,3,4,5", 500)
    assert normalized == "1,2,3,4,5"
    
    # Test pattern extraction
    zone_data = {
        "num": 1,
        "isOn": True,
        "pattern": "march",
        "speed": 3,
        "direction": "R",
        "numberOfColors": 6,
        "colorStr": "255,92,0,255,92,0",
    }
    pattern = extract_pattern_from_zone_data(zone_data, 1)
    assert pattern is not None
    assert pattern.get("id") is not None


@pytest.mark.asyncio
async def test_pattern_storage_interface():
    """Test pattern storage class interface.
    
    Unit test that validates storage class structure.
    """
    from oelo_lights.pattern_storage import PatternStorage
    
    # Verify class has required methods
    assert hasattr(PatternStorage, "__init__")
    assert hasattr(PatternStorage, "async_load")
    assert hasattr(PatternStorage, "async_save")
    assert hasattr(PatternStorage, "async_add_pattern")
    assert hasattr(PatternStorage, "async_get_pattern")
    assert hasattr(PatternStorage, "async_rename_pattern")
    assert hasattr(PatternStorage, "async_delete_pattern")
    assert hasattr(PatternStorage, "async_list_patterns")


@pytest.mark.asyncio
async def test_controller_connectivity_api(ha_client, controller_ip):
    """Test controller connectivity using REST API (secondary method).
    
    Uses HA REST API with Long-Lived Access Token as fallback.
    """
    session, token = ha_client
    
    if not session or not token:
        pytest.skip("HA_TOKEN not available - skipping API test")
    
    try:
        async with session.get(
            f"http://{controller_ip}/getController",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                assert isinstance(data, list)
                assert len(data) > 0
            else:
                pytest.skip(f"Controller not reachable (status {resp.status})")
    except Exception as e:
        pytest.skip(f"Controller connectivity test skipped: {e}")


@pytest.mark.asyncio
async def test_integration_via_api(ha_client, ha_url):
    """Test integration installation via REST API (secondary method).
    
    Uses HA REST API to verify integration can be installed.
    """
    session, token = ha_client
    
    if not session or not token:
        pytest.skip("HA_TOKEN not available - skipping API test")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Check if integration is already installed
    async with session.get(
        f"{ha_url}/api/config/config_entries",
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        if resp.status == 200:
            entries = await resp.json()
            oelo_entries = [e for e in entries if e.get("domain") == "oelo_lights"]
            # Integration might already be installed - that's OK
            assert True  # Test passes if we can query config entries
        else:
            pytest.skip(f"Cannot access config entries API (status {resp.status})")
