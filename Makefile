.PHONY: help setup start stop restart logs clean test

help:
	@echo "Oelo Lights HA Testing Makefile"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup    - Set up test environment (copy integration files)"
	@echo "  make start    - Start Home Assistant container"
	@echo "  make stop     - Stop Home Assistant container"
	@echo "  make restart  - Restart Home Assistant container"
	@echo "  make logs     - View Home Assistant logs (follow mode)"
	@echo "  make clean    - Remove container and config directory"
	@echo "  make test     - Run quick test (start, wait, check logs)"

setup:
	@echo "Setting up test environment..."
	@mkdir -p config/custom_components
	@if [ ! -d "config/custom_components/oelo_lights" ]; then \
		echo "Copying integration files..."; \
		cp -r custom_components/oelo_lights config/custom_components/; \
		echo "✓ Integration files copied"; \
	else \
		echo "✓ Integration files already exist"; \
	fi
	@if [ ! -f ".env" ]; then \
		echo "Creating .env file from template..."; \
		cp .env.example .env; \
		echo "✓ .env file created (edit if needed)"; \
	fi
	@echo "Setup complete!"

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

logs:
	@echo "Viewing Home Assistant logs (Ctrl+C to exit)..."
	docker-compose logs -f

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
	@echo "Waiting 30 seconds for Home Assistant to start..."
	@sleep 30
	@echo "Checking logs for errors..."
	@docker-compose logs --tail 50 | grep -i error || echo "No errors found in recent logs"
	@echo "Test complete! Check http://localhost:8123"
