/* js/main.js: test hook and application start. Part of the classic-script split of index.html (ARCHITECTURE.md section 14). */
(function () {
  'use strict';
  var S = window.SEPTA;
  var angDiff = S.util.angDiff,
    bearing = S.util.bearing,
    cardinal = S.util.cardinal,
    distMi = S.util.distMi,
    esc = S.util.esc,
    lateInfo = S.util.lateInfo;
  var lateVal = S.util.lateVal,
    parseSeptaDate = S.util.parseSeptaDate;
  var alertKey = S.feed.alertKey,
    normBuses = S.feed.normBuses,
    normTrains = S.feed.normTrains;
  var etaFor = S.stops.etaFor,
    speedHist = S.stops.speedHist,
    speedMps = S.stops.speedMps,
    updateSpeedHist = S.stops.updateSpeedHist;
  var evalRule = S.alerts.evalRule;
  var TP = S.routing.TP,
    buildBusCandidates = S.candidates.buildBusCandidates,
    buildNetIndex = S.routing.buildNetIndex,
    estimateTotal = S.candidates.estimateTotal;
  var loadIndego = S.routing.loadIndego,
    loadNetwork = S.routing.loadNetwork,
    nearbyStations = S.candidates.nearbyStations,
    nearbyStops = S.candidates.nearbyStops;
  var planTrips = S.planner.planTrips,
    resetPlannerCaches = S.routing.resetPlannerCaches,
    routeLeg = S.routing.routeLeg,
    waitAtStop = S.candidates.waitAtStop;
  var cancelPlan = S.routing.cancelPlan,
    inRegion = S.routing.inRegion;
  if (typeof window !== 'undefined' && window.__SEPTA_TEST__) {
    window.__SEPTA_TEST__ = {
      normBuses: normBuses,
      normTrains: normTrains,
      lateVal: lateVal,
      lateInfo: lateInfo,
      cardinal: cardinal,
      distMi: distMi,
      bearing: bearing,
      angDiff: angDiff,
      parseSeptaDate: parseSeptaDate,
      alertKey: alertKey,
      esc: esc,
      etaFor: etaFor,
      speedMps: speedMps,
      updateSpeedHist: updateSpeedHist,
      speedHist: speedHist,
      evalRule: evalRule,
      planTrips: planTrips,
      routeLeg: routeLeg,
      loadNetwork: loadNetwork,
      loadIndego: loadIndego,
      nearbyStops: nearbyStops,
      nearbyStations: nearbyStations,
      waitAtStop: waitAtStop,
      resetPlannerCaches: resetPlannerCaches,
      buildBusCandidates: buildBusCandidates,
      estimateTotal: estimateTotal,
      buildNetIndex: buildNetIndex,
      TP: TP,
      cancelPlan: cancelPlan,
      inRegion: inRegion
    };
  }
  if (typeof document === 'undefined') return;
  S.started = true;
  if (S.halt) return;
  var $ = S.util.$,
    state = S.util.state;
  var refresh = S.feed.refresh;
  var drawCenter = S.map.drawCenter,
    drawHome = S.map.drawHome,
    map = S.map.map,
    renderPlaces = S.panel.renderPlaces,
    syncModeChips = S.panel.syncModeChips;
  var updateSaveForm = S.panel.updateSaveForm;
  var stopFromHash = S.stops.stopFromHash;
  var loadAlerts = S.alerts.loadAlerts,
    renderAlerts = S.alerts.renderAlerts,
    renderNotify = S.alerts.renderNotify,
    renderRules = S.alerts.renderRules;
  var radiusCircle = {
    getBounds: function () {
      return S.map.radiusCircleBounds();
    }
  };
  if (window.__SEPTA_TEST__ && typeof window.__SEPTA_TEST__ === 'object')
    window.__SEPTA_TEST__.tripMap = map; /* test hook: read centre and zoom */
  /* ----- Boot ----- */
  $('#radius').value = state.radius;
  $('#radiusOut').textContent = state.radius + ' mi';
  syncModeChips();
  drawCenter();
  drawHome();
  renderPlaces();
  updateSaveForm();
  renderAlerts();
  map.fitBounds(radiusCircle.getBounds(), { padding: [24, 24], animate: false });
  renderRules();
  renderNotify();
  refresh();
  loadAlerts();
  stopFromHash();
})();
