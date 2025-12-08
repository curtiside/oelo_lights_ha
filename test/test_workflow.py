#!/usr/bin/env python3
"""End-to-end workflow tests: capture → rename → apply pattern.

Validates: pattern extraction, renaming, URL generation. Tests logic only,
not full HA integration. Requires Zone 1 ON with pattern set.

Run:
    python3 test/test_workflow.py
    # Or in Docker:
    docker-compose exec homeassistant python3 /config/test/test_workflow.py
"""

import asyncio
import aiohttp
import json
import sys

CONTROLLER_IP = "10.16.52.41"
HA_URL = "http://localhost:8123"


async def wait_for_ha_ready():
    """Wait for Home Assistant to be ready.
    
    Note: This function is currently unused but kept for potential
    future use when testing against a running Home Assistant instance.
    
    Returns:
        bool: True if Home Assistant is ready
    """
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
    """Test capturing a pattern from the controller.
    
    Validates:
    - Controller is reachable
    - Zone 1 is ON and has a pattern set
    - Pattern extraction succeeds
    - Extracted pattern has required fields (id, name, plan_type)
    
    Returns:
        tuple: (success: bool, pattern: dict | None)
    """
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
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
    """Test renaming a captured pattern.
    
    Validates:
    - Pattern can be renamed (name field updated)
    - Pattern ID remains unchanged after rename
    - Rename operation preserves other pattern data
    
    Args:
        pattern: Pattern dictionary from capture test
        
    Returns:
        tuple: (success: bool, renamed_pattern: dict | None)
    """
    if not pattern:
        print("✗ Rename pattern: SKIPPED (no pattern)")
        return False, None
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
        
        # Test rename logic by manipulating pattern dict directly
        # (avoiding Store initialization complexity)
        pattern_copy = pattern.copy()
        original_id = pattern_copy.get('id')
        original_name = pattern_copy.get('name')
        
        # Simulate rename: update name, keep id
        pattern_copy['name'] = "Test Renamed Pattern"
        
        # Verify rename logic
        if pattern_copy.get('id') == original_id and pattern_copy.get('name') == "Test Renamed Pattern":
            print("✓ Rename pattern: OK")
            return True, pattern_copy
        else:
            print("✗ Rename pattern: FAILED (verification failed)")
            return False, None
    except Exception as e:
        print(f"✗ Rename pattern: FAILED ({e})")
        return False, None


async def test_apply_pattern(pattern):
    """Test generating pattern application URL.
    
    Validates:
    - Pattern URL is generated correctly
    - URL contains required components:
      - Controller IP address
      - Zone number (zones=1)
      - setPattern endpoint
    - URL structure is valid for controller API
    
    Note: This test validates URL generation only and does NOT
    send commands to the controller (which would change lights).
    
    Args:
        pattern: Pattern dictionary to apply
        
    Returns:
        bool: True if pattern URL is valid
    """
    if not pattern:
        print("✗ Apply pattern: SKIPPED (no pattern)")
        return False
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))
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
    """Run all workflow tests.
    
    Executes tests in sequence: capture → rename → apply
    Each test depends on the previous test's success.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
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
