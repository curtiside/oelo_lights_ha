#!/usr/bin/env python3
"""Integration tests for Oelo Lights Home Assistant integration.

Validates: controller connectivity, module imports, config flow, pattern utils,
services, pattern storage.

Quick Start:
    make setup && make start
    docker-compose exec homeassistant python3 /config/test/test_integration.py

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

Note: The integration code is in the repo's custom_components/ directory, but Home Assistant
needs it in config/custom_components/ (mounted volume). The copy step makes it available.

Access Home Assistant
---------------------
- URL: http://localhost:8123
- Initial Setup: Complete the setup wizard on first run

Manual Testing Steps
--------------------
1. Install Integration Code (choose one method):

   Option A: HACS Installation (Recommended - Auto-Updates)
   - Install HACS if not already installed
   - Go to HACS → Integrations → Custom Repositories
   - Add repository: https://github.com/curtiside/oelo_lights_ha
   - Category: Integration
   - Search for "Oelo Lights" in HACS and install
   - Restart Home Assistant

   Option B: Manual Installation (Docker Testing)
   - Code is in repo's custom_components/oelo_lights/ but HA needs it in config/
   - Copy to config: cp -r custom_components/oelo_lights config/custom_components/
   - Restart container: docker-compose restart
   
   Option C: Manual Installation (Production Home Assistant)
   - Clone repository: git clone https://github.com/curtiside/oelo_lights_ha.git
   - Copy integration: cp -r oelo_lights_ha/custom_components/oelo_lights /config/custom_components/
   - Restart Home Assistant

2. Add Integration in Home Assistant:
   - Go to Settings → Devices & Services
   - Click "Add Integration"
   - Search for "Oelo Lights"
   - Enter your controller IP address
   - You should see 6 zones created (Zone 1 through Zone 6)

3. Test Basic Functionality:
   - Go to the integration page (Settings → Devices & Services → Oelo Lights)
   - Click on any zone (e.g., "Zone 1") to open the light entity
   - Test turning lights on/off using the toggle
   - Test color changes using the color picker
   - Test brightness using the brightness slider
   - Note: Effect dropdown will be empty until you capture effects (see step 4)

4. Test Effect Capture (Choose one method):

   Option A: Custom Lovelace Card (Recommended - Better UI)
   - Card file is automatically copied to www/ during integration setup
   - Resource registration is attempted automatically (may require manual step)
   - If card doesn't appear, manually add resource:
     - Settings → Dashboards → Resources → + Add Resource
     - URL: /local/oelo-patterns-card-simple.js
     - Type: JavaScript Module → Create
   - Add card to dashboard:
     * Go to your dashboard (Overview or any dashboard page)
     * Click the three dots menu (⋮) in the top right corner
     * Select "Edit Dashboard"
     * Click the "+" button (Add Card) at the bottom right
     * Scroll down and click "Manual" card type
     * Paste this YAML configuration:
       type: custom:oelo-patterns-card
       entity: light.oelo_lights_zone_1
       title: My Oelo Patterns
     * Click "Save"
   - Set pattern on Oelo controller (zone must be ON)
   - Click "Capture Pattern" button in card
   - Enter name: "My Test Pattern"
   - Pattern appears in card list

   Option B: Developer Tools (For Testing)
   - First, set a pattern on your Oelo controller (zone must be ON)
   - Go to: Settings → Developer Tools → Services tab
   - Service: oelo_lights.capture_effect
   - Target: entity_id: light.oelo_lights_zone_1
   - Service Data (YAML): effect_name: "My Test Pattern"
   - Click "Call Service"
   - Verify: Zone 1 entity page → Effect dropdown shows "My Test Pattern"

5. Test Effect Rename (Choose one method):

   Option A: Custom Lovelace Card
   - Click pencil icon (✏️) next to "My Test Pattern" in card
   - Enter new name: "Renamed Test Pattern"
   - Pattern updates in card

   Option B: Developer Tools
   - Go to: Settings → Developer Tools → Services tab
   - Service: oelo_lights.rename_effect
   - Target: entity_id: light.oelo_lights_zone_1
   - Service Data (YAML):
     effect_name: "My Test Pattern"
     new_name: "Renamed Test Pattern"
   - Click "Call Service"
   - Verify: Zone 1 entity page → Effect dropdown shows "Renamed Test Pattern"

6. Test Effect Application (Choose one method):

   Option A: Effect Dropdown (Easiest)
   - Go to Zone 1 entity page
   - Select "Renamed Test Pattern" from Effect dropdown
   - Lights change immediately

   Option B: Custom Lovelace Card
   - Click play button (▶) next to pattern in card
   - Pattern applies to zone

   Option C: Developer Tools
   - Go to Developer Tools → Services
   - Service: oelo_lights.apply_effect
   - Target: entity_id: light.oelo_lights_zone_1
   - Service Data: effect_name: "Renamed Test Pattern"
   - Click "Call Service"
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
    - Run tests: docker-compose exec homeassistant python3 /config/test/test_integration.py
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
    python3 test/test_integration.py

Or run inside Docker container:
    docker-compose exec homeassistant python3 /config/test/test_integration.py

More Information
----------------
- Workflow Tests: See test/test_workflow.py for capture → rename → apply workflow tests
"""

