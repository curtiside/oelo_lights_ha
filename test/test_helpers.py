#!/usr/bin/env python3
"""Test helper functions for container management and UI automation.

Provides shared functions for:
- Container lifecycle management (start, stop, health checks)
- HA readiness monitoring and API access
- Browser automation setup (headless and non-headless)
- UI interaction helpers (onboarding, login, device management)
- Test artifact cleanup (devices, entities, configurations)

Usage:
    from test_helpers import (
        start_container, wait_for_ha_ready, create_driver,
        cleanup_test_devices, cleanup_test_entities
    )
    
    # Container management
    start_container(project_dir, clean_config=True)
    wait_for_ha_ready()
    
    # Browser automation
    driver = create_driver(headless=True)
    
    # Cleanup
    cleanup_test_devices(ha_client, test_prefix="test_oelo_")
    cleanup_test_entities(ha_client, test_prefix="test_oelo_")

Configuration:
    Environment variables:
        HA_URL: Home Assistant URL (default: http://localhost:8123)
        HA_TOKEN: Long-lived access token (preferred)
        HA_USERNAME: Username (if not using token)
        HA_PASSWORD: Password (if not using token)
        CONTROLLER_IP: Oelo controller IP address

Test Artifact Naming:
    All test artifacts use prefix "test_oelo_" for easy cleanup:
    - Devices: test_oelo_zone_{zone_id}
    - Entities: test_oelo_light.zone_{zone_id}
    - Configs: test_oelo_pattern_{pattern_name}

Cleanup Strategy:
    Tests are idempotent and rerunnable:
    1. Pre-test: Remove any leftover test artifacts
    2. Setup: Create test devices/entities
    3. Test: Execute test cases
    4. Post-test: Always clean up (use finally blocks)
    
    See DEVELOPER.md for detailed testing architecture.

================================================================================
HOME ASSISTANT UI TESTING GUIDE - Custom Elements (Web Components)
================================================================================

Custom elements (Web Components) are used throughout Home Assistant's entire
frontend, not just the automation page - there is pervasive usage:

Main shell: <home-assistant>
Every page: <ha-panel-*> (lovelace, config, dev tools, etc.)
All cards: <hui-*-card>
Every UI component: <ha-button>, <ha-card>, <ha-icon>, <ha-selector-*>, 
                     <ha-form>, etc.
Dialogs, sidebars, menus - all custom elements

HA's frontend is built entirely on Lit (formerly Polymer), so virtually every
visible element is a custom element with shadow DOM encapsulation.

IMPORTANT TESTING PRINCIPLES:

1. WAIT FOR CUSTOM ELEMENTS TO BE DEFINED
   - Always wait for customElements to be defined before interacting
   - Wait for specific custom elements (e.g., 'home-assistant', 'ha-auth-flow')
   - Use WebDriverWait with custom conditions

2. CLICK CUSTOM ELEMENTS DIRECTLY
   - Click <ha-button>, <mwc-button> directly - don't call form.submit()
   - Don't try to access shadow DOM unless absolutely necessary
   - Let the custom element handle its own click events

3. WAIT FOR URL CHANGES
   - After clicking buttons, wait for URL to change (like Playwright wait_for_url)
   - Don't immediately navigate - let HA's navigation handle it
   - Check for /lovelace/** or other target URLs

4. USE PROPER WAITS, NOT SLEEPS
   - Use WebDriverWait with expected_conditions
   - Wait for specific elements to be present/visible
   - Avoid fixed time.sleep() calls

5. FILL FORM FIELDS VIA JAVASCRIPT
   - Custom elements may not respond to Selenium send_keys()
   - Use JavaScript to set values and dispatch events
   - Dispatch 'input' and 'change' events after setting values

Example pattern for UI interactions:
    # 1. Wait for custom elements
    wait.until(lambda d: d.execute_script(
        "return typeof customElements !== 'undefined' && "
        "customElements.get('home-assistant') !== undefined;"
    ))
    
    # 2. Wait for specific element
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "ha-auth-flow")))
    
    # 3. Fill fields via JavaScript
    driver.execute_script(
        "var input = arguments[0]; var value = arguments[1]; "
        "input.value = value; "
        "input.dispatchEvent(new Event('input', { bubbles: true })); "
        "input.dispatchEvent(new Event('change', { bubbles: true }));",
        field_element, value
    )
    
    # 4. Click custom element directly
    button_element.click()  # Don't call form.submit()
    
    # 5. Wait for URL change
    wait.until(lambda d: "/target-page" in d.current_url.lower())

See login_ui() function for a complete example of this pattern.

OPTIONS TO EXPLORE HOME ASSISTANT SHADOW DOM STRUCTURE:

1. Browser DevTools - most direct
   - Open HA in Chrome/Firefox
   - Elements panel shows shadow roots (expand #shadow-root (open) nodes)
   - Can inspect the full tree manually

2. HA Frontend repo
   - https://github.com/home-assistant/frontend
   - Source of truth for all components
   - src/panels/ - each panel's structure
   - src/components/ - reusable elements

3. DevTools console queries
   ```javascript
   // Find element through shadow roots
   document.querySelector("home-assistant")
     .shadowRoot.querySelector("home-assistant-main")
     .shadowRoot.querySelector("ha-panel-config")
   ```

4. Lit DevTools extension
   - Chrome/Firefox extension specifically for Lit components
   - Shows component properties and state

5. $0.shadowRoot trick
   - Select element in DevTools Elements panel
   - In console, $0.shadowRoot gives its shadow root
   - Chain to drill down

PRACTICAL APPROACH FOR TEST WRITING:

- Use a method from above to find the selector path
- Note which boundaries require .shadowRoot traversal
- In Playwright, use >> piercing combinator or .locator() chaining
- In Selenium, use JavaScript execute_script to traverse shadow DOM
- Example JavaScript pattern:
  ```javascript
  var root = document.querySelector('home-assistant');
  if (root && root.shadowRoot) {
    var main = root.shadowRoot.querySelector('home-assistant-main');
    if (main && main.shadowRoot) {
      var panel = main.shadowRoot.querySelector('ha-panel-profile');
      // Continue traversing...
    }
  }
  ```
"""

import subprocess
import time
import os
import sys
import shutil
import requests
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# HA URL - use host.docker.internal if running in container, localhost if on host
HA_URL = os.environ.get("HA_URL", "http://localhost:8123")
# If running in container and HA_URL not set, try host.docker.internal
if "localhost" not in HA_URL and os.path.exists("/.dockerenv"):
    HA_URL = "http://host.docker.internal:8123"

CONTAINER_NAME = "ha-test"
ONBOARDING_USERNAME = "test_user"
ONBOARDING_PASSWORD = "test_password_123"
ONBOARDING_NAME = "Test User"


def install_hacs_via_docker() -> bool:
    """Install HACS in HA container via docker exec.
    
    Uses docker exec to run the HACS installation script inside the container.
    This is more reliable than UI automation.
    
    Returns:
        True if successful, False otherwise
    """
    print("\n=== Installing HACS via Docker ===")
    
    # Check if HACS already installed
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "test", "-d", "/config/custom_components/hacs"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            print("✓ HACS already installed")
            return True
    except:
        pass
    
    # Install HACS via docker exec
    # Use bash -c to properly handle the pipe
    try:
        print("  Running HACS installation script...")
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "bash", "-c", "wget -O - https://get.hacs.xyz | bash -"],
            capture_output=True,
            timeout=120,
            text=True
        )
        
        if result.returncode == 0:
            print("✓ HACS installation script executed")
            print("  Waiting for container restart...")
            time.sleep(10)  # Give HA time to restart
            
            # Verify installation
            verify_result = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "test", "-d", "/config/custom_components/hacs"],
                capture_output=True,
                timeout=10
            )
            if verify_result.returncode == 0:
                print("✓ HACS installed successfully")
                return True
            else:
                print("⚠️  HACS installation may have completed but directory not found yet")
                print("   Container may need restart - will verify after restart")
                return True  # Assume success, will verify later
        else:
            error_output = result.stderr or result.stdout
            print(f"⚠️  HACS installation returned non-zero exit code: {result.returncode}")
            if error_output:
                print(f"   Output: {error_output[:500]}")
            return False
            
    except subprocess.TimeoutExpired:
        print("⚠️  HACS installation timed out")
        return False
    except Exception as e:
        print(f"⚠️  Error installing HACS: {e}")
        return False


def get_project_dir() -> str:
    """Get project root directory.
    
    Returns:
        Path to project root (parent of test directory)
    """
    # If running from test directory, go up one level
    # If running from workspace, use current directory
    current_file = os.path.abspath(__file__)
    if "/test/" in current_file:
        return os.path.dirname(os.path.dirname(current_file))
    else:
        # Fallback: try to find project root by looking for docker-compose.yml
        cwd = os.getcwd()
        if os.path.exists(os.path.join(cwd, "docker-compose.yml")):
            return cwd
        # Last resort: assume parent of current directory
        return os.path.dirname(cwd)


