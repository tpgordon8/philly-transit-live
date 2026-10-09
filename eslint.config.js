'use strict';

const js = require('@eslint/js');
const globals = require('globals');

// The app is classic scripts (no modules, no build). Each file is an IIFE and shares code through window.SEPTA.
// L is the Leaflet global loaded from the CDN before the app scripts.
const appGlobals = Object.assign({}, globals.browser, { L: 'readonly', SEPTA: 'writable' });

module.exports = [
  { ignores: ['node_modules/**', 'tests/**', 'tools/**', 'data/**'] },
  js.configs.recommended,
  {
    files: ['js/**/*.js'],
    languageOptions: { ecmaVersion: 2018, sourceType: 'script', globals: appGlobals },
    rules: {
      'no-unused-vars': ['error', { args: 'after-used', caughtErrors: 'none' }],
      'no-undef': 'error'
    }
  },
  {
    files: ['worker/worker.js'],
    languageOptions: { ecmaVersion: 2018, sourceType: 'module', globals: globals.serviceworker },
    rules: {
      'no-unused-vars': ['error', { args: 'after-used', caughtErrors: 'none' }],
      'no-undef': 'error'
    }
  },
  {
    files: ['eslint.config.js'],
    languageOptions: { ecmaVersion: 2018, sourceType: 'commonjs', globals: globals.node }
  }
];
