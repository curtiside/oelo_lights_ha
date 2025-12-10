.PHONY: help setup build start stop restart logs clean test test-all status ps shell exec

help:
	@echo "Oelo Lights HA Testing Makefile"
	@echo ""
	@echo "Container Management:"
	@echo "  make setup    - Set up test environment (copy integration files)"
	@echo "  make build    - Pull latest Home Assistant image"
	@echo "  make start    - Start Home Assistant container"
	@echo "  make stop     - Stop Home Assistant container"
	@echo "  make restart  - Restart Home Assistant container"
	@echo "  make status   - Show container status"
	@echo "  make ps       - List containers (alias for status)"
	@echo "  make logs     - View Home Assistant logs (follow mode)"
	@echo "  make shell    - Open shell in HA container"
	@echo "  make exec     - Execute command in HA container (usage: make exec CMD='command')"
	@echo "  make clean    - Remove container and config directory"
	@echo ""
	@echo "Testing:"
	@echo "  make test     - Run quick test (start, wait, check logs)"
	@echo "  make test-all - Run complete test suite (all tests in order)"

setup:
	@echo "Setting up test environment..."
	@mkdir -p config/custom_components config/test
	@if [ ! -d "config/custom_components/oelo_lights" ]; then \
		echo "Copying integration files..."; \
		cp -r custom_components/oelo_lights config/custom_components/; \
		echo "✓ Integration files copied"; \
	else \
		echo "✓ Integration files already exist"; \
	fi
	@echo "Copying test files..."; \
	cp -r test/* config/test/ 2>/dev/null || true; \
	echo "✓ Test files copied"
	@if [ ! -f ".env" ]; then \
		echo "Creating .env file from template..."; \
		cp .env.example .env; \
		echo "✓ .env file created (edit if needed)"; \
	fi
	@echo "Setup complete!"

build:
	@echo "Pulling latest Home Assistant image..."
	@docker-compose pull homeassistant
	@echo "✓ Image pulled successfully"

start:
	@echo "Starting Home Assistant..."
	docker-compose up -d
	@echo "Home Assistant starting..."
	@echo "Access at http://localhost:8123"
	@echo "View logs with: make logs"

stop:
	@echo "Stopping Home Assistant..."
	docker-compose down

restart:
	@echo "Restarting Home Assistant..."
	docker-compose restart

status:
	@echo "Container status:"
	@docker-compose ps

ps: status

logs:
	@echo "Viewing Home Assistant logs (Ctrl+C to exit)..."
	@docker-compose logs -f

shell:
	@echo "Opening shell in HA container..."
	@docker-compose exec homeassistant /bin/bash || docker-compose exec homeassistant /bin/sh

exec:
	@if [ -z "$(CMD)" ]; then \
		echo "Usage: make exec CMD='command to run'"; \
		echo "Example: make exec CMD='ls -la /config'"; \
		exit 1; \
	fi
	@docker-compose exec homeassistant $(CMD)


clean:
	@echo "Cleaning up..."
	docker-compose down
	@read -p "Remove config directory? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf config; \
		echo "✓ Config directory removed"; \
	fi
	@echo "Cleanup complete!"

test:
	@echo "Running quick test..."
	@make setup
	@make start
	@echo "Waiting for Home Assistant to start..."
	@python3 -c "from test.test_helpers import wait_for_ha_ready, install_hacs_via_docker; wait_for_ha_ready(install_hacs=True)"
	@echo "Checking logs for errors..."
	@docker-compose logs --tail 50 | grep -i error || echo "No errors found in recent logs"
	@echo "Test complete! Check http://localhost:8123"


test-all:
	@echo "Running complete test suite..."
	@make setup
	@make start
	@echo "Waiting for Home Assistant to be ready and installing HACS..."
	@python3 -c "from test.test_helpers import wait_for_ha_ready; wait_for_ha_ready(install_hacs=True)"
	@python3 test/run_all_tests.py

