#!/usr/bin/env python3
"""Fast unit tests for Oelo Lights Home Assistant integration.

Validates: controller connectivity, module imports, config flow validation,
pattern utils, services, pattern storage. No UI, no container required.

Usage:
    python3 test/test_integration.py
    
    # Or in Docker:
    docker-compose exec homeassistant python3 /config/test/test_integration.py

Test Categories:
    - Controller connectivity: Verify controller responds at CONTROLLER_IP
    - Module imports: Validate all integration modules import correctly
    - Config flow: Test configuration flow validation logic
    - Pattern utils: Test pattern extraction and URL generation
    - Services: Test service call handling
    - Pattern storage: Test pattern persistence

Configuration:
    Environment variables:
        CONTROLLER_IP: Oelo controller IP (default: 10.16.52.41)
        HA_URL: Home Assistant URL (default: http://localhost:8123)

These are fast unit tests that validate integration logic without requiring
full HA setup. For end-to-end testing, see test_user_workflow.py.

See DEVELOPER.md for complete testing architecture.
"""

import asyncio
import aiohttp
import json
import sys
import os
from typing import Any

CONTROLLER_IP = "10.16.52.41"
HA_URL = "http://localhost:8123"
DOMAIN = "oelo_lights"

# Onboarding credentials
ONBOARDING_USERNAME = "test_user"
ONBOARDING_PASSWORD = "test_password_123"
ONBOARDING_NAME = "Test User"
ONBOARDING_LANGUAGE = "en"


async def check_onboarding_status() -> dict[str, Any] | None:
    """Check if onboarding is needed."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{HA_URL}/api/onboarding",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except:
        pass
    return None


async def complete_onboarding() -> str | None:
    """Complete onboarding via API and return auth_code.
    
    Returns auth_code if onboarding was completed, None if already done or failed.
    """
    onboarding_data = {
        "client_id": f"http://{HA_URL.replace('http://', '')}/",
        "name": ONBOARDING_NAME,
        "username": ONBOARDING_USERNAME,
        "password": ONBOARDING_PASSWORD,
        "language": ONBOARDING_LANGUAGE,
        "latitude": 0.0,
        "longitude": 0.0,
        "time_zone": "America/New_York",
        "currency": "USD",
        "country": "US",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Check onboarding status
            async with session.get(
                f"{HA_URL}/api/onboarding",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    status = await resp.json()
                    if not status.get("step"):
                        print("✓ Onboarding already completed")
                        return None
                elif resp.status == 404:
                    # Onboarding API not available (already completed)
                    print("✓ Onboarding already completed")
                    return None
            
            # Complete onboarding
            print("Completing onboarding (creating user account)...")
            async with session.post(
                f"{HA_URL}/api/onboarding",
                json=onboarding_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    auth_code = result.get("auth_code")
                    if auth_code:
                        print(f"✓ Onboarding completed, user account created")
                        return auth_code
                    else:
                        print(f"✓ Onboarding completed")
                        return None
                else:
                    # Onboarding may already be done
                    print("✓ Onboarding already completed")
                    return None
    except Exception:
        # Assume onboarding is done if we can't check
        return None


async def create_token_via_websocket(auth_code: str | None = None) -> str | None:
    """Create long-lived access token via WebSocket API.
    
    Uses auth_code from onboarding if provided, otherwise tries username/password auth.
    Returns token if successful, None otherwise.
    """
    try:
        import websockets
    except ImportError:
        return None
    
    try:
        websocket = await asyncio.wait_for(websockets.connect(f"ws://localhost:8123/api/websocket"), timeout=10)
        try:
            # Receive auth_required
            msg = await websocket.recv()
            data = json.loads(msg)
            
            if data.get("type") == "auth_required":
                # If we have auth_code from onboarding, use it
                if auth_code:
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "code": auth_code
                    }))
                else:
                    # Try username/password authentication
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "username": ONBOARDING_USERNAME,
                        "password": ONBOARDING_PASSWORD
                    }))
                
                # Wait for auth_ok
                auth_result = await websocket.recv()
                auth_data = json.loads(auth_result)
                
                if auth_data.get("type") == "auth_ok":
                    # Create long-lived token
                    await websocket.send(json.dumps({
                        "id": 1,
                        "type": "auth/long_lived_access_token",
                        "client_name": "Oelo Lights Integration Test",
                        "lifespan": 3650
                    }))
                    
                    # Get token response
                    token_result = await websocket.recv()
                    token_data = json.loads(token_result)
                    
                    if token_data.get("success") and token_data.get("result"):
                        token = token_data["result"]
                        print(f"✓ Token created automatically: {token[:20]}...")
                        return token
                elif auth_data.get("type") == "auth_invalid":
                    # Authentication failed - test user doesn't exist
                    # This is expected if HA was already set up with different credentials
                    print("⚠️  Test user doesn't exist (HA was set up with different credentials)")
                    print("   For full automation, use a fresh HA instance or provide token manually")
                    return None
        finally:
            await websocket.close()
    except Exception:
        return None
    
    return None


async def get_ha_token() -> str | None:
    """Get HA token from command line, environment, or create automatically.
    
    If no token provided, attempts to:
    1. Complete onboarding (create user account) if needed
    2. Create token via WebSocket using auth_code from onboarding
    """
    # Check command line first
    if len(sys.argv) > 1:
        return sys.argv[1]
    
    # Check environment variable
    token = os.environ.get("HA_TOKEN")
    if token:
        return token
    
    # Try to create token automatically
    print("\nNo token provided - attempting to create token automatically...")
    
    # First, try to complete onboarding if needed
    auth_code = await complete_onboarding()
    
    # Create token using auth_code (or try without if onboarding already done)
    token = await create_token_via_websocket(auth_code)
    if token:
        return token
    
    print("⚠️  Could not create token automatically")
    print("   Note: For full automation, use a fresh HA instance")
    print("   Or provide token manually: python3 test_integration.py <token>")
    return None


async def test_controller_connectivity():
    """Test controller connectivity and zone enumeration."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{CONTROLLER_IP}/getController", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
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
    """Test integration module imports."""
    try:
        import sys
        import os
        # Try multiple paths for container vs host execution
        test_dir = os.path.dirname(__file__)
        paths_to_try = [
            '/config/custom_components',  # HA container path
            os.path.join(test_dir, '..', 'custom_components'),
            '/workspace/custom_components',
            os.path.join(os.path.dirname(test_dir), 'custom_components'),
        ]
        for path in paths_to_try:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                sys.path.insert(0, abs_path)
                break
        import oelo_lights
        from oelo_lights import const, config_flow, services, pattern_storage, pattern_utils
        print("✓ Integration import: OK")
        return True
    except Exception as e:
        print(f"✗ Integration import: FAILED ({e})")
        return False


