class OeloPatternsCard extends HTMLElement {
  setConfig(config) {
    this.config = config;
    this.entityId = config.entity;
    this.hass = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (hass && this.entityId) {
      this.updateCard();
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
              <h2>Oelo Patterns</h2>
              <mwc-button outlined class="capture-btn" @click=${() => this.capturePattern()}>
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
    }
    this.updateCard();
  }

  async updateCard() {
    if (!this.hass || !this.entityId) return;

    try {
      const patterns = await this.getPatterns();
      this.renderPatterns(patterns);
    } catch (error) {
      console.error('Error loading patterns:', error);
      this.patternsList.innerHTML = `<div class="error">Error loading patterns: ${error.message}</div>`;
    }
  }

  async getPatterns() {
    const response = await this.hass.callService('oelo_lights', 'list_patterns', {
      entity_id: this.entityId
    });
    return response.patterns || [];
  }

  renderPatterns(patterns) {
    if (patterns.length === 0) {
      this.patternsList.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:lightbulb-outline"></ha-icon>
          <p>No patterns captured yet</p>
          <p class="hint">Use the Oelo app to set a pattern, then click "Capture Pattern" to save it</p>
        </div>
      `;
      return;
    }

    this.patternsList.innerHTML = patterns.map((pattern, index) => `
      <div class="pattern-item" data-pattern-id="${pattern.id}">
        <div class="pattern-info">
          <div class="pattern-name">${this.escapeHtml(pattern.name)}</div>
          <div class="pattern-id">${pattern.id}</div>
        </div>
        <div class="pattern-actions">
          <mwc-icon-button 
            class="apply-btn" 
            title="Apply Pattern"
            @click=${() => this.applyPattern(pattern.id)}
          >
            <ha-icon icon="mdi:play"></ha-icon>
          </mwc-icon-button>
          <mwc-icon-button 
            class="rename-btn" 
            title="Rename Pattern"
            @click=${() => this.renamePattern(pattern)}
          >
            <ha-icon icon="mdi:pencil"></ha-icon>
          </mwc-icon-button>
          <mwc-icon-button 
            class="delete-btn" 
            title="Delete Pattern"
            @click=${() => this.deletePattern(pattern.id, pattern.name)}
          >
            <ha-icon icon="mdi:delete"></ha-icon>
          </mwc-icon-button>
        </div>
      </div>
    `).join('');

    // Re-attach event listeners
    this.attachEventListeners();
  }

  attachEventListeners() {
    this.patternsList.querySelectorAll('.apply-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const patternItem = e.target.closest('.pattern-item');
        const patternId = patternItem.dataset.patternId;
        this.applyPattern(patternId);
      });
    });

    this.patternsList.querySelectorAll('.rename-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const patternItem = e.target.closest('.pattern-item');
        const patternId = patternItem.dataset.patternId;
        const patternName = patternItem.querySelector('.pattern-name').textContent;
        this.renamePattern({ id: patternId, name: patternName });
      });
    });

    this.patternsList.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const patternItem = e.target.closest('.pattern-item');
        const patternId = patternItem.dataset.patternId;
        const patternName = patternItem.querySelector('.pattern-name').textContent;
        this.deletePattern(patternId, patternName);
      });
    });
  }

  async capturePattern() {
    const patternName = prompt('Enter a name for this pattern (optional):');
    
    try {
      await this.hass.callService('oelo_lights', 'capture_pattern', {
        entity_id: this.entityId,
        pattern_name: patternName || undefined
      });
      
      this.showNotification('Pattern captured successfully!', 'success');
      this.updateCard();
    } catch (error) {
      this.showNotification(`Error capturing pattern: ${error.message}`, 'error');
    }
  }

  async applyPattern(patternId) {
    try {
      await this.hass.callService('oelo_lights', 'apply_pattern', {
        entity_id: this.entityId,
        pattern_id: patternId
      });
      
      this.showNotification('Pattern applied!', 'success');
    } catch (error) {
      this.showNotification(`Error applying pattern: ${error.message}`, 'error');
    }
  }

  async renamePattern(pattern) {
    const newName = prompt('Enter new name for pattern:', pattern.name);
    
    if (!newName || newName.trim() === '') {
      return;
    }

    try {
      await this.hass.callService('oelo_lights', 'rename_pattern', {
        entity_id: this.entityId,
        pattern_id: pattern.id,
        new_name: newName.trim()
      });
      
      this.showNotification('Pattern renamed!', 'success');
      this.updateCard();
    } catch (error) {
      this.showNotification(`Error renaming pattern: ${error.message}`, 'error');
    }
  }

  async deletePattern(patternId, patternName) {
    if (!confirm(`Are you sure you want to delete "${patternName}"?`)) {
      return;
    }

    try {
      await this.hass.callService('oelo_lights', 'delete_pattern', {
        entity_id: this.entityId,
        pattern_id: patternId
      });
      
      this.showNotification('Pattern deleted!', 'success');
      this.updateCard();
    } catch (error) {
      this.showNotification(`Error deleting pattern: ${error.message}`, 'error');
    }
  }

  showNotification(message, type = 'info') {
    const event = new Event('hass-notification', { bubbles: true, cancelable: false });
    event.detail = { message, type };
    this.dispatchEvent(event);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  getCardSize() {
    return 3;
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
  documentationURL: 'https://github.com/curtiside/oelo_lights_ha'
});
