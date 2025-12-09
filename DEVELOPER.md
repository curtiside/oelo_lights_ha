# Developer Guide

Development and testing tools for Oelo Lights Home Assistant integration.

## Quick Start

```bash
make setup && make start
# Complete onboarding in browser: http://localhost:8123
# Configure .env.test with credentials
make test-all
```

**Test-Fix-Retest Cycle:**
- After code changes: `make restart && make test-all`
- After test changes: `make test-all`
- After Dockerfile changes: `make build && make test-all`

See `Makefile` for commands.

## Cleanup

When done testing, stop or remove containers:

```bash
# Stop container (keeps config for next time)
make stop

# Full cleanup (removes container and config)
make clean
```

See [Cleanup When Done Testing](#cleanup-when-done-testing) section for details.

## Testing Architecture

Tests use a **locally running HA container** approach:
- User manually starts HA container (persists between runs)
- User completes onboarding manually (one-time setup)
- Tests connect to existing HA instance
- Tests focus on integration functionality, not HA setup

### Benefits

- **Faster**: No container startup/onboarding wait time
- **More Reliable**: No fragile onboarding automation
- **Better DX**: HA persists, can inspect/debug state
- **Flexible**: Test against different HA versions/configs

## Test Setup (One-Time)

### 1. Start HA Container

```bash
make start
# OR
make setup && make start
```

Wait for HA to be ready:
```bash
make logs
# Wait for "Home Assistant has started"
# Press Ctrl+C to exit log view
```

### 2. Complete Onboarding

Open browser: http://localhost:8123

Complete onboarding wizard:
- Create user account (e.g., `test_user` / `test_password_123`)
- Complete location setup
- Skip analytics (optional)

**Important:** After completing onboarding, you should be automatically logged in. If you see authentication warnings in logs but can access the UI, that's normal - the warnings are from the browser's authentication attempts.

**Save credentials** for tests.

### 3. Configure Test Credentials

**Option A: Username/Password (Recommended - Auto-creates Token)**

The `.env.test` file is checked into git with example values. Update it with your credentials:

```bash
# Edit .env.test and set:
HA_USERNAME=test_user
HA_PASSWORD=test_password_123
CONTROLLER_IP=your_oelo_controller_ip  # ⚠️ IMPORTANT: Change this to your Oelo controller IP
```

**Important:** You must update `CONTROLLER_IP` in `.env.test` to match your Oelo controller's IP address. The default value (`10.16.52.41`) is an example and will not work unless it matches your controller.

**Token Creation:** Tests will automatically create a long-lived access token from `HA_USERNAME` and `HA_PASSWORD` via WebSocket API. This happens automatically when tests need API access - you don't need to manually create a token if you provide username/password credentials.

**Option B: Manual Token Creation**

1. Ensure you're logged in to Home Assistant (http://localhost:8123)
2. Click your profile icon (bottom left)
3. Scroll down to **Long-Lived Access Tokens**
4. Click **Create Token**
5. Enter a name (e.g., "Test Token")
6. Click **OK**
7. **Copy the token immediately** (it's only shown once)
8. Update `.env.test`:

```bash
# Edit .env.test and uncomment/update:
HA_TOKEN=eyJ0eXAiOiJKV1QiLCJhbGc...
# Comment out HA_USERNAME and HA_PASSWORD if using token
# ⚠️ IMPORTANT: Also update CONTROLLER_IP to your Oelo controller IP
```

**Where credentials are stored:**
- `.env.test` file in project root (checked into git with example values)
- **Important:** Update `CONTROLLER_IP` in `.env.test` to match your Oelo controller's IP address
- Update with your local test credentials (username/password or token)
- Or set as environment variables before running tests (overrides `.env.test`)

**Note:** You may see warnings in HA logs like:
```
Login attempt or request with invalid authentication from localhost. Requested URL: '/auth/token'
```
These are **normal and harmless** - they occur when the browser checks for authentication tokens. As long as you can access the UI and create tokens, you can safely ignore these warnings.

### 4. Fix Configuration Files (If Needed)

If HA is in recovery mode due to missing config files:

```bash
# Check configuration.yaml for missing includes
make exec CMD='cat /config/configuration.yaml'

# Create missing files (empty files are OK)
make exec CMD='cd /config && touch automations.yaml scenes.yaml scripts.yaml groups.yaml'

# Restart HA
make restart
```

### 5. Verify Integration Installed

Integration should be in `/config/custom_components/oelo_lights/` (mounted from `./custom_components`).

If not, copy manually:
```bash
cp -r custom_components/oelo_lights config/custom_components/
```

Restart HA:
```bash
make restart
```

Or use make setup to copy files:
```bash
make setup
```

## Running Tests

### First-Time Setup

**Build the test container:**
```bash
make build
```

This builds the test runner container with all dependencies (Selenium, ChromeDriver, Python packages). 

**Note:** `make test-all` will automatically build the test container if it doesn't exist, but it's recommended to run `make build` explicitly first to ensure it's up-to-date. You only need to rebuild if you modify `test/Dockerfile.test` or need to update dependencies.

### Environment Variables

Tests accept configuration via environment variables or command-line arguments:

```bash
# Required
HA_URL=http://localhost:8123          # HA instance URL
CONTROLLER_IP=10.16.52.41             # Oelo controller IP

# Authentication (choose one):
HA_TOKEN=<long-lived-token>            # Pre-created token (preferred)
# OR
HA_USERNAME=test_user                 # Username (tests auto-create token)
HA_PASSWORD=test_password_123         # Password (tests auto-create token)
```

**Credential Storage:**
- `.env.test` file in project root (checked into git with example values)
- **Important:** Update `CONTROLLER_IP` in `.env.test` to match your Oelo controller's IP address
- Update with your local test credentials (username/password or token)

**Automatic Token Creation:**
- If `HA_USERNAME` and `HA_PASSWORD` are provided, tests automatically create `HA_TOKEN` via WebSocket API
- This happens automatically when tests need API access - no manual token creation needed
- The token is created on-demand and cached in the environment for the test session
- Works as long as the user account exists and credentials are correct

### Test Categories

1. **Unit Tests** (`test_integration.py`, `test_workflow.py`)
   - No HA dependency
   - Run fast, no container needed
   - Test core logic
   - If using API: Auto-creates token from `HA_USERNAME`/`HA_PASSWORD` if `HA_TOKEN` not provided

2. **Integration Tests** (`test_user_workflow.py`)
   - Requires running HA
   - Primarily UI-based (Selenium), doesn't require tokens
   - Tests device configuration via UI
   - Tests pattern workflow via UI

### Running Tests

**Load environment variables:**
```bash
source .env.test
```

**Run all tests:**
```bash
make test-all
# OR
python3 test/run_all_tests.py
```

**Run unit tests (no HA needed):**
```bash
python3 test/test_integration.py
python3 test/test_workflow.py
```

**Run integration tests (requires HA):**
```bash
python3 test/test_user_workflow.py \
  --ha-url http://localhost:8123 \
  --ha-token $HA_TOKEN \
  --controller-ip 10.16.52.41 \
  [--skip-patterns] \
  [--keep-container]
```

**Watch browser during tests:**
```bash
# Terminal 1: Run tests
make test-all

# Terminal 2: Watch browser (auto-opens Chrome DevTools)
make watch

# Or with custom options
python3 test/watch_browser.py --interval 0.5 --screenshots --open-devtools
```

**Run with command-line args:**
```bash
python3 test/test_user_workflow.py \
  --ha-url http://localhost:8123 \
  --ha-token <token> \
  --controller-ip 10.16.52.41
```

## Test Structure

All test files and test infrastructure in `test/` directory. See inline documentation:

```bash
head -100 test/test_integration.py
head -100 test/test_workflow.py
head -100 test/test_user_workflow.py
head -100 test/test_helpers.py
```

### Test Files

**Core Test Scripts:**
- **test_integration.py** - Fast unit tests (no UI, no container)
  - Controller connectivity, imports, config flow validation, pattern utils, services, storage

- **test_workflow.py** - Pattern logic unit tests (no UI, no container)
  - Pattern capture/rename/apply logic validation

- **test_user_workflow.py** - Complete end-to-end test (container + UI)
  - Container management, onboarding, HACS installation (automated via Docker), integration installation (from curtiside/oelo_lights_ha), device configuration, pattern workflow

- **test_helpers.py** - Shared helper functions
  - Container management, HA readiness checks, browser automation, UI interactions

- **run_all_tests.py** - Master test runner
  - Executes all tests in correct order

**Test Infrastructure:**
- **Dockerfile.test** - Test runner container image
- **setup_automated.sh** - Automated setup script
- **setup_with_browser.py** - Browser-based setup helper
- **create_token.py** - Create HA access token helper
- **create_token_browser.py** - Browser-based token creation
- **install_chromedriver.sh** - ChromeDriver installation script

**Test Utilities:**
- **test_add_card.py** - Card addition test
- **test_full_setup.py** - Full setup test
- **run_full_ui_tests.py** - Full UI test suite

**Test Output Files** (gitignored, created during test runs):
- `test_output.log` - Test execution log
- `onboarding_*.json` - Onboarding diagnostic files
- `onboarding_*.html` - Onboarding page source
- `onboarding_*.png` - Onboarding screenshots

## Test Setup and Cleanup

Tests are **idempotent** and **rerunnable** - they work correctly even if:
- Previous test run failed partway through
- Test artifacts already exist
- Tests are interrupted (Ctrl+C, crash, timeout)

### Core Principles

1. **Pre-test Cleanup**: Remove any leftover test artifacts before starting
2. **State Detection**: Check what exists before creating/modifying
3. **Idempotent Operations**: All operations can be safely repeated
4. **Post-test Cleanup**: Always clean up, even on failure (use `finally` blocks)
5. **Error Recovery**: Handle partial failures gracefully

### Test Lifecycle

```
1. Pre-Test Cleanup
   ↓ Detect existing test artifacts
   ↓ Remove devices/entities/configs
   
2. State Verification
   ↓ Check HA is running
   ↓ Verify authentication
   ↓ Verify integration installed
   
3. Test Setup
   ↓ Create test devices
   ↓ Configure test entities
   
4. Run Tests
   ↓ Execute test cases
   
5. Post-Test Cleanup (finally)
   ↓ Remove test devices
   ↓ Clean up entities
   ↓ Verify cleanup complete
```

### Test Artifact Naming

All test artifacts use consistent prefix `test_oelo_`:
- Devices: `test_oelo_zone_{zone_id}`
- Entities: `test_oelo_light.zone_{zone_id}`
- Configs: `test_oelo_pattern_{pattern_name}`

This makes cleanup easy - find all artifacts with prefix and remove in bulk.

### Example Test Pattern

```python
def test_device_add(ha_client, controller_ip):
    device_id = None
    try:
        # Pre-test: Clean up leftovers
        cleanup_test_devices(ha_client)
        
        # Setup: Create device
        device_id = add_test_device(ha_client, controller_ip)
        
        # Test: Verify device
        assert verify_device_exists(ha_client, device_id)
        
    finally:
        # Post-test: Always clean up
        if device_id:
            remove_device(ha_client, device_id)
```

See `test/test_helpers.py` for cleanup helper functions.

## Development Environment

### Test-Fix-Retest Workflow

**After making code or test changes:**

**1. Integration code changes** (`custom_components/oelo_lights/`):
```bash
make restart          # Restart HA to pick up code changes
make test-all         # Run tests
```

**2. Test code changes** (`test/` directory):
```bash
make test-all         # Tests are mounted, no rebuild needed
```

**3. Dockerfile changes** (`test/Dockerfile.test`):
```bash
make build            # Rebuild test container
make test-all         # Run tests
```

**Quick retest (skip HACS/integration installation):**
```bash
make restart          # Restart HA (if code changed)
python3 test/run_all_tests.py  # Or run specific test
# OR with skip flags:
docker-compose run --rm test python3 -u /tests/test_user_workflow.py --skip-hacs --skip-patterns
```

**Note:** 
- Integration code is mounted read-only, so changes are immediately available
- Test code is mounted read-only, so changes are immediately available
- HA needs restart to reload integration code changes
- Test container only needs rebuild if Dockerfile or dependencies change

### Updating Integration Code

After code changes:
1. HACS: Redownload integration (HACS → Integrations → oelo_lights_ha → Redownload)
2. Restart HA or Reload integration (Settings → Devices & Services → oelo_lights_ha → Reload)

**For local testing (faster):**
```bash
make restart          # Restart HA container to pick up changes
make test-all         # Run tests
```

### Docker Setup

Uses Docker Compose for local HA testing. See `docker-compose.yml`.

**All operations via Makefile** - No need to use `docker-compose` directly:

**Container Management:**
- `make start` - Start containers
- `make stop` - Stop containers  
- `make restart` - Restart containers
- `make status` or `make ps` - Check container status
- `make logs` - View logs (follow mode)
- `make shell` - Open shell in container
- `make exec CMD='...'` - Execute command in container
- `make build` - Build test container image
- `make clean` - Remove containers and optionally config

See `make help` for all available commands.

**Services:**
- `homeassistant` - HA container (user manages lifecycle)
- `test` - Test runner container (runs tests)

**Volumes:**
- `./config:/config` - HA configuration (persists)
- `./custom_components:/config/custom_components:ro` - Integration code (read-only)

### Makefile Commands

- `make setup` - Copy integration and test files to `config/`
- `make start` - Start HA container
- `make stop` - Stop container
- `make restart` - Restart container
- `make logs` - View HA logs
- `make clean` - Remove container and optionally `config/` directory
- `make test` - Quick test (setup, start, check logs)
- `make test-all` - Run all tests

### Viewing Browser During Tests

There are several ways to see what's happening in the browser during test execution:

### Option 1: Automated Browser Monitor (Easiest)

Use the `watch_browser.py` script to automatically monitor the browser:

```bash
# Terminal 1: Run tests
make test-all

# Terminal 2: Watch browser (auto-opens Chrome DevTools)
make watch
```

The script will:
- Automatically detect when Chrome remote debugging is available
- Show browser tabs, URLs, and titles in real-time
- Optionally open Chrome DevTools automatically
- Optionally take screenshots at state changes

**Manual Chrome Remote Debugging:**

If you prefer manual connection:

1. **Start the test** (it will run in headless mode):
   ```bash
   make test-all
   ```

2. **Open Chrome** on your host machine and navigate to:
   ```
   chrome://inspect
   ```

3. **Click "Open dedicated DevTools for Node"** or look for the remote target under "Remote Target"

4. You'll see the browser window and can interact with it in real-time

**Note:** The test container exposes port 9222, so Chrome on your host can connect to `localhost:9222`.

### Option 2: Non-Headless Mode with Screenshots

Run the test with browser visible and take screenshots:

```bash
# Run test with visible browser (requires Xvfb in container)
docker-compose run --rm test python3 -u /tests/test_user_workflow.py --no-headless --screenshots --skip-hacs --skip-patterns

# Screenshots will be saved to test/screenshot_*.png
```

**Note:** Non-headless mode requires Xvfb (already installed in test container). The browser runs in a virtual display that you can't directly see, but screenshots capture the state.

### Option 3: Screenshots Only (Headless)

Take screenshots without running in non-headless mode:

```bash
docker-compose run --rm test python3 -u /tests/test_user_workflow.py --screenshots --skip-hacs --skip-patterns
```

Screenshots are saved to `test/screenshot_*.png` at key test steps (e.g., after login).

### Troubleshooting Browser Viewing

- **Chrome remote debugging not showing targets**: Ensure port 9222 is accessible and the test is running
- **Non-headless mode fails**: Xvfb should start automatically, but check container logs if issues occur
- **Screenshots not saving**: Check that `/workspace/test/` is writable in the container

## Cleanup When Done Testing

**Stop container (keeps config/data):**
```bash
make stop
```

**Check container status:**
```bash
make status
# OR
make ps
```

**View logs:**
```bash
make logs
# Press Ctrl+C to exit
```

**Open shell in container:**
```bash
make shell
```

**Execute command in container:**
```bash
make exec CMD='ls -la /config'
make exec CMD='cat /config/configuration.yaml'
```

**Full cleanup (remove container and config):**
```bash
make clean
# Prompts to remove config directory
```

**Build test container:**
```bash
make build
```

**When to run `make build`:**
- **First time setup** - Builds the test container image (required before running tests)
- **After modifying `test/Dockerfile.test`** - Rebuilds with your changes
- **After updating dependencies** - If you change Python packages or system packages in Dockerfile
- **If test container was removed** - Docker Compose will auto-build on first run, but explicit build ensures it's up-to-date

**Note:** The `homeassistant` service uses a pre-built image and doesn't need building. Only the `test` service needs building.

**What gets removed:**
- Container: `ha-test` (homeassistant service)
- Container: `ha-test-runner` (test service, if running)
- Config directory: `./config/` (if you choose to remove it)
  - Contains: HA configuration, `.storage/`, `custom_components/`, etc.

**What persists (unless explicitly removed):**
- Docker images: `ghcr.io/home-assistant/home-assistant:stable` (reused on next start)
- Built test image: `oelo_lights_ha-test` (reused on next test run)
- Config directory: `./config/` (unless removed with `make clean` or manually)

## Troubleshooting

### HA Not Accessible

```bash
# Check container status
make status

# Check logs
make logs

# Restart container
make restart
```

### Authentication Warnings (Normal)

**Common Warning:**
```
Login attempt or request with invalid authentication from localhost (127.0.0.1). 
Requested URL: '/auth/token'
```

**This is normal and harmless.** These warnings occur when:
- Browser automatically attempts to authenticate
- Browser checks for existing session tokens
- HA's authentication system logs all token endpoint access attempts

**When to ignore:**
- ✅ You can access HA UI (http://localhost:8123)
- ✅ You can log in successfully
- ✅ You can navigate the dashboard
- ✅ You can create long-lived access tokens

**When to investigate:**
- ❌ You cannot log in
- ❌ You cannot access protected pages
- ❌ Token creation fails
- ❌ Tests fail with authentication errors

**If warnings persist but everything works:**
- These are informational logs, not errors
- HA's ban system logs all authentication attempts for security
- No action needed if functionality is normal

### Authentication Fails (Actual Issues)

**Symptoms:**
- Cannot log in via browser
- Cannot create long-lived access token
- Tests fail with authentication errors
- 401 Unauthorized errors in API calls

**Solutions:**
- **Must be logged in**: You must be logged in via browser before creating a token
- **Complete onboarding first**: Ensure onboarding is complete and you've created a user account
- **Verify token is valid**: If using existing token, check it hasn't expired
- **Check username/password**: If using username/password auth, verify credentials are correct
- **Clear browser cache**: If authentication issues persist, try clearing browser cache/cookies
- **Check HA logs**: Look for actual errors (not just warnings) using `make logs`

### Integration Not Found

- Verify integration is in `/config/custom_components/oelo_lights/`
- Check HA logs for import errors
- Restart HA after copying integration

### Dashboard in Recovery Mode

**Symptoms:**
- Overview dashboard shows "Recovery Mode" message
- Dashboard fails to load
- Error message about invalid configuration

**Common Causes:**

1. **Missing configuration files** (most common):
   - `configuration.yaml` references files that don't exist
   - Example: `!include automations.yaml` but file is missing

2. **Invalid dashboard configuration:**
   - Integration tried to add card but created invalid config
   - Dashboard configuration file is corrupted

3. **Card resource not registered:**
   - Card JavaScript file not found
   - Resource not registered in Lovelace

**Solutions:**

1. **Check HA logs for specific error:**
   ```bash
   make logs | grep -i "error\|recovery\|failed" | tail -20
   ```

2. **Fix missing configuration files:**
   ```bash
   # Check what files are referenced
   make exec CMD='cat /config/configuration.yaml'
   
   # Create missing files (empty files are OK)
   make exec CMD='touch /config/automations.yaml /config/scenes.yaml /config/scripts.yaml'
   
   # Or remove references from configuration.yaml
   make exec CMD='sed -i "/!include.*automations.yaml/d" /config/configuration.yaml'
   
   # Restart HA
   make restart
   ```

3. **Reset dashboard to default:**
   - Go to: http://localhost:8123/config/lovelace/dashboards
   - Click on "Overview" dashboard
   - Click "Reset to default" or "Delete dashboard"
   - Dashboard will be recreated automatically

4. **Manually fix dashboard config:**
   - Go to: http://localhost:8123/config/lovelace/dashboards
   - Click "Edit Dashboard" (three dots menu)
   - Click "Raw configuration editor"
   - Look for invalid card configurations
   - Remove or fix invalid entries
   - Save

5. **Check card resource registration:**
   - Settings → Dashboards → Resources
   - Look for `/local/oelo-patterns-card.js`
   - If missing, add manually:
     - Click "+ Add Resource"
     - URL: `/local/oelo-patterns-card.js`
     - Type: JavaScript Module
     - Save

**Quick Fix for Missing Files:**
```bash
# Create all common HA config files that might be referenced
make exec CMD='cd /config && touch automations.yaml scenes.yaml scripts.yaml groups.yaml'
make restart

# Wait for HA to fully start (30-60 seconds), then check status
sleep 30
make status

# Verify HA started successfully (should return 401, not recovery mode)
curl http://localhost:8123/api/config
```

**After fixing:**
- Refresh browser (http://localhost:8123)
- Dashboard should load normally
- Recovery mode message should be gone

### Test Artifacts Not Cleaned Up

Tests use prefix `test_oelo_` - manually remove if needed:
```bash
# Via HA UI: Settings → Devices & Services → Remove test devices
# Or via API (see test_helpers.py cleanup functions)
```

### Tests Fail After Interruption

Tests are designed to be rerunnable - just run again. Pre-test cleanup removes leftovers.

## Code Documentation

All documentation is inline. See module docstrings:

```bash
head -200 custom_components/oelo_lights/__init__.py
head -200 custom_components/oelo_lights/config_flow.py
head -200 custom_components/oelo_lights/services.py
head -200 test/test_helpers.py
```

## Project Structure

- `custom_components/oelo_lights/` - Integration code
- `test/` - Test files and test infrastructure
  - `test_*.py` - Core test scripts
  - `test_helpers.py` - Shared test utilities
  - `run_all_tests.py` - Master test runner
  - `Dockerfile.test` - Test runner container image
  - `setup_*.sh`, `setup_*.py` - Setup scripts
  - `create_token*.py` - Token creation helpers
  - `install_chromedriver.sh` - ChromeDriver installer
  - `REFACTORING_PLAN.md` - Test refactoring documentation
  - `test_output.log` - Test execution log (gitignored)
  - `onboarding_*` - Diagnostic files (gitignored, created during runs)
- `config/` - Docker test environment (gitignored)
- `Makefile` - Development commands
- `docker-compose.yml` - Local HA testing setup
