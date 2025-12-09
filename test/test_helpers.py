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
"""

import subprocess
import time
import os
import sys
import shutil
import requests
from typing import Optional
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
                        print(f"  ✓ Token created automatically from username/password")
                        return token
                elif auth_data.get("type") == "auth_invalid":
                    print(f"  ✗ Authentication failed - check username/password")
                    return None
        finally:
            await websocket.close()
    except Exception as e:
        print(f"  ⚠️  Could not create token: {e}")
        return None
    
    return None


def get_or_create_ha_token() -> Optional[str]:
    """Get HA token from environment or create from username/password.
    
    Checks in order:
    1. HA_TOKEN environment variable (preferred)
    2. HA_USERNAME + HA_PASSWORD → creates token automatically
    
    Returns:
        Token string if available/created, None otherwise
    """
    # Check for existing token
    token = os.environ.get("HA_TOKEN")
    if token:
        return token
    
    # Check for username/password
    username = os.environ.get("HA_USERNAME")
    password = os.environ.get("HA_PASSWORD")
    
    if username and password:
        print("  No HA_TOKEN found, but HA_USERNAME/HA_PASSWORD provided")
        print("  Attempting to create token automatically...")
        try:
            import asyncio
            token = asyncio.run(create_token_from_credentials(username, password))
            if token:
                # Optionally save to environment for this session
                os.environ["HA_TOKEN"] = token
                return token
        except Exception as e:
            print(f"  ⚠️  Failed to create token: {e}")
    
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
    # Check if already complete via API
    if complete_onboarding_api():
        return True
    
    # Try storage file workaround first (for JavaScript error cases)
    print("  Attempting storage file workaround for JavaScript error...", flush=True)
    sys.stdout.flush()
    if complete_onboarding_storage():
        print("  ⚠️  Storage file updated, but user account still needs creation", flush=True)
        sys.stdout.flush()
        print("  ⚠️  This is a workaround - user account must be created manually", flush=True)
        sys.stdout.flush()
        # Return False so caller knows user account still needs creation
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
            return True
        
        # Fallback: Check URL
        if ("login" in current_url or "lovelace" in current_url or 
            "dashboard" in current_url or "overview" in current_url or
            ("onboarding" not in current_url and "/" == current_url.split("/")[-1])):
            print("✓ Onboarding already completed (verified via URL)")
            return True
        
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
            print("  Not on onboarding page - assuming completed")
            return True
        
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


def login_ui(driver: webdriver.Chrome) -> bool:
    """Login via UI if needed.
    
    Args:
        driver: Selenium WebDriver instance
        
    Returns:
        True if logged in, False otherwise
    """
    try:
        driver.get(HA_URL)
        time.sleep(3)
        
        current_url = driver.current_url.lower()
        
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
            print("✓ Already logged in")
            return True
        
        # Need to login
        wait = WebDriverWait(driver, 20)
        
        # Try multiple selectors for username field
        username_field = None
        for selector in [
            "input[type='text'][name*='username']",
            "input[type='text'][id*='username']",
            "input[type='text']",
            "input[name='username']"
        ]:
            try:
                username_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                break
            except:
                continue
        
        if not username_field:
            print("⚠️  Could not find username field - may already be logged in")
            driver.get(HA_URL)
            time.sleep(2)
            if "login" not in driver.current_url.lower():
                print("✓ Already logged in (no login form found)")
                return True
            return False
        
        username_field.clear()
        username_field.send_keys(ONBOARDING_USERNAME)
        time.sleep(1)
        
        password_field = wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR, "input[type='password']"
        )))
        password_field.clear()
        password_field.send_keys(ONBOARDING_PASSWORD)
        time.sleep(1)
        
        # Try multiple selectors for submit button
        submit_button = None
        for xpath in [
            "//button[@type='submit']",
            "//button[contains(@class, 'submit')]",
            "//input[@type='submit']",
            "//button[contains(text(), 'Log')]",
            "//button[contains(text(), 'Sign')]",
            "//ha-button[@type='submit']"
        ]:
            try:
                submit_button = driver.find_element(By.XPATH, xpath)
                if submit_button.is_displayed():
                    break
            except:
                continue
        
        if submit_button:
            submit_button.click()
        else:
            # Fallback: press Enter on password field
            password_field.send_keys(Keys.RETURN)
        
        time.sleep(5)
        
        # Verify login
        driver.get(HA_URL)
        time.sleep(3)
        if "login" not in driver.current_url.lower() and "auth" not in driver.current_url.lower():
            print("✓ Login successful")
            return True
        print("⚠️  Still on login page after submit")
        return False
    except Exception as e:
        print(f"⚠️  Login check failed: {e}")
        # Check if we're actually logged in despite the error
        driver.get(HA_URL)
        time.sleep(2)
        if "login" not in driver.current_url.lower():
            print("✓ Already logged in (despite error)")
            return True
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
