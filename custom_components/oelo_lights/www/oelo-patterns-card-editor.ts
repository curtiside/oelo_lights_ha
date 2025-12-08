import { LitElement, html, customElement, property } from 'lit-element';
import { HomeAssistant } from 'custom-card-helpers';

interface OeloPatternsCardConfig {
  type: string;
  entity: string;
  title?: string;
}

@customElement('oelo-patterns-card-editor')
export class OeloPatternsCardEditor extends LitElement {
  @property({ attribute: false }) public hass!: HomeAssistant;
  @property({ attribute: false }) public config!: OeloPatternsCardConfig;

  render() {
    if (!this.hass) {
      return html`<div>Loading...</div>`;
    }

    const entities = Object.keys(this.hass.states).filter(
      (entityId) => entityId.startsWith('light.oelo_lights_zone_')
    );

    return html`
      <div class="card-config">
        <div class="config-row">
          <paper-input
            label="Title (optional)"
            .value=${this.config.title || ''}
            .configValue=${'title'}
            @value-changed=${this._valueChanged}
          ></paper-input>
        </div>
        <div class="config-row">
          <paper-dropdown-menu
            label="Entity"
            .configValue=${'entity'}
            @value-changed=${this._valueChanged}
          >
            <paper-listbox slot="dropdown-content" .selected=${entities.indexOf(this.config.entity)}>
              ${entities.map(
                (entityId) => html`
                  <paper-item>${entityId}</paper-item>
                `
              )}
            </paper-listbox>
          </paper-dropdown-menu>
        </div>
      </div>
    `;
  }

  _valueChanged(ev: CustomEvent) {
    if (!this.config || !this.hass) {
      return;
    }
    const target = ev.target as any;
    if (this[`_${target.configValue}`] === target.value) {
      return;
    }
    if (target.configValue) {
      if (target.value === '') {
        delete this.config[target.configValue];
      } else {
        this.config = {
          ...this.config,
          [target.configValue]: target.checked !== undefined ? target.checked : target.value,
        };
      }
    }
    fireEvent(this, 'config-changed', { config: this.config });
  }
}
