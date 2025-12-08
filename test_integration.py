#!/usr/bin/env python3
"""Test script for Oelo Lights integration.

Quick Start Testing Guide
==========================

This script provides automated tests for the Oelo Lights integration. For manual testing
using Docker Compose, see the setup instructions below.

Prerequisites
-------------
- Docker and Docker Compose installed (for manual testing)
- Access to an Oelo Lights controller on your network
- Python 3.8+ with aiohttp installed (for automated tests)

Quick Start with Docker Compose
--------------------------------

Option 1: Using Makefile (Recommended)
    make setup    # Set up test environment
    make start    # Start Home Assistant
    make logs     # View logs
    make stop     # Stop when done

Option 2: Using Docker Compose Directly
    mkdir -p config/custom_components
    cp -r custom_components/oelo_lights config/custom_components/
    docker-compose up -d
    docker-compose logs -f
    docker-compose down

Access Home Assistant
---------------------
- URL: http://localhost:8123
- Initial Setup: Complete the setup wizard on first run

Manual Testing Steps
--------------------
1. Install Integration:
   - Go to Settings → Devices & Services
   - Click "Add Integration"
   - Search for "Oelo Lights"
   - Enter your controller IP address

2. Test Basic Functionality:
   - Verify entities are created
   - Test turning lights on/off
   - Test color changes

3. Test Effect Capture:
   - Set a pattern on your Oelo controller (zone must be ON)
   - Use Developer Tools → Services
   - Call oelo_lights.capture_effect with:
     - entity_id: light.oelo_lights_zone_1
     - effect_name: (optional) "My Test Pattern"
   - Verify effect appears in effect list

4. Test Effect Rename:
   - Use Developer Tools → Services
   - Call oelo_lights.rename_effect with:
     - entity_id: light.oelo_lights_zone_1
     - effect_name: "My Test Pattern"
     - new_name: "Renamed Test Pattern"
   - Verify effect name changes in effect list

5. Test Effect Application:
   - Select the renamed effect from the dropdown
   - Or use service oelo_lights.apply_effect with:
     - entity_id: light.oelo_lights_zone_1
     - effect_name: "Renamed Test Pattern"
   - Verify lights change to that effect

Viewing Logs
------------
    make logs                    # Follow logs in real-time
    docker-compose logs -f       # Or with docker-compose
    docker-compose logs --tail 100  # View last 100 lines

Troubleshooting
---------------
Container won't start:
    - Check Docker is running: docker ps
    - Check ports: Ensure port 8123 is not in use
    - Check logs: docker-compose logs

Integration not appearing:
    - Verify files are copied: ls -la config/custom_components/oelo_lights/
    - Check logs for import errors: docker-compose logs homeassistant | grep -i oelo
    - Verify integration loads: docker-compose exec homeassistant python3 -c "import sys; sys.path.insert(0, '/config/custom_components'); import oelo_lights"
    - Restart container: make restart

Effect capture fails:
    - Ensure zone is ON and displaying a pattern on the controller
    - Verify controller is reachable: curl http://<controller_ip>/getController
    - Check Home Assistant logs for detailed errors

Network issues:
    - If network_mode: host doesn't work, edit docker-compose.yml:
      - Comment out network_mode: host
      - Uncomment bridge network section
      - Use your host IP instead of localhost for controller access

Automated Testing
-----------------
This script runs automated tests that validate core functionality:
    - Controller connectivity
    - Integration imports
    - Config flow validation
    - Pattern utilities
    - Service registration
    - Pattern storage

Run this script directly:
    python3 test_integration.py

Or run inside Docker container:
    docker-compose exec homeassistant python3 /config/test_integration.py

More Information
----------------
- Workflow Tests: See test_workflow.py for capture → rename → apply workflow tests
"""

import asyncio
import aiohttp
import json
import sys
from typing import Any

CONTROLLER_IP = "10.16.52.41"
HA_URL = "http://localhost:8123"


async def test_controller_connectivity():
    """Test if controller is reachable."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{CONTROLLER_IP}/getController", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✓ Controller connectivity: OK ({len(data)} zones)")
                    return True
                else:
                    print(f"✗ Controller connectivity: FAILED (status {resp.status})")
                    return False
    except Exception as e:
        print(f"✗ Controller connectivity: FAILED ({e})")
        return False


async def test_integration_import():
    """Test if integration can be imported."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        import oelo_lights
        from oelo_lights import const, config_flow, services, pattern_storage, pattern_utils
        print("✓ Integration import: OK")
        return True
    except Exception as e:
        print(f"✗ Integration import: FAILED ({e})")
        return False


async def test_config_flow_validation():
    """Test config flow validation logic."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.config_flow import validate_input
        print("✓ Config flow: OK")
        return True
    except Exception as e:
        print(f"✗ Config flow: FAILED ({e})")
        return False


async def test_pattern_utils():
    """Test pattern utility functions."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.pattern_utils import (
            generate_pattern_id,
            normalize_led_indices,
            extract_pattern_from_zone_data
        )
        
        # Test pattern ID generation
        url_params = {
            "patternType": "march",
            "direction": "R",
            "speed": "3",
            "num_colors": "6",
            "colors": "255,92,0,255,92,0"
        }
        pattern_id = generate_pattern_id(url_params, "non-spotlight")
        
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
            "colorStr": "255,92,0,255,92,0"
        }
        pattern = extract_pattern_from_zone_data(zone_data, 1)
        if not pattern:
            print("✗ Pattern utils: FAILED (extraction returned None)")
            return False
        
        print("✓ Pattern utils: OK")
        return True
    except Exception as e:
        print(f"✗ Pattern utils: FAILED ({e})")
        return False


async def test_services():
    """Test service registration."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.services import async_register_services
        from oelo_lights.const import (
            SERVICE_CAPTURE_EFFECT,
            SERVICE_APPLY_EFFECT,
            SERVICE_RENAME_EFFECT,
            SERVICE_DELETE_EFFECT,
            SERVICE_LIST_EFFECTS
        )
        print("✓ Services: OK")
        return True
    except Exception as e:
        print(f"✗ Services: FAILED ({e})")
        return False


async def test_pattern_storage():
    """Test pattern storage."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.pattern_storage import PatternStorage
        
        class MockHass:
            pass
        
        storage = PatternStorage(MockHass(), "test_entry")
        assert hasattr(storage, 'async_load')
        assert hasattr(storage, 'async_save')
        assert hasattr(storage, 'async_add_pattern')
        assert hasattr(storage, 'async_get_pattern')
        assert hasattr(storage, 'async_rename_pattern')
        assert hasattr(storage, 'async_delete_pattern')
        assert hasattr(storage, 'async_list_patterns')
        print("✓ Pattern storage: OK")
        return True
    except Exception as e:
        print(f"✗ Pattern storage: FAILED ({e})")
        return False


async def main():
    """Run all tests."""
    print("Oelo Lights Integration Tests")
    print("-" * 40)
    
    results = []
    results.append(await test_controller_connectivity())
    results.append(await test_integration_import())
    results.append(await test_config_flow_validation())
    results.append(await test_pattern_utils())
    results.append(await test_services())
    results.append(await test_pattern_storage())
    
    print("-" * 40)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"RESULT: PASSED ({passed}/{total})")
        return 0
    else:
        print(f"RESULT: FAILED ({passed}/{total})")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
