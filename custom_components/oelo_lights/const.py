"""Constants for the Oelo Lights integration."""

DOMAIN = "oelo_lights"

# Configuration keys
CONF_IP_ADDRESS = "ip_address"
CONF_ZONES = "zones"
CONF_POLL_INTERVAL = "poll_interval"
CONF_AUTO_POLL = "auto_poll"
CONF_COMMAND_TIMEOUT = "command_timeout"
CONF_DEBUG_LOGGING = "debug_logging"
CONF_MAX_LEDS = "max_leds"
CONF_SPOTLIGHT_PLAN_LIGHTS = "spotlight_plan_lights"
CONF_VERIFY_COMMANDS = "verify_commands"
CONF_VERIFICATION_RETRIES = "verification_retries"
CONF_VERIFICATION_DELAY = "verification_delay"
CONF_VERIFICATION_TIMEOUT = "verification_timeout"

# Defaults
DEFAULT_POLL_INTERVAL = 300  # 5 minutes
DEFAULT_AUTO_POLL = True
DEFAULT_COMMAND_TIMEOUT = 10
DEFAULT_DEBUG_LOGGING = False
DEFAULT_MAX_LEDS = 500
DEFAULT_SPOTLIGHT_PLAN_LIGHTS = "1,2,3,4,8,9,10,11,21,22,23,24,25,35,36,37,38,59,60,61,62,67,68,69,70,93,94,95,112,113,114,115,132,133,134,135,153,154,155,156"
DEFAULT_VERIFY_COMMANDS = False
DEFAULT_VERIFICATION_RETRIES = 3
DEFAULT_VERIFICATION_DELAY = 2
DEFAULT_VERIFICATION_TIMEOUT = 30
DEFAULT_ZONES = [1, 2, 3, 4, 5, 6]

# Storage
STORAGE_VERSION = 1
STORAGE_KEY_PATTERNS = f"{DOMAIN}_patterns"

# Service names (using "effect" for Home Assistant consistency)
SERVICE_CAPTURE_EFFECT = "capture_effect"
SERVICE_APPLY_EFFECT = "apply_effect"
SERVICE_ON_AND_APPLY_EFFECT = "on_and_apply_effect"
SERVICE_RENAME_EFFECT = "rename_effect"
SERVICE_DELETE_EFFECT = "delete_effect"
SERVICE_LIST_EFFECTS = "list_effects"

# Pattern storage limits
MAX_PATTERNS = 200
