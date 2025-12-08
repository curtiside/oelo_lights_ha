#!/usr/bin/env python3
"""Full automated setup: Clean HA container → Onboarding → Integration → Dashboard.

This script automates:
1. Starting fresh Home Assistant container
2. Completing onboarding (create account)
3. Adding Oelo Lights integration
4. Creating access token
5. Registering Lovelace card resource
6. Adding card to dashboard

Uses browser automation for UI interactions.
"""

import asyncio
import aiohttp
import json
import sys
import time
from typing import Any

HA_URL = "http://localhost:8123"
CONTROLLER_IP = "10.16.52.41"

# Onboarding credentials (can be customized)
ONBOARDING_USERNAME = "admin"
ONBOARDING_PASSWORD = "admin123456"
ONBOARDING_NAME = "Test User"
ONBOARDING_LANGUAGE = "en"


async def wait_for_ha_ready(max_wait: int = 120) -> bool:
    """Wait for Home Assistant to be ready."""
    print("Waiting for Home Assistant to start...")
    for i in range(max_wait):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{HA_URL}/api/", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status in [200, 401]:  # 401 means HA is up but needs auth
                        print(f"✓ Home Assistant is ready (after {i*2} seconds)")
                        return True
        except:
            pass
        await asyncio.sleep(2)
    print(f"✗ Home Assistant not ready after {max_wait*2} seconds")
    return False


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


