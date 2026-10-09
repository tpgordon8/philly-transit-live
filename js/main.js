/* js/main.js: test hook and application start. Part of the classic-script split of index.html (ARCHITECTURE.md section 14). */ /*@split*/
(function(){/*@split*/
'use strict';/*@split*/
var S=window.SEPTA;/*@split*/
var angDiff=S.util.angDiff,bearing=S.util.bearing,cardinal=S.util.cardinal,distMi=S.util.distMi,esc=S.util.esc,lateInfo=S.util.lateInfo;/*@split*/
var lateVal=S.util.lateVal,parseSeptaDate=S.util.parseSeptaDate;/*@split*/
var alertKey=S.feed.alertKey,normBuses=S.feed.normBuses,normTrains=S.feed.normTrains;/*@split*/
var etaFor=S.stops.etaFor,speedHist=S.stops.speedHist,speedMps=S.stops.speedMps,updateSpeedHist=S.stops.updateSpeedHist;/*@split*/
var evalRule=S.alerts.evalRule;/*@split*/
var TP=S.planner.TP,buildBusCandidates=S.planner.buildBusCandidates,buildNetIndex=S.planner.buildNetIndex,estimateTotal=S.planner.estimateTotal;/*@split*/
var loadIndego=S.planner.loadIndego,loadNetwork=S.planner.loadNetwork,nearbyStations=S.planner.nearbyStations,nearbyStops=S.planner.nearbyStops;/*@split*/
var planTrips=S.planner.planTrips,resetPlannerCaches=S.planner.resetPlannerCaches,routeLeg=S.planner.routeLeg,waitAtStop=S.planner.waitAtStop;/*@split*/
if(typeof window!=='undefined'&&window.__SEPTA_TEST__){
  window.__SEPTA_TEST__={normBuses:normBuses,normTrains:normTrains,lateVal:lateVal,lateInfo:lateInfo,cardinal:cardinal,distMi:distMi,bearing:bearing,angDiff:angDiff,parseSeptaDate:parseSeptaDate,alertKey:alertKey,esc:esc,etaFor:etaFor,speedMps:speedMps,updateSpeedHist:updateSpeedHist,speedHist:speedHist,evalRule:evalRule,
    planTrips:planTrips,routeLeg:routeLeg,loadNetwork:loadNetwork,loadIndego:loadIndego,nearbyStops:nearbyStops,nearbyStations:nearbyStations,waitAtStop:waitAtStop,
    resetPlannerCaches:resetPlannerCaches,buildBusCandidates:buildBusCandidates,estimateTotal:estimateTotal,buildNetIndex:buildNetIndex,TP:TP};
}
if(typeof document==='undefined')return;
S.started=true;/*@split*/
if(S.halt)return;/*@split*/
var $=S.util.$,state=S.util.state;/*@split*/
var refresh=S.feed.refresh;/*@split*/
var drawCenter=S.ui.drawCenter,drawHome=S.ui.drawHome,map=S.ui.map,renderPlaces=S.ui.renderPlaces,syncModeChips=S.ui.syncModeChips;/*@split*/
var updateSaveForm=S.ui.updateSaveForm;/*@split*/
var stopFromHash=S.stops.stopFromHash;/*@split*/
var loadAlerts=S.alerts.loadAlerts,renderAlerts=S.alerts.renderAlerts,renderNotify=S.alerts.renderNotify,renderRules=S.alerts.renderRules;/*@split*/
var radiusCircle={getBounds:function(){return S.ui.radiusCircleBounds()}};/*@split*/
if(window.__SEPTA_TEST__&&typeof window.__SEPTA_TEST__==='object')window.__SEPTA_TEST__.tripMap=map; /* test hook: read centre and zoom */
/* ----- Boot ----- */
$('#radius').value=state.radius;$('#radiusOut').textContent=state.radius+' mi';
syncModeChips();drawCenter();drawHome();renderPlaces();updateSaveForm();renderAlerts();
map.fitBounds(radiusCircle.getBounds(),{padding:[24,24],animate:false});
renderRules();renderNotify();
refresh();loadAlerts();
stopFromHash();
})();/*@split*/
