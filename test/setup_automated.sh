#!/bin/bash
# Automated setup script for fresh Home Assistant container
# This script guides through the setup process

set -e

echo "=========================================="
echo "Home Assistant Automated Setup"
echo "=========================================="
echo ""
echo "This script will help you set up:"
echo "  1. Complete onboarding (create account)"
echo "  2. Add Oelo Lights integration"
echo "  3. Create access token"
echo "  4. Register Lovelace card"
echo "  5. Add card to dashboard"
echo ""
echo "Starting Home Assistant container..."
echo ""

cd "$(dirname "$0")"

# Start container if not running
if ! docker-compose ps | grep -q "Up"; then
    echo "Starting container..."
    docker-compose up -d
    echo "Waiting for Home Assistant to start (30 seconds)..."
    sleep 30
fi

echo ""
echo "=========================================="
echo "STEP 1: Complete Onboarding"
echo "=========================================="
echo ""
echo "Open your browser to: http://localhost:8123"
echo ""
echo "You should see a 'Welcome home!' page."
echo "If you see a login page, onboarding is already complete - skip to Step 2."
echo ""
echo "On the onboarding page:"
echo "  1. Enter your name: Test User"
echo "  2. Enter username: admin"
echo "  3. Enter password: admin123456"
echo "  4. Complete the remaining onboarding steps"
echo ""
read -p "Press Enter when onboarding is complete..."

echo ""
echo "=========================================="
echo "STEP 2: Add Oelo Lights Integration"
echo "=========================================="
echo ""
echo "In Home Assistant:"
echo "  1. Go to: Settings → Devices & Services"
echo "  2. Click: 'Add Integration' (bottom right)"
echo "  3. Search for: 'Oelo Lights'"
echo "  4. Enter IP address: 10.16.52.41"
echo "  5. Complete the integration setup"
echo ""
read -p "Press Enter when integration is added..."

echo ""
echo "=========================================="
echo "STEP 3: Create Access Token"
echo "=========================================="
echo ""
echo "In Home Assistant:"
echo "  1. Click your profile (bottom left)"
echo "  2. Scroll to: 'Long-Lived Access Tokens'"
echo "  3. Click: 'Create Token'"
echo "  4. Name it: 'Test Token'"
echo "  5. Copy the token (you'll need it next)"
echo ""
read -p "Enter your access token: " HA_TOKEN

if [ -z "$HA_TOKEN" ]; then
    echo "ERROR: Token is required"
    exit 1
fi

echo ""
echo "=========================================="
echo "STEP 4: Register Card & Add to Dashboard"
echo "=========================================="
echo ""
echo "Running automated card setup..."
docker-compose exec -T homeassistant python3 /config/test/test_add_card.py "$HA_TOKEN"

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "✓ Onboarding complete"
echo "✓ Integration added"
echo "✓ Access token created"
echo "✓ Card registered and added to dashboard"
echo ""
echo "Refresh your dashboard at http://localhost:8123"
echo "The Oelo Patterns card should now be visible!"
echo ""
