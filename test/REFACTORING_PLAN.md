# Test Refactoring Plan

## Goal
Refactor tests to simulate complete user workflow from container start to test completion:
1. **Container Management**: Start fresh HA container, manage lifecycle
2. **Fresh HA Setup**: Clean config, start container, wait for readiness
3. **Onboarding**: Complete onboarding via UI
4. **HACS Installation**: Install HACS via UI
5. **Integration Installation**: Install oelo_lights_ha via HACS
6. **Device Configuration**: Add device, set IP address via UI
7. **Pattern Workflow**: Capture, rename, and apply patterns via UI
8. **Cleanup**: Stop container, clean up test artifacts

## Current State Analysis

### test_integration.py
- **Current**: Tests basic functionality + API-based installation
- **Issue**: Uses API shortcuts, doesn't test HACS installation
- **Status**: Good for unit tests, but not user workflow

### test_integration_ui.py
- **Current**: UI verification after API installation
- **Issue**: Redundant if end-to-end test works, fragile UI selectors
- **Status**: **REMOVE** - End-to-end test covers this

### test_workflow.py
- **Current**: Pattern logic tests only (no UI)
- **Status**: **KEEP** - Fast unit tests for pattern logic validation

### test_workflow_ui.py
- **Current**: Pattern capture/rename/apply via UI
- **Issue**: Redundant if end-to-end test works, fragile UI selectors
- **Status**: **REMOVE** - End-to-end test covers this

### test_full_setup.py
- **Current**: Some automation but incomplete
- **Issue**: Doesn't include HACS installation
- **Status**: Partial automation

## Proposed New Structure

### test_user_workflow.py (NEW - Main Test)
**Purpose**: Complete end-to-end user workflow test with container management

**Container Lifecycle**:
1. **Pre-test Setup**
   - Stop existing container if running
   - Clean config directory (optional flag)
   - Ensure Docker/Docker Compose available
   - Verify container image available

2. **Container Start**
   - Start fresh container via `docker-compose up -d`
   - Wait for container to be healthy
   - Monitor container logs for startup errors
   - Verify container is accessible on port 8123

3. **HA Readiness**
   - Wait for HA API to respond (HTTP 200/401)
   - Wait for onboarding page to be available
   - Verify no critical errors in logs
   - Set up browser driver for UI automation

**Test Steps**:
1. **Fresh HA Setup**
   - Verify onboarding page appears
   - Check container health
   - Verify network connectivity

2. **Onboarding**
   - Complete onboarding via UI (name, username, password)
   - Verify dashboard appears

3. **HACS Installation**
   - Navigate to HACS installation page
   - Install HACS via UI (download, restart)
   - Wait for HA restart
   - Complete HACS onboarding (accept terms, select categories)
   - Verify HACS appears in sidebar
   - **Clear logs**: Navigate to http://localhost:8123/config/logs → Click "Clear" button

4. **Integration Installation via HACS**
   - Navigate to HACS → Integrations
   - Add custom repository (GitHub URL)
   - Search and install "oelo_lights_ha"
   - Restart HA
   - Verify integration appears in Settings → Integrations

5. **Add Device**
   - Navigate to Settings → Devices & Services
   - Click "Add Integration"
   - Search "Oelo Lights"
   - Enter IP address
   - Complete config flow
   - Verify device entities created

6. **Configure Options**
   - Click on integration → Configure
   - Set zones, poll interval, etc.
   - Submit configuration
   - Verify options saved

7. **Pattern Capture**
   - Navigate to dashboard
   - Find Oelo Patterns card
   - Click "Capture Pattern" button
   - Enter pattern name
   - Verify pattern captured

8. **Pattern Rename**
   - Find captured pattern in card
   - Click rename/edit button
   - Enter new name
   - Verify pattern renamed

9. **Pattern Apply**
   - Find pattern in card
   - Click apply button
   - Verify pattern applied to controller