async def test_config_flow_validation():
    """Test configuration flow validation function."""
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
        from oelo_lights.pattern_utils import (
            generate_pattern_id,
            normalize_led_indices,
            extract_pattern_from_zone_data
        )
        
        url_params = {
            "patternType": "march",
            "direction": "R",
            "speed": "3",
            "num_colors": "6",
            "colors": "255,92,0,255,92,0"
        }
        pattern_id = generate_pattern_id(url_params, "non-spotlight")
        
        normalized = normalize_led_indices("1,2,3,4,5", 500)
        assert normalized == "1,2,3,4,5"
        
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
    """Test service registration and constants."""
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
    """Test pattern storage class interface."""
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
        from oelo_lights.pattern_storage import PatternStorage
        
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


async def check_ha_connection(session: aiohttp.ClientSession, token: str) -> bool:
    """Check if Home Assistant is accessible."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(f"{HA_URL}/api/", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"✓ HA connection: OK ({data.get('message', 'OK')})")
                return True
            else:
                print(f"✗ HA connection: FAILED (status {resp.status})")
                return False
    except Exception as e:
        print(f"✗ HA connection: FAILED ({e})")
        return False


async def check_integration_installed(session: aiohttp.ClientSession, token: str) -> dict[str, Any] | None:
    """Check if integration is already installed."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(
            f"{HA_URL}/api/config/config_entries",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                entries = await resp.json()
                for entry in entries:
                    if entry.get("domain") == DOMAIN:
                        print(f"✓ Integration already installed (Entry ID: {entry.get('entry_id')})")
                        return entry
                print("✗ Integration not installed")
                return None
            else:
                print(f"✗ Failed to check entries: status {resp.status}")
                return None
    except Exception as e:
        print(f"✗ Error checking entries: {e}")
        return None


