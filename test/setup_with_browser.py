#!/usr/bin/env python3
"""Full setup using browser automation - more reliable than API-only approach.

This script provides step-by-step instructions and can be extended with
browser automation tools to fully automate:
1. Onboarding (create account)
2. Add integration
3. Create token
4. Add card to dashboard
"""

print("=" * 60)
print("Home Assistant Full Setup Guide")
print("=" * 60)
print("")
print("This script will guide you through browser automation.")
print("For now, follow these steps manually or use browser automation:")
print("")
print("STEP 1: Complete Onboarding")
print("  - Go to http://localhost:8123")
print("  - Fill in: Name, Username, Password")
print("  - Complete onboarding steps")
print("")
print("STEP 2: Add Integration")
print("  - Settings → Devices & Services → Add Integration")
print("  - Search 'Oelo Lights'")
print("  - Enter IP: 10.16.52.41")
print("")
print("STEP 3: Create Token")
print("  - Profile (bottom left) → Long-Lived Access Tokens")
print("  - Create Token → Name: 'Test Token'")
print("  - Copy the token")
print("")
print("STEP 4: Run Card Installation")
print("  docker-compose exec homeassistant python3 /config/test/test_add_card.py YOUR_TOKEN")
print("")
print("The card will be automatically added to your dashboard!")
