import { LitElement, html, css, customElement, property, state } from 'lit-element';
import { HomeAssistant } from 'custom-card-helpers';
import { fireEvent } from 'custom-card-helpers/src/fire-event';

interface Pattern {
  id: string;
  name: string;
  plan_type?: string;
}

interface OeloPatternsCardConfig {
  type: string;
  entity: string;
  title?: string;
}

@customElement('oelo-patterns-card')
export class OeloPatternsCard extends LitElement {
  @property({ attribute: false }) public hass!: HomeAssistant;
  @property({ attribute: false }) public config!: OeloPatternsCardConfig;

  @state() private _patterns: Pattern[] = [];
  @state() private _loading = false;
  @state() private _error: string | null = null;

  static get styles() {
    return css`
      :host {
        display: block;
      }

      ha-card {
        padding: 16px;
      }

      .card-content {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }

      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
      }

      .header h2 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 400;
        color: var(--primary-text-color);
      }

      .capture-btn {
        --mdc-theme-primary: var(--primary-color);
      }

      .patterns-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .pattern-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px;
        background: var(--card-background-color, var(--primary-background-color));
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        transition: box-shadow 0.2s;
      }

      .pattern-item:hover {
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
      }

      .pattern-info {
        flex: 1;
        min-width: 0;
      }

      .pattern-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--primary-text-color);
        margin-bottom: 4px;
        word-break: break-word;
      }

      .pattern-id {
        font-size: 0.75rem;
        color: var(--secondary-text-color);
        font-family: monospace;
        word-break: break-all;
      }

      .pattern-actions {
        display: flex;
        gap: 4px;
        margin-left: 12px;
      }

      .pattern-actions mwc-icon-button {
        --mdc-icon-button-size: 36px;
        --mdc-icon-size: 20px;
        color: var(--secondary-text-color);
      }

      .pattern-actions mwc-icon-button:hover {
        color: var(--primary-color);
      }

      .apply-btn {
        color: var(--success-color, #4caf50);
      }

      .delete-btn {
        color: var(--error-color, #f44336);
      }

      .empty-state {
        text-align: center;
        padding: 32px 16px;
        color: var(--secondary-text-color);
      }

      .empty-state ha-icon {
        font-size: 48px;
        color: var(--disabled-text-color);
        margin-bottom: 16px;
      }

      .empty-state p {
        margin: 8px 0;
      }

      .empty-state .hint {
        font-size: 0.875rem;
        color: var(--disabled-text-color);
      }

      .loading,
      .error {
        text-align: center;
        padding: 32px 16px;
        color: var(--secondary-text-color);
      }

      .error {
        color: var(--error-color, #f44336);
      }

      @media (max-width: 600px) {
        .header {
          flex-direction: column;
          align-items: flex-start;
          gap: 12px;
        }

        .capture-btn {
          width: 100%;
        }

        .pattern-item {
          flex-direction: column;
          align-items: flex-start;
        }

        .pattern-actions {
          width: 100%;
          justify-content: flex-end;
          margin-left: 0;
          margin-top: 8px;
        }
      }
    `;
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadPatterns();
  }

  async _loadPatterns() {
    if (!this.hass || !this.config?.entity) return;

    this._loading = true;
    this._error = null;

    try {
      const response = await this.hass.callService('oelo_lights', 'list_patterns', {
        entity_id: this.config.entity,
      });
      this._patterns = response.patterns || [];
    } catch (error: any) {
      this._error = error.message || 'Failed to load patterns';
      console.error('Error loading patterns:', error);
    } finally {
      this._loading = false;
    }
  }

  async _capturePattern() {
    const patternName = prompt('Enter a name for this pattern (optional):');
    
    try {
      await this.hass.callService('oelo_lights', 'capture_pattern', {
        entity_id: this.config.entity,
        pattern_name: patternName || undefined,
      });
      
      this._showNotification('Pattern captured successfully!', 'success');
      this._loadPatterns();
    } catch (error: any) {
      this._showNotification(`Error capturing pattern: ${error.message}`, 'error');
    }
  }