10. **Post-test Cleanup**
    - Capture test artifacts (screenshots, logs)
    - Optionally stop container (or leave running for debugging)
    - Generate test report
    - Return exit code based on test results

### test_integration.py (REFACTORED)
**Purpose**: Fast API-based unit tests (no UI, no container)

**Keep**: Basic functionality tests (imports, config flow validation, pattern utils, services)
**Remove**: Installation steps (moved to user workflow test)
**Change**: Focus on logic validation, can run without HA running

### test_workflow.py (KEEP AS-IS)
**Purpose**: Pattern logic validation (no UI, no container)

**Status**: Keep for fast unit tests - validates pattern extraction, renaming, URL generation

### test_integration_ui.py (REMOVE)
**Reason**: Redundant - end-to-end test covers UI verification. Fragile UI selectors add maintenance burden.

### test_workflow_ui.py (REMOVE)
**Reason**: Redundant - end-to-end test covers pattern workflow. Fragile UI selectors add maintenance burden.

## Implementation Plan

### Phase 1: Create Helper Functions
- Extract common functions to `test_helpers.py`:
  - **Container Management**:
    - `stop_container()` - Stop HA container
    - `start_container()` - Start HA container
    - `restart_container()` - Restart HA container
    - `clean_config()` - Clean config directory (optional)
    - `check_container_health()` - Verify container is running
    - `wait_for_container_ready()` - Wait for container to be healthy
  - **HA Readiness**:
    - `wait_for_ha_ready()` - Wait for HA API to respond
    - `wait_for_ha_restart()` - Wait for HA to restart and be ready
    - `check_ha_logs()` - Check for errors in logs
  - **Browser Automation**:
    - `create_driver()` - Create Selenium WebDriver
    - `login_ui()` - Login via UI
    - `complete_onboarding_ui()` - Complete onboarding via UI
  - **HACS & Integration**:
    - `install_hacs_ui()` (NEW) - Install HACS via UI
    - `clear_logs_ui()` (NEW) - Clear logs via UI (http://localhost:8123/config/logs)
    - `install_integration_via_hacs_ui()` (NEW) - Install integration via HACS
  - **Device Configuration**:
    - `add_device_via_ui()` (REFACTORED) - Add device via UI
    - `configure_options_via_ui()` (REFACTORED) - Configure options via UI
  - **Pattern Workflow**:
    - `capture_pattern_ui()` (REFACTORED) - Capture pattern via UI
    - `rename_pattern_ui()` (REFACTORED) - Rename pattern via UI
    - `apply_pattern_ui()` (REFACTORED) - Apply pattern via UI

### Phase 2: Create test_user_workflow.py
- Implement complete user workflow with container management
- **Container Setup**:
  - Check Docker/Docker Compose availability
  - Stop existing container
  - Clean config (optional flag)
  - Start fresh container
  - Wait for container health
  - Wait for HA readiness
- **Test Execution**:
  - Use helper functions from Phase 1
  - Test each step independently with verification
  - Handle restarts (HACS install, integration install)
  - Capture screenshots on failures
- **Cleanup**:
  - Optionally stop container (configurable)
  - Save test artifacts
  - Generate test report

### Phase 3: Refactor Existing Tests
- Refactor `test_integration.py` to remove installation steps, keep unit tests
- Keep `test_workflow.py` as-is (fast unit tests)
- **Remove** `test_integration_ui.py` (redundant)
- **Remove** `test_workflow_ui.py` (redundant)

### Phase 4: Update Test Runner
- Update `run_all_tests.py` to run new workflow
- Add option to skip HACS installation (for faster tests)

## HACS Installation Details

### HACS Installation Steps (via UI):
1. Navigate to: https://hacs.xyz/docs/setup/download
2. Copy HACS installation command
3. Install via Developer Tools → YAML (or download manually)
4. Restart HA
5. Complete HACS onboarding (accept terms, select categories)
6. Verify HACS appears in sidebar

### Integration Installation via HACS:
1. Navigate to HACS → Integrations
2. Click "Custom repositories" (three dots menu)
3. Add repository:
   - Repository: `https://github.com/curtiside/oelo_lights_ha`
   - Category: Integration
4. Search "Oelo Lights"
5. Click "Download"
6. Restart HA
7. Verify integration available in Settings → Integrations

## Key Challenges

1. **Container Management**: Need to manage Docker container lifecycle
   - Solution: Use `docker-compose` commands, implement health checks, handle container failures gracefully

2. **HACS Installation**: Requires downloading and installing HACS first
   - Solution: Use browser automation to download HACS, install via Developer Tools → YAML

3. **HA Restarts**: Need to wait for HA to restart and be ready after HACS/integration installs
   - Solution: Implement robust wait functions with timeouts, monitor container logs, check API readiness

4. **Container Health**: Container may start but HA not ready, or HA may crash
   - Solution: Implement health checks, monitor logs, retry with exponential backoff

5. **UI Element Detection**: HACS and integration UI elements may change
   - Solution: Use multiple selector strategies, take screenshots on failure, implement retry logic

6. **Test Duration**: Full workflow will take 10-15 minutes (container start + all steps)
   - Solution: Make tests modular, allow skipping steps, add progress indicators, parallelize where possible

7. **Config Management**: Need fresh config for each test run
   - Solution: Option to clean config before start, backup config for debugging, use separate test configs

## Success Criteria

✅ **Container Management**:
   - Tests start fresh container automatically
   - Tests wait for container to be healthy
   - Tests handle container failures gracefully
   - Tests can clean up after completion

✅ **HA Setup**:
   - Tests wait for HA to be ready
   - Tests verify onboarding page appears
   - Tests complete onboarding via UI

✅ **HACS & Integration**:
   - Tests install HACS via UI
   - Tests clear logs after HACS installation (via UI)
   - Tests install integration via HACS (not manual copy)
   - Tests handle HA restarts after installations

✅ **Device Configuration**:
   - Tests add device via UI
   - Tests set IP address via UI
   - Tests configure options via UI

✅ **Pattern Workflow**:
   - Tests capture pattern via UI
   - Tests rename pattern via UI
   - Tests apply pattern via UI

✅ **Test Infrastructure**:
   - All steps verified independently
   - Tests can run in CI/CD environment
   - Tests generate reports and artifacts
   - Tests handle failures gracefully with clear error messages

## File Structure After Refactoring

```
test/
├── test_helpers.py              # Shared helper functions (container + UI)
├── test_user_workflow.py         # Complete user workflow with container (NEW)
├── test_integration.py           # Fast API unit tests (REFACTORED)
├── test_workflow.py              # Pattern logic unit tests (KEEP)
├── run_all_tests.py              # Test runner (UPDATED)
└── REFACTORING_PLAN.md           # This file
```

**Removed Files**:
- `test_integration_ui.py` - Redundant, covered by end-to-end test
- `test_workflow_ui.py` - Redundant, covered by end-to-end test

## Rationale for Test Structure

### Why Remove test_integration_ui.py and test_workflow_ui.py?

**Problems with separate UI tests**:
1. **Fragile**: UI selectors break when HA/HACS updates their UI
2. **Redundant**: End-to-end test already covers all UI interactions
3. **Maintenance burden**: Need to update selectors in multiple places
4. **Incomplete**: They assume integration already installed, don't test full workflow

**Value of end-to-end test**:
- Tests complete user workflow from container start to pattern application
- Single source of truth for UI testing
- More realistic - matches actual user experience
- Easier to maintain - one set of UI selectors

**What we keep**:
- `test_integration.py` - Fast unit tests (no UI, no container) for logic validation
- `test_workflow.py` - Fast unit tests for pattern logic (no UI, no container)
- `test_user_workflow.py` - Complete end-to-end test (container + UI)

**Test Strategy**:
- **Fast feedback**: Unit tests (`test_integration.py`, `test_workflow.py`) run quickly without container
- **Full validation**: End-to-end test (`test_user_workflow.py`) validates complete user experience
- **No redundancy**: Each test has a clear purpose, no overlap

## Container Management Details

### Docker Compose Commands
- Start: `docker-compose up -d`
- Stop: `docker-compose down`
- Restart: `docker-compose restart`
- Logs: `docker-compose logs -f`
- Health check: `docker-compose ps`

### Container Health Checks
- Container status: `docker ps` or `docker-compose ps`
- HA API readiness: HTTP GET to `http://localhost:8123/api/`
- Log monitoring: Check for "Home Assistant is running" message
- Port availability: Verify port 8123 is listening

### Config Directory Management
- Location: `./config` (mapped to `/config` in container)
- Clean option: Remove `config/` before starting (fresh install)
- No backup needed: Tests use fresh container each time
- Test artifacts: Save logs, screenshots to `test/artifacts/`

### Integration File Handling
- **HACS Installation**: Integration files installed via HACS (no manual copy needed)
- **Manual Fallback**: If HACS fails, can copy files to `config/custom_components/oelo_lights/`
- **File Verification**: Verify integration files exist after HACS installation

### Container Management Implementation

#### Helper Functions (test_helpers.py)

```python
# Container Management
def stop_container(project_dir: str) -> bool:
    """Stop HA container using docker-compose."""
    # Run: docker-compose down
    # Return: success status

def start_container(project_dir: str, clean_config: bool = False) -> bool:
    """Start HA container, optionally cleaning config."""
    # If clean_config: remove config/ directory (no backup needed)
    # Run: docker-compose up -d
    # Return: success status

def restart_container(project_dir: str) -> bool:
    """Restart HA container."""
    # Run: docker-compose restart
    # Return: success status

def check_container_health(container_name: str = "ha-test") -> bool:
    """Check if container is running and healthy."""
    # Run: docker ps --filter name=ha-test --format "{{.Status}}"
    # Check: status contains "Up"
    # Return: health status

def wait_for_container_ready(max_wait: int = 120) -> bool:
    """Wait for container to be ready."""
    # Poll check_container_health() every 2 seconds
    # Return: True when ready, False on timeout

def wait_for_ha_ready(max_wait: int = 180) -> bool:
    """Wait for HA API to respond."""
    # Poll: GET http://localhost:8123/api/
    # Expect: 200 or 401 status
    # Return: True when ready, False on timeout

def wait_for_ha_restart(max_wait: int = 180) -> bool:
    """Wait for HA to restart and be ready."""
    # Wait for API to become unavailable (restarting)
    # Then wait for API to become available again
    # Return: True when ready, False on timeout

def check_ha_logs_for_errors() -> list[str]:
    """Check container logs for errors."""
    # Run: docker-compose logs --tail 100
    # Filter: lines containing "ERROR" or "CRITICAL"
    # Return: list of error lines

def clear_logs_ui(driver) -> bool:
    """Clear HA logs via UI (http://localhost:8123/config/logs)."""
    # Navigate to: http://localhost:8123/config/logs
    # Find and click "Clear" button
    # Verify logs cleared
    # Return: success status
```

#### Main Test (test_user_workflow.py)

```python
def main():
    """Run complete user workflow test."""
    project_dir = os.path.dirname(os.path.dirname(__file__))
    
    # 1. Pre-test setup
    print("Stopping existing container...")
    stop_container(project_dir)
    
    if args.clean_config:
        print("Cleaning config directory...")
        clean_config(project_dir)  # No backup needed
    
    # 2. Start container
    print("Starting container...")
    if not start_container(project_dir):
        print("Failed to start container")
        return 1
    
    # 3. Wait for container health
    print("Waiting for container to be healthy...")
    if not wait_for_container_ready():
        print("Container failed to become healthy")
        return 1
    
    # 4. Wait for HA readiness
    print("Waiting for Home Assistant to be ready...")
    if not wait_for_ha_ready():
        print("Home Assistant failed to become ready")
        return 1
    
    # 5. Run test steps...
    # (onboarding, HACS, clear logs, integration, device, patterns)
    
    # 6. Cleanup
    if args.keep_container:
        print("Keeping container running for debugging")
    else:
        print("Stopping container...")
        stop_container(project_dir)
    
    return 0
```

### Command-Line Arguments

```python
import argparse

parser = argparse.ArgumentParser(description="Oelo Lights User Workflow Test")
parser.add_argument(
    "--clean-config",
    action="store_true",
    help="Clean config directory before starting (fresh install)"
)
parser.add_argument(
    "--keep-container",
    action="store_true",
    help="Keep container running after test (for debugging)"
)
parser.add_argument(
    "--skip-hacs",
    action="store_true",
    help="Skip HACS installation (use manual integration copy)"
)
parser.add_argument(
    "--skip-patterns",
    action="store_true",
    help="Skip pattern workflow tests"
)
parser.add_argument(
    "--controller-ip",
    default="10.16.52.41",
    help="Controller IP address for testing"
)
parser.add_argument(
    "--timeout",
    type=int,
    default=180,
    help="Timeout for HA readiness (seconds)"
)
```

### Usage Examples

```bash
# Full test with fresh container
python3 test/test_user_workflow.py --clean-config

# Test without cleaning config (faster, reuses existing setup)
python3 test/test_user_workflow.py

# Test and keep container running for debugging
python3 test/test_user_workflow.py --keep-container

# Test without HACS (uses manual integration copy)
python3 test/test_user_workflow.py --skip-hacs

# Test only setup, skip pattern workflow
python3 test/test_user_workflow.py --skip-patterns

# Test with custom controller IP
python3 test/test_user_workflow.py --controller-ip 192.168.1.100
```

### Makefile Integration

Update `Makefile` to use new test:

```makefile
test-user-workflow:
	@echo "Running complete user workflow test..."
	@python3 test/test_user_workflow.py --clean-config

test-user-workflow-fast:
	@echo "Running user workflow test (reuse config)..."
	@python3 test/test_user_workflow.py

test-user-workflow-debug:
	@echo "Running user workflow test (keep container)..."
	@python3 test/test_user_workflow.py --keep-container
```

## Test Execution Flow

```
1. Pre-test Setup
   ├── Check Docker/Docker Compose available
   ├── Stop existing container (if running)
   ├── Clean config directory (optional)
   └── Verify container image available

2. Container Start
   ├── Start container: docker-compose up -d
   ├── Wait for container health
   ├── Monitor startup logs
   └── Verify port 8123 accessible

3. HA Readiness
   ├── Wait for HA API to respond
   ├── Wait for onboarding page
   ├── Check for critical errors
   └── Initialize browser driver

4. Onboarding
   ├── Complete onboarding via UI
   ├── Verify dashboard appears
   └── Create test user account

5. HACS Installation
   ├── Navigate to HACS installation
   ├── Install HACS via UI
   ├── Wait for HA restart
   ├── Complete HACS onboarding
   ├── Verify HACS in sidebar
   └── Clear logs via UI (http://localhost:8123/config/logs → Clear)

6. Integration Installation
   ├── Navigate to HACS → Integrations
   ├── Add custom repository
   ├── Install oelo_lights_ha
   ├── Wait for HA restart
   └── Verify integration available

7. Device Configuration
   ├── Add device via UI
   ├── Set IP address
   ├── Configure options
   └── Verify entities created

8. Pattern Workflow
   ├── Capture pattern via UI
   ├── Rename pattern via UI
   └── Apply pattern via UI

9. Post-test
   ├── Capture test artifacts
   ├── Generate test report
   ├── Optionally stop container
   └── Return exit code
```