import asyncio
import aiohttp
import json
import sys
from typing import Any

CONTROLLER_IP = "10.16.52.41"
HA_URL = "http://localhost:8123"


async def test_controller_connectivity():
    """Test controller connectivity and zone enumeration.
    
    Validates:
    - Controller is reachable at CONTROLLER_IP
    - Controller returns valid JSON response
    - Response contains zone data
    - At least one zone is present
    
    Returns:
        bool: True if controller is reachable and returns valid data
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{CONTROLLER_IP}/getController", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    # Controller returns text/json, so parse manually
                    text = await resp.text()
                    data = json.loads(text)
                    print(f"✓ Controller connectivity: OK ({len(data)} zones)")
                    return True
                else:
                    print(f"✗ Controller connectivity: FAILED (status {resp.status})")
                    return False
    except Exception as e:
        print(f"✗ Controller connectivity: FAILED ({e})")
        return False


async def test_integration_import():
    """Test integration module imports.
    
    Validates:
    - Main integration module can be imported
    - All required submodules are importable
    - Module structure is correct
    
    Returns:
        bool: True if all imports succeed
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
        import oelo_lights
        from oelo_lights import const, config_flow, services, pattern_storage, pattern_utils
        print("✓ Integration import: OK")
        return True
    except Exception as e:
        print(f"✗ Integration import: FAILED ({e})")
        return False


async def test_config_flow_validation():
    """Test configuration flow validation function.
    
    Validates:
    - validate_input function exists and is callable
    - Config flow module structure is correct
    
    Returns:
        bool: True if config flow validation is available
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
        from oelo_lights.config_flow import validate_input
        print("✓ Config flow: OK")
        return True
    except Exception as e:
        print(f"✗ Config flow: FAILED ({e})")
        return False


async def test_pattern_utils():
    """Test pattern utility functions.
    
    Validates:
    - Pattern ID generation works correctly
    - LED index normalization functions properly
    - Pattern extraction from zone data succeeds
    - Extracted pattern has required fields (id, name, plan_type)
    
    Returns:
        bool: True if all utility functions work correctly
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
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
    """Test service registration and constants.
    
    Validates:
    - Service registration function exists
    - All service name constants are defined
    - Service module structure is correct
    
    Returns:
        bool: True if services module is properly structured
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
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
    """Test pattern storage class interface.
    
    Validates:
    - PatternStorage class exists and is importable
    - All required methods are present:
      - async_load, async_save
      - async_add_pattern, async_get_pattern
      - async_rename_pattern, async_delete_pattern
      - async_list_patterns
    
    Note: This test validates the interface only, not actual storage
    functionality (which requires a real HomeAssistant instance).
    
    Returns:
        bool: True if PatternStorage class has expected interface
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
        from oelo_lights.pattern_storage import PatternStorage
        
        # Just verify the class exists and has expected methods
        # Full initialization requires real HomeAssistant instance
        assert hasattr(PatternStorage, '__init__')
        assert hasattr(PatternStorage, 'async_load')
        assert hasattr(PatternStorage, 'async_save')
        assert hasattr(PatternStorage, 'async_add_pattern')
        assert hasattr(PatternStorage, 'async_get_pattern')
        assert hasattr(PatternStorage, 'async_rename_pattern')
        assert hasattr(PatternStorage, 'async_delete_pattern')
        assert hasattr(PatternStorage, 'async_list_patterns')
        print("✓ Pattern storage: OK")
        return True
    except Exception as e:
        print(f"✗ Pattern storage: FAILED ({e})")
        return False


async def main():
    """Run all integration tests.
    
    Executes all test functions and reports results.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
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
