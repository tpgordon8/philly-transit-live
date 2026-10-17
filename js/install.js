/* js/install.js: Septer as an installed app (ARCHITECTURE.md section 17). Releases the launch splash, registers the service worker (sw.js),
   offers "Install Septer" on Chromium phones and the Add to Home Screen hint on iOS Safari after the person has used the app a little,
   offers a reload when a new version is waiting, and says so when the device is offline. Everything here is optional: any failure
   leaves the app exactly as it was. Only the install card state is stored (localStorage septa.install.v1), never anything about trips or places. */
(function () {
  'use strict';
  var S = window.SEPTA;
  var KEY = 'septa.install.v1';
  var DISMISS_MS = 30 * 24 * 60 * 60 * 1000;
  var UPDATE_CHECK_MS = 30 * 60 * 1000;
  var root = document.documentElement;
  var deferred = null; /* the saved beforeinstallprompt event (Chromium) */
  var engaged = false;
  var reg = null;
  var lastUpdateCheck = 0;
  var reloading = false;
  var cards = {};

  /* ---- launch splash: index.html draws it in CSS on <html>; this class lets it go ---- */
  function releaseSplash() {
    root.classList.add('app-ready');
  }
  releaseSplash();

  /* ---- saved state (all access guarded: private windows and blocked storage must not matter) ---- */
  function load() {
    try {
      var o = JSON.parse(localStorage.getItem(KEY) || '{}');
      return o && typeof o === 'object' && !Array.isArray(o) ? o : {};
    } catch (e) {
      return {};
    }
  }
  function save(o) {
    try {
      localStorage.setItem(KEY, JSON.stringify(o));
    } catch (e) {
      /* storage unavailable: the card may come back next visit, which is acceptable */
    }
  }
  function patch(p) {
    var o = load();
    for (var k in p) o[k] = p[k];
    save(o);
    return o;
  }
  function dismissedRecently(o) {
    return typeof o.dismissedAt === 'number' && Date.now() - o.dismissedAt < DISMISS_MS;
  }

  /* ---- what kind of device is this ---- */
  function standalone() {
    try {
      if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return true;
      if (window.matchMedia && window.matchMedia('(display-mode: fullscreen)').matches) return true;
    } catch (e) {
      /* fall through */
    }
    return window.navigator.standalone === true;
  }
  function isIOS() {
    var ua = navigator.userAgent || '';
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && (navigator.maxTouchPoints || 0) > 1);
  }
  function isIOSSafari() {
    var ua = navigator.userAgent || '';
    return isIOS() && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS|OPT\/|GSA\/|DuckDuckGo/.test(ua);
  }
  function isTouchDevice() {
    var ua = navigator.userAgent || '';
    if (/Android|iPhone|iPad|iPod|Mobile/.test(ua)) return true;
    try {
      return window.matchMedia('(pointer: coarse)').matches && window.matchMedia('(hover: none)').matches;
    } catch (e) {
      return false;
    }
  }

  /* ---- cards ---- */
  var SHARE_SVG =
    '<svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 12.5V2.8M6.6 6.1 10 2.7l3.4 3.4M5 9H4.2A1.2 1.2 0 0 0 3 10.2v6.6A1.2 1.2 0 0 0 4.2 18h11.6a1.2 1.2 0 0 0 1.2-1.2v-6.6A1.2 1.2 0 0 0 15.8 9H15"/></svg>';
  function makeCard(id, label, title, textHtml, goLabel, xLabel, onGo, onX) {
    var el = document.createElement('div');
    el.className = 'inst-card is-away';
    el.id = id;
    el.hidden = true;
    el.setAttribute('role', 'region');
    el.setAttribute('aria-label', label);
    el.innerHTML =
      '<div class="ic-body"><p class="ic-title"></p><p class="ic-text">' + textHtml + '</p></div>';
    el.querySelector('.ic-title').textContent = title;
    if (goLabel) {
      var go = document.createElement('button');
      go.type = 'button';
      go.className = 'ic-go';
      go.textContent = goLabel;
      go.addEventListener('click', onGo);
      el.appendChild(go);
    }
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'ic-x';
    x.textContent = xLabel;
    x.addEventListener('click', onX);
    el.appendChild(x);
    document.body.appendChild(el);
    return el;
  }
  function showCard(name) {
    var el = cards[name];
    if (!el) return;
    el.hidden = false;
    el.setAttribute('data-shown', '1');
    void el.offsetWidth; /* lets the entrance transition run (reduced-motion users get none, see css) */
    el.classList.remove('is-away');
  }
  function hideCard(name) {
    var el = cards[name];
    if (!el) return;
    el.removeAttribute('data-shown');
    el.hidden = true;
    el.classList.add('is-away');
  }

  function typing() {
    var a = document.activeElement;
    if (!a || a === document.body) return false;
    var t = (a.tagName || '').toUpperCase();
    if (t === 'TEXTAREA' || t === 'SELECT') return true;
    if (t !== 'INPUT') return false;
    return !/^(checkbox|radio|button|submit|range|reset|color|file|image)$/i.test(a.type || 'text');
  }
  function keyboardUp() {
    if (typing()) return true;
    try {
      return parseInt(root.style.getPropertyValue('--kb') || '0', 10) > 0;
    } catch (e) {
      return false;
    }
  }

  /* Which one card (if any) should be visible right now. The update card outranks the install offers; never in standalone for the install ones. */
  function wanted() {
    if (cards.update && cards.update.getAttribute('data-want') === '1') return 'update';
    if (standalone()) return null;
    var o = load();
    if (!engaged) return null;
    if (deferred && isTouchDevice() && !dismissedRecently(o) && !o.installed) return 'install';
    if (!deferred && isIOSSafari() && !o.iosDone) return 'ios';
    return null;
  }
  function render() {
    var w = wanted();
    var hide = keyboardUp();
    for (var n in cards) {
      if (n === w && !hide) {
        if (cards[n].hidden) showCard(n);
      } else if (!cards[n].hidden) hideCard(n);
    }
  }

  function buildCards() {
    if (cards.install) return;
    cards.install = makeCard(
      'installCard',
      'Install Septer',
      'Install Septer',
      'Opens full screen from your home screen, like any app.',
      'Install',
      'Not now',
      doInstall,
      function () {
        patch({ dismissedAt: Date.now() });
        render();
      }
    );
    cards.ios = makeCard(
      'iosHintCard',
      'Add Septer to your Home Screen',
      'Add Septer to your Home Screen',
      'Tap ' + SHARE_SVG + ' Share, then Add to Home Screen.',
      '',
      'Got it',
      null,
      function () {
        patch({ iosDone: true });
        render();
      }
    );
    cards.update = makeCard(
      'updateCard',
      'Update ready',
      'A new version is ready',
      'Reload to use it. Your places and settings are kept.',
      'Reload',
      'Later',
      applyUpdate,
      function () {
        cards.update.setAttribute('data-want', '0');
        render();
      }
    );
  }

  function doInstall() {
    var ev = deferred;
    if (!ev) return;
    deferred = null;
    hideCard('install');
    try {
      ev.prompt();
      Promise.resolve(ev.userChoice)
        .then(function (c) {
          if (c && c.outcome === 'accepted') patch({ installed: true });
          else patch({ dismissedAt: Date.now() });
        })
        .catch(function () {});
    } catch (e) {
      /* prompt() can only be used once */
    }
  }

  /* ---- engagement: a second visit, a search, or a pinned stop ---- */
  function markEngaged() {
    if (engaged) return;
    engaged = true;
    buildCards();
    render();
  }
  function countVisit() {
    var counted = false;
    try {
      counted = sessionStorage.getItem('septa.install.visit') === '1';
      if (!counted) sessionStorage.setItem('septa.install.visit', '1');
    } catch (e) {
      /* count it anyway */
    }
    var o = load();
    if (!counted) o = patch({ visits: (typeof o.visits === 'number' ? o.visits : 0) + 1 });
    if (o.visits >= 2) engaged = true;
  }
  function watchEngagement() {
    document.addEventListener(
      'submit',
      function (e) {
        if (e.target && e.target.id === 'searchForm') markEngaged();
      },
      true
    );
    try {
      var seen = S.board && S.board.pins ? S.board.pins().length : 0;
      if (S.board && S.board.onChange) {
        S.board.onChange(function () {
          var n = S.board.pins().length;
          if (n > seen) markEngaged();
          seen = n;
        });
      }
    } catch (e) {
      /* board module missing: search and second visit still count */
    }
  }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferred = e;
    buildCards();
    render();
  });
  window.addEventListener('appinstalled', function () {
    deferred = null;
    patch({ installed: true });
    render();
  });
  document.addEventListener('focusin', render);
  document.addEventListener('focusout', function () {
    setTimeout(render, 60);
  });
  if (window.visualViewport) window.visualViewport.addEventListener('resize', render);

  /* ---- offline pill ---- */
  function offlinePill() {
    var el = document.getElementById('offlineBar');
    if (!el) {
      el = document.createElement('div');
      el.id = 'offlineBar';
      el.hidden = true;
      el.setAttribute('role', 'status');
      el.textContent = 'You are offline. Vehicles show again when you reconnect.';
      document.body.appendChild(el);
    }
    return el;
  }
  function syncOnline() {
    var off = navigator.onLine === false;
    var el = offlinePill();
    el.hidden = !off;
    root.classList.toggle('is-offline', off);
  }
  window.addEventListener('online', syncOnline);
  window.addEventListener('offline', syncOnline);

  /* ---- service worker ---- */
  function secureEnough() {
    var h = location.hostname;
    return location.protocol === 'https:' || h === 'localhost' || h === '127.0.0.1' || h === '[::1]';
  }
  function offerUpdate() {
    buildCards();
    cards.update.setAttribute('data-want', '1');
    render();
  }
  function applyUpdate() {
    var w = reg && reg.waiting;
    if (!w) {
      location.reload();
      return;
    }
    reloading = true;
    try {
      w.postMessage({ type: 'SKIP_WAITING' });
    } catch (e) {
      location.reload();
    }
  }
  function watchWorker(r) {
    function check(w) {
      w.addEventListener('statechange', function () {
        if (w.state === 'installed' && navigator.serviceWorker.controller) offerUpdate();
      });
    }
    if (r.waiting && navigator.serviceWorker.controller) offerUpdate();
    if (r.installing) check(r.installing);
    r.addEventListener('updatefound', function () {
      if (r.installing) check(r.installing);
    });
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (reloading) location.reload();
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && Date.now() - lastUpdateCheck > UPDATE_CHECK_MS) {
        lastUpdateCheck = Date.now();
        r.update().catch(function () {});
      }
    });
  }
  function registerWorker() {
    try {
      if (!('serviceWorker' in navigator) || !secureEnough()) return;
      navigator.serviceWorker
        .register('sw.js', { updateViaCache: 'none' })
        .then(function (r) {
          reg = r;
          lastUpdateCheck = Date.now();
          watchWorker(r);
        })
        .catch(function () {});
    } catch (e) {
      /* never break the app over the worker */
    }
  }

  try {
    syncOnline();
    countVisit();
    watchEngagement();
    if (engaged) {
      buildCards();
      render();
    }
    if (document.readyState === 'complete') registerWorker();
    else window.addEventListener('load', registerWorker);
  } catch (e) {
    /* an optional layer: the app already runs */
  }

  S.install = {
    wanted: wanted,
    standalone: standalone,
    state: load,
    markEngaged: markEngaged,
    offerUpdate: offerUpdate
  };
})();
