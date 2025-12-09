#!/usr/bin/env python3
"""Full UI test runner: clean HA → onboarding → integration → UI verification.

Runs complete test process:
1. Wait for HA to be ready
2. Complete onboarding via API (creates user account)
3. Create token via API
4. Install integration via API
5. Configure options via API
6. Run UI verification tests (browser clicks)
7. Run workflow UI tests (pattern capture/rename/apply via UI)

All UI interactions use browser automation - no developer tools.
"""

import asyncio
import aiohttp
import json
import sys
import os
import time
import subprocess
from typing import Any

HA_URL = "http://localhost:8123"
CONTROLLER_IP = "10.16.52.41"
ONBOARDING_USERNAME = "test_user"
ONBOARDING_PASSWORD = "test_password_123"
ONBOARDING_NAME = "Test User"


async def wait_for_ha_ready(max_wait=120):
    """Wait for Home Assistant to be ready."""
    print("Waiting for Home Assistant to be ready...")
    for i in range(max_wait):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{HA_URL}/api/", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status in [200, 401]:
                        print(f"✓ Home Assistant is ready (after {i*2} seconds)")
                        return True
        except:
            pass
        await asyncio.sleep(2)
    print(f"✗ Home Assistant not ready after {max_wait*2} seconds")
    return False


async def complete_onboarding() -> str | None:
    """Complete onboarding via API and return auth_code."""
    onboarding_data = {
        "client_id": f"http://{HA_URL.replace('http://', '')}/",
        "name": ONBOARDING_NAME,
        "username": ONBOARDING_USERNAME,
        "password": ONBOARDING_PASSWORD,
        "language": "en",
        "latitude": 0.0,
        "longitude": 0.0,
        "time_zone": "America/New_York",
        "currency": "USD",
        "country": "US",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HA_URL}/api/onboarding", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 404:
                    print("✓ Onboarding already completed")
                    return None
            
            print("Completing onboarding (creating user account)...")
            async with session.post(f"{HA_URL}/api/onboarding", json=onboarding_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    auth_code = result.get("auth_code")
                    if auth_code:
                        print(f"✓ Onboarding completed, user account created")
                        return auth_code
                    print("✓ Onboarding completed")
                    return None
                else:
                    print("✓ Onboarding already completed")
                    return None
    except Exception:
        return None


async def create_token(auth_code: str | None = None) -> str | None:
    """Create long-lived access token via WebSocket."""
    try:
        import websockets
    except ImportError:
        return None
    
    try:
        async with websockets.connect(f"ws://localhost:8123/api/websocket", timeout=10) as websocket:
            msg = await websocket.recv()
            data = json.loads(msg)
            
            if data.get("type") == "auth_required":
                if auth_code:
                    await websocket.send(json.dumps({"type": "auth", "code": auth_code}))
                else:
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "username": ONBOARDING_USERNAME,
                        "password": ONBOARDING_PASSWORD
                    }))
                
                auth_result = await websocket.recv()
                auth_data = json.loads(auth_result)
                
                if auth_data.get("type") == "auth_ok":
                    await websocket.send(json.dumps({
                        "id": 1,
                        "type": "auth/long_lived_access_token",
                        "client_name": "Oelo Lights UI Test",
                        "lifespan": 3650
                    }))
                    
                    token_result = await websocket.recv()
                    token_data = json.loads(token_result)
                    
                    if token_data.get("success") and token_data.get("result"):
                        token = token_data["result"]
                        print(f"✓ Token created: {token[:20]}...")
                        return token
    except Exception:
        return None
    
    return None


