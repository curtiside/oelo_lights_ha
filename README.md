# Oelo Lights Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

## Overview

This custom integration allows you to control your Oelo Lights system directly from Home Assistant. It supports multi-zone control, effects, color, and brightness, with the ability to capture, save, rename, and apply custom effects from your Oelo controller.

---

## Features

- Control up to 6 Oelo light zones individually
- Set color, brightness, and effects per zone
- **Capture effects** from your Oelo controller and save them for reuse
- **Rename and manage** saved effects
- **Apply saved effects** to any zone
- Dynamic effect list showing captured effects
- Optimized polling (single request for all zones)
- Handles device availability and offline detection
- Debounced command sending to prevent overload
- Home Assistant native config flow (UI setup)
- Supports Home Assistant scenes, automations, and scripts
- Spotlight plan support for zones with more than 40 LEDs

---

## Installation

### HACS Installation (Recommended - Auto-Updates)

1. **Install HACS** (if not already installed):
   - Follow the [HACS installation guide](https://hacs.xyz/docs/setup/download)

2. **Add this repository to HACS:**
   - Go to **HACS > Integrations**
   - Click the three dots menu (top right) → **Custom repositories**
   - Add repository: `https://github.com/Cinegration/Oelo_Lights_HA`
   - Category: **Integration**
   - Click **Add**

3. **Install the integration:**
   - Search for "Oelo Lights" in HACS
   - Click **Download**
   - Restart Home Assistant

4. **Updates:**
   - HACS will notify you when updates are available
   - Go to **HACS > Integrations** → **Oelo Lights** → **Update**

### Manual Installation (Manual Updates Required)

1. **Clone or download this repository:**
   ```bash
   git clone https://github.com/Cinegration/Oelo_Lights_HA.git
   # Or download and extract the ZIP file
   ```

2. **Copy the integration folder:**
   ```bash
   # On Linux/Mac:
   cp -r Oelo_Lights_HA/custom_components/oelo_lights /config/custom_components/
   
   # On Windows:
   # Copy the 'oelo_lights' folder from 'custom_components' to your Home Assistant 'custom_components' directory
   ```

3. **Restart Home Assistant:**
   - Go to **Settings > System > Restart**
   - Or restart your Home Assistant instance

4. **Verify installation:**
   - Check the logs for any errors
   - The integration should appear in **Settings > Devices & Services > Integrations**

5. **To update manually:**
   - Pull latest changes: `cd Oelo_Lights_HA && git pull`
   - Copy updated files to `/config/custom_components/oelo_lights/`
   - Restart Home Assistant

---

## Configuration

1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **Oelo Lights**.
3. Enter the IP address of your Oelo controller.
4. Click **Submit** to complete the setup.
5. Configure options (optional):
   - **Zones**: Select which zones to create entities for (default: all zones 1-6)
   - **Poll Interval**: How often to poll the controller (default: 300 seconds)
   - **Auto Poll**: Enable automatic polling (default: enabled)
   - **Spotlight Plan Lights**: LED indices for spotlight plans (default provided)
   - **Max LEDs**: Maximum LEDs per zone (default: 500)
   - **Command Verification**: Optional verification settings
   - **Advanced**: Command timeout, debug logging

---

## Usage

### Basic Control

- Each zone appears as a separate light entity in Home Assistant (e.g., `light.oelo_lights_zone_1`).
- You can control color, brightness, and effects from the UI, automations, or scripts.
- All standard Home Assistant light features are supported.

### Capturing Effects

**Important**: Effects must be created/set in the Oelo app first, then captured in Home Assistant.

The workflow is:

1. **Set the desired effect in the Oelo app** on your controller (the zone must be ON)
2. **Capture the effect** using one of these methods:

   **Using Services:**
   ```yaml
   service: oelo_lights.capture_effect
   data:
     entity_id: light.oelo_lights_zone_1
     effect_name: "My Custom Effect"  # Optional, defaults to auto-generated name
   ```

   **Using Developer Tools:**
   - Go to **Developer Tools > Services**
   - Select `oelo_lights.capture_effect`
   - Enter `entity_id` (e.g., `light.oelo_lights_zone_1`)
   - Optionally enter `effect_name`
   - Click **Call Service**

3. The captured effect will appear in the effect list for all zones

### Applying Effects

**Using the UI:**
- Select a zone light entity
- Click the effect dropdown
- Choose a captured effect

**Using Services:**
```yaml
service: oelo_lights.apply_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "My Custom Effect"
```

**Using Automations:**
```yaml
automation:
  - alias: "Apply Christmas Effect"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: oelo_lights.apply_effect
        data:
          entity_id: light.oelo_lights_zone_1
          effect_name: "Christmas Pattern"
```

### Managing Effects

**Rename an effect:**
```yaml
service: oelo_lights.rename_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "Old Name"  # or use effect_id instead
  new_name: "New Name"
```

**Note**: You can use either `effect_name` or `effect_id` to identify the effect. The `pattern_name` and `pattern_id` parameters are also supported for backward compatibility.

**Delete an effect:**
```yaml
service: oelo_lights.delete_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "Effect to Delete"  # or use effect_id instead
```

**List all effects:**
```yaml
service: oelo_lights.list_effects
data:
  entity_id: light.oelo_lights_zone_1
```

**Complete Workflow Example** (Capture → Rename → Apply):
```yaml
# 1. Capture effect (after setting it in Oelo app)
service: oelo_lights.capture_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "My Pattern"

# 2. Rename it
service: oelo_lights.rename_effect
data:
  entity_id: light.oelo_lights_zone_1
  effect_name: "My Pattern"
  new_name: "Renamed Pattern"

# 3. Apply the renamed pattern
service: oelo_lights.apply_effect
data:
  entity_id: light.oelo_lights_zone_2
  effect_name: "Renamed Pattern"
```

### Available Services

- `oelo_lights.capture_effect` - Capture current effect from controller
- `oelo_lights.apply_effect` - Apply a saved effect to a zone
- `oelo_lights.on_and_apply_effect` - Turn on and apply effect in one action
- `oelo_lights.rename_effect` - Rename a saved effect
- `oelo_lights.delete_effect` - Delete a saved effect
- `oelo_lights.list_effects` - List all saved effects

---

## Troubleshooting

- **Lights show as "Unavailable":**
  - Check that your Oelo controller is online and reachable from your Home Assistant network
  - Ensure the IP address is correct in the integration settings
  - Verify network connectivity: `ping <controller_ip>`

- **Effects not appearing:**
  - Make sure you've captured at least one effect using `oelo_lights.capture_effect`
  - The zone must be ON and showing a pattern when capturing
  - Effects are shared across all zones - capture once, use anywhere
  - Check Home Assistant logs for errors
  - Try refreshing the entity: `homeassistant.update_entity` service

- **Effect capture fails:**
  - Ensure the zone is ON and displaying a pattern
  - Verify the controller is responding: `curl http://<controller_ip>/getController`
  - Check Home Assistant logs for detailed error messages

- **General issues:**
  - Check Home Assistant logs: **Settings > System > Logs**
  - Enable debug logging in integration options for detailed information
  - Restart Home Assistant after making configuration changes

---

## Advanced Configuration

- **Effect Storage:** Effects are stored per controller (shared across all zones). Up to 200 effects can be stored. Patterns are captured once and can be applied to any zone.
- **Pattern Workflow:** Patterns are created in the Oelo app, then captured in Home Assistant. Once captured, they can be renamed and applied to any zone.
- **Spotlight Plans:** Special handling for zones with more than 40 LEDs. The controller returns limited data (40 LEDs), which is reconstructed using your Spotlight Plan Lights configuration during capture and application.
- **Service Parameters:** Services support both `effect_name`/`effect_id` (new) and `pattern_name`/`pattern_id` (backward compatibility) parameters.

---

## Contributing

Pull requests, bug reports, and feature requests are welcome!  
Please open an issue or PR on [GitHub](https://github.com/Cinegration/Oelo_Lights_HA).

---

## License

MIT License

---

## Credits

- [Oelo Lighting Solutions](https://oelo.com/)
- [Home Assistant](https://www.home-assistant.io/)