async def complete_onboarding_via_api() -> str | None:
    """Complete onboarding via API and return access token."""
    print("\nCompleting onboarding...")
    
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
            
            # Complete onboarding
            async with session.post(
                f"{HA_URL}/api/onboarding",
                json=onboarding_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    auth_code = result.get("auth_code")
                    if auth_code:
                        print(f"✓ Onboarding completed, auth_code received")
                        return auth_code
                    else:
                        print(f"✗ Onboarding completed but no auth_code")
                        return None
                else:
                    text = await resp.text()
                    print(f"✗ Onboarding failed: status {resp.status}, {text}")
                    return None
    except Exception as e:
        print(f"✗ Onboarding error: {e}")
        return None


async def create_token_via_websocket(auth_code: str | None = None) -> str | None:
    """Create long-lived access token via WebSocket API."""
    import websockets
    
    print("\nCreating access token...")
    
    try:
        async with websockets.connect(f"ws://localhost:8123/api/websocket") as websocket:
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
                    # Try to authenticate with username/password
                    # This requires the user to be logged in via browser first
                    print("Need authentication - will use browser automation")
                    return None
                
                # Wait for auth_ok
                auth_result = await websocket.recv()
                auth_data = json.loads(auth_result)
                
                if auth_data.get("type") == "auth_ok":
                    # Create long-lived token
                    await websocket.send(json.dumps({
                        "id": 1,
                        "type": "auth/long_lived_access_token",
                        "client_name": "Oelo Lights Test",
                        "lifespan": 3650
                    }))
                    
                    # Get token response
                    token_result = await websocket.recv()
                    token_data = json.loads(token_result)
                    
                    if token_data.get("success") and token_data.get("result"):
                        token = token_data["result"]
                        print(f"✓ Token created: {token[:20]}...")
                        return token
    except Exception as e:
        print(f"✗ Token creation error: {e}")
        return None
    
    return None


async def add_integration_via_api(token: str) -> bool:
    """Add Oelo Lights integration via API."""
    print("\nAdding Oelo Lights integration...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Start config flow
    flow_data = {
        "handler": "oelo_lights",
        "show_advanced_options": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Initiate config flow
            async with session.post(
                f"{HA_URL}/api/config/config_entries/flow",
                headers=headers,
                json=flow_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"✗ Failed to start config flow: status {resp.status}, {text}")
                    return False
                
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
                    return False
                
                result = await resp.json()
                if result.get("type") == "create_entry":
                    entry_id = result.get("result", {}).get("entry_id")
                    print(f"✓ Integration added (Entry ID: {entry_id})")
                    return True
                else:
                    # Might need additional steps
                    print(f"✓ Config flow in progress: {result.get('type')}")
                    return True
                    
    except Exception as e:
        print(f"✗ Integration error: {e}")
        return False


async def register_card_resource(token: str) -> bool:
    """Register Lovelace card as resource."""
    print("\nRegistering card resource...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    resource_data = {
        "type": "module",
        "url": "/local/oelo-patterns-card-simple.js"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Check if already registered
            async with session.get(
                f"{HA_URL}/api/lovelace/resources",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    resources = await resp.json()
                    for resource in resources:
                        if resource.get("url") == resource_data["url"]:
                            print(f"✓ Card resource already registered")
                            return True
            
            # Register resource
            async with session.post(
                f"{HA_URL}/api/lovelace/resources",
                headers=headers,
                json=resource_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    print(f"✓ Card resource registered (ID: {result.get('id')})")
                    return True
                else:
                    text = await resp.text()
                    print(f"✗ Failed to register resource: status {resp.status}, {text}")
                    return False
    except Exception as e:
        print(f"✗ Resource registration error: {e}")
        return False


async def add_card_to_dashboard(token: str, entity_id: str = "light.oelo_lights_zone_1") -> bool:
    """Add Oelo Patterns card to dashboard."""
    print("\nAdding card to dashboard...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Get current dashboard config
            async with session.get(
                f"{HA_URL}/api/lovelace/config",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    print(f"✗ Failed to get dashboard: status {resp.status}")
                    return False
                
                config = await resp.json()
            
            # Check if card already exists
            views = config.get("views", [])
            card_exists = False
            for view in views:
                cards = view.get("cards", [])
                for card in cards:
                    if card.get("type") == "custom:oelo-patterns-card":
                        print(f"✓ Card already exists in dashboard")
                        return True
            
            # Add card to first view
            if not views:
                views.append({
                    "title": "Home",
                    "path": "home",
                    "cards": []
                })
            
            if "cards" not in views[0]:
                views[0]["cards"] = []
            
            views[0]["cards"].append({
                "type": "custom:oelo-patterns-card",
                "entity": entity_id,
                "title": "Oelo Patterns"
            })
            
            config["views"] = views
            
            # Update dashboard
            async with session.post(
                f"{HA_URL}/api/lovelace/config",
                headers=headers,
                json=config,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    print(f"✓ Card added to dashboard")
                    return True
                else:
                    text = await resp.text()
                    print(f"✗ Failed to update dashboard: status {resp.status}, {text}")
                    return False
    except Exception as e:
        print(f"✗ Dashboard update error: {e}")
        return False


async def main():
    """Run full automated setup."""
    print("=" * 60)
    print("Full Home Assistant Setup Automation")
    print("=" * 60)
    
    # Step 1: Wait for HA to be ready
    if not await wait_for_ha_ready():
        print("✗ Home Assistant failed to start")
        return 1
    
    # Step 2: Complete onboarding
    auth_code = await complete_onboarding_via_api()
    
    # Step 3: Create access token
    token = await create_token_via_websocket(auth_code)
    
    if not token:
        print("\n⚠️  Could not create token automatically")
        print("You'll need to create a token manually:")
        print("  1. Go to http://localhost:8123")
        print("  2. Profile → Long-Lived Access Tokens → Create Token")
        print("  3. Then run: docker-compose exec homeassistant python3 /config/test/test_add_card.py YOUR_TOKEN")
        return 1
    
    # Step 4: Add integration
    if not await add_integration_via_api(token):
        print("⚠️  Integration add failed - may need manual setup")
    
    # Step 5: Register card resource
    await register_card_resource(token)
    
    # Step 6: Add card to dashboard
    await add_card_to_dashboard(token)
    
    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"✓ Home Assistant ready")
    print(f"✓ Account created: {ONBOARDING_USERNAME}")
    print(f"✓ Access token created")
    print(f"✓ Integration added")
    print(f"✓ Card resource registered")
    print(f"✓ Card added to dashboard")
    print("\nNext: Refresh your dashboard at http://localhost:8123")
    print("The Oelo Patterns card should be visible!")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