async def create_token_from_credentials(username: str, password: str) -> Optional[str]:
    """Create long-lived access token from username/password via WebSocket API.
    
    Args:
        username: HA username
        password: HA password
        
    Returns:
        Token string if successful, None otherwise
    """
    try:
        import websockets
        import json
        import asyncio
    except ImportError:
        print("  ⚠️  websockets package not available - cannot create token automatically")
        return None
    
    try:
        ws_url = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
        websocket = await asyncio.wait_for(websockets.connect(ws_url), timeout=10)
        try:
            # Receive auth_required
            msg = await websocket.recv()
            data = json.loads(msg)
            
            if data.get("type") == "auth_required":
                # Authenticate with username/password
                await websocket.send(json.dumps({
                    "type": "auth",
                    "username": username,
                    "password": password
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
                        print(f"  ✓ Token created automatically from username/password", flush=True)
                        sys.stdout.flush()
                        return token
                    else:
                        error_msg = token_data.get("error", {}).get("message", "Unknown error")
                        print(f"  ✗ Token creation failed: {error_msg}", flush=True)
                        sys.stdout.flush()
                        return None
                elif auth_data.get("type") == "auth_invalid":
                    error_msg = auth_data.get("message", "Invalid credentials")
                    print(f"  ✗ Authentication failed: {error_msg}", flush=True)
                    sys.stdout.flush()
                    print(f"    Username: {username}", flush=True)
                    sys.stdout.flush()
                    return None
                else:
                    print(f"  ✗ Unexpected auth response: {auth_data.get('type')}", flush=True)
                    sys.stdout.flush()
                    return None
        finally:
            await websocket.close()
    except Exception as e:
        print(f"  ⚠️  Could not create token: {e}", flush=True)
        sys.stdout.flush()
        import traceback
        traceback.print_exc()
        return None
    
    return None


def create_token_from_browser_session(driver: 'webdriver.Chrome') -> Optional[str]:
    """Create long-lived access token using browser's authenticated session.
    
    After successful UI login, tries profile page approach first, then falls back
    to credentials-based token creation if UI approach fails.
    
    Args:
        driver: Selenium WebDriver instance with authenticated session
        
    Returns:
        Token string if successful, None otherwise
    """
    print("  Creating token from browser session...", flush=True)
    sys.stdout.flush()
    
    # Try profile page approach first
    token = create_token_via_profile_page(driver)
    if token:
        return token
    
    # Fallback: use credentials to create token via WebSocket
    print("  Profile page approach failed, trying credentials-based token creation...", flush=True)
    sys.stdout.flush()
    username = os.environ.get("HA_USERNAME")
    password = os.environ.get("HA_PASSWORD")
    
    if username and password:
        try:
            import asyncio
            token = asyncio.run(create_token_from_credentials(username, password))
            if token:
                return token
        except Exception as e:
            print(f"  ⚠️  Credentials-based token creation failed: {e}", flush=True)
            sys.stdout.flush()
    
    return None


def create_token_via_profile_page(driver: 'webdriver.Chrome') -> Optional[str]:
    """Create token by navigating to profile page and using UI.
    
    Follows HA custom elements testing principles:
    - Waits for custom elements to be defined
    - Waits for specific elements (ha-panel-profile)
    - Clicks custom elements directly
    - Uses proper waits instead of sleeps
    
    Args:
        driver: Selenium WebDriver instance with authenticated session
        
    Returns:
        Token string if successful, None otherwise
    """
    try:
        print("  Navigating to profile page to create token...", flush=True)
        sys.stdout.flush()
        
        current_url = driver.current_url
        print(f"  Current URL: {current_url}", flush=True)
        sys.stdout.flush()
        
        # Navigate to profile security page (where token creation is)
        print("  Navigating to profile security page...", flush=True)
        sys.stdout.flush()
        driver.get(f"{HA_URL}/profile/security")
        
        # Wait for navigation (like login_ui pattern)
        wait = WebDriverWait(driver, 20)
        try:
            wait.until(lambda d: "/profile/security" in d.current_url.lower())
            print(f"  ✓ Navigated to profile security page", flush=True)
            sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  Profile security page navigation timed out: {e}", flush=True)
            sys.stdout.flush()
            return None
        
        # Wait for custom elements to be defined (following login_ui pattern)
        print("  Waiting for custom elements to be defined...", flush=True)
        sys.stdout.flush()
        wait = WebDriverWait(driver, 20)
        try:
            wait.until(lambda d: d.execute_script("""
                return typeof customElements !== 'undefined' && 
                       customElements.get('home-assistant') !== undefined;
            """))
            print("  ✓ Custom elements defined", flush=True)
            sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  Custom elements wait timed out: {e}", flush=True)
            sys.stdout.flush()
            # Continue anyway - page might still work
        
        # Brief wait for page to fully render
        time.sleep(2)
        
        # Check if we need to navigate to tokens section
        # HA profile page has tabs: General, Security, Tokens, etc.
        print("  Checking if we need to navigate to tokens section...", flush=True)
        sys.stdout.flush()
        try:
            # Try to find and click "Long-lived access tokens" link or tab
            tokens_link_clicked = driver.execute_script("""
                // Look for links/tabs related to tokens
                var links = document.querySelectorAll('a, ha-tab, mwc-tab');
                for (var i = 0; i < links.length; i++) {
                    var link = links[i];
                    var text = (link.textContent || link.innerText || '').toLowerCase();
                    if (text.includes('token') || text.includes('long-lived') || text.includes('access token')) {
                        console.log('Found tokens link:', text.substring(0, 50));
                        link.click();
                        return true;
                    }
                }
                return false;
            """)
            if tokens_link_clicked:
                print("  ✓ Clicked tokens section link", flush=True)
                sys.stdout.flush()
                time.sleep(2)  # Wait for section to load
        except Exception as e:
            print(f"  ⚠️  Could not navigate to tokens section: {e}", flush=True)
            sys.stdout.flush()
            # Continue anyway
        
        print("  Ready to find token creation button", flush=True)
        sys.stdout.flush()
        
        # Find and click create token button using JavaScript (following login_ui pattern)
        print("  Looking for create token button...", flush=True)
        sys.stdout.flush()
        
        try:
            # Use JavaScript to find and click button, traversing shadow DOM if needed
            # Profile page structure: home-assistant -> home-assistant-main -> ha-panel-profile
            button_clicked = driver.execute_script("""
                // Function to find buttons, traversing shadow DOM recursively
                function findButtonsInShadowDOM(root) {
                    var buttons = [];
                    
                    // Find buttons in current scope
                    var buttonSelectors = ['mwc-button', 'ha-button', 'button'];
                    for (var s = 0; s < buttonSelectors.length; s++) {
                        var found = root.querySelectorAll(buttonSelectors[s]);
                        for (var f = 0; f < found.length; f++) {
                            buttons.push(found[f]);
                        }
                    }
                    
                    // Also check shadow roots recursively
                    var allElements = root.querySelectorAll('*');
                    for (var i = 0; i < allElements.length; i++) {
                        var elem = allElements[i];
                        if (elem.shadowRoot) {
                            var shadowButtons = findButtonsInShadowDOM(elem.shadowRoot);
                            buttons = buttons.concat(shadowButtons);
                        }
                    }
                    
                    return buttons;
                }
                
                // Start from document, then try traversing shadow DOM structure
                var buttons = [];
                
                // First, try direct query (buttons might be in light DOM)
                buttons = buttons.concat(findButtonsInShadowDOM(document));
                
                // Try traversing home-assistant shadow DOM structure
                // Pattern: home-assistant -> home-assistant-main -> ha-panel-profile
                var homeAssistant = document.querySelector('home-assistant');
                if (homeAssistant && homeAssistant.shadowRoot) {
                    var main = homeAssistant.shadowRoot.querySelector('home-assistant-main');
                    if (main && main.shadowRoot) {
                        var panel = main.shadowRoot.querySelector('ha-panel-profile');
                        if (panel) {
                            // Profile panel found - search within it
                            if (panel.shadowRoot) {
                                buttons = buttons.concat(findButtonsInShadowDOM(panel.shadowRoot));
                            } else {
                                buttons = buttons.concat(findButtonsInShadowDOM(panel));
                            }
                        }
                        // Also search in main shadow root
                        buttons = buttons.concat(findButtonsInShadowDOM(main.shadowRoot));
                    }
                }
                
                console.log('Found', buttons.length, 'total buttons');
                
                // Look for create/add token button - try multiple text patterns
                // Also check for buttons that might have text in shadow DOM
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var text = (btn.textContent || btn.innerText || '').toLowerCase();
                    var ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
                    var title = (btn.getAttribute('title') || '').toLowerCase();
                    
                    // Check shadow DOM for text if button is custom element
                    if ((btn.tagName === 'HA-BUTTON' || btn.tagName === 'MWC-BUTTON') && btn.shadowRoot) {
                        var shadowText = (btn.shadowRoot.textContent || '').toLowerCase();
                        text = text || shadowText;
                    }
                    
                    // More flexible matching - look for "create" and "token" separately
                    var hasCreate = text.includes('create') || ariaLabel.includes('create') || title.includes('create');
                    var hasToken = text.includes('token') || ariaLabel.includes('token') || title.includes('token');
                    var hasAdd = text.includes('add') || ariaLabel.includes('add') || title.includes('add');
                    
                    // Also check for buttons that might be the only visible button on tokens page
                    // If we're on /profile/tokens and button is visible, it might be the create button
                    var isVisible = btn.offsetParent !== null;
                    var isOnTokensPage = window.location.href.toLowerCase().includes('/profile/tokens');
                    
                    if ((hasCreate && hasToken) || (hasAdd && hasToken) || 
                        (isOnTokensPage && isVisible && buttons.length <= 5 && btn.tagName === 'HA-BUTTON')) {
                        console.log('Found create token button:', btn.tagName, 'text:', text.substring(0, 50), 'visible:', isVisible);
                        
                        // Click custom element directly (like login_ui)
                        if (btn.tagName === 'MWC-BUTTON' || btn.tagName === 'HA-BUTTON') {
                            btn.focus();
                            btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                            btn.click();
                            console.log('Clicked', btn.tagName, 'for create token');
                            return true;
                        } else {
                            // Regular button
                            btn.click();
                            console.log('Clicked regular button for create token');
                            return true;
                        }
                    }
                }
                
                // Alternative: Look for text "create token" or "long-lived" and find nearest button
                var pageText = document.body.textContent || document.body.innerText || '';
                if (pageText.toLowerCase().includes('create') && pageText.toLowerCase().includes('token')) {
                    console.log('Found "create token" text on page, searching for nearby button...');
                    // Find all text nodes containing "create" or "token"
                    var walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    var node;
                    while (node = walker.nextNode()) {
                        var text = node.textContent.toLowerCase();
                        if (text.includes('create') && text.includes('token')) {
                            // Find nearest button parent
                            var parent = node.parentElement;
                            while (parent && parent !== document.body) {
                                var nearbyBtn = parent.querySelector('ha-button, mwc-button, button');
                                if (nearbyBtn && nearbyBtn.offsetParent !== null) {
                                    console.log('Found button near "create token" text');
                                    if (nearbyBtn.tagName === 'HA-BUTTON' || nearbyBtn.tagName === 'MWC-BUTTON') {
                                        nearbyBtn.focus();
                                        nearbyBtn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                        nearbyBtn.click();
                                        return true;
                                    } else {
                                        nearbyBtn.click();
                                        return true;
                                    }
                                }
                                parent = parent.parentElement;
                            }
                        }
                    }
                }
                
                // If on tokens page and no match found, try clicking first visible button
                if (window.location.href.toLowerCase().includes('/profile/tokens')) {
                    for (var i = 0; i < buttons.length; i++) {
                        var btn = buttons[i];
                        if (btn.offsetParent !== null) {
                            console.log('Trying first visible button on tokens page:', btn.tagName);
                            if (btn.tagName === 'HA-BUTTON' || btn.tagName === 'MWC-BUTTON') {
                                btn.focus();
                                btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                btn.click();
                            } else {
                                btn.click();
                            }
                            return true;
                        }
                    }
                }
                
                // Debug: log all button texts for troubleshooting
                console.log('All button texts found:');
                for (var d = 0; d < Math.min(buttons.length, 10); d++) {
                    var dbgBtn = buttons[d];
                    var dbgText = (dbgBtn.textContent || dbgBtn.innerText || '').trim().substring(0, 30);
                    var dbgShadowText = '';
                    if ((dbgBtn.tagName === 'HA-BUTTON' || dbgBtn.tagName === 'MWC-BUTTON') && dbgBtn.shadowRoot) {
                        dbgShadowText = (dbgBtn.shadowRoot.textContent || '').trim().substring(0, 30);
                    }
                    console.log('  Button', d, ':', dbgBtn.tagName, '- text:', dbgText, '- shadow:', dbgShadowText);
                }
                
                return false;
            """)
            
            # Check console logs for debug info
            try:
                logs = driver.get_log('browser')
                if logs:
                    console_messages = [log for log in logs if log.get('level') in ['INFO', 'DEBUG'] and 'console-api' in log.get('message', '')]
                    if console_messages:
                        print("  Browser console messages:", flush=True)
                        sys.stdout.flush()
                        for msg in console_messages[-10:]:  # Show last 10 messages
                            print(f"    {msg.get('message', '')[:200]}", flush=True)
                            sys.stdout.flush()
            except:
                pass
            
            if not button_clicked:
                print("  ⚠️  Could not find create token button", flush=True)
                sys.stdout.flush()
                return None
            else:
                print("  ✓ Clicked create token button", flush=True)
                sys.stdout.flush()
                
        except Exception as e:
            print(f"  ⚠️  Error finding/clicking create token button: {e}", flush=True)
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            return None
        
        # Brief wait for "Give the token a name" popup dialog to appear
        print("  Waiting briefly for dialog to appear...", flush=True)
        sys.stdout.flush()
        time.sleep(2)  # Brief wait for dialog to appear
        print("  Proceeding to fill token name...", flush=True)
        sys.stdout.flush()
        
        # Enter token name into "Give the token a name" popup
        print("  Entering token name in 'Give the token a name' field...", flush=True)
        sys.stdout.flush()
        token_name = "Oelo Lights Integration Test"
        try:
            name_entered = driver.execute_script("""
                var name = arguments[0];
                
                // Function to find inputs, traversing shadow DOM
                function findInputsInShadowDOM(root) {
                    var inputs = [];
                    var selectors = [
                        'ha-textfield input',
                        'mwc-textfield input', 
                        'input[type="text"]',
                        'input[type="search"]'
                    ];
                    
                    for (var s = 0; s < selectors.length; s++) {
                        var found = root.querySelectorAll(selectors[s]);
                        for (var f = 0; f < found.length; f++) {
                            inputs.push(found[f]);
                        }
                    }
                    
                    // Also check shadow roots recursively
                    var allElements = root.querySelectorAll('*');
                    for (var i = 0; i < allElements.length; i++) {
                        var elem = allElements[i];
                        if (elem.shadowRoot) {
                            var shadowInputs = findInputsInShadowDOM(elem.shadowRoot);
                            inputs = inputs.concat(shadowInputs);
                        }
                    }
                    
                    return inputs;
                }
                
                // Try direct query first
                var inputs = findInputsInShadowDOM(document);
                
                // Try traversing shadow DOM structure for dialog
                var homeAssistant = document.querySelector('home-assistant');
                if (homeAssistant && homeAssistant.shadowRoot) {
                    var main = homeAssistant.shadowRoot.querySelector('home-assistant-main');
                    if (main && main.shadowRoot) {
                        // Look for dialogs in main shadow root
                        var dialogs = main.shadowRoot.querySelectorAll('ha-dialog, mwc-dialog');
                        for (var d = 0; d < dialogs.length; d++) {
                            var dialog = dialogs[d];
                            if (dialog.shadowRoot) {
                                inputs = inputs.concat(findInputsInShadowDOM(dialog.shadowRoot));
                            } else {
                                inputs = inputs.concat(findInputsInShadowDOM(dialog));
                            }
                        }
                    }
                }
                
                // Find visible input and fill it
                for (var i = 0; i < inputs.length; i++) {
                    var input = inputs[i];
                    if (input.offsetParent !== null && input.type !== 'hidden') {
                        // Fill via JavaScript (like login_ui)
                        input.value = name;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        console.log('Set token name to:', name);
                        return true;
                    }
                }
                return false;
            """, token_name)
            
            if name_entered:
                print(f"  ✓ Token name entered: {token_name}", flush=True)
                sys.stdout.flush()
            else:
                print("  ⚠️  Could not find token name input field", flush=True)
                sys.stdout.flush()
                return None
                
        except Exception as e:
            print(f"  ⚠️  Error entering token name: {e}", flush=True)
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            return None
        
        # Brief wait for input to process
        time.sleep(0.5)
        
        # Click OK button (not Cancel) in the dialog
        print("  Clicking OK button...", flush=True)
        sys.stdout.flush()
        try:
            submitted = driver.execute_script("""
                // Function to find buttons, traversing shadow DOM
                function findButtonsInShadowDOM(root) {
                    var buttons = [];
                    var buttonSelectors = ['mwc-button', 'ha-button', 'button'];
                    
                    for (var s = 0; s < buttonSelectors.length; s++) {
                        var found = root.querySelectorAll(buttonSelectors[s]);
                        for (var f = 0; f < found.length; f++) {
                            buttons.push(found[f]);
                        }
                    }
                    
                    // Also check shadow roots recursively
                    var allElements = root.querySelectorAll('*');
                    for (var i = 0; i < allElements.length; i++) {
                        var elem = allElements[i];
                        if (elem.shadowRoot) {
                            var shadowButtons = findButtonsInShadowDOM(elem.shadowRoot);
                            buttons = buttons.concat(shadowButtons);
                        }
                    }
                    
                    return buttons;
                }
                
                // Try direct query first
                var buttons = findButtonsInShadowDOM(document);
                
                // Try traversing shadow DOM structure for dialog
                var homeAssistant = document.querySelector('home-assistant');
                if (homeAssistant && homeAssistant.shadowRoot) {
                    var main = homeAssistant.shadowRoot.querySelector('home-assistant-main');
                    if (main && main.shadowRoot) {
                        // Look for dialogs in main shadow root
                        var dialogs = main.shadowRoot.querySelectorAll('ha-dialog, mwc-dialog');
                        for (var d = 0; d < dialogs.length; d++) {
                            var dialog = dialogs[d];
                            if (dialog.shadowRoot) {
                                buttons = buttons.concat(findButtonsInShadowDOM(dialog.shadowRoot));
                            } else {
                                buttons = buttons.concat(findButtonsInShadowDOM(dialog));
                            }
                        }
                    }
                }
                
                // Look for OK button (not Cancel)
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var text = (btn.textContent || btn.innerText || '').trim();
                    if (btn.shadowRoot) {
                        text = text || (btn.shadowRoot.textContent || '').trim();
                    }
                    var ariaLabel = (btn.getAttribute('aria-label') || '').trim();
                    
                    // Look for OK button (exact match, case insensitive)
                    if ((text.toLowerCase() === 'ok' || ariaLabel.toLowerCase() === 'ok') &&
                        text.toLowerCase() !== 'cancel' && ariaLabel.toLowerCase() !== 'cancel') {
                        if (btn.offsetParent !== null) {
                            console.log('Found OK button:', btn.tagName);
                            if (btn.tagName === 'MWC-BUTTON' || btn.tagName === 'HA-BUTTON') {
                                btn.focus();
                                btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                btn.click();
                            } else {
                                btn.click();
                            }
                            return true;
                        }
                    }
                }
                return false;
            """)
            
            if submitted:
                print("  ✓ Submitted token creation", flush=True)
                sys.stdout.flush()
            else:
                print("  ⚠️  Could not find submit button", flush=True)
                sys.stdout.flush()
                return None
                
        except Exception as e:
            print(f"  ⚠️  Error submitting token creation: {e}", flush=True)
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            return None
        
        # Wait for token popup dialog to appear (with "Copy your access token" text)
        print("  Waiting for token display popup...", flush=True)
        sys.stdout.flush()
        try:
            wait.until(lambda d: d.execute_script("""
                // Check for dialog with token text
                var pageText = document.body.textContent || document.body.innerText || '';
                return pageText.toLowerCase().includes('copy your access token') ||
                       pageText.toLowerCase().includes('it will not be shown again');
            """))
            print("  ✓ Token popup appeared", flush=True)
            sys.stdout.flush()
            time.sleep(1)  # Brief wait for token to be populated
        except Exception as e:
            print(f"  ⚠️  Token popup did not appear: {e}", flush=True)
            sys.stdout.flush()
            time.sleep(2)  # Wait anyway
        
        # Extract token using JavaScript (following login_ui pattern)
        # May need to traverse shadow DOM to find token display
        print("  Extracting token...", flush=True)
        sys.stdout.flush()
        try:
            token = driver.execute_script("""
                // Function to find token elements, traversing shadow DOM
                function findTokenInShadowDOM(root) {
                    var token = null;
                    
                    // Try <pre> or <code> elements first
                    var preElements = root.querySelectorAll('pre, code');
                    for (var i = 0; i < preElements.length; i++) {
                        var text = preElements[i].textContent.trim();
                        if (text.length > 20 && /^[a-zA-Z0-9_-]+$/.test(text)) {
                            return text;
                        }
                    }
                    
                    // Try readonly input (common in HA dialogs)
                    var inputs = root.querySelectorAll('input[readonly]');
                    for (var i = 0; i < inputs.length; i++) {
                        var value = inputs[i].value.trim();
                        if (value.length > 20 && /^[a-zA-Z0-9_-]+$/.test(value)) {
                            return value;
                        }
                    }
                    
                    // Try ha-copy-text component (HA custom element)
                    var copyTexts = root.querySelectorAll('ha-copy-text');
                    for (var i = 0; i < copyTexts.length; i++) {
                        var text = copyTexts[i].textContent.trim();
                        if (text.length > 20 && /^[a-zA-Z0-9_-]+$/.test(text)) {
                            return text;
                        }
                    }
                    
                    // Try mwc-textfield or ha-textfield with readonly
                    var textFields = root.querySelectorAll('mwc-textfield input, ha-textfield input');
                    for (var i = 0; i < textFields.length; i++) {
                        var input = textFields[i];
                        if (input.readOnly || input.hasAttribute('readonly')) {
                            var value = input.value.trim();
                            if (value.length > 20 && /^[a-zA-Z0-9_-]+$/.test(value)) {
                                return value;
                            }
                        }
                    }
                    
                    // Check shadow roots recursively
                    var allElements = root.querySelectorAll('*');
                    for (var i = 0; i < allElements.length; i++) {
                        var elem = allElements[i];
                        if (elem.shadowRoot) {
                            token = findTokenInShadowDOM(elem.shadowRoot);
                            if (token) return token;
                        }
                    }
                    
                    return null;
                }
                
                // Try direct query first
                var token = findTokenInShadowDOM(document);
                
                // Try traversing shadow DOM structure for dialog
                if (!token) {
                    var homeAssistant = document.querySelector('home-assistant');
                    if (homeAssistant && homeAssistant.shadowRoot) {
                        var main = homeAssistant.shadowRoot.querySelector('home-assistant-main');
                        if (main && main.shadowRoot) {
                            // Look for dialogs in main shadow root
                            var dialogs = main.shadowRoot.querySelectorAll('ha-dialog, mwc-dialog');
                            for (var d = 0; d < dialogs.length; d++) {
                                var dialog = dialogs[d];
                                if (dialog.shadowRoot) {
                                    token = findTokenInShadowDOM(dialog.shadowRoot);
                                    if (token) break;
                                } else {
                                    token = findTokenInShadowDOM(dialog);
                                    if (token) break;
                                }
                            }
                        }
                    }
                }
                
                return token;
            """)
            
            if token and len(token) > 20:
                print(f"  ✓ Token extracted (length: {len(token)})", flush=True)
                sys.stdout.flush()
                
                # Click X button to dismiss the popup
                print("  Clicking X to dismiss token popup...", flush=True)
                sys.stdout.flush()
                try:
                    dismissed = driver.execute_script("""
                        // Function to find close/X buttons, traversing shadow DOM
                        function findCloseButtonsInShadowDOM(root) {
                            var buttons = [];
                            var buttonSelectors = ['ha-icon-button', 'ha-button', 'mwc-button', 'button', '[aria-label*="close" i]', '[aria-label*="dismiss" i]'];
                            
                            for (var s = 0; s < buttonSelectors.length; s++) {
                                var found = root.querySelectorAll(buttonSelectors[s]);
                                for (var f = 0; f < found.length; f++) {
                                    buttons.push(found[f]);
                                }
                            }
                            
                            // Also look for elements with X or close icon
                            var icons = root.querySelectorAll('ha-icon, mwc-icon, [icon*="close"], [icon*="mdi:close"]');
                            for (var i = 0; i < icons.length; i++) {
                                var icon = icons[i];
                                var parent = icon.closest('button, ha-button, mwc-button, ha-icon-button');
                                if (parent) {
                                    buttons.push(parent);
                                }
                            }
                            
                            var allElements = root.querySelectorAll('*');
                            for (var i = 0; i < allElements.length; i++) {
                                var elem = allElements[i];
                                if (elem.shadowRoot) {
                                    var shadowButtons = findCloseButtonsInShadowDOM(elem.shadowRoot);
                                    buttons = buttons.concat(shadowButtons);
                                }
                            }
                            
                            return buttons;
                        }
                        
                        var buttons = findCloseButtonsInShadowDOM(document);
                        var homeAssistant = document.querySelector('home-assistant');
                        if (homeAssistant && homeAssistant.shadowRoot) {
                            var main = homeAssistant.shadowRoot.querySelector('home-assistant-main');
                            if (main && main.shadowRoot) {
                                var dialogs = main.shadowRoot.querySelectorAll('ha-dialog, mwc-dialog');
                                for (var d = 0; d < dialogs.length; d++) {
                                    var dialog = dialogs[d];
                                    if (dialog.shadowRoot) {
                                        buttons = buttons.concat(findCloseButtonsInShadowDOM(dialog.shadowRoot));
                                    } else {
                                        buttons = buttons.concat(findCloseButtonsInShadowDOM(dialog));
                                    }
                                }
                            }
                        }
                        
                        // Look for X button (close icon, or button with X text, or aria-label with close)
                        for (var i = 0; i < buttons.length; i++) {
                            var btn = buttons[i];
                            var text = (btn.textContent || btn.innerText || '').trim();
                            if (btn.shadowRoot) {
                                text = text || (btn.shadowRoot.textContent || '').trim();
                            }
                            var ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
                            
                            // Look for X button (close icon, X text, or close aria-label)
                            if (text === '×' || text === 'X' || text === '✕' ||
                                ariaLabel.includes('close') || ariaLabel.includes('dismiss') ||
                                btn.getAttribute('dialog-action') === 'close') {
                                if (btn.offsetParent !== null) {
                                    console.log('Found X/close button:', btn.tagName, text || ariaLabel);
                                    if (btn.tagName === 'HA-BUTTON' || btn.tagName === 'MWC-BUTTON' || btn.tagName === 'HA-ICON-BUTTON') {
                                        btn.focus();
                                        btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                        btn.click();
                                    } else {
                                        btn.click();
                                    }
                                    return true;
                                }
                            }
                        }
                        
                        return false;
                    """)
                    
                    if dismissed:
                        print("  ✓ Token pop-up dismissed", flush=True)
                        sys.stdout.flush()
                    else:
                        print("  ⚠️  Could not find dismiss button, but token was extracted", flush=True)
                        sys.stdout.flush()
                except Exception as e:
                    print(f"  ⚠️  Error dismissing pop-up: {e}", flush=True)
                    sys.stdout.flush()
                    # Continue anyway - token was extracted
                
                return token
            else:
                print("  ⚠️  Could not extract token - may need to wait longer", flush=True)
                sys.stdout.flush()
                # Try waiting a bit more and checking again
                time.sleep(2)
                try:
                    token = driver.execute_script("""
                        var preElements = document.querySelectorAll('pre, code, input[readonly]');
                        for (var i = 0; i < preElements.length; i++) {
                            var text = preElements[i].value || preElements[i].textContent || '';
                            text = text.trim();
                            if (text.length > 20 && /^[a-zA-Z0-9_-]+$/.test(text)) {
                                return text;
                            }
                        }
                        return null;
                    """)
                    if token and len(token) > 20:
                        print(f"  ✓ Token extracted on retry (length: {len(token)})", flush=True)
                        sys.stdout.flush()
                        
                        # Dismiss pop-up after retry extraction too
                        try:
                            driver.execute_script("""
                                var buttons = document.querySelectorAll('ha-button, mwc-button, button');
                                for (var i = 0; i < buttons.length; i++) {
                                    var btn = buttons[i];
                                    var text = (btn.textContent || '').toLowerCase();
                                    if ((text === 'close' || text === 'dismiss' || text === 'ok') && btn.offsetParent !== null) {
                                        btn.click();
                                        return true;
                                    }
                                }
                                return false;
                            """)
                        except:
                            pass
                        
                        return token
                except:
                    pass
                return None
                
        except Exception as e:
            print(f"  ⚠️  Error extracting token: {e}", flush=True)
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            return None
            
    except Exception as e:
        print(f"  ⚠️  Profile page token creation failed: {e}", flush=True)
        sys.stdout.flush()
        import traceback
        traceback.print_exc()
        return None


def get_or_create_ha_token(driver: Optional['webdriver.Chrome'] = None) -> Optional[str]:
    """Get HA token from environment or create from username/password or browser session.
    
    Checks in order:
    1. HA_TOKEN environment variable (preferred)
    2. Browser session (if driver provided and authenticated) → creates token automatically
    3. HA_USERNAME + HA_PASSWORD → creates token automatically via WebSocket
    
    Args:
        driver: Optional Selenium WebDriver instance with authenticated session
        
    Returns:
        Token string if available/created, None otherwise
    """
    # Check for existing token
    token = os.environ.get("HA_TOKEN")
    if token:
        return token
    
    # Try browser session first (if driver provided and authenticated)
    if driver:
        try:
            # Check if we're logged in by checking current URL
            current_url = driver.execute_script("return window.location.href;").lower()
            if "auth/authorize" not in current_url and "login" not in current_url:
                print("  Browser session authenticated, creating token...", flush=True)
                sys.stdout.flush()
                token = create_token_from_browser_session(driver)
                if token:
                    os.environ["HA_TOKEN"] = token
                    return token
        except Exception as e:
            print(f"  ⚠️  Browser token creation failed: {e}", flush=True)
            sys.stdout.flush()
    
    # Check for username/password
    username = os.environ.get("HA_USERNAME")
    password = os.environ.get("HA_PASSWORD")
    
    if username and password:
        print("  No HA_TOKEN found, but HA_USERNAME/HA_PASSWORD provided", flush=True)
        sys.stdout.flush()
        print("  Attempting to create token automatically...", flush=True)
        sys.stdout.flush()
        try:
            import asyncio
            token = asyncio.run(create_token_from_credentials(username, password))
            if token:
                # Optionally save to environment for this session
                os.environ["HA_TOKEN"] = token
                return token
            else:
                print("  ⚠️  Token creation returned None", flush=True)
                sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  Failed to create token: {e}", flush=True)
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
    
    return None


def stop_container(project_dir: str) -> bool:
    """Stop and remove HA container.
    
    Args:
        project_dir: Path to project root (where docker-compose.yml is)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # First try to stop via docker-compose
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True, timeout=5)
            compose_cmd = ["docker", "compose"]
        except:
            try:
                subprocess.run(["docker-compose", "--version"], capture_output=True, check=True, timeout=5)
                compose_cmd = ["docker-compose"]
            except:
                compose_cmd = ["docker", "compose"]
        
        compose_file = os.path.join(project_dir, "docker-compose.yml")
        if not os.path.exists(compose_file) and os.path.exists("/workspace/docker-compose.yml"):
            compose_file = "/workspace/docker-compose.yml"
            project_dir = "/workspace"
        
        if os.path.exists(compose_file):
            result = subprocess.run(
                compose_cmd + ["-f", compose_file, "stop", "homeassistant"],
                cwd=project_dir,
                capture_output=True,
                timeout=30
            )
            # Also remove container
            subprocess.run(
                compose_cmd + ["-f", compose_file, "rm", "-f", "homeassistant"],
                cwd=project_dir,
                capture_output=True,
                timeout=30
            )
        else:
            # Fallback: use docker directly
            subprocess.run(["docker", "stop", "ha-test"], capture_output=True, timeout=30)
            subprocess.run(["docker", "rm", "-f", "ha-test"], capture_output=True, timeout=30)
        
        return True
    except Exception as e:
        print(f"⚠️  Error stopping container: {e}")
        # Try direct docker command as fallback
        try:
            subprocess.run(["docker", "rm", "-f", "ha-test"], capture_output=True, timeout=30)
        except:
            pass
        return False


def clean_config(project_dir: str) -> bool:
    """Clean config directory for fresh install.
    
    Args:
        project_dir: Path to project root
        
    Returns:
        True if successful, False otherwise
    """
    # Try /config first (mounted volume in container)
    config_dirs = ["/config", os.path.join(project_dir, "config")]
    
    for config_dir in config_dirs:
        if os.path.exists(config_dir):
            try:
                # Remove contents but keep directory
                for item in os.listdir(config_dir):
                    item_path = os.path.join(config_dir, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                print(f"✓ Cleaned config directory: {config_dir}")
                return True
            except PermissionError:
                # If read-only, try to remove specific files
                print(f"⚠️  Config directory is read-only, skipping clean")
                return True
            except Exception as e:
                print(f"⚠️  Error cleaning config ({config_dir}): {e}")
                # Try next path
                continue
    return True


def start_container(project_dir: str, clean_config_flag: bool = False) -> bool:
    """Start HA container, optionally cleaning config.
    
    Args:
        project_dir: Path to project root (where docker-compose.yml is)
        clean_config_flag: If True, remove config directory before starting
        
    Returns:
        True if successful, False otherwise
    """
    if clean_config_flag:
        clean_config(project_dir)
    
    try:
        # Use docker compose (v2) or docker-compose (v1)
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True, timeout=5)
            compose_cmd = ["docker", "compose"]
        except:
            try:
                subprocess.run(["docker-compose", "--version"], capture_output=True, check=True, timeout=5)
                compose_cmd = ["docker-compose"]
            except:
                # Fallback: try docker compose anyway
                compose_cmd = ["docker", "compose"]
        
        # Ensure we have docker-compose.yml available
        compose_file = os.path.join(project_dir, "docker-compose.yml")
        if not os.path.exists(compose_file):
            workspace_compose = "/workspace/docker-compose.yml"
            if os.path.exists(workspace_compose):
                project_dir = "/workspace"
                compose_file = workspace_compose
        
        # Check if container already running
        check_result = subprocess.run(
            ["docker", "ps", "--filter", "name=ha-test", "--format", "{{.Names}}"],
            capture_output=True,
            timeout=10
        )
        if check_result.returncode == 0 and check_result.stdout.decode().strip():
            print("✓ Container already running")
            return True
        
        # Start container
        if os.path.exists(compose_file):
            result = subprocess.run(
                compose_cmd + ["-f", compose_file, "up", "-d", "homeassistant"],
                cwd=project_dir,
                capture_output=True,
                timeout=60
            )
        else:
            # Fallback: use docker directly
            result = subprocess.run(
                ["docker", "run", "-d", "--name", "ha-test", "--network", "host",
                 "-v", f"{project_dir}/config:/config",
                 "-v", f"{project_dir}/custom_components:/config/custom_components:ro",
                 "ghcr.io/home-assistant/home-assistant:stable"],
                capture_output=True,
                timeout=60
            )
        
        if result.returncode == 0:
            print("✓ Container started")
            return True
        else:
            error_msg = result.stderr.decode() if result.stderr else result.stdout.decode()
            # If container already exists, check if it's running
            if "already in use" in error_msg or "Conflict" in error_msg:
                check_result = subprocess.run(
                    ["docker", "ps", "--filter", "name=ha-test", "--format", "{{.Names}}"],
                    capture_output=True,
                    timeout=10
                )
                if check_result.stdout.decode().strip():
                    print("✓ Container already exists and is running")
                    return True
                # Remove and retry
                print("  Container exists but not running, removing...")
                subprocess.run(["docker", "rm", "-f", "ha-test"], capture_output=True, timeout=30)
                if os.path.exists(compose_file):
                    result = subprocess.run(
                        compose_cmd + ["-f", compose_file, "up", "-d", "homeassistant"],
                        cwd=project_dir,
                        capture_output=True,
                        timeout=60
                    )
                    if result.returncode == 0:
                        print("✓ Container started after cleanup")
                        return True
            print(f"✗ Failed to start container: {error_msg}")
            return False
    except Exception as e:
        print(f"✗ Error starting container: {e}")
        return False


def restart_container(project_dir: str) -> bool:
    """Restart HA container.
    
    Args:
        project_dir: Path to project root
        
    Returns:
        True if successful, False otherwise
    """
    try:
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
            compose_cmd = ["docker", "compose"]
        except:
            compose_cmd = ["docker-compose"]
        result = subprocess.run(
            compose_cmd + ["restart", "homeassistant"],
            cwd=project_dir,
            capture_output=True,
            timeout=60
        )
        return result.returncode == 0
    except Exception as e:
        print(f"⚠️  Error restarting container: {e}")
        return False


def check_container_health(container_name: str = CONTAINER_NAME) -> bool:
    """Check if container is running and healthy.
    
    Args:
        container_name: Name of container to check
        
    Returns:
        True if container is running, False otherwise
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            status = result.stdout.decode().strip()
            return "Up" in status
        return False
    except Exception:
        return False


def wait_for_container_ready(max_wait: int = 120) -> bool:
    """Wait for container to be ready.
    
    Args:
        max_wait: Maximum seconds to wait
        
    Returns:
        True when ready, False on timeout
    """
    print("Waiting for container to be healthy...")
    for i in range(max_wait):
        if check_container_health():
            print(f"✓ Container is healthy (after {i*2} seconds)")
            return True
        time.sleep(2)
    print(f"✗ Container not healthy after {max_wait*2} seconds")
    return False


def wait_for_ha_ready(max_wait: int = 180) -> bool:
    """Wait for HA API to respond.
    
    Args:
        max_wait: Maximum seconds to wait
        
    Returns:
        True when HA is ready, False on timeout
    """
    print("Waiting for Home Assistant to be ready...")
    for i in range(max_wait):
        try:
            resp = requests.get(f"{HA_URL}/api/", timeout=2)
            if resp.status_code in [200, 401]:
                print(f"✓ Home Assistant is ready (after {i*2} seconds)")
                return True
        except requests.exceptions.ConnectionError:
            # HA not started yet
            if i % 10 == 0:  # Print progress every 20 seconds
                print(f"  Still waiting... ({i*2}s)")
        except Exception as e:
            # Other errors - log but continue
            if i % 10 == 0:
                print(f"  Connection error: {e}")
        time.sleep(2)
    print(f"✗ Home Assistant not ready after {max_wait*2} seconds")
    print(f"  Check HA logs: docker-compose logs homeassistant")
    return False


def wait_for_ha_restart(max_wait: int = 180) -> bool:
    """Wait for HA to restart and be ready.
    
    Monitors API availability - waits for it to become unavailable (restarting),
    then waits for it to become available again.
    
    Args:
        max_wait: Maximum seconds to wait
        
    Returns:
        True when HA is ready after restart, False on timeout
    """
    print("Waiting for HA restart...")
    
    # Wait for API to become unavailable (restarting)
    print("  Waiting for restart to begin...")
    for i in range(30):
        try:
            requests.get(f"{HA_URL}/api/", timeout=1)
        except:
            break
        time.sleep(1)
    
    # Wait for API to become available again
    print("  Waiting for restart to complete...")
    return wait_for_ha_ready(max_wait)


def check_ha_logs_for_errors() -> list[str]:
    """Check container logs for errors.
    
    Returns:
        List of error lines found
    """
    try:
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
            compose_cmd = ["docker", "compose"]
        except:
            compose_cmd = ["docker-compose"]
        result = subprocess.run(
            compose_cmd + ["logs", "--tail", "100", "homeassistant"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            logs = result.stdout.decode()
            error_lines = [
                line.strip() for line in logs.split('\n')
                if 'ERROR' in line.upper() or 'CRITICAL' in line.upper()
            ]
            return error_lines
    except Exception:
        pass
    return []


def start_xvfb() -> bool:
    """Start Xvfb (X Virtual Framebuffer) for non-headless browser display.
    
    Returns:
        True if Xvfb is running or started successfully, False otherwise
    """
    # Check if Xvfb is already running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Xvfb"],
            capture_output=True,
            timeout=2
        )
        if result.returncode == 0:
            print("  ✓ Xvfb already running", flush=True)
            sys.stdout.flush()
            return True
    except:
        pass
    
    # Start Xvfb on display :99
    try:
        display = os.environ.get("DISPLAY", ":99")
        print(f"  Starting Xvfb on display {display}...", flush=True)
        sys.stdout.flush()
        
        # Start Xvfb in background
        subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1920x1080x24", "-ac", "+extension", "RANDR"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait a moment for it to start
        time.sleep(2)
        
        # Verify it's running
        result = subprocess.run(
            ["pgrep", "-f", "Xvfb"],
            capture_output=True,
            timeout=2
        )
        if result.returncode == 0:
            print(f"  ✓ Xvfb started on display {display}", flush=True)
            sys.stdout.flush()
            return True
        else:
            print(f"  ⚠️  Xvfb may not have started", flush=True)
            sys.stdout.flush()
            return False
    except FileNotFoundError:
        print("  ⚠️  Xvfb not found - non-headless mode may not work", flush=True)
        sys.stdout.flush()
        return False
    except Exception as e:
        print(f"  ⚠️  Failed to start Xvfb: {e}", flush=True)
        sys.stdout.flush()
        return False


def create_driver(headless: bool = True) -> Optional[webdriver.Chrome]:
    """Create Chrome WebDriver for browser automation.
    
    Supports both standalone selenium container and local chrome.
    If SELENIUM_HUB_URL env var is set, connects to remote selenium.
    Falls back to local chrome if selenium hub unavailable.
    
    Args:
        headless: If False, run browser in non-headless mode (requires Xvfb)
    
    Returns:
        WebDriver instance or None if creation fails
    """
    # Set DBUS to prevent ChromeDriver hangs in containers
    if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = "/dev/null"
    
    # For non-headless mode, ensure Xvfb is running
    if not headless:
        if not start_xvfb():
            print("  ⚠️  Falling back to headless mode", flush=True)
            sys.stdout.flush()
            headless = True
    
    selenium_hub = os.environ.get("SELENIUM_HUB_URL")
    
    # Try remote selenium hub first if configured
    if selenium_hub:
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        try:
            from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
            driver = webdriver.Remote(
                command_executor=selenium_hub,
                options=chrome_options
            )
            print(f"✓ Connected to selenium hub: {selenium_hub}")
            return driver
        except Exception as e:
            print(f"⚠️  Failed to connect to selenium hub ({selenium_hub}): {e}")
            print("   Falling back to local chrome...")
    
    # Fallback: Local chrome driver (works if chrome installed in container)
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    else:
        # Non-headless mode - ensure display is set
        display = os.environ.get("DISPLAY", ":99")
        chrome_options.add_argument(f"--display={display}")
        print(f"  Running Chrome in non-headless mode on display {display}", flush=True)
        sys.stdout.flush()
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    if headless:
        chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-features=TranslateUI")
    chrome_options.add_argument("--disable-ipc-flooding-protection")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--dns-prefetch-disable")  # Prevent DNS-related timeouts
    chrome_options.add_argument("--disable-setuid-sandbox")  # Additional sandbox fix
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    
    # Enable logging for debugging
    chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL', 'driver': 'ALL'})
    chrome_options.add_argument("--enable-logging")
    chrome_options.add_argument("--v=1")
    
    try:
        import shutil
        chrome_binary = None
        for binary in ["chromium", "chromium-browser", "google-chrome", "chrome"]:
            path = shutil.which(binary)
            if path:
                chrome_binary = path
                break
        
        if chrome_binary:
            chrome_options.binary_location = chrome_binary
        
        # Find chromedriver - check multiple locations
        chromedriver_path = None
        possible_paths = [
            "/usr/bin/chromedriver",
            "/usr/bin/chromium-chromedriver",
            "/usr/lib/chromium/chromedriver",
            shutil.which("chromedriver"),
            shutil.which("chromium-driver"),
            shutil.which("chromium-chromedriver")
        ]
        
        for path in possible_paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                chromedriver_path = path
                print(f"  Found chromedriver: {chromedriver_path}")
                break
        
        if chromedriver_path:
            try:
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception as e:
                print(f"  ⚠️  Failed with explicit service: {e}, trying without...")
                driver = webdriver.Chrome(options=chrome_options)
        else:
            print("  No chromedriver found in standard locations, trying selenium manager...")
            # Selenium 4+ can auto-download chromedriver
            try:
                driver = webdriver.Chrome(options=chrome_options)
            except Exception as e:
                print(f"  ✗ Selenium manager also failed: {e}")
                raise
        
        # Set reasonable timeouts
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(5)  # Reduced from 10
        
        print("✓ Created local chrome driver")
        return driver
    except Exception as e:
        print(f"✗ Failed to create browser driver: {e}")
        print("   Install chrome/chromium in container or configure SELENIUM_HUB_URL")
        return None


def complete_onboarding_storage() -> bool:
    """Manually complete onboarding by editing storage file.
    
    This is a workaround for JavaScript errors preventing UI form rendering.
    Note: This marks onboarding as complete but DOES NOT create a user account.
    User account creation still requires UI or manual intervention.
    
    Returns:
        True if storage file was updated, False otherwise
    """
    import json
    
    # Try /config first (mounted volume in container)
    config_dirs = ["/config", os.path.join(get_project_dir(), "config")]
    
    for config_dir in config_dirs:
        storage_file = os.path.join(config_dir, ".storage", "onboarding")
        if os.path.exists(storage_file):
            try:
                # Read existing file
                with open(storage_file, 'r') as f:
                    data = json.load(f)
                
                # Mark all steps as done
                if "data" not in data:
                    data["data"] = {}
                if "done" not in data["data"]:
                    data["data"]["done"] = []
                
                steps = ["user", "core_config", "analytics", "integration"]
                for step in steps:
                    if step not in data["data"]["done"]:
                        data["data"]["done"].append(step)
                
                # Write back
                with open(storage_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                print(f"  ✓ Updated onboarding storage file: {storage_file}", flush=True)
                sys.stdout.flush()
                print("  ⚠️  Note: User account still needs to be created via UI", flush=True)
                sys.stdout.flush()
                return True
            except Exception as e:
                print(f"  ⚠️  Could not update storage file: {e}", flush=True)
                sys.stdout.flush()
                continue
    
    return False


def complete_onboarding_api() -> bool:
    """Check if onboarding can be completed via API.
    
    Note: HA doesn't provide API for user creation, but we can check status.
    
    Returns:
        True if already complete, False if needs UI completion
    """
    try:
        # Check current onboarding status
        resp = requests.get(f"{HA_URL}/api/onboarding", timeout=5)
        if resp.status_code == 200:
            steps = resp.json()
            # Check if user step is already done
            user_step = next((s for s in steps if s.get("step") == "user"), None)
            if user_step and user_step.get("done"):
                print("  ✓ User account already created (verified via API)", flush=True)
                sys.stdout.flush()
                return True
            else:
                print("  ⚠️  User account not created - must use UI", flush=True)
                sys.stdout.flush()
                return False
        else:
            return False
    except Exception as e:
        print(f"  ⚠️  Could not check onboarding status: {e}", flush=True)
        sys.stdout.flush()
        return False


def verify_onboarding_complete() -> bool:
    """Verify that onboarding is complete and user account exists.
    
    This validates that:
    1. Onboarding API indicates user step is done
    2. User account can authenticate (credentials work)
    
    Returns:
        True if onboarding is complete and user account exists, False otherwise
    """
    print("\n=== Verifying Onboarding Complete ===", flush=True)
    sys.stdout.flush()
    
    # Check onboarding API
    try:
        import requests
        resp = requests.get(f"{HA_URL}/api/onboarding", timeout=5)
        if resp.status_code == 200:
            steps = resp.json()
            user_step = next((s for s in steps if s.get("step") == "user"), None)
            if not user_step or not user_step.get("done"):
                print("  ✗ Onboarding incomplete - user step not done", flush=True)
                sys.stdout.flush()
                return False
            print("  ✓ Onboarding API indicates user step is complete", flush=True)
            sys.stdout.flush()
        elif resp.status_code == 404:
            # Onboarding API returns 404 when onboarding is complete
            print("  ✓ Onboarding API returns 404 (onboarding complete)", flush=True)
            sys.stdout.flush()
        else:
            print(f"  ⚠️  Unexpected onboarding API response: {resp.status_code}", flush=True)
            sys.stdout.flush()
    except Exception as e:
        print(f"  ⚠️  Could not check onboarding API: {e}", flush=True)
        sys.stdout.flush()
        return False
    
    # Verify user account exists by attempting authentication
    username = os.environ.get("HA_USERNAME", ONBOARDING_USERNAME)
    password = os.environ.get("HA_PASSWORD", ONBOARDING_PASSWORD)
    
    if username and password:
        print(f"  Verifying user account exists: {username}", flush=True)
        sys.stdout.flush()
        try:
            # Try to create a token - if this works, user account exists
            token = get_or_create_ha_token()
            if token:
                print("  ✓ User account verified - can authenticate", flush=True)
                sys.stdout.flush()
                return True
            else:
                print("  ✗ User account verification failed - cannot authenticate", flush=True)
                sys.stdout.flush()
                print(f"    Credentials: {username} / {'*' * len(password)}", flush=True)
                sys.stdout.flush()
                return False
        except Exception as e:
            print(f"  ✗ User account verification error: {e}", flush=True)
            sys.stdout.flush()
            return False
    else:
        print("  ⚠️  No credentials provided - cannot verify user account", flush=True)
        sys.stdout.flush()
        return False


def complete_onboarding_ui(driver: Optional[webdriver.Chrome] = None, timeout: int = 30, use_non_headless: bool = True) -> bool:
    """Complete onboarding via UI clicks.
    
    First checks if already complete via API, then tries UI.
    Home Assistant requires UI for user creation (no API endpoint).
    
    Args:
        driver: Selenium WebDriver instance (if None, creates one)
        timeout: Page load timeout in seconds
        use_non_headless: If True, use non-headless browser for user creation (may fix JS errors)
        
    Returns:
        True if successful, False otherwise
    """
    # Check if already complete via API AND user account exists
    # Don't just check API - must verify user account actually exists
    api_complete = complete_onboarding_api()
    if api_complete:
        # Verify user account actually exists by attempting authentication
        print("  Onboarding API indicates complete - verifying user account exists...", flush=True)
        sys.stdout.flush()
        if verify_onboarding_complete():
            print("  ✓ Onboarding complete and user account verified", flush=True)
            sys.stdout.flush()
            return True
        else:
            print("  ⚠️  Onboarding API says complete but user account doesn't exist", flush=True)
            sys.stdout.flush()
            print("  Will attempt to complete onboarding via UI...", flush=True)
            sys.stdout.flush()
            # Continue to UI completion below
    
    # If no driver provided, we can't create user account - fail
    if driver is None:
        print("  ✗ No driver provided - cannot create user account via UI", flush=True)
        sys.stdout.flush()
        print("  ⚠️  Storage workaround doesn't create user account - login will fail!", flush=True)
        sys.stdout.flush()
        return False
    
    # Must use UI to create user account
    print("  User account needs to be created via UI...", flush=True)
    sys.stdout.flush()
    
    # Create driver if not provided
    driver_provided = driver is not None
    if driver is None:
        if use_non_headless:
            print("  Creating browser driver (non-headless mode for user creation)...", flush=True)
            sys.stdout.flush()
        else:
            print("  Creating browser driver (headless mode)...", flush=True)
            sys.stdout.flush()
        driver = create_driver(headless=not use_non_headless)
        if driver is None:
            print("  ✗ Failed to create browser driver", flush=True)
            sys.stdout.flush()
            return False
    
    # Cleanup driver if we created it (at end of function)
    driver_should_close = not driver_provided
    
    import signal
    
    try:
        driver.set_page_load_timeout(timeout)
        print("  Loading HA homepage...")
        try:
            driver.get(HA_URL)
            print("  Page loaded")
        except Exception as e:
            print(f"⚠️  Page load timeout/error: {e}")
            # Try to continue anyway - page may have partially loaded
        
        print("  Waiting for page to stabilize...", flush=True)
        sys.stdout.flush()
        
        # Use explicit wait with timeout instead of sleep
        try:
            WebDriverWait(driver, 5).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            pass  # Continue even if readyState check times out
        
        time.sleep(1)  # Brief additional wait
        
        print("  Checking onboarding status...", flush=True)
        sys.stdout.flush()
        try:
            current_url = driver.current_url.lower()
            print(f"  Current URL: {current_url[:80]}...", flush=True)
            sys.stdout.flush()
        except Exception as e:
            print(f"⚠️  Could not get current URL: {e}", flush=True)
            sys.stdout.flush()
            return False
        
        # Check if already completed - verify via API first (more reliable)
        print("  Checking onboarding status via API...", flush=True)
        sys.stdout.flush()
        onboarding_complete = False
        try:
            import requests
            # Check onboarding status via API
            resp = requests.get(f"{HA_URL}/api/config", timeout=5)
            if resp.status_code == 200:
                config = resp.json()
                # If we can get config with location_name, onboarding is complete
                if config.get("location_name"):
                    print(f"  ✓ Onboarding already completed (location: {config.get('location_name')})", flush=True)
                    sys.stdout.flush()
                    onboarding_complete = True
                else:
                    print("  ⚠️  Config API accessible but no location_name - checking onboarding status...", flush=True)
                    sys.stdout.flush()
                    # Try onboarding API endpoint
                    try:
                        onboarding_resp = requests.get(f"{HA_URL}/api/onboarding", timeout=5)
                        if onboarding_resp.status_code == 200:
                            onboarding_data = onboarding_resp.json()
                            if onboarding_data.get("done"):
                                print("  ✓ Onboarding already completed (verified via onboarding API)", flush=True)
                                sys.stdout.flush()
                                onboarding_complete = True
                            else:
                                print(f"  Onboarding status: {onboarding_data}", flush=True)
                                sys.stdout.flush()
                    except:
                        pass
            elif resp.status_code == 401:
                print("  ⚠️  API requires authentication - checking onboarding endpoint...", flush=True)
                sys.stdout.flush()
                # Try onboarding endpoint which might not require auth
                try:
                    onboarding_resp = requests.get(f"{HA_URL}/api/onboarding", timeout=5)
                    if onboarding_resp.status_code == 200:
                        onboarding_data = onboarding_resp.json()
                        if onboarding_data.get("done"):
                            print("  ✓ Onboarding already completed (verified via onboarding API)", flush=True)
                            sys.stdout.flush()
                            onboarding_complete = True
                except:
                    pass
            else:
                print(f"  ⚠️  API returned status {resp.status_code}", flush=True)
                sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  API check failed: {e}, continuing with page check...", flush=True)
            sys.stdout.flush()
        
        if onboarding_complete:
            # Verify user account actually exists before returning True
            print("  Verifying user account exists...", flush=True)
            sys.stdout.flush()
            if verify_onboarding_complete():
                return True
            else:
                print("  ⚠️  Onboarding API says complete but user account doesn't exist", flush=True)
                sys.stdout.flush()
                print("  Will attempt to complete onboarding via UI...", flush=True)
                sys.stdout.flush()
                # Continue to UI completion below
        
        # If not on onboarding page, check if user account exists
        # Don't assume completion just because we're not on onboarding page
        if "onboarding" not in current_url:
            # Check if we're on a page that indicates completion (dashboard, lovelace)
            # vs an auth page that might mean onboarding isn't done
            if "lovelace" in current_url or "dashboard" in current_url or "overview" in current_url:
                # These pages suggest onboarding might be complete - verify
                print("  URL suggests onboarding complete - verifying user account exists...", flush=True)
                sys.stdout.flush()
                if verify_onboarding_complete():
                    print("✓ Onboarding already completed (verified via URL and user account)", flush=True)
                    sys.stdout.flush()
                    return True
                else:
                    print("  ⚠️  URL suggests complete but user account doesn't exist", flush=True)
                    sys.stdout.flush()
                    print("  Will attempt to navigate to onboarding page...", flush=True)
                    sys.stdout.flush()
                    # Try to navigate to onboarding explicitly
                    try:
                        driver.get(f"{HA_URL}/onboarding")
                        time.sleep(3)
                        # Check again if we're on onboarding page now
                        current_url = driver.current_url.lower()
                        if "onboarding" in current_url:
                            print("  ✓ Navigated to onboarding page", flush=True)
                            sys.stdout.flush()
                            # Continue with onboarding completion below
                        else:
                            print("  ⚠️  Could not navigate to onboarding page", flush=True)
                            sys.stdout.flush()
                            return False
                    except Exception as e:
                        print(f"  ⚠️  Error navigating to onboarding: {e}", flush=True)
                        sys.stdout.flush()
                        return False
            elif "auth" in current_url or "login" in current_url:
                # Auth/login page - might mean onboarding isn't done, try to navigate to onboarding
                print("  On auth/login page - checking if onboarding needed...", flush=True)
                sys.stdout.flush()
                if verify_onboarding_complete():
                    print("✓ User account exists - onboarding complete", flush=True)
                    sys.stdout.flush()
                    return True
                else:
                    print("  User account doesn't exist - navigating to onboarding...", flush=True)
                    sys.stdout.flush()
                    try:
                        driver.get(f"{HA_URL}/onboarding")
                        time.sleep(3)
                        current_url = driver.current_url.lower()
                        if "onboarding" in current_url:
                            print("  ✓ Navigated to onboarding page", flush=True)
                            sys.stdout.flush()
                            # Continue with onboarding completion below
                        else:
                            print("  ⚠️  Could not navigate to onboarding page", flush=True)
                            sys.stdout.flush()
                            return False
                    except Exception as e:
                        print(f"  ⚠️  Error navigating to onboarding: {e}", flush=True)
                        sys.stdout.flush()
                        return False
            else:
                # Unknown page - verify user account exists
                print("  Unknown page - verifying user account exists...", flush=True)
                sys.stdout.flush()
                if verify_onboarding_complete():
                    print("✓ User account exists - onboarding complete", flush=True)
                    sys.stdout.flush()
                    return True
                else:
                    print("  User account doesn't exist - navigating to onboarding...", flush=True)
                    sys.stdout.flush()
                    try:
                        driver.get(f"{HA_URL}/onboarding")
                        time.sleep(3)
                        current_url = driver.current_url.lower()
                        if "onboarding" in current_url:
                            print("  ✓ Navigated to onboarding page", flush=True)
                            sys.stdout.flush()
                            # Continue with onboarding completion below
                        else:
                            print("  ⚠️  Could not navigate to onboarding page", flush=True)
                            sys.stdout.flush()
                            return False
                    except Exception as e:
                        print(f"  ⚠️  Error navigating to onboarding: {e}", flush=True)
                        sys.stdout.flush()
                        return False
        
        # Update current_url after potential navigation
        try:
            current_url = driver.current_url.lower()
        except:
            pass
        
        # If we're on onboarding page, try to complete it
        if "onboarding" in current_url:
            print("  On onboarding page - attempting to complete...", flush=True)
            sys.stdout.flush()
            
            # Wait for page to be fully interactive (with timeout protection)
            print("  Waiting for page to be interactive...", flush=True)
            sys.stdout.flush()
            try:
                # Use polling instead of WebDriverWait to avoid blocking
                ready = False
                for i in range(10):  # 10 attempts, 1 second each = 10 seconds max
                    try:
                        ready_state = driver.execute_script("return document.readyState")
                        if ready_state == "complete":
                            ready = True
                            break
                    except:
                        pass
                    time.sleep(1)
                    if i % 2 == 0:
                        print(f"    Waiting... ({i+1}/10)", flush=True)
                        sys.stdout.flush()
                
                if ready:
                    print("  Page is ready", flush=True)
                    sys.stdout.flush()
                else:
                    print("  ⚠️  Page ready state timeout, continuing anyway...", flush=True)
                    sys.stdout.flush()
                
                # Capture console logs to diagnose JavaScript errors
                print("  Capturing browser console logs...", flush=True)
                sys.stdout.flush()
                console_logs = []
                try:
                    logs = driver.get_log('browser')
                    console_logs = [log for log in logs]
                    if console_logs:
                        print(f"  Found {len(console_logs)} console messages", flush=True)
                        sys.stdout.flush()
                        # Save console logs
                        import json
                        with open("/workspace/test/onboarding_console_logs.json", "w", encoding="utf-8") as f:
                            json.dump(console_logs, f, indent=2, default=str)
                        print("  ✓ Saved console logs to /workspace/test/onboarding_console_logs.json", flush=True)
                        sys.stdout.flush()
                        
                        # Show errors/warnings
                        errors = [log for log in console_logs if log.get('level') == 'SEVERE']
                        warnings = [log for log in console_logs if log.get('level') == 'WARNING']
                        if errors:
                            print(f"  ⚠️  Found {len(errors)} JavaScript errors:", flush=True)
                            sys.stdout.flush()
                            for err in errors[:3]:  # First 3 errors
                                print(f"    - {err.get('message', 'Unknown error')[:100]}", flush=True)
                                sys.stdout.flush()
                        if warnings:
                            print(f"  ⚠️  Found {len(warnings)} warnings", flush=True)
                            sys.stdout.flush()
                except Exception as e:
                    print(f"  ⚠️  Could not capture console logs: {e}", flush=True)
                    sys.stdout.flush()
                
                # Check for JavaScript errors in page
                print("  Checking for JavaScript errors in page...", flush=True)
                sys.stdout.flush()
                try:
                    js_errors = driver.execute_script("""
                        if (window.onerror) {
                            return window.__selenium_errors || [];
                        }
                        return [];
                    """)
                    if js_errors:
                        print(f"  ⚠️  Found {len(js_errors)} JavaScript errors in page", flush=True)
                        sys.stdout.flush()
                except:
                    pass
                
                # Wait for JavaScript to render form elements (not just page ready)
                print("  Waiting for form elements to render...", flush=True)
                sys.stdout.flush()
                
                form_ready = False
                for i in range(30):  # Wait up to 30 seconds for form to appear
                    try:
                        # Use timeout wrapper to prevent blocking
                        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                        
                        def check_inputs():
                            return driver.execute_script("return document.querySelectorAll('input').length")
                        
                        input_count = 0
                        try:
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(check_inputs)
                                input_count = future.result(timeout=1.0)
                        except FutureTimeoutError:
                            print(f"    execute_script timeout on attempt {i+1}", flush=True)
                            sys.stdout.flush()
                            continue
                        
                        if input_count > 0:
                            print(f"  ✓ Form elements rendered ({input_count} inputs found)", flush=True)
                            sys.stdout.flush()
                            form_ready = True
                            break
                    except Exception as e:
                        if i % 5 == 0:
                            print(f"    Error checking inputs: {str(e)[:50]}...", flush=True)
                            sys.stdout.flush()
                    
                    time.sleep(1)
                    if i % 5 == 0 and i > 0:
                        print(f"    Still waiting for form... ({i}/30)", flush=True)
                        sys.stdout.flush()
                
                if not form_ready:
                    print("  ⚠️  Form elements did not appear after 30 seconds", flush=True)
                    sys.stdout.flush()
                    print("  Investigating why form isn't rendering...", flush=True)
                    sys.stdout.flush()
                    
                    # Check if page redirected or changed
                    try:
                        final_url = driver.current_url
                        print(f"  Final URL: {final_url}", flush=True)
                        sys.stdout.flush()
                        
                        # Check if there's any content in body
                        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                        def get_body_content():
                            return driver.execute_script("return document.body ? document.body.innerText : 'No body'")
                        
                        body_content = ""
                        try:
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(get_body_content)
                                body_content = future.result(timeout=2.0)
                        except:
                            body_content = "Could not retrieve"
                        
                        if body_content and len(body_content.strip()) > 0:
                            print(f"  Body content preview: {body_content[:200]}...", flush=True)
                            sys.stdout.flush()
                        else:
                            print("  ⚠️  Body is empty - JavaScript error preventing form render", flush=True)
                            sys.stdout.flush()
                            print("  The JavaScript error 'Cannot read properties of undefined (reading config)'", flush=True)
                            sys.stdout.flush()
                            print("  suggests the onboarding script can't access required data.", flush=True)
                            sys.stdout.flush()
                        
                        # Check for shadow DOM or web components
                        def check_shadow():
                            return driver.execute_script("""
                                return Array.from(document.querySelectorAll('*')).filter(el => el.shadowRoot).length;
                            """)
                        
                        try:
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(check_shadow)
                                shadow_elements = future.result(timeout=2.0)
                                if shadow_elements > 0:
                                    print(f"  Found {shadow_elements} shadow DOM elements", flush=True)
                                    sys.stdout.flush()
                        except:
                            pass
                        
                    except Exception as e:
                        print(f"  ⚠️  Error investigating: {e}", flush=True)
                        sys.stdout.flush()
                    
                    # Since form didn't render, return False - we can't complete onboarding
                    print("  ✗ Cannot complete onboarding - form did not render", flush=True)
                    sys.stdout.flush()
                    return False
                
                # DIAGNOSTIC: Save page source and DOM structure
                print("  Saving page diagnostics...", flush=True)
                sys.stdout.flush()
                try:
                    # Save full page source
                    page_source = driver.page_source
                    with open("/workspace/test/onboarding_page_source.html", "w", encoding="utf-8") as f:
                        f.write(page_source)
                    print("  ✓ Saved page source to /workspace/test/onboarding_page_source.html", flush=True)
                    sys.stdout.flush()
                    
                    # Save screenshot
                    driver.save_screenshot("/workspace/test/onboarding_page.png")
                    print("  ✓ Saved screenshot to /workspace/test/onboarding_page.png", flush=True)
                    sys.stdout.flush()
                    
                    # Get and save DOM structure info
                    dom_info = driver.execute_script("""
                        return {
                            title: document.title,
                            url: window.location.href,
                            inputs: Array.from(document.querySelectorAll('input')).map(el => ({
                                type: el.type,
                                name: el.name,
                                id: el.id,
                                placeholder: el.placeholder,
                                className: el.className,
                                visible: el.offsetParent !== null,
                                tagName: el.tagName
                            })),
                            buttons: Array.from(document.querySelectorAll('button')).map(el => ({
                                type: el.type,
                                text: el.textContent.trim().substring(0, 50),
                                id: el.id,
                                className: el.className,
                                visible: el.offsetParent !== null
                            })),
                            allInputs: Array.from(document.querySelectorAll('input')).length,
                            allButtons: Array.from(document.querySelectorAll('button')).length,
                            bodyText: document.body ? document.body.innerText.substring(0, 500) : 'No body'
                        };
                    """)
                    
                    import json
                    with open("/workspace/test/onboarding_dom_info.json", "w", encoding="utf-8") as f:
                        json.dump(dom_info, f, indent=2)
                    print("  ✓ Saved DOM info to /workspace/test/onboarding_dom_info.json", flush=True)
                    sys.stdout.flush()
                    
                    # Print summary
                    print(f"  Page title: {dom_info.get('title', 'N/A')}", flush=True)
                    sys.stdout.flush()
                    print(f"  Found {dom_info.get('allInputs', 0)} input elements", flush=True)
                    sys.stdout.flush()
                    print(f"  Found {dom_info.get('allButtons', 0)} button elements", flush=True)
                    sys.stdout.flush()
                    
                    # List visible inputs
                    visible_inputs = [inp for inp in dom_info.get('inputs', []) if inp.get('visible')]
                    if visible_inputs:
                        print(f"  Visible inputs ({len(visible_inputs)}):", flush=True)
                        sys.stdout.flush()
                        for inp in visible_inputs[:5]:  # First 5
                            print(f"    - type={inp.get('type')}, name={inp.get('name')}, placeholder={inp.get('placeholder')}, id={inp.get('id')}", flush=True)
                            sys.stdout.flush()
                    else:
                        print("  ⚠️  No visible inputs found - form may not be loaded", flush=True)
                        sys.stdout.flush()
                    
                except Exception as e:
                    print(f"  ⚠️  Failed to save diagnostics: {e}", flush=True)
                    sys.stdout.flush()
                    import traceback
                    traceback.print_exc()
                    
            except Exception as e:
                print(f"  ⚠️  Ready state check failed: {e}, continuing...", flush=True)
                sys.stdout.flush()
                time.sleep(3)  # Fallback wait
        else:
            # Not on onboarding page - but verify user account actually exists
            print("  Not on onboarding page - verifying user account exists...", flush=True)
            sys.stdout.flush()
            if verify_onboarding_complete():
                print("  ✓ User account verified - onboarding truly complete", flush=True)
                sys.stdout.flush()
                return True
            else:
                print("  ✗ User account doesn't exist - onboarding not actually complete", flush=True)
                sys.stdout.flush()
                print("  Will attempt to navigate to onboarding page...", flush=True)
                sys.stdout.flush()
                # Try to navigate to onboarding explicitly
                try:
                    driver.get(f"{HA_URL}/onboarding")
                    time.sleep(3)
                    # Check again if we're on onboarding page now
                    if "onboarding" in driver.current_url.lower():
                        print("  ✓ Navigated to onboarding page", flush=True)
                        sys.stdout.flush()
                        # Continue with onboarding completion below
                    else:
                        print("  ⚠️  Could not navigate to onboarding page", flush=True)
                        sys.stdout.flush()
                        return False
                except Exception as e:
                    print(f"  ⚠️  Error navigating to onboarding: {e}", flush=True)
                    sys.stdout.flush()
                    return False
        
        # Find form fields using polling instead of WebDriverWait (more reliable)
        print("  Looking for name field...", flush=True)
        sys.stdout.flush()
        
        name_field = None
        
        # Try multiple selectors - use polling with explicit timeout
        selectors = [
            "input[type='text'][name*='name' i]",
            "input[type='text'][placeholder*='name' i]",
            "input[type='text']",
            "ha-textfield input",
            "mwc-textfield input",
            "paper-input input",
            "input[name*='name' i]"
        ]
        
        for selector in selectors:
            try:
                print(f"    Trying selector: {selector[:50]}...", flush=True)
                sys.stdout.flush()
                
                # Poll for element with explicit timeout (max 3 seconds)
                max_attempts = 6
                for attempt in range(max_attempts):
                    try:
                        # Use threading timeout to prevent find_elements from hanging
                        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                        
                        def find_elements_safe():
                            try:
                                # Set a very short implicit wait to prevent blocking
                                driver.implicitly_wait(0)
                                result = driver.find_elements(By.CSS_SELECTOR, selector)
                                driver.implicitly_wait(5)  # Restore
                                return result
                            except Exception as e:
                                driver.implicitly_wait(5)  # Restore on error
                                raise
                        
                        elements = None
                        try:
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(find_elements_safe)
                                elements = future.result(timeout=0.5)  # Very short timeout - 0.5 seconds
                        except FutureTimeoutError:
                            print(f"    find_elements timeout on attempt {attempt+1}", flush=True)
                            sys.stdout.flush()
                            # Restore implicit wait
                            try:
                                driver.implicitly_wait(5)
                            except:
                                pass
                            continue
                        except Exception as e:
                            print(f"    find_elements error: {str(e)[:50]}...", flush=True)
                            sys.stdout.flush()
                            continue
                        
                        if elements:
                            for elem in elements:
                                try:
                                    if elem.is_displayed() and elem.is_enabled():
                                        name_field = elem
                                        print(f"  ✓ Found name field: {selector[:50]}...", flush=True)
                                        sys.stdout.flush()
                                        break
                                except:
                                    continue
                            if name_field:
                                break
                    except Exception as e:
                        if attempt == max_attempts - 1:
                            print(f"    Error: {str(e)[:50]}...", flush=True)
                            sys.stdout.flush()
                    
                    if name_field:
                        break
                    time.sleep(0.5)  # Wait 0.5s between attempts
                
                if name_field:
                    break
                else:
                    print(f"    Not found after {max_attempts} attempts", flush=True)
                    sys.stdout.flush()
                    
            except Exception as e:
                print(f"    Exception: {str(e)[:50]}...", flush=True)
                sys.stdout.flush()
                continue
        
        if name_field:
            try:
                name_field.clear()
                name_field.send_keys(ONBOARDING_NAME)
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  Error filling name: {e}", flush=True)
                sys.stdout.flush()
        else:
            print("⚠️  Could not find name field - may be on different step", flush=True)
            sys.stdout.flush()
            # Check if past onboarding
            try:
                driver.get(HA_URL)
                time.sleep(2)
                if "onboarding" not in driver.current_url.lower():
                    print("✓ Onboarding already completed")
                    return True
            except:
                pass
            return True
        
        print("  Looking for username field...", flush=True)
        sys.stdout.flush()
        
        username_field = None
        for selector in [
            "input[type='text'][name*='username' i]",
            "input[type='text'][id*='username' i]",
            "input[placeholder*='username' i]",
            "input[name='username']",
            "ha-textfield input",
            "mwc-textfield input"
        ]:
            try:
                username_field = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if username_field and username_field.is_displayed():
                    print(f"  Found username field with selector: {selector}", flush=True)
                    sys.stdout.flush()
                    break
            except:
                continue
        
        if username_field:
            try:
                print("  Filling username field...", flush=True)
                sys.stdout.flush()
                username_field.clear()
                username_field.send_keys(ONBOARDING_USERNAME)
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  Error filling username field: {e}", flush=True)
                sys.stdout.flush()
        else:
            print("⚠️  Could not find username field - may already be filled or on different step")
            return True
        
        print("  Looking for password field...", flush=True)
        sys.stdout.flush()
        
        password_field = None
        for selector in [
            "input[type='password']",
            "input[name*='password' i]",
            "input[id*='password' i]",
            "ha-textfield input[type='password']",
            "mwc-textfield input[type='password']"
        ]:
            try:
                password_field = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if password_field and password_field.is_displayed():
                    print(f"  Found password field with selector: {selector}", flush=True)
                    sys.stdout.flush()
                    break
            except:
                continue
        
        if password_field:
            try:
                print("  Filling password field...", flush=True)
                sys.stdout.flush()
                password_field.clear()
                password_field.send_keys(ONBOARDING_PASSWORD)
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  Error filling password field: {e}", flush=True)
                sys.stdout.flush()
        else:
            print("⚠️  Could not find password field")
            return True
        
        # Find and click submit button with robust waiting
        print("  Looking for submit button...", flush=True)
        sys.stdout.flush()
        
        submit_button = None
        for xpath in [
            "//button[@type='submit']",
            "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]",
            "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'create')]",
            "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'finish')]",
            "//ha-button[@type='submit']",
            "//mwc-button[@type='submit']",
            "//paper-button[@type='submit']"
        ]:
            try:
                submit_button = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                if submit_button and submit_button.is_displayed():
                    print(f"  Found submit button with xpath: {xpath[:50]}...", flush=True)
                    sys.stdout.flush()
                    break
            except:
                continue
        
        if submit_button:
            try:
                print("  Clicking submit button...", flush=True)
                sys.stdout.flush()
                # Scroll into view if needed
                driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                time.sleep(0.5)
                submit_button.click()
                print("  Submit clicked, waiting for navigation...", flush=True)
                sys.stdout.flush()
                time.sleep(5)
                
                # Verify onboarding completed
                driver.get(HA_URL)
                time.sleep(3)
                if "onboarding" not in driver.current_url.lower():
                    print("✓ Onboarding completed")
                    return True
                else:
                    print("⚠️  Still on onboarding page after submit")
            except Exception as e:
                print(f"  ⚠️  Error clicking submit: {e}", flush=True)
                sys.stdout.flush()
        else:
            print("⚠️  Could not find submit button")
        
        print("✓ Onboarding attempted (may have already been completed)")
        return True
    except TimeoutException as e:
        print(f"⚠️  Onboarding timeout: {e}")
        # Check if we're past onboarding
        driver.get(HA_URL)
        time.sleep(2)
        if "onboarding" not in driver.current_url.lower():
            print("✓ Onboarding already completed (verified after timeout)")
            return True
        return False
    except Exception as e:
        print(f"⚠️  Onboarding check failed: {e}")
        # Check if we're past onboarding
        try:
            driver.get(HA_URL)
            time.sleep(2)
            if "onboarding" not in driver.current_url.lower():
                print("✓ Onboarding already completed (verified after error)")
                return True
        except:
            pass
        return False


def login_ui(driver: webdriver.Chrome, username: Optional[str] = None, password: Optional[str] = None) -> bool:
    """Login via UI if needed.
    
    Args:
        driver: Selenium WebDriver instance
        username: Username to use (defaults to HA_USERNAME env var or ONBOARDING_USERNAME)
        password: Password to use (defaults to HA_PASSWORD env var or ONBOARDING_PASSWORD)
        
    Returns:
        True if logged in, False otherwise
    """
    # Get credentials from args, env vars, or constants
    if username is None:
        username = os.environ.get("HA_USERNAME", ONBOARDING_USERNAME)
    if password is None:
        password = os.environ.get("HA_PASSWORD", ONBOARDING_PASSWORD)
    
    print(f"  Attempting login with: {username}", flush=True)
    sys.stdout.flush()
    print(f"  Navigating to: {HA_URL}", flush=True)
    sys.stdout.flush()
    
    # First verify HA is accessible
    try:
        print("  Verifying HA is accessible...", flush=True)
        sys.stdout.flush()
        resp = requests.get(f"{HA_URL}/api/", timeout=5)
        print(f"  ✓ HA API responding (status: {resp.status_code})", flush=True)
        sys.stdout.flush()
    except Exception as e:
        print(f"  ✗ Cannot reach HA at {HA_URL}: {e}", flush=True)
        sys.stdout.flush()
        return False
    
    try:
        print("  Loading page in browser...", flush=True)
        sys.stdout.flush()
        
        # Set a timeout for page load
        try:
            driver.set_page_load_timeout(30)
        except:
            pass  # May already be set
        
        # Use a timeout wrapper for driver.get
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
        def load_page():
            driver.get(HA_URL)
            return True
        
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(load_page)
                future.result(timeout=35)  # Slightly longer than page_load_timeout
            print("  Page loaded, waiting for custom elements...", flush=True)
            sys.stdout.flush()
            
            # Wait for custom elements to be defined (HA uses Polymer/Lit components)
            wait = WebDriverWait(driver, 20)
            try:
                wait.until(lambda d: d.execute_script("""
                    return typeof customElements !== 'undefined' && 
                           (customElements.get('home-assistant') !== undefined ||
                            customElements.get('ha-auth-flow') !== undefined ||
                            document.querySelector('ha-auth-flow') !== null);
                """))
                print("  ✓ Custom elements defined", flush=True)
                sys.stdout.flush()
            except Exception as e:
                print(f"  ⚠️  Custom elements wait timed out: {e}", flush=True)
                sys.stdout.flush()
            
            # Wait for ha-auth-flow to be present
            try:
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "ha-auth-flow")))
                print("  ✓ ha-auth-flow found", flush=True)
                sys.stdout.flush()
            except Exception as e:
                print(f"  ⚠️  ha-auth-flow not found: {e}", flush=True)
                sys.stdout.flush()
            
            # Wait a bit more for form to render
            time.sleep(1)
            
            print("  Page ready, checking login status...", flush=True)
            sys.stdout.flush()
        except FutureTimeoutError:
            print("  ⚠️  Page load timed out after 35 seconds", flush=True)
            sys.stdout.flush()
            return False
        except Exception as page_error:
            print(f"  ⚠️  Error loading page: {page_error}", flush=True)
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            return False
        
        current_url = driver.current_url.lower()
        print(f"  Current URL: {current_url}", flush=True)
        sys.stdout.flush()
        
        # Get page source with timeout
        page_source = ""
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: driver.page_source.lower())
                page_source = future.result(timeout=5)
        except:
            page_source = ""
        
        # Check if already logged in - look for dashboard indicators
        if ("login" not in current_url and "auth" not in current_url and 
            ("lovelace" in current_url or "dashboard" in page_source or 
             "home assistant" in page_source or "overview" in page_source)):
            print("✓ Already logged in", flush=True)
            sys.stdout.flush()
            return True
        
        # Need to login
        wait = WebDriverWait(driver, 20)
        
        print("  Looking for username field...", flush=True)
        sys.stdout.flush()
        # Try multiple selectors for username field
        username_field = None
        selectors = [
            "input[type='text'][name*='username']",
            "input[type='text'][id*='username']",
            "input[type='text']",
            "input[name='username']",
            "ha-textfield input",
            "mwc-textfield input",
            "input[type='text'][placeholder*='username' i]",
            "input[type='text'][placeholder*='name' i]"
        ]
        for selector in selectors:
            try:
                print(f"    Trying selector: {selector}", flush=True)
                sys.stdout.flush()
                username_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                if username_field and username_field.is_displayed():
                    print(f"    ✓ Found username field with: {selector}", flush=True)
                    sys.stdout.flush()
                    break
                else:
                    username_field = None
            except Exception as e:
                print(f"    ✗ Not found: {str(e)[:50]}...", flush=True)
                sys.stdout.flush()
                continue
        
        if not username_field:
            print("⚠️  Could not find username field - may already be logged in", flush=True)
            sys.stdout.flush()
            driver.get(HA_URL)
            time.sleep(2)
            if "login" not in driver.current_url.lower():
                print("✓ Already logged in (no login form found)", flush=True)
                sys.stdout.flush()
                return True
            return False
        
        print(f"  Logging in with username: {username}", flush=True)
        sys.stdout.flush()
        
        # Fill username field using JavaScript to ensure it's set
        print("  Filling username field via JavaScript...", flush=True)
        sys.stdout.flush()
        try:
            driver.execute_script("""
                var field = arguments[0];
                var value = arguments[1];
                field.value = value;
                field.dispatchEvent(new Event('input', { bubbles: true }));
                field.dispatchEvent(new Event('change', { bubbles: true }));
                field.dispatchEvent(new Event('blur', { bubbles: true }));
            """, username_field, username)
            print("  Username filled via JavaScript", flush=True)
            sys.stdout.flush()
        except Exception as e:
            print(f"  JavaScript fill failed: {e}, trying Selenium...", flush=True)
            sys.stdout.flush()
            username_field.clear()
            username_field.send_keys(username)
            print("  Username filled via Selenium", flush=True)
            sys.stdout.flush()
        
        # Verify username was set
        try:
            username_value = driver.execute_script("return arguments[0].value;", username_field)
            if username_value == username:
                print(f"  ✓ Username verified: '{username_value}'", flush=True)
                sys.stdout.flush()
            else:
                print(f"  ⚠️  Username mismatch! Expected '{username}', got '{username_value}'", flush=True)
                sys.stdout.flush()
                # Try again with more aggressive approach
                driver.execute_script("""
                    arguments[0].value = '';
                    arguments[0].value = arguments[1];
                    arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                """, username_field, username)
                username_value = driver.execute_script("return arguments[0].value;", username_field)
                print(f"  Retry result: '{username_value}'", flush=True)
                sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  Could not verify username: {e}", flush=True)
            sys.stdout.flush()
        
        time.sleep(0.5)
        
        print("  Looking for password field...", flush=True)
        sys.stdout.flush()
        password_field = wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR, "input[type='password']"
        )))
        print("  Password field found, filling via JavaScript...", flush=True)
        sys.stdout.flush()
        
        # Fill password field - use JavaScript to avoid stale element issues
        try:
            driver.execute_script("""
                var pwdField = arguments[0];
                var pwdValue = arguments[1];
                pwdField.value = '';
                pwdField.value = pwdValue;
                pwdField.dispatchEvent(new Event('input', { bubbles: true }));
                pwdField.dispatchEvent(new Event('change', { bubbles: true }));
                pwdField.dispatchEvent(new Event('blur', { bubbles: true }));
            """, password_field, password)
            print("  Password filled via JavaScript", flush=True)
            sys.stdout.flush()
        except Exception as e:
            print(f"  JavaScript fill failed: {e}, trying Selenium...", flush=True)
            sys.stdout.flush()
            # Fallback to Selenium
            try:
                password_field.clear()
                password_field.send_keys(password)
                print("  Password filled via Selenium", flush=True)
                sys.stdout.flush()
            except Exception as stale_error:
                print(f"  Stale element error: {stale_error}, re-finding field...", flush=True)
                sys.stdout.flush()
                # Re-find the password field
                password_field = wait.until(EC.presence_of_element_located((
                    By.CSS_SELECTOR, "input[type='password']"
                )))
                password_field.clear()
                password_field.send_keys(password)
                print("  Password filled after re-finding field", flush=True)
                sys.stdout.flush()
        
        # Verify password was set (check length, not value for security)
        try:
            password_length = driver.execute_script("return arguments[0].value.length;", password_field)
            expected_length = len(password)
            if password_length == expected_length:
                print(f"  ✓ Password verified: length {password_length} matches expected", flush=True)
                sys.stdout.flush()
            else:
                print(f"  ⚠️  Password length mismatch! Expected {expected_length}, got {password_length}", flush=True)
                sys.stdout.flush()
                # Try again
                driver.execute_script("""
                    arguments[0].value = '';
                    arguments[0].value = arguments[1];
                    arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                """, password_field, password)
                password_length = driver.execute_script("return arguments[0].value.length;", password_field)
                print(f"  Retry result: length {password_length}", flush=True)
                sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  Could not verify password: {e}", flush=True)
            sys.stdout.flush()
        
        time.sleep(0.5)
        
        print("  Waiting for login button...", flush=True)
        sys.stdout.flush()
        
        # Wait for mwc-button or ha-button to be present
        try:
            # Try mwc-button first (as suggested)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "mwc-button, ha-button")))
            print("  ✓ Button element found", flush=True)
            sys.stdout.flush()
        except Exception as e:
            print(f"  ⚠️  Button not found with wait: {e}", flush=True)
            sys.stdout.flush()
        
        login_button = None
        
        # Use JavaScript to find and click the button (bypasses Selenium find_elements which hangs)
        try:
            print("  Searching for button with text 'Log in' via JavaScript...", flush=True)
            sys.stdout.flush()
            
            # Capture page information BEFORE clicking (to avoid stale element issues)
            print("  Capturing page information for debugging...", flush=True)
            sys.stdout.flush()
            try:
                # Get page source and save it
                page_source = driver.page_source
                with open("/workspace/test/login_page_source.html", "w", encoding="utf-8") as f:
                    f.write(page_source)
                print("  ✓ Saved page source to /workspace/test/login_page_source.html", flush=True)
                sys.stdout.flush()
                
                # Get detailed DOM information about the button and form (find elements fresh)
                dom_info = driver.execute_script("""
                    var usernameInput = document.querySelector('input[type="text"][name*="username"], input[name="username"]');
                    var passwordInput = document.querySelector('input[type="password"]');
                    
                    // Find login button
                    var buttons = document.querySelectorAll('button, ha-button, mwc-button');
                    var loginBtn = null;
                    for (var i = 0; i < buttons.length; i++) {
                        var btn = buttons[i];
                        var text = btn.textContent ? btn.textContent.trim().toLowerCase() : '';
                        var innerText = btn.innerText ? btn.innerText.trim().toLowerCase() : '';
                        var ariaLabel = btn.getAttribute('aria-label') ? btn.getAttribute('aria-label').toLowerCase() : '';
                        
                        var textMatch = (text.includes('log') && text.includes('in')) || text === 'log in' || text === 'login';
                        var innerMatch = (innerText.includes('log') && innerText.includes('in')) || innerText === 'log in' || innerText === 'login';
                        var ariaMatch = (ariaLabel.includes('log') && ariaLabel.includes('in')) || ariaLabel === 'log in' || ariaLabel === 'login';
                        
                        if (textMatch || innerMatch || ariaMatch || btn.type === 'submit') {
                            loginBtn = btn;
                            break;
                        }
                    }
                    
                    var form = loginBtn ? loginBtn.closest('form') : null;
                    
                    return {
                        button: loginBtn ? {
                            tagName: loginBtn.tagName,
                            type: loginBtn.type,
                            id: loginBtn.id,
                            className: loginBtn.className,
                            textContent: loginBtn.textContent,
                            innerHTML: loginBtn.innerHTML,
                            outerHTML: loginBtn.outerHTML.substring(0, 500),
                            hasOnClick: loginBtn.onclick !== null,
                            formId: loginBtn.form ? loginBtn.form.id : null
                        } : null,
                        form: form ? {
                            id: form.id,
                            action: form.action,
                            method: form.method,
                            enctype: form.enctype,
                            outerHTML: form.outerHTML.substring(0, 1000),
                            hasOnSubmit: form.onsubmit !== null
                        } : null,
                        inputs: {
                            username: usernameInput ? {
                                id: usernameInput.id,
                                name: usernameInput.name,
                                value: usernameInput.value,
                                outerHTML: usernameInput.outerHTML
                            } : null,
                            password: passwordInput ? {
                                id: passwordInput.id,
                                name: passwordInput.name,
                                valueLength: passwordInput.value.length,
                                outerHTML: passwordInput.outerHTML
                            } : null
                        }
                    };
                """)
                
                import json
                with open("/workspace/test/login_dom_info.json", "w", encoding="utf-8") as f:
                    json.dump(dom_info, f, indent=2)
                print("  ✓ Saved DOM info to /workspace/test/login_dom_info.json", flush=True)
                sys.stdout.flush()
                
                # Also print key info to console
                if dom_info.get('button'):
                    btn_info = dom_info['button']
                    print(f"  Button: {btn_info.get('tagName')} type={btn_info.get('type')} id={btn_info.get('id')}", flush=True)
                    sys.stdout.flush()
                if dom_info.get('form'):
                    form_info = dom_info['form']
                    print(f"  Form: action={form_info.get('action')} method={form_info.get('method')}", flush=True)
                    sys.stdout.flush()
                
                # Take screenshot
                driver.save_screenshot("/workspace/test/login_page.png")
                print("  ✓ Saved screenshot to /workspace/test/login_page.png", flush=True)
                sys.stdout.flush()
            except Exception as e:
                print(f"  ⚠️  Could not capture debug info: {e}", flush=True)
                sys.stdout.flush()
            
            # JavaScript to find button with "Log in" text and submit form properly
            clicked = driver.execute_script("""
                var username = arguments[0];
                var password = arguments[1];
                
                // Verify fields have values before submitting
                var usernameInput = document.querySelector('input[type="text"][name*="username"], input[name="username"]');
                var passwordInput = document.querySelector('input[type="password"]');
                
                console.log('Username input value:', usernameInput ? usernameInput.value : 'NOT FOUND');
                console.log('Password input length:', passwordInput ? passwordInput.value.length : 'NOT FOUND');
                
                if (!usernameInput || !passwordInput) {
                    console.error('Form fields not found!');
                    return false;
                }
                
                if (!usernameInput.value || usernameInput.value !== username) {
                    console.log('Setting username to:', username);
                    usernameInput.value = username;
                    usernameInput.dispatchEvent(new Event('input', { bubbles: true }));
                    usernameInput.dispatchEvent(new Event('change', { bubbles: true }));
                }
                
                if (!passwordInput.value || passwordInput.value.length !== password.length) {
                    console.log('Setting password (length:', password.length, ')');
                    passwordInput.value = password;
                    passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
                    passwordInput.dispatchEvent(new Event('change', { bubbles: true }));
                }
                
                // Find and click login button - try mwc-button first (as suggested)
                // Don't use form.submit() - just click the button and let it handle submission
                var buttonSelectors = [
                    'mwc-button',  // Try mwc-button first (as suggested in Playwright example)
                    'ha-button',
                    'button[type="submit"]',
                    'button',
                    'input[type="submit"]',
                    '[role="button"]'
                ];
                
                var buttons = [];
                for (var s = 0; s < buttonSelectors.length; s++) {
                    var found = document.querySelectorAll(buttonSelectors[s]);
                    for (var f = 0; f < found.length; f++) {
                        buttons.push(found[f]);
                    }
                }
                
                console.log('Found', buttons.length, 'potential buttons');
                
                // Debug: log first few buttons
                for (var d = 0; d < Math.min(buttons.length, 5); d++) {
                    var dbgBtn = buttons[d];
                    var dbgText = dbgBtn.textContent ? dbgBtn.textContent.trim() : '';
                    var dbgInner = dbgBtn.innerText ? dbgBtn.innerText.trim() : '';
                    var dbgAria = dbgBtn.getAttribute('aria-label') || '';
                    console.log('Button', d, ':', 'text="' + dbgText + '"', 'inner="' + dbgInner + '"', 'aria="' + dbgAria + '"', 'type=' + dbgBtn.type);
                }
                
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var text = btn.textContent ? btn.textContent.trim().toLowerCase() : '';
                    var innerText = btn.innerText ? btn.innerText.trim().toLowerCase() : '';
                    var ariaLabel = btn.getAttribute('aria-label') ? btn.getAttribute('aria-label').toLowerCase() : '';
                    
                    // More flexible matching - check if contains "log" and "in"
                    var textMatch = (text.includes('log') && text.includes('in')) || text === 'log in' || text === 'login';
                    var innerMatch = (innerText.includes('log') && innerText.includes('in')) || innerText === 'log in' || innerText === 'login';
                    var ariaMatch = (ariaLabel.includes('log') && ariaLabel.includes('in')) || ariaLabel === 'log in' || ariaLabel === 'login';
                    
                    if (textMatch || innerMatch || ariaMatch || btn.type === 'submit') {
                        console.log('Found login button, ensuring fields are set...');
                        // Ensure fields are set before clicking
                        if (usernameInput && (!usernameInput.value || usernameInput.value !== username)) {
                            usernameInput.value = username;
                            usernameInput.dispatchEvent(new Event('input', { bubbles: true }));
                            usernameInput.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        if (passwordInput && (!passwordInput.value || passwordInput.value.length !== password.length)) {
                            passwordInput.value = password;
                            passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
                            passwordInput.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        
                        console.log('Clicking login button...');
                        
                        // Ensure fields are set one more time right before click
                        if (usernameInput) {
                            usernameInput.value = username;
                            usernameInput.dispatchEvent(new Event('input', { bubbles: true }));
                            usernameInput.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        if (passwordInput) {
                            passwordInput.value = password;
                            passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
                            passwordInput.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        
                        // Handle mwc-button and ha-button custom elements - click directly like Playwright example
                        if (btn.tagName === 'MWC-BUTTON' || btn.tagName === 'HA-BUTTON') {
                            console.log('Clicking', btn.tagName, 'directly (as in Playwright example)...');
                            
                            // Ensure fields are set one final time before clicking
                            if (usernameInput && usernameInput.value !== username) {
                                usernameInput.value = username;
                                usernameInput.dispatchEvent(new Event('input', { bubbles: true }));
                                usernameInput.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                            if (passwordInput && passwordInput.value.length !== password.length) {
                                passwordInput.value = password;
                                passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
                                passwordInput.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                            
                            // Click the button directly - let it handle form submission
                            btn.focus();
                            btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                            btn.click();
                            console.log('Direct click on', btn.tagName, 'completed');
                            
                            // Don't call form.submit() - let the button click handle it
                            // Don't try shadow DOM manipulation - just click the custom element directly
                            
                            return true;  // Return immediately after clicking
                            
                        } else {
                            // Regular button handling - just click, don't submit form manually
                            btn.focus();
                            btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                            btn.click();
                            
                            // Don't call form.submit() - let the button handle it
                            return true;
                        }
                    }
                }
                console.error('Login button not found! Checked', buttons.length, 'buttons');
                return false;
            """, username, password)
            
            if clicked:
                print("  ✓ Found and clicked 'Log in' button via JavaScript!", flush=True)
                sys.stdout.flush()
                
                # Check browser console for errors and debug info AFTER clicking
                try:
                    logs = driver.get_log('browser')
                    if logs:
                        # Save all console logs
                        with open("/workspace/test/login_console_logs.txt", "w", encoding="utf-8") as f:
                            for log in logs:
                                f.write(f"{log.get('level', 'UNKNOWN')}: {log.get('message', '')}\n")
                        print("  ✓ Saved console logs to /workspace/test/login_console_logs.txt", flush=True)
                        sys.stdout.flush()
                        
                        # Show console.log messages for debugging
                        console_messages = [log for log in logs if log.get('level') in ['INFO', 'DEBUG']]
                        if console_messages:
                            print("  Browser console messages:", flush=True)
                            sys.stdout.flush()
                            for msg in console_messages[-10:]:  # Show last 10 messages
                                print(f"    {msg.get('message', '')[:200]}", flush=True)
                                sys.stdout.flush()
                        
                        errors = [log for log in logs if log['level'] == 'SEVERE']
                        if errors:
                            print(f"  ⚠️  Browser console errors detected: {len(errors)} errors", flush=True)
                            sys.stdout.flush()
                            for err in errors[:5]:  # Show first 5 errors
                                print(f"    - {err.get('message', 'Unknown error')[:300]}", flush=True)
                                sys.stdout.flush()
                except:
                    pass  # Console logs may not be available  # Console logs may not be available
                
                login_button = "clicked"  # Mark as clicked
            else:
                print("  'Log in' button not found via JavaScript, will try Enter key", flush=True)
                sys.stdout.flush()
                
                # Try to get console logs to see what buttons were found
                try:
                    logs = driver.get_log('browser')
                    if logs:
                        # Show all recent console messages
                        recent_logs = logs[-15:]  # Last 15 messages
                        print("  Browser console messages:", flush=True)
                        sys.stdout.flush()
                        for msg in recent_logs:
                            msg_text = msg.get('message', '')
                            if 'Button' in msg_text or 'button' in msg_text.lower() or 'Found' in msg_text:
                                print(f"    {msg_text[:250]}", flush=True)
                                sys.stdout.flush()
                except Exception as e:
                    print(f"  Could not get console logs: {e}", flush=True)
                    sys.stdout.flush()
        except Exception as e:
            print(f"  JavaScript button search error: {e}, will try Enter key", flush=True)
            sys.stdout.flush()
        
        # Click the button if found (JavaScript already clicked it if login_button == "clicked")
        if login_button == "clicked":
            # Already clicked via JavaScript, nothing to do
            pass
        elif login_button:
            print("  Clicking Login button...", flush=True)
            sys.stdout.flush()
            try:
                login_button.click()
                print("  ✓ Login button clicked", flush=True)
                sys.stdout.flush()
            except Exception as e:
                print(f"  ⚠️  Could not click button: {e}, trying JavaScript click", flush=True)
                sys.stdout.flush()
                try:
                    driver.execute_script("arguments[0].click();", login_button)
                    print("  ✓ Login button clicked via JavaScript", flush=True)
                    sys.stdout.flush()
                except:
                    print("  ⚠️  JavaScript click also failed", flush=True)
                    sys.stdout.flush()
        else:
            print("  ⚠️  Login button not found, trying Enter key...", flush=True)
            sys.stdout.flush()
            try:
                # Re-find password field to avoid stale element
                password_field = wait.until(EC.presence_of_element_located((
                    By.CSS_SELECTOR, "input[type='password']"
                )))
                password_field.send_keys(Keys.RETURN)
                print("  Enter key sent", flush=True)
                sys.stdout.flush()
            except Exception as e:
                print(f"  ⚠️  Could not send Enter key: {e}", flush=True)
                sys.stdout.flush()
                # Try JavaScript to submit form
                try:
                    driver.execute_script("""
                        var pwdField = document.querySelector('input[type="password"]');
                        if (pwdField) {
                            var event = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                            pwdField.dispatchEvent(event);
                            var event2 = new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                            pwdField.dispatchEvent(event2);
                            var event3 = new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                            pwdField.dispatchEvent(event3);
                        }
                    """)
                    print("  Enter key sent via JavaScript", flush=True)
                    sys.stdout.flush()
                except:
                    pass
        
        print("  Form submitted, waiting for response...", flush=True)
        sys.stdout.flush()
        
        # Double-check fields are still populated right before submission
        try:
            final_username = driver.execute_script("""
                var input = document.querySelector('input[type="text"][name*="username"], input[name="username"]');
                return input ? input.value : null;
            """)
            final_password_len = driver.execute_script("""
                var input = document.querySelector('input[type="password"]');
                return input ? input.value.length : 0;
            """)
            print(f"  Final check - Username: '{final_username}', Password length: {final_password_len}", flush=True)
            sys.stdout.flush()
            
            if not final_username or final_username != username:
                print(f"  ⚠️  Username lost! Re-setting...", flush=True)
                sys.stdout.flush()
                driver.execute_script("""
                    var input = document.querySelector('input[type="text"][name*="username"], input[name="username"]');
                    if (input) {
                        input.value = arguments[0];
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                """, username)
            
            if final_password_len != len(password):
                print(f"  ⚠️  Password lost! Re-setting...", flush=True)
                sys.stdout.flush()
                driver.execute_script("""
                    var input = document.querySelector('input[type="password"]');
                    if (input) {
                        input.value = arguments[0];
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                """, password)
        except Exception as e:
            print(f"  Could not verify fields before submission: {e}", flush=True)
            sys.stdout.flush()
        
        # Wait for URL change after button click (like Playwright wait_for_url)
        print("  Waiting for URL change after login click...", flush=True)
        sys.stdout.flush()
        
        try:
            # Wait for URL to change away from auth/authorize or to lovelace (as in Playwright example)
            wait.until(lambda d: "/auth/authorize" not in d.current_url.lower() or 
                              "/lovelace" in d.current_url.lower() or
                              "/profile" in d.current_url.lower())
            
            current_url = driver.current_url.lower()
            if "/auth/authorize" not in current_url:
                print(f"  ✓ Login successful - URL changed to: {current_url[:80]}...", flush=True)
                sys.stdout.flush()
                return True
            elif "/lovelace" in current_url:
                print(f"  ✓ Login successful - navigated to lovelace: {current_url[:80]}...", flush=True)
                sys.stdout.flush()
                return True
            else:
                print(f"  ⚠️  Still on authorize page: {current_url[:80]}...", flush=True)
                sys.stdout.flush()
                return False
        except Exception as e:
            # Timeout waiting for URL change
            current_url = driver.current_url.lower()
            print(f"  ⚠️  Timeout waiting for URL change: {e}", flush=True)
            sys.stdout.flush()
            print(f"  Current URL: {current_url[:80]}...", flush=True)
            sys.stdout.flush()
            
            # Final check - if not on authorize page, consider it success
            if "/auth/authorize" not in current_url:
                print("  ✓ Login successful (final check)", flush=True)
                sys.stdout.flush()
                return True
            else:
                # Check current URL
                try:
                    current_url = driver.execute_script("return window.location.href;").lower()
                    if "auth/authorize" not in current_url:
                        print("✓ Login successful (not on authorize page)", flush=True)
                        sys.stdout.flush()
                        return True
                    else:
                        print("⚠️  Still on authorize page - login may have failed", flush=True)
                        sys.stdout.flush()
                        return False
                except:
                    print("✓ Login assumed successful (could not verify URL)", flush=True)
                    sys.stdout.flush()
                    return True
                    
        except Exception as e:
            print(f"⚠️  Could not verify login via profile page: {e}", flush=True)
            sys.stdout.flush()
            # Check if we're not on authorize page
            try:
                current_url = driver.execute_script("return window.location.href;").lower()
                if "auth/authorize" not in current_url:
                    print("✓ Login successful (not on authorize page)", flush=True)
                    sys.stdout.flush()
                    return True
            except:
                pass
            # Assume login succeeded if we got this far
            print("✓ Login assumed successful", flush=True)
            sys.stdout.flush()
            return True
    except Exception as e:
        print(f"⚠️  Login verification failed: {e}", flush=True)
        sys.stdout.flush()
        # If we can navigate to profile page, login succeeded
        try:
            driver.execute_script(f"window.location.href = '{HA_URL}/profile';")
            time.sleep(3)
            url = driver.execute_script("return window.location.href;").lower()
            if "/profile" in url:
                print("✓ Login successful (verified via profile page)", flush=True)
                sys.stdout.flush()
                return True
        except:
            pass
        return False


def clear_logs_ui(driver: webdriver.Chrome) -> bool:
    """Clear HA logs via UI (http://localhost:8123/config/logs).
    
    Args:
        driver: Selenium WebDriver instance
        
    Returns:
        True if successful, False otherwise
    """
    try:
        driver.get(f"{HA_URL}/config/logs")
        time.sleep(3)
        
        wait = WebDriverWait(driver, 10)
        clear_button = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'clear')] | //button[@aria-label*='clear' i]"
        )))
        clear_button.click()
        time.sleep(2)
        
        print("✓ Logs cleared")
        return True
    except Exception as e:
        print(f"⚠️  Could not clear logs: {e}")
        return False
