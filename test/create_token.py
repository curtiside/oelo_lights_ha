#!/usr/bin/env python3
"""Create Home Assistant long-lived access token via WebSocket API.

This script creates a token by:
1. Connecting via WebSocket
2. Authenticating (if needed)
3. Creating a long-lived access token
"""

import asyncio
import json
import websockets
import sys

HA_URL = "localhost:8123"
WS_URL = f"ws://{HA_URL}/api/websocket"


async def create_token_via_websocket() -> str | None:
    """Create a long-lived access token via WebSocket API."""
    try:
        async with websockets.connect(WS_URL) as websocket:
            # Receive auth_required message
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            print(f"Received: {auth_data.get('type')}")
            
            if auth_data.get("type") == "auth_required":
                # For fresh installs, we might need to complete onboarding first
                # Try to create token without auth (won't work but shows the flow)
                print("Authentication required - need to complete onboarding/login first")
                return None
            
            # If we had a token, we could authenticate and create a new one:
            # await websocket.send(json.dumps({
            #     "type": "auth",
            #     "access_token": existing_token
            # }))
            # 
            # Then create long-lived token:
            # await websocket.send(json.dumps({
            #     "id": 1,
            #     "type": "auth/long_lived_access_token",
            #     "client_name": "Oelo Lights Test",
            #     "lifespan": 3650
            # }))
            
    except Exception as e:
        print(f"Error: {e}")
        return None
    
    return None


if __name__ == "__main__":
    print("Note: Token creation requires authentication.")
    print("For a fresh install, complete onboarding/login first via browser.")
    print("Then create token manually or use browser automation.")
    token = asyncio.run(create_token_via_websocket())
    if token:
        print(f"Token created: {token}")
    else:
        print("Could not create token automatically - use browser to create one")
