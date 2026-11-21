import assert from 'node:assert/strict';
import test from 'node:test';

import {
  navigateAuthorizationWindow,
  openAuthorizationPlaceholder,
} from '../src/lib/externalAuthorization.js';

function makeWindowProxy() {
  let opener = {};
  const calls = [];
  return {
    calls,
    get opener() { return opener; },
    set opener(value) { opener = value; },
    closed: false,
    location: {
      replace(url) { calls.push(['navigate', url, opener]); },
    },
    close() { this.closed = true; },
  };
}

test('authorization placeholder is opened synchronously and opener is severed', () => {
  const popup = makeWindowProxy();
  let args;
  globalThis.window = {
    open(...values) {
      args = values;
      return popup;
    },
  };

  const opened = openAuthorizationPlaceholder();

  assert.equal(opened, popup);
  assert.deepEqual(args, ['about:blank', '_blank']);
  assert.equal(popup.opener, null);
});

test('provider URL is navigated only after opener is null', () => {
  const popup = makeWindowProxy();

  navigateAuthorizationWindow(popup, 'https://accounts.example.test/authorize');

  assert.equal(popup.opener, null);
  assert.deepEqual(popup.calls, [
    ['navigate', 'https://accounts.example.test/authorize', null],
  ]);
});

test('popup blocking is reported when the browser returns null', () => {
  globalThis.window = { open: () => null };

  assert.throws(
    () => openAuthorizationPlaceholder(),
    /browser blocked the authorization window/,
  );
});

test('a closed placeholder is not navigated', () => {
  const popup = makeWindowProxy();
  popup.closed = true;

  assert.throws(
    () => navigateAuthorizationWindow(popup, 'https://accounts.example.test/authorize'),
    /no longer available/,
  );
  assert.deepEqual(popup.calls, []);
});