  async _applyPattern(patternId: string) {
    try {
      await this.hass.callService('oelo_lights', 'apply_pattern', {
        entity_id: this.config.entity,
        pattern_id: patternId,
      });
      
      this._showNotification('Pattern applied!', 'success');
    } catch (error: any) {
      this._showNotification(`Error applying pattern: ${error.message}`, 'error');
    }
  }

  async _renamePattern(pattern: Pattern) {
    const newName = prompt('Enter new name for pattern:', pattern.name);
    
    if (!newName || newName.trim() === '') {
      return;
    }

    try {
      await this.hass.callService('oelo_lights', 'rename_pattern', {
        entity_id: this.config.entity,
        pattern_id: pattern.id,
        new_name: newName.trim(),
      });
      
      this._showNotification('Pattern renamed!', 'success');
      this._loadPatterns();
    } catch (error: any) {
      this._showNotification(`Error renaming pattern: ${error.message}`, 'error');
    }
  }

  async _deletePattern(patternId: string, patternName: string) {
    if (!confirm(`Are you sure you want to delete "${patternName}"?`)) {
      return;
    }

    try {
      await this.hass.callService('oelo_lights', 'delete_pattern', {
        entity_id: this.config.entity,
        pattern_id: patternId,
      });
      
      this._showNotification('Pattern deleted!', 'success');
      this._loadPatterns();
    } catch (error: any) {
      this._showNotification(`Error deleting pattern: ${error.message}`, 'error');
    }
  }

  _showNotification(message: string, type: 'info' | 'success' | 'error' = 'info') {
    fireEvent(this, 'hass-notification', {
      message,
      notification_id: `oelo-patterns-${Date.now()}`,
      type,
    });
  }

  render() {
    if (!this.config) {
      return html`<ha-card><div class="error">Invalid configuration</div></ha-card>`;
    }

    return html`
      <ha-card>
        <div class="card-content">
          <div class="header">
            <h2>${this.config.title || 'Oelo Patterns'}</h2>
            <mwc-button 
              outlined 
              class="capture-btn" 
              @click=${this._capturePattern}
              .disabled=${this._loading}
            >
              <ha-icon icon="mdi:content-save"></ha-icon>
              Capture Pattern
            </mwc-button>
          </div>
          
          ${this._loading
            ? html`<div class="loading">Loading patterns...</div>`
            : this._error
            ? html`<div class="error">${this._error}</div>`
            : this._patterns.length === 0
            ? html`
                <div class="empty-state">
                  <ha-icon icon="mdi:lightbulb-outline"></ha-icon>
                  <p>No patterns captured yet</p>
                  <p class="hint">Use the Oelo app to set a pattern, then click "Capture Pattern" to save it</p>
                </div>
              `
            : html`
                <div class="patterns-list">
                  ${this._patterns.map(
                    (pattern) => html`
                      <div class="pattern-item">
                        <div class="pattern-info">
                          <div class="pattern-name">${pattern.name}</div>
                          <div class="pattern-id">${pattern.id}</div>
                        </div>
                        <div class="pattern-actions">
                          <mwc-icon-button
                            class="apply-btn"
                            title="Apply Pattern"
                            @click=${() => this._applyPattern(pattern.id)}
                          >
                            <ha-icon icon="mdi:play"></ha-icon>
                          </mwc-icon-button>
                          <mwc-icon-button
                            class="rename-btn"
                            title="Rename Pattern"
                            @click=${() => this._renamePattern(pattern)}
                          >
                            <ha-icon icon="mdi:pencil"></ha-icon>
                          </mwc-icon-button>
                          <mwc-icon-button
                            class="delete-btn"
                            title="Delete Pattern"
                            @click=${() => this._deletePattern(pattern.id, pattern.name)}
                          >
                            <ha-icon icon="mdi:delete"></ha-icon>
                          </mwc-icon-button>
                        </div>
                      </div>
                    `
                  )}
                </div>
              `}
        </div>
      </ha-card>
    `;
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
