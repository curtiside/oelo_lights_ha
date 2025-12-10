#!/usr/bin/env python3
"""End-to-end workflow tests: capture → rename → apply pattern.

Validates: pattern extraction, renaming, URL generation. Tests logic only,
not full HA integration. Requires Zone 1 ON with pattern set.

Usage:
    python3 test/test_workflow.py
    # Or in Docker:
    docker-compose exec homeassistant python3 /config/test/test_workflow.py

Test Workflow:
    1. Capture pattern from Zone 1 (must be ON with pattern)
    2. Extract pattern name from controller response
    3. Save pattern to storage
    4. Rename pattern using storage API
    5. Verify renamed pattern is visible in pattern list
    6. Generate apply URL with renamed pattern
    7. Verify URL format and parameters

Prerequisites:
    - Zone 1 must be ON with pattern set on controller
    - Controller accessible at CONTROLLER_IP
    - Home Assistant running (for API access)

Configuration:
    Environment variables:
        CONTROLLER_IP: Oelo controller IP (default: 10.16.52.41)
        HA_URL: Home Assistant URL (default: http://localhost:8123)

See DEVELOPER.md for complete testing architecture.
"""

import asyncio
import aiohttp
import json
import sys

CONTROLLER_IP = "10.16.52.41"
HA_URL = "http://localhost:8123"


async def wait_for_ha_ready():
    """Wait for Home Assistant to be ready.
    
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
    """Test capturing pattern from controller.
    
    Validates controller reachable, zone 1 ON with pattern, extraction succeeds.
    
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
        test_dir = os.path.dirname(__file__)
        paths_to_try = [
            '/config/custom_components',  # HA container path
            os.path.join(test_dir, '..', 'custom_components'),
            '/workspace/custom_components',
            os.path.join(os.path.dirname(test_dir), 'custom_components'),
        ]
        for path in paths_to_try:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path) and abs_path not in sys.path:
                sys.path.insert(0, abs_path)
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
    """Test renaming captured pattern with actual storage.
    
    Validates:
    1. Pattern is saved to storage
    2. Pattern is renamed using storage API
    3. Renamed pattern is visible in pattern list
    4. ID unchanged, other data preserved
    
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
        from unittest.mock import AsyncMock, MagicMock
        
        test_dir = os.path.dirname(__file__)
        paths_to_try = [
            '/config/custom_components',  # HA container path
            os.path.join(test_dir, '..', 'custom_components'),
            '/workspace/custom_components',
            os.path.join(os.path.dirname(test_dir), 'custom_components'),
        ]
        for path in paths_to_try:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path) and abs_path not in sys.path:
                sys.path.insert(0, abs_path)
        
        from oelo_lights.pattern_storage import PatternStorage
        
        # Create a mock Home Assistant instance for storage
        mock_hass = MagicMock()
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_save = AsyncMock()
        
        # Create storage instance with test entry ID
        storage = PatternStorage(mock_hass, "test_entry_workflow")
        storage.store = mock_store
        storage._patterns = []  # Start with empty patterns
        
        original_id = pattern.get('id')
        original_name = pattern.get('name')
        new_name = "Test Renamed Pattern"
        
        # Step 1: Add pattern to storage
        print("  Adding pattern to storage...")
        added = await storage.async_add_pattern(pattern)
        if not added:
            print("✗ Rename pattern: FAILED (could not add pattern to storage)")
            return False, None
        
        # Step 2: Verify pattern was added
        patterns_before = await storage.async_list_patterns()
        pattern_found = False
        for p in patterns_before:
            if p.get('id') == original_id:
                pattern_found = True
                if p.get('name') != original_name:
                    print(f"✗ Rename pattern: FAILED (pattern name mismatch: expected '{original_name}', got '{p.get('name')}')")
                    return False, None
                break
        
        if not pattern_found:
            print("✗ Rename pattern: FAILED (pattern not found in storage after add)")
            return False, None
        
        # Step 3: Rename the pattern
        print(f"  Renaming pattern from '{original_name}' to '{new_name}'...")
        renamed = await storage.async_rename_pattern(pattern_id=original_id, new_name=new_name)
        if not renamed:
            print("✗ Rename pattern: FAILED (rename operation returned False)")
            return False, None
        
        # Step 4: Verify rename is visible in pattern list
        patterns_after = await storage.async_list_patterns()
        renamed_pattern = None
        for p in patterns_after:
            if p.get('id') == original_id:
                renamed_pattern = p
                break
        
        if not renamed_pattern:
            print("✗ Rename pattern: FAILED (pattern not found in storage after rename)")
            return False, None
        
        # Step 5: Validate rename results
        if renamed_pattern.get('id') != original_id:
            print(f"✗ Rename pattern: FAILED (ID changed: expected '{original_id}', got '{renamed_pattern.get('id')}')")
            return False, None
        
        if renamed_pattern.get('name') != new_name:
            print(f"✗ Rename pattern: FAILED (name not updated: expected '{new_name}', got '{renamed_pattern.get('name')}')")
            return False, None
        
        # Verify other data preserved
        if renamed_pattern.get('url_params') != pattern.get('url_params'):
            print("✗ Rename pattern: FAILED (url_params changed)")
            return False, None
        
        print(f"✓ Rename pattern: OK (saved and verified in pattern list)")
        print(f"  Original name: '{original_name}'")
        print(f"  New name: '{new_name}'")
        print(f"  Pattern ID: '{original_id}' (unchanged)")
        return True, renamed_pattern
        
    except Exception as e:
        import traceback
        print(f"✗ Rename pattern: FAILED ({e})")
        traceback.print_exc()
        return False, None


async def test_apply_pattern(pattern):
    """Test applying pattern (URL generation only, no controller call).
    
    Validates URL generation from stored pattern data. Does not send commands.
    
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
        test_dir = os.path.dirname(__file__)
        paths_to_try = [
            '/config/custom_components',  # HA container path
            os.path.join(test_dir, '..', 'custom_components'),
            '/workspace/custom_components',
            os.path.join(os.path.dirname(test_dir), 'custom_components'),
        ]
        for path in paths_to_try:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path) and abs_path not in sys.path:
                sys.path.insert(0, abs_path)
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