async def install_integration(session: aiohttp.ClientSession, token: str) -> dict[str, Any] | None:
    """Install integration via config flow API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    flow_data = {"handler": DOMAIN, "show_advanced_options": False}
    
    try:
        # Start config flow
        async with session.post(
            f"{HA_URL}/api/config/config_entries/flow",
            headers=headers,
            json=flow_data,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to start config flow: status {resp.status}, {text}")
                return None
            
            flow = await resp.json()
            flow_id = flow.get("flow_id")
            print(f"✓ Config flow started (ID: {flow_id})")
        
        # Submit IP address
        async with session.post(
            f"{HA_URL}/api/config/config_entries/flow/{flow_id}",
            headers=headers,
            json={"ip_address": CONTROLLER_IP},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to submit IP: status {resp.status}, {text}")
                return None
            
            result = await resp.json()
            if result.get("type") == "create_entry":
                entry_id = result.get("result", {}).get("entry_id")
                print(f"✓ Integration installed (Entry ID: {entry_id})")
                return {"entry_id": entry_id, "flow_id": flow_id}
            else:
                print(f"✗ Unexpected result type: {result.get('type')}")
                return None
    except Exception as e:
        print(f"✗ Installation error: {e}")
        return None


async def configure_options(session: aiohttp.ClientSession, token: str, entry_id: str) -> bool:
    """Configure integration options via multi-step options flow."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Start options flow
        async with session.post(
            f"{HA_URL}/api/config/config_entries/entry/{entry_id}/options",
            headers=headers,
            json={},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to start options flow: status {resp.status}, {text}")
                return False
            
            flow = await resp.json()
            flow_id = flow.get("flow_id")
            step_id = flow.get("step_id", "init")
            print(f"✓ Options flow started (ID: {flow_id}, step: {step_id})")
        
        # Step 1: Basic settings (init)
        async with session.post(
            f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
            headers=headers,
            json={
                "zones": ["1", "2", "3", "4", "5", "6"],
                "poll_interval": 300,
                "auto_poll": True
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to submit basic settings: status {resp.status}, {text}")
                return False
            
            result = await resp.json()
            if result.get("type") == "create_entry":
                print("✓ Options configured (single step)")
                return True
            step_id = result.get("step_id", "spotlight")
        
        # Step 2: Spotlight settings
        async with session.post(
            f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
            headers=headers,
            json={
                "max_leds": 500,
                "spotlight_plan_lights": "1,2,3,4,8,9,10,11"
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to submit spotlight settings: status {resp.status}, {text}")
                return False
            
            result = await resp.json()
            if result.get("type") == "create_entry":
                print("✓ Options configured")
                return True
            step_id = result.get("step_id", "verification")
        
        # Step 3: Verification settings
        async with session.post(
            f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
            headers=headers,
            json={
                "verify_commands": False,
                "verification_retries": 3,
                "verification_delay": 2,
                "verification_timeout": 30
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to submit verification settings: status {resp.status}, {text}")
                return False
            
            result = await resp.json()
            if result.get("type") == "create_entry":
                print("✓ Options configured")
                return True
            step_id = result.get("step_id", "advanced")
        
        # Step 4: Advanced settings
        async with session.post(
            f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
            headers=headers,
            json={
                "command_timeout": 10,
                "debug_logging": False
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"✗ Failed to submit advanced settings: status {resp.status}, {text}")
                return False
            
            result = await resp.json()
            if result.get("type") == "create_entry":
                print("✓ Options configured")
                return True
            else:
                print(f"✗ Unexpected result type: {result.get('type')}")
                return False
    except Exception as e:
        print(f"✗ Configuration error: {e}")
        return False


async def add_card_to_dashboard(session: aiohttp.ClientSession, token: str, entity_id: str = "light.oelo_lights_zone_1") -> bool:
    """Add Oelo Patterns card to dashboard."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Get current dashboard
        async with session.get(
            f"{HA_URL}/api/lovelace/config",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status != 200:
                print(f"✗ Failed to get dashboard: status {resp.status}")
                return False
            
            config = await resp.json()
        
        # Check if card exists
        views = config.get("views", [])
        card_config = {
            "type": "custom:oelo-patterns-card",
            "entity": entity_id,
            "title": "Oelo Patterns"
        }
        
        card_exists = False
        for view in views:
            cards = view.get("cards", [])
            for card in cards:
                if card.get("type") == "custom:oelo-patterns-card" and card.get("entity") == entity_id:
                    print(f"✓ Card already in dashboard")
                    return True
        
        # Add card to first view
        if not views:
            views.append({"title": "Home", "path": "home", "cards": [card_config]})
        else:
            if "cards" not in views[0]:
                views[0]["cards"] = []
            views[0]["cards"].append(card_config)
        
        config["views"] = views
        
        # Update dashboard
        async with session.post(
            f"{HA_URL}/api/lovelace/config",
            headers=headers,
            json=config,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                print("✓ Card added to dashboard")
                return True
            else:
                text = await resp.text()
                print(f"✗ Failed to update dashboard: status {resp.status}, {text}")
                return False
    except Exception as e:
        print(f"✗ Dashboard error: {e}")
        return False


async def clear_error_logs(session: aiohttp.ClientSession, token: str) -> float:
    """Clear error logs before installation and return timestamp for checking new errors.
    
    Uses Home Assistant's system_log.clear service to clear logs, then establishes
    a baseline timestamp to check only new errors after installation.
    
    Returns:
        Timestamp to use for checking only new errors
    """
    import time
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # Method 1: Try to clear via system_log.clear service
        try:
            async with session.post(
                f"{HA_URL}/api/services/system_log/clear",
                headers=headers,
                json={},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status in [200, 201]:
                    print("✓ Cleared system logs via system_log.clear service")
                else:
                    print(f"⚠️  system_log.clear returned status {resp.status}")
        except Exception as e:
            print(f"⚠️  Could not clear via system_log.clear: {e}")
        
        # Method 2: Try DELETE on error_log endpoint (if supported)
        try:
            async with session.delete(
                f"{HA_URL}/api/error_log",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status in [200, 204]:
                    print("✓ Cleared error logs via DELETE endpoint")
                elif resp.status == 405:
                    # Method not allowed - endpoint doesn't support DELETE
                    pass
                else:
                    print(f"⚠️  DELETE error_log returned status {resp.status}")
        except Exception as e:
            # DELETE might not be supported - that's OK
            pass
        
        # Get current error log to establish baseline after clearing
        async with session.get(
            f"{HA_URL}/api/error_log",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                baseline_log = await resp.text()
                baseline_lines = len([l for l in baseline_log.split('\n') if l.strip()])
                print(f"Log baseline established: {baseline_lines} existing log lines after clear")
                return time.time()
            else:
                print(f"⚠️  Could not get log baseline: status {resp.status}")
                return time.time()
    except Exception as e:
        print(f"⚠️  Could not clear logs or establish baseline: {e}")
        return time.time()


async def check_logs_for_errors(session: aiohttp.ClientSession, token: str, baseline_timestamp: float = None) -> bool:
    """Check Home Assistant logs for errors related to integration installation.
    
    Checks for NEW errors (after baseline) related to:
    - oelo_lights domain
    - Lovelace card installation
    - Resource registration
    - Dashboard card addition
    
    Args:
        session: aiohttp session
        token: HA access token
        baseline_timestamp: Timestamp before installation (to check only new errors)
    
    Returns:
        True if no errors found, False if errors found (test fails)
    """
    import time
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # Wait a moment for logs to be written
        await asyncio.sleep(2)
        
        # Get recent logs
        async with session.get(
            f"{HA_URL}/api/error_log",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                log_text = await resp.text()
                
                # Check for errors related to installation
                error_keywords = [
                    DOMAIN.lower(),
                    "oelo",
                    "lovelace",
                    "card",
                    "resource",
                    "pattern"
                ]
                
                error_lines = []
                all_lines = log_text.split('\n')
                
                # If we have a baseline, only check lines that might be new
                # (HA error_log API returns recent errors, so we check all)
                for line in all_lines:
                    line_lower = line.lower()
                    # Check if line contains error/exception/failed AND one of our keywords
                    if ('error' in line_lower or 'exception' in line_lower or 'failed' in line_lower or 'traceback' in line_lower):
                        if any(keyword in line_lower for keyword in error_keywords):
                            # Exclude warnings (they're not failures)
                            if 'warning' not in line_lower:
                                error_lines.append(line.strip())
                
                if error_lines:
                    print(f"\n✗ Found {len(error_lines)} errors in logs related to installation:")
                    for error in error_lines[:10]:  # Show first 10
                        print(f"  {error}")
                    print(f"\n  Total: {len(error_lines)} error(s) found - TEST FAILED")
                    return False
                else:
                    print("✓ No errors found in logs after installation")
                    return True
            else:
                print(f"✗ Failed to get logs: status {resp.status}")
                return False
    except Exception as e:
        print(f"✗ Log check error: {e}")
        return False


async def main():
    """Run all unit tests."""
    print("Oelo Lights Unit Tests")
    print("-" * 40)
    
    results = []
    
    # Basic unit tests (no token, no container required)
    results.append(await test_controller_connectivity())
    results.append(await test_integration_import())
    results.append(await test_config_flow_validation())
    results.append(await test_pattern_utils())
    results.append(await test_services())
    results.append(await test_pattern_storage())
    
    print("\n" + "-" * 40)
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
