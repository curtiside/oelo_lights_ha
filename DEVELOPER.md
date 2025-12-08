# Developer Guide

Development and testing tools for Oelo Lights Home Assistant integration.

## Quick Start

```bash
make setup && make start
```

See `Makefile` for all available commands.

## Testing

### Test Files

All test files are in `test/` directory. See inline documentation:

- **Integration tests**: `test/test_integration.py` - Validates controller connectivity, module imports, config flow, pattern utils, services, pattern storage
- **Workflow tests**: `test/test_workflow.py` - End-to-end pattern capture → rename → apply workflow
- **Card setup**: `test/test_add_card.py` - Automatically adds Lovelace card to dashboard
- **Setup automation**: `test/setup_automated.sh` - Guides through HA onboarding and integration setup

### Running Tests

```bash
# Run integration tests
docker-compose exec homeassistant python3 /config/test/test_integration.py

# Run workflow tests
docker-compose exec homeassistant python3 /config/test/test_workflow.py
```

See test file docstrings for prerequisites and detailed usage.

## Development Environment

### Docker Setup

Uses Docker Compose for local HA testing. See `docker-compose.yml` for configuration.

### Makefile Commands

- `make setup` - Copy integration and test files to `config/`
- `make start` - Start HA container
- `make stop` - Stop container
- `make restart` - Restart container
- `make logs` - View HA logs
- `make clean` - Remove container and optionally `config/` directory
- `make test` - Quick test (setup, start, check logs)

### Manual Setup

For manual setup without Makefile, see `test/setup_automated.sh` for step-by-step guidance.

## Code Documentation

All code documentation is inline. See module docstrings:

```bash
head -200 custom_components/oelo_lights/__init__.py
head -200 custom_components/oelo_lights/services.py
```

## Project Structure

- `custom_components/oelo_lights/` - Integration code
- `test/` - Test files and setup scripts
- `config/` - Docker test environment (gitignored)
- `Makefile` - Development commands
- `docker-compose.yml` - Local HA testing setup