async def install_integration(token: str) -> str | None:
    """Install integration via API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{HA_URL}/api/config/config_entries/flow",
                headers=headers,
                json={"handler": "oelo_lights"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                
                flow = await resp.json()
                flow_id = flow.get("flow_id")
            
            async with session.post(
                f"{HA_URL}/api/config/config_entries/flow/{flow_id}",
                headers=headers,
                json={"ip_address": CONTROLLER_IP},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                
                result = await resp.json()
                if result.get("type") == "create_entry":
                    entry_id = result.get("result", {}).get("entry_id")
                    print(f"✓ Integration installed (Entry ID: {entry_id})")
                    return entry_id
    except Exception:
        return None
    
    return None


async def configure_options(token: str, entry_id: str) -> bool:
    """Configure options via API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Start options flow
            async with session.post(
                f"{HA_URL}/api/config/config_entries/entry/{entry_id}/options",
                headers=headers,
                json={},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return False
                
                flow = await resp.json()
                flow_id = flow.get("flow_id")
            
            # Step 1: Basic
            async with session.post(
                f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
                headers=headers,
                json={"zones": ["1", "2", "3", "4", "5", "6"], "poll_interval": 300, "auto_poll": True},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return False
            
            # Step 2: Spotlight
            async with session.post(
                f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
                headers=headers,
                json={"max_leds": 500, "spotlight_plan_lights": "1,2,3,4,8,9,10,11"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return False
            
            # Step 3: Verification
            async with session.post(
                f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
                headers=headers,
                json={"verify_commands": False, "verification_retries": 3, "verification_delay": 2, "verification_timeout": 30},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return False
            
            # Step 4: Advanced
            async with session.post(
                f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
                headers=headers,
                json={"command_timeout": 10, "debug_logging": False},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return False
                
                result = await resp.json()
                if result.get("type") == "create_entry":
                    print("✓ Options configured")
                    return True
    except Exception:
        return False
    
    return False


def run_ui_test(test_file: str) -> int:
    """Run UI test file and return exit code."""
    print(f"\n{'='*60}")
    print(f"Running {test_file}...")
    print('='*60)
    
    test_path = os.path.join(os.path.dirname(__file__), test_file)
    if not os.path.exists(test_path):
        print(f"✗ Test file not found: {test_path}")
        return 1
    
    # Run test in container
    result = subprocess.run(
        ["docker-compose", "exec", "-T", "homeassistant", "python3", f"/config/test/{test_file}"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    return result.returncode


async def main():
    """Run full UI test process."""
    print("="*60)
    print("Oelo Lights Full UI Test Process")
    print("="*60)
    
    # Step 1: Wait for HA
    if not await wait_for_ha_ready():
        print("✗ Cannot proceed - HA not ready")
        return 1
    
    # Step 2: Complete onboarding
    print("\n=== Step 1: Onboarding ===")
    auth_code = await complete_onboarding()
    
    # Step 3: Create token
    print("\n=== Step 2: Create Token ===")
    token = await create_token(auth_code)
    if not token:
        print("✗ Cannot proceed - token creation failed")
        return 1
    
    # Step 4: Install integration
    print("\n=== Step 3: Install Integration ===")
    entry_id = await install_integration(token)
    if not entry_id:
        print("✗ Cannot proceed - integration installation failed")
        return 1
    
    # Step 5: Configure options
    print("\n=== Step 4: Configure Options ===")
    if not await configure_options(token, entry_id):
        print("⚠️  Options configuration failed, continuing anyway...")
    
    # Step 6: Wait for entities to be created
    print("\n=== Step 5: Waiting for entities ===")
    await asyncio.sleep(5)
    print("✓ Setup complete")
    
    # Step 7: Run UI tests
    print("\n=== Step 6: Running UI Tests ===")
    
    # Run integration UI tests
    integration_result = run_ui_test("test_integration_ui.py")
    
    # Run workflow UI tests
    workflow_result = run_ui_test("test_workflow_ui.py")
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    if integration_result == 0 and workflow_result == 0:
        print("RESULT: ALL TESTS PASSED")
        return 0
    else:
        print(f"RESULT: SOME TESTS FAILED (integration: {integration_result}, workflow: {workflow_result})")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
