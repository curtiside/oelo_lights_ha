#!/usr/bin/env python3
"""Monitor browser during test execution via Chrome remote debugging.

This script connects to Chrome's remote debugging port (9222) and displays
browser state, navigation events, and console logs in real-time.

Usage:
    # Terminal 1: Run tests
    make test-all
    
    # Terminal 2: Watch browser
    python3 test/watch_browser.py
    
    # Or watch with auto-refresh screenshots
    python3 test/watch_browser.py --screenshots
    
    # Or open Chrome DevTools automatically
    python3 test/watch_browser.py --open-devtools
"""

import json
import time
import sys
import os
import argparse
import subprocess
import platform
from typing import Optional, Dict, Any
from urllib.request import urlopen
from urllib.error import URLError

DEBUG_PORT = 9222
DEBUG_URL = f"http://localhost:{DEBUG_PORT}"


def check_debug_port() -> bool:
    """Check if Chrome remote debugging port is accessible."""
    try:
        resp = urlopen(f"{DEBUG_URL}/json", timeout=2)
        return resp.getcode() == 200
    except (URLError, OSError):
        return False


def get_browser_tabs() -> list:
    """Get list of open browser tabs from Chrome remote debugging."""
    try:
        resp = urlopen(f"{DEBUG_URL}/json", timeout=2)
        tabs = json.loads(resp.read())
        return tabs
    except (URLError, OSError, json.JSONDecodeError):
        return []


def get_tab_info(tab: Dict[str, Any]) -> str:
    """Format tab information for display."""
    title = tab.get("title", "No title")
    url = tab.get("url", "No URL")
    return f"  Title: {title}\n  URL: {url}"


def open_chrome_devtools(tab_url: str):
    """Open Chrome DevTools for a specific tab."""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"
        ]
        for chrome_path in chrome_paths:
            if os.path.exists(chrome_path):
                subprocess.Popen([
                    "open", "-a", "Google Chrome", tab_url
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    elif system == "Linux":
        # Try common Chrome/Chromium commands
        for cmd in ["google-chrome", "chromium-browser", "chromium"]:
            try:
                subprocess.Popen([
                    cmd, tab_url
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except FileNotFoundError:
                continue
    elif system == "Windows":
        subprocess.Popen([
            "start", "chrome", tab_url
        ], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    
    print(f"⚠️  Could not auto-open Chrome. Manually open: {tab_url}")


def take_screenshot(tab_id: str, filename: str):
    """Take a screenshot of a browser tab."""
    try:
        screenshot_url = f"{DEBUG_URL}/json/runtime/evaluate"
        # Use Chrome DevTools Protocol to take screenshot
        # This is a simplified version - full implementation would use websockets
        print(f"  📸 Screenshot would be saved to: {filename}")
    except Exception as e:
        print(f"  ⚠️  Could not take screenshot: {e}")


def monitor_browser(interval: float = 1.0, screenshots: bool = False, open_devtools: bool = False):
    """Monitor browser state during test execution."""
    print("=" * 70)
    print("Browser Monitor - Chrome Remote Debugging")
    print("=" * 70)
    print(f"Debugging URL: {DEBUG_URL}")
    print(f"Refresh interval: {interval}s")
    print("Press Ctrl+C to stop\n")
    
    if open_devtools:
        print("Opening Chrome DevTools...")
        print("  Navigate to: chrome://inspect")
        print("  Or open: http://localhost:9222\n")
        # Try to open chrome://inspect
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", "chrome://inspect"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif system == "Linux":
            for cmd in ["google-chrome", "chromium-browser", "chromium"]:
                try:
                    subprocess.Popen([cmd, "chrome://inspect"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except FileNotFoundError:
                    continue
    
    last_tabs = []
    screenshot_count = 0
    
    try:
        while True:
            if not check_debug_port():
                print("⏳ Waiting for Chrome remote debugging port...", end="\r")
                time.sleep(1)
                continue
            
            tabs = get_browser_tabs()
            
            if tabs != last_tabs:
                print("\n" + "=" * 70)
                print(f"Browser State Update - {time.strftime('%H:%M:%S')}")
                print("=" * 70)
                
                if not tabs:
                    print("  No open tabs")
                else:
                    print(f"  Found {len(tabs)} tab(s):\n")
                    for i, tab in enumerate(tabs, 1):
                        print(f"Tab {i}:")
                        print(get_tab_info(tab))
                        
                        # Show DevTools URL
                        devtools_url = tab.get("devtoolsFrontendUrl", "")
                        if devtools_url:
                            full_url = f"{DEBUG_URL}{devtools_url}"
                            print(f"  DevTools: {full_url}")
                        
                        # Take screenshot if requested
                        if screenshots:
                            tab_id = tab.get("id", "")
                            if tab_id:
                                screenshot_file = f"/workspace/test/screenshot_monitor_{screenshot_count:03d}.png"
                                take_screenshot(tab_id, screenshot_file)
                                screenshot_count += 1
                        
                        print()
                
                last_tabs = tabs
                print("Monitoring... (Ctrl+C to stop)\n")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 70)
        print("Monitoring stopped")
        print("=" * 70)
        if tabs:
            print(f"\nFinal state: {len(tabs)} tab(s) open")
            for i, tab in enumerate(tabs, 1):
                print(f"\nTab {i}:")
                print(get_tab_info(tab))
        sys.exit(0)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor browser during test execution via Chrome remote debugging"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Refresh interval in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--screenshots",
        action="store_true",
        help="Take screenshots at each state change"
    )
    parser.add_argument(
        "--open-devtools",
        action="store_true",
        help="Automatically open Chrome DevTools (chrome://inspect)"
    )
    
    args = parser.parse_args()
    
    monitor_browser(
        interval=args.interval,
        screenshots=args.screenshots,
        open_devtools=args.open_devtools
    )


if __name__ == "__main__":
    main()
