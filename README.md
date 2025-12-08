# Oelo Lights Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

Control Oelo Lights from Home Assistant. Multi-zone control, effect capture/storage/management, spotlight plan support.

**Documentation:** All documentation is inline in code files. See module docstrings:
```bash
head -200 custom_components/oelo_lights/__init__.py
head -200 custom_components/oelo_lights/services.py
```

---

## Installation

### HACS (Recommended)

1. Install [HACS](https://hacs.xyz/docs/setup/download) if needed
2. HACS → Integrations → Custom repositories → Add `https://github.com/curtiside/oelo_lights_ha` (Category: Integration)
3. Search "oelo_lights_ha" → Download → Restart

### Manual

```bash
git clone https://github.com/curtiside/oelo_lights_ha.git
cp -r oelo_lights_ha/custom_components/oelo_lights /config/custom_components/
# Restart Home Assistant
```

---

## Configuration

### Initial Setup

Settings → Devices & Services → Add Integration → Search "oelo_lights_ha" → Enter controller IP address → Submit.

**Required:**
- **Controller IP Address** - IPv4 address of Oelo controller on local network

Integration validates IP and creates entities for all zones (1-6) with default settings. Pattern management card is automatically added to Overview dashboard during setup.

### Configure Options (After Setup)

Settings → Devices & Services → oelo_lights_ha → Configure (or click integration → Configure button).

**Note:** Changing zones requires restart. Other options take effect immediately.

**Optional Settings:**

- **Zones** - Select zones to create entities (1-6, default: all zones)
- **Poll Interval** - Status polling frequency (10-3600 seconds, default: 300)
- **Auto Poll** - Enable automatic polling (default: enabled)
- **Spotlight Plan Lights** - Comma-delimited LED indices for spotlight plans (default provided)
- **Max LEDs** - Maximum LEDs per zone (1-500, default: 500)
- **Verify Commands** - Verify commands after sending (default: disabled)
- **Verification Retries** - Retry attempts (1-10, default: 3)
- **Verification Delay** - Delay between retries (1-10 seconds, default: 2)
- **Verification Timeout** - Max wait time (10-120 seconds, default: 30)
- **Command Timeout** - HTTP request timeout (5-30 seconds, default: 10)
- **Debug Logging** - Enable detailed logging (default: disabled)

### Finding Controller IP

**Oelo Evolution App:**
- Open app → Settings/Device Information → Find IP address

**Router Admin:**
- Log into router → Connected Devices/DHCP Client List → Look for "Oelo" device

**Network Scanner:**
- Use Fing, Angry IP Scanner, nmap (`nmap -sn 192.168.1.0/24`), or Advanced IP Scanner
- Look for device on port 80 returning JSON from `/getController`

**Controller Display:**
- Some controllers show IP on built-in screen/LED display

**Manual Test:**
```bash
curl http://<controller_ip>/getController
# Should return JSON array of zone statuses
```

### IP Validation

Integration validates IP by:
1. Format check (IPv4)
2. Connection test to `/getController` endpoint
3. Response validation (JSON array expected)

If validation fails, error shown and integration won't initialize until valid IP provided.

---

## Usage

### Basic Control

Each zone is a light entity (`light.oelo_lights_zone_1`, etc.). Control via UI, automations, scripts.

### Accessing Pattern Management

**Pattern Application (Apply):**
- **Light Entity UI** - Click zone entity → Effect dropdown (shows captured patterns only)

**Pattern Management (Capture, Rename, Delete):**
- **Dashboard Card** - Automatically added to Overview dashboard during setup/reload. Provides buttons for Capture, Apply, Rename, Delete. Replaces any existing zones card if present.
- **Add to Other Dashboards** - Edit dashboard → + Add Card → Manual → Paste: `type: custom:oelo-patterns-card`, `entity: light.oelo_lights_ha_zone_1`, `title: Oelo Patterns`
- **Developer Tools → Services** - Settings → Developer Tools → Services → Search `oelo_lights` → Use `capture_effect`, `rename_effect`, `delete_effect` services

### Effect Workflow

1. **Create pattern in Oelo app** (zone must be ON)
2. **Capture**: Dashboard card "Capture Pattern" button (auto-added) or Developer Tools → Services → `oelo_lights.capture_effect`
3. **Apply**: Effect dropdown in light entity UI, dashboard card "Apply" button, or `oelo_lights.apply_effect` service

### Services

- `capture_effect` - Capture current pattern (zone must be ON)
- `apply_effect` - Apply saved effect
- `on_and_apply_effect` - Turn on + apply
- `rename_effect` - Rename saved effect
- `delete_effect` - Delete saved effect
- `list_effects` - List all saved effects

**Parameters:** Use `effect_name` or `effect_id`. `pattern_name`/`pattern_id` supported for backward compatibility.

**Service Examples:**

Capture effect:
```yaml
service: oelo_lights.capture_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "Christmas Pattern"
```

Apply effect:
```yaml
service: oelo_lights.apply_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "Christmas Pattern"
```

Rename effect:
```yaml
service: oelo_lights.rename_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "Old Name"
  new_name: "New Name"
```

Delete effect:
```yaml
service: oelo_lights.delete_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "Pattern to Delete"
```

### Pattern Types

**Spotlight Plans:**
- Automatically detected when pattern type is "spotlight"
- Controller returns only 40 LEDs, but zones can have up to 500
- Spotlight Plan Lights setting specifies which LEDs are active
- Other LEDs set to off (0,0,0)

**Non-Spotlight Plans:**
- Standard patterns (march, stationary, river, chase, twinkle, split, fade, sprinkle, takeover, streak, bolt, custom)
- Uses colors as returned from controller

### Pattern Management

- Up to 200 patterns per controller (shared across all zones)
- Patterns identified by stable ID (generated from pattern parameters)
- Pattern names editable via `rename_effect` service
- Duplicate patterns automatically prevented (same parameters = same ID)
- Patterns appear in effect dropdown for all zones

### Example Automations

**Sunset Pattern:**
```yaml
automation:
  - alias: "Sunset Pattern"
    trigger:
      - platform: sun
        event: sunset
    action:
      - service: oelo_lights.apply_effect
        data:
          entity_id: light.oelo_lights_zone_1
          effect_name: "Sunset Effect"
```

**Midnight Off:**
```yaml
automation:
  - alias: "Lights Off at Midnight"
    trigger:
      - platform: time
        at: "00:00:00"
    action:
      - service: light.turn_off
        target:
          entity_id: light.oelo_lights_zone_1
```

**Capture and Apply:**
```yaml
# First capture pattern (after setting in Oelo app)
automation:
  - alias: "Capture Pattern"
    trigger:
      - platform: state
        entity_id: input_button.capture_pattern
        to: "pressed"
    action:
      - service: oelo_lights.capture_effect
        data:
          entity_id: light.oelo_lights_zone_1
          effect_name: "My Pattern"

# Then apply it later
automation:
  - alias: "Apply Pattern"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: oelo_lights.apply_effect
        data:
          entity_id: light.oelo_lights_zone_1
          effect_name: "My Pattern"
```

See `custom_components/oelo_lights/services.py` for detailed service documentation.

---

## Troubleshooting

### "Controller IP address not configured"
- Enter IP address in integration settings
- Verify IP format (IPv4 address)

### "Cannot connect to controller"
- Verify IP address is correct
- Check controller is online: `ping <controller_ip>`
- Verify network connectivity (same network/VLAN)
- Check firewall rules
- Test manually: `curl http://<ip>/getController` (should return JSON array)

### "Device responded but doesn't appear to be an Oelo controller"
- Verify correct IP address
- Test endpoint: `curl http://<ip>/getController`
- Should return JSON array of zone statuses
- Check controller firmware compatibility

### Lights show as "Unavailable"
- Check controller IP in integration settings
- Verify network connectivity (`ping <ip>`)
- Ensure controller is powered on
- Try refreshing entity: `homeassistant.update_entity`

### Effects not appearing
- Capture at least one effect (zone must be ON)
- Effects shared across all zones
- Refresh entity: `homeassistant.update_entity`
- Check Home Assistant logs for errors

### Effect capture fails
- Zone must be ON and displaying a pattern
- Verify controller responding: `curl http://<ip>/getController`
- Check Home Assistant logs for detailed errors
- Ensure pattern is set in Oelo app first

### Commands not working
- Verify effect exists (check effect list)
- Check device logs for error messages
- Enable debug logging in integration options
- Verify controller IP and zone number are correct

### General issues
- Check Home Assistant logs: Settings → System → Logs
- Enable debug logging in integration options
- Restart Home Assistant after configuration changes
- See `custom_components/oelo_lights/` module docstrings for details

## Requirements

- Home Assistant 2023.1 or later
- Oelo Lights controller on local network
- Controller IP address (IPv4)
- Network connectivity between Home Assistant and controller

## Authentication & Security

**No Credentials Required**

Oelo Lights controller uses open HTTP API with no authentication:
- No username/password required
- No API keys or tokens
- No encryption (HTTP only, not HTTPS)
- Simple GET requests to controller IP

**Security Considerations:**
- Controller should be on trusted local network
- Consider firewall rules to restrict access
- Controller accessible to anyone on network who knows IP

## Contributing

Issues/PRs welcome: https://github.com/curtiside/oelo_lights_ha

## Support

- **GitHub Issues**: [Report an issue](https://github.com/curtiside/oelo_lights_ha/issues)
- **Home Assistant Community**: [Home Assistant Community Forum](https://community.home-assistant.io)

## License

MIT License

## Acknowledgments

Built upon [Cinegration/Oelo_Lights_HA](https://github.com/Cinegration/Oelo_Lights_HA) and extended with pattern capture/storage/management, spotlight plan support, and Hubitat driver feature parity.
