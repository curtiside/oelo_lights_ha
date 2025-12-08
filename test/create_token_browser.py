#!/usr/bin/env python3
"""Create Home Assistant token using browser automation via MCP browser tools.

This script uses the browser to:
1. Navigate to Home Assistant
2. Log in (if needed)
3. Go to Profile → Long-Lived Access Tokens
4. Create a token
5. Extract and return it

Note: This requires the MCP browser extension to be available.
"""

import json
import sys

# This would need to be called via the MCP browser tools
# For now, providing instructions for manual creation

print("=" * 60)
print("Home Assistant Token Creation")
print("=" * 60)
print("")
print("Since you've already added the integration, you're logged in.")
print("To create a token:")
print("")
print("1. In your browser, go to: http://localhost:8123")
print("2. Click your profile (bottom left)")
print("3. Scroll to 'Long-Lived Access Tokens'")
print("4. Click 'Create Token'")
print("5. Name it 'Test Token'")
print("6. Copy the token")
print("")
print("Then run:")
print("  docker-compose exec homeassistant python3 /config/test/test_add_card.py YOUR_TOKEN")
print("")
print("Or set as environment variable:")
print("  export HA_TOKEN=your_token")
print("  docker-compose exec homeassistant python3 /config/test/test_add_card.py")
