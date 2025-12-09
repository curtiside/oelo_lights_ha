#!/bin/bash
# Install ChromeDriver and Chromium in Home Assistant container

set -e

echo "Installing ChromeDriver and Chromium..."

# Install dependencies
apt-get update
apt-get install -y \
    wget \
    gnupg \
    unzip \
    chromium \
    chromium-driver \
    || apk add --no-cache \
    chromium \
    chromium-chromedriver \
    || echo "Warning: Could not install via apt/apk"

# Alternative: Install ChromeDriver manually if package manager fails
if ! command -v chromedriver &> /dev/null; then
    echo "Installing ChromeDriver manually..."
    CHROMEDRIVER_VERSION=$(curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE_$(curl -sS https://chromedriver.storage.googleapis.com/LATEST_RELEASE | cut -d. -f1-2) || echo "114.0.5735.90")
    wget -q -O /tmp/chromedriver.zip "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip" || \
    wget -q -O /tmp/chromedriver.zip "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_$(curl -sS https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE 2>/dev/null | cut -d. -f1 || echo '114')/chromedriver-linux64.zip" || \
    echo "Warning: Could not download ChromeDriver"
    
    if [ -f /tmp/chromedriver.zip ]; then
        unzip -q /tmp/chromedriver.zip -d /tmp/
        mv /tmp/chromedriver* /usr/local/bin/chromedriver || mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver
        chmod +x /usr/local/bin/chromedriver
        rm -f /tmp/chromedriver.zip
    fi
fi

# Verify installation
if command -v chromedriver &> /dev/null || command -v chromium-driver &> /dev/null; then
    echo "✓ ChromeDriver installed"
else
    echo "✗ ChromeDriver installation failed"
    exit 1
fi

if command -v chromium &> /dev/null || command -v chromium-browser &> /dev/null; then
    echo "✓ Chromium installed"
else
    echo "✗ Chromium installation failed"
    exit 1
fi

echo "Installation complete!"
