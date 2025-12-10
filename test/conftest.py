"""Pytest configuration and fixtures for Oelo Lights integration tests.

Uses pytest-homeassistant-custom-component as the primary testing framework.
Falls back to HA REST/WebSocket API with Long-Lived Access Token as secondary method.

Fixtures:
    hass: Home Assistant instance (from pytest-homeassistant-custom-component)
    enable_custom_integrations: Auto-enable custom integrations
    mock_config_entry: Mock configuration entry for testing
    ha_client: aiohttp client session with HA token for API testing
"""

import pytest
from typing import Any
import os

# Import pytest-homeassistant-custom-component fixtures
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock configuration entry for testing.
    
    Returns:
        MockConfigEntry: Mock config entry with default Oelo Lights settings
    """
    return MockConfigEntry(
        domain="oelo_lights",
        data={
            "ip_address": os.environ.get("CONTROLLER_IP", "10.16.52.41"),
        },
        options={
            "zones": ["1", "2", "3", "4", "5", "6"],
            "poll_interval": 300,
            "auto_poll": True,
            "max_leds": 500,
            "spotlight_plan_lights": "1,2,3,4,8,9,10,11",
            "verify_commands": False,
            "verification_retries": 3,
            "verification_delay": 2,
            "verification_timeout": 30,
            "command_timeout": 10,
            "debug_logging": False,
        },
        title="Oelo Lights Test",
        entry_id="test_oelo_entry_1",
    )


@pytest.fixture
async def ha_client():
    """Create an aiohttp client session for HA REST API testing.
    
    This fixture provides API access as a fallback when pytest-homeassistant-custom-component
    doesn't cover specific test scenarios.
    
    Returns:
        tuple: (session, token) for API calls
    """
    import aiohttp
    
    # Get or create a test token from environment
    token = os.environ.get("HA_TOKEN")
    
    async with aiohttp.ClientSession() as session:
        yield (session, token)


@pytest.fixture
def controller_ip() -> str:
    """Get controller IP from environment or use default.
    
    Returns:
        str: Controller IP address
    """
    return os.environ.get("CONTROLLER_IP", "10.16.52.41")


@pytest.fixture
def ha_url() -> str:
    """Get Home Assistant URL from environment or use default.
    
    Returns:
        str: Home Assistant URL
    """
    return os.environ.get("HA_URL", "http://localhost:8123")
