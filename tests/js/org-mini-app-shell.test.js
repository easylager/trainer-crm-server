'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { describe, it } = require('node:test');

const shellPath = path.resolve(__dirname, '../../static/webapp/mini-app-org-shell.js');

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.className = '';
    this.disabled = false;
    this._innerHTML = '';
    this._textContent = '';
    this.classList = {
      add: (name) => {
        if (!this.classList.contains(name)) this.className = `${this.className} ${name}`.trim();
      },
      remove: (name) => {
        this.className = this.className
          .split(/\s+/)
          .filter((className) => className !== name)
          .join(' ');
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
  }

  set innerHTML(value) {
    this._innerHTML = value;
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._textContent = value;
    this._innerHTML = '';
  }

  get textContent() {
    return (
      this._textContent +
      this._innerHTML.replace(/<[^>]*>/g, '') +
      this.children.map((child) => child.textContent).join('')
    );
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  addEventListener(type, listener) {
    (this.listeners[type] ||= []).push(listener);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  click() {
    if (this.disabled) return;
    for (const listener of this.listeners.click || []) listener({ target: this });
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }
}

function mountShell() {
  const body = new Element('body');
  body.setAttribute('data-org-shell', 'tabs');
  body.setAttribute('data-org-active', 'home');
  const document = {
    body,
    readyState: 'complete',
    createElement: (tagName) => new Element(tagName),
  };
  const window = { location: { href: '', search: '?school=1' } };
  vm.runInNewContext(fs.readFileSync(shellPath, 'utf8'), { document, window });
  return { body, window };
}

function buttonByText(body, label) {
  return body
    .descendants()
    .find((element) => element.tagName === 'button' && element.textContent.includes(label));
}

describe('organization mini-app shell unavailable destinations', () => {
  it('disables unavailable tabs, announces Скоро, and prevents navigation', () => {
    const { body, window } = mountShell();

    for (const label of ['Расписание', 'Клиенты', 'Каталог']) {
      const tab = buttonByText(body, label);
      assert.ok(tab, `${label} tab exists`);
      assert.equal(tab.disabled, true, `${label} tab is disabled`);
      assert.match(tab.textContent, /Скоро/i, `${label} tab announces that it is coming soon`);
      tab.click();
      assert.equal(window.location.href, '', `${label} tab does not navigate`);
    }
  });

  it('marks Team as Скоро and prevents navigation', () => {
    const { body, window } = mountShell();
    buttonByText(body, 'Ещё').click();
    const team = buttonByText(body, 'Команда');
    assert.ok(team, 'Team entry exists in More');
    assert.equal(team.disabled, true, 'Team entry is disabled');
    assert.match(team.textContent, /Скоро/i, 'Team entry announces that it is coming soon');
    team.click();
    assert.equal(window.location.href, '', 'Team entry does not navigate');
  });
});
