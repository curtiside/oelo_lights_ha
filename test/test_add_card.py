#!/usr/bin/env python3
"""Test script to automatically add Oelo Patterns card to Home Assistant dashboard.

This script uses Home Assistant's REST API to:
1. Register the Lovelace card as a resource (if not already registered)
2. Add the card to the default dashboard

Prerequisites:
- Home Assistant running and accessible
- Integration already added
- Long-lived access token (create at Profile → Long-Lived Access Tokens)
"""

import asyncio
import aiohttp
import json
import sys
from typing import Any

HA_URL = "http://localhost:8123"
# Get token from: Profile → Long-Lived Access Tokens → Create Token
HA_TOKEN = ""  # Set your token here or pass as environment variable or command line arg
CONTROLLER_IP = "10.16.52.41"


async def get_ha_token() -> str:
    """Get HA token from command line, environment, or script variable."""
    import os
    # Check command line args first
    if len(sys.argv) > 1:
        return sys.argv[1]
    # Then environment variable
    token = os.environ.get("HA_TOKEN") or HA_TOKEN
    if not token:
        print("ERROR: HA_TOKEN not set")
        print("Usage: python3 test/test_add_card.py <your_token>")
        print("   OR: export HA_TOKEN=your_token_here && python3 test/test_add_card.py")
        print("\nGet token from: Home Assistant → Profile → Long-Lived Access Tokens → Create Token")
        sys.exit(1)
    return token


async def check_ha_connection(session: aiohttp.ClientSession, token: str) -> bool:
    """Check if Home Assistant is accessible."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(f"{HA_URL}/api/", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"✓ Connected to Home Assistant: {data.get('message', 'OK')}")
                return True
            else:
                print(f"✗ Connection failed: status {resp.status}")
                return False
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False


async def check_card_resource(session: aiohttp.ClientSession, token: str) -> bool:
    """Check if card resource is already registered."""
    headers = {"Authorization": f"Bearer {token}"}
    resource_url = "/local/oelo-patterns-card-simple.js"
    
    try:
        # Get Lovelace resources
        async with session.get(
            f"{HA_URL}/api/lovelace/resources",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                resources = await resp.json()
                for resource in resources:
                    if resource.get("url") == resource_url:
                        print(f"✓ Card resource already registered (ID: {resource.get('id')})")
                        return True
                print("✗ Card resource not registered")
                return False
            else:
                print(f"✗ Failed to get resources: status {resp.status}")
                return False
    except Exception as e:
        print(f"✗ Error checking resources: {e}")
        return False


async def register_card_resource(session: aiohttp.ClientSession, token: str) -> bool:
    """Register card as Lovelace resource."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    resource_data = {
        "type": "module",
        "url": "/local/oelo-patterns-card-simple.js"
    }
    
    try:
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
        print(f"✗ Error registering resource: {e}")
        return False


async def get_default_dashboard(session: aiohttp.ClientSession, token: str) -> dict[str, Any] | None:
    """Get the default dashboard configuration."""
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        async with session.get(
            f"{HA_URL}/api/lovelace/config",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                config = await resp.json()
                return config
            else:
                print(f"✗ Failed to get dashboard: status {resp.status}")
                return None
    except Exception as e:
        print(f"✗ Error getting dashboard: {e}")
        return None


async def add_card_to_dashboard(session: aiohttp.ClientSession, token: str, entity_id: str = "light.oelo_lights_zone_1") -> bool:
    """Add Oelo Patterns card to the default dashboard."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Get current dashboard config
    config = await get_default_dashboard(session, token)
    if not config:
        return False
    
    # Check if card already exists
    card_config = {
        "type": "custom:oelo-patterns-card",
        "entity": entity_id,
        "title": "Oelo Patterns"
    }
    
    # Look for existing card
    views = config.get("views", [])
    card_exists = False
    for view in views:
        cards = view.get("cards", [])
        for card in cards:
            if card.get("type") == "custom:oelo-patterns-card" and card.get("entity") == entity_id:
                print(f"✓ Card already exists in dashboard (view: {view.get('title', 'Unknown')})")
                card_exists = True
                break
        if card_exists:
            break
    
    if card_exists:
        return True
    
    # Add card to first view (or create view if none exists)
    if not views:
        # Create a new view
        views.append({
            "title": "Home",
            "path": "home",
            "cards": [card_config]
        })
    else:
        # Add to first view
        if "cards" not in views[0]:
            views[0]["cards"] = []
        views[0]["cards"].append(card_config)
    
    config["views"] = views
    
    # Update dashboard
    try:
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
        print(f"✗ Error updating dashboard: {e}")
        return False


async def verify_card_file(session: aiohttp.ClientSession, token: str) -> bool:
    """Verify card file is accessible."""
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        async with session.get(
            f"{HA_URL}/local/oelo-patterns-card-simple.js",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                content = await resp.text()
                if "oelo-patterns-card" in content:
                    print(f"✓ Card file accessible ({len(content)} bytes)")
                    return True
                else:
                    print("✗ Card file exists but content invalid")
                    return False
            else:
                print(f"✗ Card file not accessible: status {resp.status}")
                return False
    except Exception as e:
        print(f"✗ Error checking card file: {e}")
        return False


async def main():
    """Run card installation test."""
    print("=" * 60)
    print("Oelo Patterns Card Installation Test")
    print("=" * 60)
    
    token = await get_ha_token()
    
    async with aiohttp.ClientSession() as session:
        results = []
        
        # Test 1: Check HA connection
        print("\n1. Checking Home Assistant connection...")
        results.append(await check_ha_connection(session, token))
        
        # Test 2: Verify card file exists
        print("\n2. Verifying card file...")
        results.append(await verify_card_file(session, token))
        
        # Test 3: Check if resource registered
        print("\n3. Checking card resource registration...")
        resource_exists = await check_card_resource(session, token)
        
        # Test 4: Register resource if needed
        if not resource_exists:
            print("\n4. Registering card resource...")
            results.append(await register_card_resource(session, token))
        else:
            print("\n4. Resource already registered, skipping...")
            results.append(True)
        
        # Test 5: Add card to dashboard
        print("\n5. Adding card to dashboard...")
        results.append(await add_card_to_dashboard(session, token))
        
        # Summary
        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        passed = sum(results)
        total = len(results)
        print(f"Passed: {passed}/{total}")
        
        if passed == total:
            print("✓ Card installation complete!")
            print("\nNext steps:")
            print("1. Refresh your Home Assistant dashboard")
            print("2. The Oelo Patterns card should appear")
            print("3. Set a pattern on your Oelo controller")
            print("4. Click 'Capture Pattern' in the card")
            return 0
        else:
            print("✗ Some steps failed")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
