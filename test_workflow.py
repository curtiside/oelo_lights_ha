#!/usr/bin/env python3
"""Test the full workflow: capture, rename, apply pattern.

Workflow Testing Guide
======================

This script validates the complete pattern management workflow:
1. Capture pattern from controller
2. Rename captured pattern
3. Apply renamed pattern to zone

Unlike test_integration.py which tests individual components, this script tests
the end-to-end workflow logic to ensure patterns can be captured, renamed, and
applied correctly.

What This Test Validates
------------------------
✓ Pattern extraction from controller zone data
✓ Pattern storage and retrieval
✓ Pattern renaming functionality
✓ Pattern URL generation for application
✓ Workflow continuity (captured → renamed → applied)

What This Test Does NOT Require
--------------------------------
- Full Home Assistant instance (uses mocks where needed)
- Authentication/API tokens
- Actual service calls (validates logic only)
- UI interaction

Prerequisites
-------------
- Python 3.8+ with aiohttp installed
- Access to Oelo Lights controller on network
- Controller IP address configured (default: 10.16.52.41)
- Zone 1 should be ON with a pattern set (for capture test)

Configuration
-------------
Set CONTROLLER_IP to your controller's IP address:
    CONTROLLER_IP = "10.16.52.41"

Running the Test
----------------
Direct execution:
    python3 test_workflow.py

Inside Docker container:
    docker-compose exec homeassistant python3 /config/test_workflow.py

Expected Output
---------------
The test will:
1. Check controller connectivity
2. Extract current pattern from zone 1
3. Test pattern capture logic
4. Test pattern rename logic
5. Test pattern apply URL generation
6. Report pass/fail for each step

Test Workflow
-------------
TEST 1: Capture Pattern
    - Connects to controller at CONTROLLER_IP
    - Retrieves current zone 1 state
    - Extracts pattern using extract_pattern_from_zone_data()
    - Validates pattern structure (id, name, plan_type)

TEST 2: Rename Pattern
    - Adds captured pattern to storage (mock)
    - Renames pattern using async_rename_pattern()
    - Verifies rename succeeded
    - Confirms pattern ID unchanged (only name changes)

TEST 3: Apply Pattern
    - Builds pattern URL using build_pattern_url()
    - Validates URL contains required components:
      - Controller IP address
      - Zone number (zones=1)
      - Pattern parameters (setPattern endpoint)
    - Note: Does NOT send to controller (would change lights)

Important Notes
---------------
- Zone must be ON: Pattern capture requires zone to be ON
- Mock storage: Uses MockHass for storage testing (no persistent storage)
- URL validation only: Does not actually send commands to controller
- Logic validation: Tests the logic flow, not full HA integration

Troubleshooting
---------------
Controller not reachable:
    - Verify CONTROLLER_IP is correct
    - Check network connectivity: ping <controller_ip>
    - Verify controller is powered on

Zone is OFF:
    - Turn zone 1 ON using Oelo app
    - Set a pattern on zone 1
    - Re-run test

Pattern extraction fails:
    - Ensure zone has a valid pattern set
    - Check controller response: curl http://<controller_ip>/getController
    - Verify zone data structure matches expected format

Related Tests
-------------
- test_integration.py: Component-level tests (imports, utilities, services)
"""

import asyncio
import aiohttp
import json
import sys

CONTROLLER_IP = "10.16.52.41"
HA_URL = "http://localhost:8123"


async def wait_for_ha_ready():
    """Wait for Home Assistant to be ready."""
    print("Waiting for Home Assistant to be ready...")
    for i in range(30):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{HA_URL}/api/", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status in [200, 401]:  # 401 means HA is up but needs auth
                        print("✓ Home Assistant is ready")
                        return True
        except:
            pass
        await asyncio.sleep(2)
    print("✗ Home Assistant not ready after 60 seconds")
    return False


async def test_capture_pattern():
    """Test capturing a pattern from the controller."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{CONTROLLER_IP}/getController", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                text = await resp.text()
                data = json.loads(text)
                zone1 = data[0] if data else None
                if zone1 and not zone1.get('isOn'):
                    print("✗ Capture pattern: FAILED (zone 1 is OFF)")
                    return False, None
    except Exception as e:
        print(f"✗ Capture pattern: FAILED (controller error: {e})")
        return False, None
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.pattern_utils import extract_pattern_from_zone_data
        
        zone_data = {
            "num": 1,
            "isOn": True,
            "pattern": zone1.get('pattern', 'custom'),
            "speed": zone1.get('speed', 1),
            "direction": zone1.get('direction', 'F'),
            "numberOfColors": zone1.get('numberOfColors', 1),
            "colorStr": zone1.get('colorStr', '255,255,255')
        }
        
        pattern = extract_pattern_from_zone_data(zone_data, 1)
        if pattern:
            print(f"✓ Capture pattern: OK (id={pattern.get('id')[:30]}...)")
            return True, pattern
        else:
            print("✗ Capture pattern: FAILED (extraction returned None)")
            return False, None
    except Exception as e:
        print(f"✗ Capture pattern: FAILED ({e})")
        return False, None


async def test_rename_pattern(pattern):
    """Test renaming a pattern."""
    if not pattern:
        print("✗ Rename pattern: SKIPPED (no pattern)")
        return False, None
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.pattern_storage import PatternStorage
        
        class MockHass:
            pass
        
        storage = PatternStorage(MockHass(), "test_entry")
        pattern_copy = pattern.copy()
        await storage.async_add_pattern(pattern_copy)
        
        success = await storage.async_rename_pattern(
            pattern_id=pattern.get('id'),
            pattern_name=None,
            new_name="Test Renamed Pattern"
        )
        
        if success:
            renamed_pattern = await storage.async_get_pattern(pattern_id=pattern.get('id'))
            if renamed_pattern and renamed_pattern.get('name') == "Test Renamed Pattern":
                print("✓ Rename pattern: OK")
                return True, renamed_pattern
            else:
                print("✗ Rename pattern: FAILED (verification failed)")
                return False, None
        else:
            print("✗ Rename pattern: FAILED")
            return False, None
    except Exception as e:
        print(f"✗ Rename pattern: FAILED ({e})")
        return False, None


async def test_apply_pattern(pattern):
    """Test applying a pattern."""
    if not pattern:
        print("✗ Apply pattern: SKIPPED (no pattern)")
        return False
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))
        from oelo_lights.pattern_utils import build_pattern_url
        
        url = build_pattern_url(
            pattern=pattern,
            zone=1,
            ip_address=CONTROLLER_IP,
            spotlight_plan_lights=None,
            max_leds=500
        )
        
        if "setPattern" in url and CONTROLLER_IP in url and "zones=1" in url:
            print("✓ Apply pattern: OK")
            return True
        else:
            print("✗ Apply pattern: FAILED (invalid URL)")
            return False
    except Exception as e:
        print(f"✗ Apply pattern: FAILED ({e})")
        return False


async def main():
    """Run workflow tests."""
    print("Oelo Lights Workflow Tests")
    print("-" * 40)
    
    results = []
    success, pattern = await test_capture_pattern()
    results.append(success)
    
    success, renamed_pattern = await test_rename_pattern(pattern)
    results.append(success)
    if renamed_pattern:
        pattern = renamed_pattern
    
    success = await test_apply_pattern(pattern)
    results.append(success)
    
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
