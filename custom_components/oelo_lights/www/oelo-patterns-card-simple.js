/**
 * Oelo Patterns Card - Simple JavaScript version
 * No build step required - works directly in Home Assistant
 */

class OeloPatternsCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error('Entity is required');
    }
    this.config = config;
    this.entityId = config.entity;
    this._hass = null;
    this._patterns = [];
    this._loading = false;
    this._error = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (hass && this.entityId) {
      this._loadPatterns();
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    if (!this.content) {
      this.innerHTML = `
        <ha-card>
          <div class="card-content">
            <div class="header">
              <h2>${this.config.title || 'Oelo Patterns'}</h2>
              <mwc-button 
                outlined 
                class="capture-btn" 
                @click="${() => this._capturePattern()}"
                title="Capture current pattern from controller (set pattern in Oelo app first)"
              >
                <ha-icon icon="mdi:content-save"></ha-icon>
                Capture Pattern
              </mwc-button>
            </div>
            <div class="patterns-list" id="patterns-list">
              <div class="loading">Loading patterns...</div>
            </div>
          </div>
        </ha-card>
      `;
      this.content = this.querySelector('.card-content');
      this.patternsList = this.querySelector('#patterns-list');
      this._attachStyles();
    }
    this._loadPatterns();
  }

  _attachStyles() {
    if (document.getElementById('oelo-patterns-card-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'oelo-patterns-card-styles';
    style.textContent = `
      oelo-patterns-card {
        display: block;
      }
      oelo-patterns-card ha-card {
        padding: 16px;
      }
      oelo-patterns-card .card-content {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      oelo-patterns-card .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
      }
      oelo-patterns-card .header h2 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 400;
        color: var(--primary-text-color);
      }
      oelo-patterns-card .capture-btn {
        --mdc-theme-primary: var(--primary-color);
      }
      oelo-patterns-card .patterns-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      oelo-patterns-card .pattern-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px;
        background: var(--card-background-color, var(--primary-background-color));
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        transition: box-shadow 0.2s;
      }
      oelo-patterns-card .pattern-item:hover {
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
      }
      oelo-patterns-card .pattern-info {
        flex: 1;
        min-width: 0;
      }
      oelo-patterns-card .pattern-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--primary-text-color);
        margin-bottom: 4px;
        word-break: break-word;
      }
      oelo-patterns-card .pattern-id {
        font-size: 0.75rem;
        color: var(--secondary-text-color);
        font-family: monospace;
        word-break: break-all;
      }
      oelo-patterns-card .pattern-actions {
        display: flex;
        gap: 4px;
        margin-left: 12px;
      }
      oelo-patterns-card .pattern-actions mwc-icon-button {
        --mdc-icon-button-size: 36px;
        --mdc-icon-size: 20px;
        color: var(--secondary-text-color);
      }
      oelo-patterns-card .pattern-actions mwc-icon-button:hover {
        color: var(--primary-color);
      }
      oelo-patterns-card .apply-btn {
        color: var(--success-color, #4caf50);
      }
      oelo-patterns-card .delete-btn {
        color: var(--error-color, #f44336);
      }
      oelo-patterns-card .empty-state {
        text-align: center;
        padding: 32px 16px;
        color: var(--secondary-text-color);
      }
      oelo-patterns-card .empty-state ha-icon {
        font-size: 48px;
        color: var(--disabled-text-color);
        margin-bottom: 16px;
      }
      oelo-patterns-card .empty-state p {
        margin: 8px 0;
      }
      oelo-patterns-card .empty-state .hint {
        font-size: 0.875rem;
        color: var(--disabled-text-color);
      }
      oelo-patterns-card .loading,
      oelo-patterns-card .error {
        text-align: center;
        padding: 32px 16px;
        color: var(--secondary-text-color);
      }
      oelo-patterns-card .error {
        color: var(--error-color, #f44336);
      }
      @media (max-width: 600px) {
        oelo-patterns-card .header {
          flex-direction: column;
          align-items: flex-start;
          gap: 12px;
        }
        oelo-patterns-card .capture-btn {
          width: 100%;
        }
        oelo-patterns-card .pattern-item {
          flex-direction: column;
          align-items: flex-start;
        }
        oelo-patterns-card .pattern-actions {
          width: 100%;
          justify-content: flex-end;
          margin-left: 0;
          margin-top: 8px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  async _loadPatterns() {
    if (!this._hass || !this.entityId) return;

    this._loading = true;
    this._error = null;
    this._updateDisplay();

    try {
      const response = await this._hass.callService('oelo_lights', 'list_patterns', {
        entity_id: this.entityId,
      });
      this._patterns = response.patterns || [];
    } catch (error) {
      this._error = error.message || 'Failed to load patterns';
      console.error('Error loading patterns:', error);
    } finally {
      this._loading = false;
      this._updateDisplay();
    }
  }

  _updateDisplay() {
    if (!this.patternsList) return;

    if (this._loading) {
      this.patternsList.innerHTML = '<div class="loading">Loading patterns...</div>';
      return;
    }

    if (this._error) {
      this.patternsList.innerHTML = `<div class="error">${this._escapeHtml(this._error)}</div>`;
      return;
    }

    if (this._patterns.length === 0) {
      this.patternsList.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:lightbulb-outline"></ha-icon>
          <p>No patterns captured yet</p>
          <p class="hint"><strong>Workflow:</strong><br>1) Create/set pattern in Oelo app<br>2) Click "Capture Pattern" to save it here</p>
        </div>
      `;
      return;
    }

    this.patternsList.innerHTML = this._patterns.map((pattern) => `
      <div class="pattern-item" data-pattern-id="${this._escapeHtml(pattern.id)}">
        <div class="pattern-info">
          <div class="pattern-name">${this._escapeHtml(pattern.name)}</div>
          <div class="pattern-id">${this._escapeHtml(pattern.id)}</div>
        </div>
        <div class="pattern-actions">
          <mwc-icon-button 
            class="apply-btn" 
            title="Apply Pattern"
            data-pattern-id="${this._escapeHtml(pattern.id)}"
          >
            <ha-icon icon="mdi:play"></ha-icon>
          </mwc-icon-button>
          <mwc-icon-button 
            class="rename-btn" 
            title="Rename Pattern"
            data-pattern-id="${this._escapeHtml(pattern.id)}"
            data-pattern-name="${this._escapeHtml(pattern.name)}"
          >
            <ha-icon icon="mdi:pencil"></ha-icon>
          </mwc-icon-button>
          <mwc-icon-button 
            class="delete-btn" 
            title="Delete Pattern"
            data-pattern-id="${this._escapeHtml(pattern.id)}"
            data-pattern-name="${this._escapeHtml(pattern.name)}"
          >
            <ha-icon icon="mdi:delete"></ha-icon>
          </mwc-icon-button>
        </div>
      </div>
    `).join('');

    // Attach event listeners
    this.patternsList.querySelectorAll('.apply-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const patternId = e.currentTarget.dataset.patternId;
        this._applyPattern(patternId);
      });
    });

    this.patternsList.querySelectorAll('.rename-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const patternId = e.currentTarget.dataset.patternId;
        const patternName = e.currentTarget.dataset.patternName;
        this._renamePattern({ id: patternId, name: patternName });
      });
    });

    this.patternsList.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const patternId = e.currentTarget.dataset.patternId;
        const patternName = e.currentTarget.dataset.patternName;
        this._deletePattern(patternId, patternName);
      });
    });
  }

  async _capturePattern() {
    // Remind user to set pattern in Oelo app first
    const confirmed = confirm(
      'Make sure you have set your desired pattern in the Oelo app first.\n\n' +
      'Click OK to capture the current pattern from the controller.'
    );
    
    if (!confirmed) return;
    
    const patternName = prompt('Enter a name for this pattern (optional):');
    
    try {
      await this._hass.callService('oelo_lights', 'capture_pattern', {
        entity_id: this.entityId,
        pattern_name: patternName || undefined,
      });
      
      this._showNotification('Pattern captured successfully!', 'success');
      this._loadPatterns();
    } catch (error) {
      this._showNotification(`Error capturing pattern: ${error.message}`, 'error');
    }
  }

  async _applyPattern(patternId) {
    try {
      await this._hass.callService('oelo_lights', 'apply_pattern', {
        entity_id: this.entityId,
        pattern_id: patternId,
      });
      
      this._showNotification('Pattern applied!', 'success');
    } catch (error) {
      this._showNotification(`Error applying pattern: ${error.message}`, 'error');
    }
  }

  async _renamePattern(pattern) {
    const newName = prompt('Enter new name for pattern:', pattern.name);
    
    if (!newName || newName.trim() === '') {
      return;
    }

    try {
      await this._hass.callService('oelo_lights', 'rename_pattern', {
        entity_id: this.entityId,
        pattern_id: pattern.id,
        new_name: newName.trim(),
      });
      
      this._showNotification('Pattern renamed!', 'success');
      this._loadPatterns();
    } catch (error) {
      this._showNotification(`Error renaming pattern: ${error.message}`, 'error');
    }
  }

  async _deletePattern(patternId, patternName) {
    if (!confirm(`Are you sure you want to delete "${patternName}"?`)) {
      return;
    }

    try {
      await this._hass.callService('oelo_lights', 'delete_pattern', {
        entity_id: this.entityId,
        pattern_id: patternId,
      });
      
      this._showNotification('Pattern deleted!', 'success');
      this._loadPatterns();
    } catch (error) {
      this._showNotification(`Error deleting pattern: ${error.message}`, 'error');
    }
  }

  _showNotification(message, type = 'info') {
    const event = new CustomEvent('hass-notification', {
      bubbles: true,
      cancelable: false,
      detail: {
        message,
        notification_id: `oelo-patterns-${Date.now()}`,
        type,
      },
    });
    this.dispatchEvent(event);
  }

  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    return document.createElement('oelo-patterns-card-editor');
  }

  static getStubConfig() {
    return {
      type: 'custom:oelo-patterns-card',
      entity: 'light.oelo_lights_zone_1',
    };
  }
}

customElements.define('oelo-patterns-card', OeloPatternsCard);

// Register card with Home Assistant
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'oelo-patterns-card',
  name: 'Oelo Patterns',
  description: 'Manage Oelo light patterns',
  preview: true,
  documentationURL: 'https://github.com/curtiside/oelo_lights_ha',
});
