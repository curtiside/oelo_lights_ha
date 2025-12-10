# Testing Guide for Oelo Lights Home Assistant Integration

## Testing Methodology

This integration uses a **two-tier testing approach**:

1. **Primary Method**: `pytest-homeassistant-custom-component`
   - Recommended by Home Assistant for custom integrations
   - Provides fixtures and mocks for HA components
   - Fast, isolated unit tests

2. **Secondary Method**: HA REST/WebSocket API with Long-Lived Access Token
   - Used when pytest-homeassistant-custom-component doesn't cover specific scenarios
   - Full integration testing with real HA instance
   - Requires running HA container

## Test Structure

```
test/
├── conftest.py                    # Pytest fixtures and configuration
├── test_integration_pytest.py     # Pytest-based tests (primary method)
├── test_integration.py            # Legacy tests (API-based, secondary method)
├── test_workflow.py               # Pattern workflow tests
├── test_add_card.py               # Lovelace card installation tests
├── test_helpers.py                # Shared helper functions
└── run_all_tests.py               # Test runner
```

## Setup

### 1. Install Test Dependencies

```bash
pip install -r requirements-test.txt
```

This installs:
- `pytest-homeassistant-custom-component` (primary testing framework)
- `pytest`, `pytest-asyncio` (pytest support)
- `aiohttp`, `requests` (REST API testing)
- `websockets` (WebSocket API testing)

### 2. Start Home Assistant Container

```bash
make setup    # Copy integration files to config/
make start    # Start HA container
```

### 3. Install HACS in Container

HACS is automatically installed when using `make test` or `make test-all`.

To install manually:

```bash
docker exec -it ha-test bash -c "wget -O - https://get.hacs.xyz | bash -"
```

Or use the helper function:

```python
from test.test_helpers import install_hacs_via_docker
install_hacs_via_docker()
```

## Running Tests

### Run Pytest Tests (Primary Method)

```bash
# Run all pytest tests
pytest test/test_integration_pytest.py -v

# Run specific test
pytest test/test_integration_pytest.py::test_config_flow_init -v

# Run with coverage
pytest test/test_integration_pytest.py --cov=custom_components/oelo_lights
```

### Run API-Based Tests (Secondary Method)

```bash
# Run all tests
python3 test/run_all_tests.py

# Run specific test
python3 test/test_integration.py
python3 test/test_workflow.py
python3 test/test_add_card.py
```

### Run via Makefile

```bash
# Quick test (start HA, install HACS, check logs)
make test

# Full test suite
make test-all
```

## Test Categories

### Unit Tests (No HA Required)

- `test_pattern_utils()` - Pattern utility functions
- `test_pattern_storage_interface()` - Storage class structure

### Integration Tests (Requires HA)

**Using pytest-homeassistant-custom-component:**
- `test_config_flow_init()` - Config flow initialization
- `test_config_flow_ip_validation()` - IP validation
- `test_integration_setup()` - Integration setup with MockConfigEntry
- `test_services_registered()` - Service registration

**Using HA REST API:**
- `test_controller_connectivity_api()` - Controller connectivity
- `test_integration_via_api()` - Integration installation via API

### Workflow Tests

- `test_capture_pattern()` - Pattern capture from controller
- `test_rename_pattern()` - Pattern renaming
- `test_apply_pattern()` - Pattern application (URL generation)

## Configuration

### Environment Variables

- `CONTROLLER_IP` - Oelo controller IP (default: 10.16.52.41)
- `HA_URL` - Home Assistant URL (default: http://localhost:8123)
- `HA_TOKEN` - Long-lived access token (for API tests)
- `HA_USERNAME` / `HA_PASSWORD` - Credentials (token auto-creation)

### Pytest Configuration

Fixtures are defined in `conftest.py`:
- `hass` - Home Assistant instance
- `mock_config_entry` - Mock configuration entry
- `ha_client` - aiohttp session with HA token
- `controller_ip` - Controller IP from environment
- `ha_url` - HA URL from environment

## HACS Installation

HACS is required for testing the integration installation workflow. It's automatically installed via:

1. **Docker exec method** (recommended):
   ```bash
   docker exec -it ha-test bash -c "wget -O - https://get.hacs.xyz | bash -"
   ```

2. **Automatic installation**:
   - `wait_for_ha_ready(install_hacs=True)` installs HACS after HA is ready
   - Used by `make test` and `make test-all`

3. **Manual verification**:
   ```bash
   docker exec ha-test test -d /config/custom_components/hacs && echo "HACS installed" || echo "HACS not installed"
   ```

## Troubleshooting

### Pytest Tests Fail

- Ensure `pytest-homeassistant-custom-component` is installed
- Check that custom_components path is correct
- Verify pytest-asyncio is installed for async tests

### API Tests Fail

- Ensure HA container is running: `docker ps | grep ha-test`
- Check HA is accessible: `curl http://localhost:8123/api/`
- Verify HA_TOKEN is set or HA_USERNAME/HA_PASSWORD provided

### HACS Not Installing

- Check container is running: `docker ps | grep ha-test`
- Verify network connectivity: `docker exec ha-test ping -c 1 get.hacs.xyz`
- Check container logs: `docker logs ha-test | grep -i hacs`

### Controller Not Reachable

- Verify controller IP is correct: `ping $CONTROLLER_IP`
- Check firewall rules
- Ensure controller is on same network as test machine

## Best Practices

1. **Use pytest-homeassistant-custom-component first** - It's faster and more reliable
2. **Use API tests for end-to-end scenarios** - When you need real HA behavior
3. **Mock external dependencies** - Don't require real controller for unit tests
4. **Clean up test artifacts** - Remove test devices/entities after tests
5. **Use fixtures** - Share setup/teardown code via pytest fixtures

## References

- [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
- [HACS Installation Guide](https://hacs.xyz/docs/use/download/download/#to-download-hacs-container)
- [Home Assistant Testing](https://developers.home-assistant.io/docs/development_testing/)
