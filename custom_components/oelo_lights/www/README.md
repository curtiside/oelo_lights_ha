# Oelo Patterns Card

A custom Lovelace card for managing Oelo light patterns in Home Assistant.

## Features

- **View Patterns**: See all captured patterns for a zone
- **Capture Patterns**: Capture the current pattern from the controller
- **Apply Patterns**: Apply saved patterns with one click
- **Rename Patterns**: Rename patterns for easier identification
- **Delete Patterns**: Remove patterns you no longer need

## Installation

### Method 1: Simple JavaScript Version (Recommended - No Build Required)

1. Copy `oelo-patterns-card-simple.js` to your Home Assistant `www` directory:
   ```
   /config/www/oelo-patterns-card-simple.js
   ```

2. Add the card resource to your Lovelace configuration:
   - Go to **Settings** → **Dashboards** → **Resources**
   - Click **+ Add Resource**
   - Enter URL: `/local/oelo-patterns-card-simple.js`
   - Type: **JavaScript Module**
   - Click **Create**

3. Add the card to your dashboard:
   - Edit your dashboard
   - Click **+ Add Card**
   - Search for **Oelo Patterns** or use **Manual** card
   - Add this configuration:
   ```yaml
   type: custom:oelo-patterns-card
   entity: light.oelo_lights_zone_1
   title: My Oelo Patterns
   ```

### Method 2: TypeScript Version (For Development)

If you want to modify the card or build from source:

1. Install dependencies:
   ```bash
   cd custom_components/oelo_lights/www
   npm install
   ```

2. Build the card:
   ```bash
   npm run build
   ```

3. Copy `dist/oelo-patterns-card.js` to `/config/www/`

4. Add as resource in Lovelace (same as Method 1)

### Method 3: HACS (Future)

This card will be available through HACS once the integration is published.

## Configuration

### Card Options

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `entity` | string | **Required** | The Oelo light entity ID (e.g., `light.oelo_lights_zone_1`) |
| `title` | string | `"Oelo Patterns"` | Custom title for the card |

### Example Configuration

```yaml
type: custom:oelo-patterns-card
entity: light.oelo_lights_zone_1
title: Christmas Patterns
```

## Usage

### Capturing a Pattern

**Important**: Patterns are created in the Oelo app, not in Home Assistant.

1. **Create/set your pattern** in the Oelo app on your device
2. Click the **"Capture Pattern"** button in the card
3. Confirm that you've set the pattern in the Oelo app
4. Optionally enter a name for the pattern
5. The pattern will be saved and appear in the list for future use

### Applying a Pattern

1. Click the play button (▶) next to any pattern
2. The pattern will be applied to the zone immediately

### Renaming a Pattern

1. Click the pencil icon (✏️) next to a pattern
2. Enter the new name
3. The pattern will be updated

### Deleting a Pattern

1. Click the delete icon (🗑️) next to a pattern
2. Confirm the deletion
3. The pattern will be removed

## Requirements

- Oelo Lights integration installed and configured
- At least one Oelo light entity created
- **Pattern Creation**: Patterns must be created/set in the Oelo app first
- **Pattern Capture**: Patterns must be captured using the card or `oelo_lights.capture_pattern` service before they appear in the list

## Troubleshooting

### Card shows "No patterns captured yet"

- Make sure you've captured at least one pattern using the `oelo_lights.capture_pattern` service
- Verify the entity ID is correct
- Check that the Oelo Lights integration is working properly

### Patterns not updating

- Refresh the card by reloading the dashboard
- Check Home Assistant logs for errors
- Verify the entity ID matches an existing Oelo light entity

### Service calls failing

- Ensure the Oelo Lights integration is properly configured
- Check that the controller is online and reachable
- Verify the entity ID is correct

## Development

### Building from TypeScript

If you want to build from the TypeScript source:

```bash
npm install
npm run build
```

### Testing Locally

1. Copy the built files to your `www` directory
2. Add the card resource to Lovelace
3. Refresh your browser cache (Ctrl+Shift+R)

## License

MIT License - Same as the main Oelo Lights integration
