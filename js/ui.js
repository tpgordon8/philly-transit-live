/* js/ui.js: map, vehicle markers, status line, vehicle detail panel, location search and saved places. Part of the classic-script split of index.html (ARCHITECTURE.md section 14). */ /*@split*/
(function(){/*@split*/
'use strict';/*@split*/
var S=window.SEPTA;/*@split*/
function closeStop(){return S.stops.closeStop.apply(null,arguments)}/*@split*/
function openStop(){return S.stops.openStop.apply(null,arguments)}/*@split*/
function tripRenderPlaces(){return S.trip.tripRenderPlaces.apply(null,arguments)}/*@split*/
if(S.halt)return;/*@split*/
var $=S.util.$,CARD=S.util.CARD,CARD_LONG=S.util.CARD_LONG,DROP_AFTER_MS=S.util.DROP_AFTER_MS,MODE_NAME=S.util.MODE_NAME,PHILLY=S.util.PHILLY;/*@split*/
var SEATS=S.util.SEATS,angDiff=S.util.angDiff,bearing=S.util.bearing,cardinal=S.util.cardinal,distMi=S.util.distMi,el=S.util.el,esc=S.util.esc;/*@split*/
var fmtMi=S.util.fmtMi,hideBanner=S.util.hideBanner,isStarred=S.util.isStarred,lateInfo=S.util.lateInfo,routeFilterOn=S.util.routeFilterOn;/*@split*/
var routesStore=S.util.routesStore,saveRoutes=S.util.saveRoutes,showBanner=S.util.showBanner,starKey=S.util.starKey,state=S.util.state;/*@split*/
var store=S.util.store;/*@split*/
var apply=S.feed.apply,collect=S.feed.collect,refresh=S.feed.refresh,wantedSources=S.feed.wantedSources;/*@split*/
/* The center written to localStorage. A stop link moves state.center for this session only, so savePrefs
   writes savedCenter, which only setCenter() without noSave updates. */
var savedCenter=state.center;
function savePrefs(){store.set('septa.prefs.v1',{center:savedCenter,radius:state.radius,filters:state.filters})}
/* ----- Map ----- */
var map=L.map('map',{zoomControl:false,markerZoomAnimation:false,attributionControl:true}).setView([state.center.lat,state.center.lng],14);
L.control.zoom({position:'bottomright'}).addTo(map);
map.attributionControl.setPrefix(false);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
var mapEl=map.getContainer(),glideTimer;
function noGlide(){mapEl.classList.add('noglide');clearTimeout(glideTimer);glideTimer=setTimeout(function(){mapEl.classList.remove('noglide')},700)}
function glideSoon(){clearTimeout(glideTimer);glideTimer=setTimeout(function(){mapEl.classList.remove('noglide')},160)}
map.on('zoomstart viewreset resize',noGlide);
map.on('zoomend',glideSoon);
var radiusCircle=null,centerPin=null,homePin=null,gmhLine=null;
function drawCenter(){
  var ll=[state.center.lat,state.center.lng],m=state.radius*1609.344;
  if(!radiusCircle){radiusCircle=L.circle(ll,{radius:m,className:'rad',interactive:false}).addTo(map)}
  else{radiusCircle.setLatLng(ll);radiusCircle.setRadius(m)}
  if(!centerPin){centerPin=L.marker(ll,{icon:L.divIcon({className:'pin',html:'<span class="me"></span>',iconSize:[18,18],iconAnchor:[9,9]}),interactive:false,keyboard:false,zIndexOffset:-500}).addTo(map)}
  else centerPin.setLatLng(ll);
}
function drawHome(){
  var h=state.places.home;
  if(homePin){homePin.remove();homePin=null}
  if(h){homePin=L.marker([h.lat,h.lng],{icon:L.divIcon({className:'pin',html:'<span class="hm">H</span>',iconSize:[26,26],iconAnchor:[13,13]}),title:'Home: '+h.name,keyboard:false,zIndexOffset:-400}).addTo(map)}
}
function fitRadius(){map.fitBounds(radiusCircle.getBounds(),{padding:[24,24],animate:true})}
/* ----- Markers ----- */
var markers=new Map();
function shapeSVG(kind){
  if(kind==='train'||kind==='subway'){
    return '<svg class="vb" width="64" height="40" viewBox="0 0 64 40" aria-hidden="true">'+
      '<line class="ln" x1="2" y1="37" x2="62" y2="37"/>'+
      '<path class="bd" d="M10 8H44Q56 8 60 22V31H6V12Q6 8 10 8Z"/>'+
      '<rect class="wn" x="10" y="11" width="7" height="5" rx="1"/><rect class="wn" x="20" y="11" width="7" height="5" rx="1"/><rect class="wn" x="30" y="11" width="7" height="5" rx="1"/><rect class="wn" x="40" y="11" width="7" height="5" rx="1"/>'+
      '<circle class="hl" cx="57" cy="25" r="2"/>'+
      '<circle class="wh" cx="15" cy="33" r="3"/><circle class="wh" cx="26" cy="33" r="3"/><circle class="wh" cx="43" cy="33" r="3"/><circle class="wh" cx="54" cy="33" r="3"/></svg>';
  }
  return '<svg class="vb" width="64" height="40" viewBox="0 0 64 40" aria-hidden="true">'+
    (kind==='trolley'?'<path class="pole" d="M22 8L40 0"/>':'')+
    '<rect class="bd" x="8" y="8" width="48" height="24" rx="7"/>'+
    '<rect class="wn" x="12" y="10.5" width="8" height="4" rx="1"/><rect class="wn" x="23" y="10.5" width="8" height="4" rx="1"/><rect class="wn" x="34" y="10.5" width="8" height="4" rx="1"/><rect class="wn" x="45" y="10.5" width="8" height="4" rx="1"/>'+
    '<rect class="hl" x="54" y="24" width="3" height="4" rx="1"/>'+
    '<circle class="wh" cx="19" cy="33" r="3.6"/><circle class="wh" cx="45" cy="33" r="3.6"/></svg>';
}
function vehInner(v){
  var c=cardinal(v.heading);
  return shapeSVG(v.kind)+'<span class="rt">'+esc(v.badge)+'</span><span class="dr'+(c?'':' none')+'">'+(c||'?')+'</span>';
}
function vehSig(v){return v.kind+'|'+v.badge+'|'+(cardinal(v.heading)||'')}
/* Accessible name for a marker, e.g. "Route 12 bus heading S, 2 min late". lateInfo() already turns 999 into words. */
function vehLabel(v){
  var c=cardinal(v.heading);
  var nm=v.kind==='train'?'Regional Rail train '+v.badge+(v.route?' '+v.route:''):'Route '+v.badge+' '+MODE_NAME[v.kind].toLowerCase();
  return nm+(c?' heading '+c:'')+', '+lateInfo(v.late).txt.toLowerCase();
}
function vehTitle(v){return (v.kind==='train'?'Train '+v.badge+' · '+v.route:'Route '+v.badge+' '+MODE_NAME[v.kind].toLowerCase())}
function syncMarkers(list){
  var keep=new Set();
  list.forEach(function(v){
    keep.add(v.key);
    var m=markers.get(v.key);
    if(!m){
      m=L.marker([v.lat,v.lng],{icon:L.divIcon({className:'veh-wrap k-'+v.kind,html:vehInner(v),iconSize:[80,44],iconAnchor:[40,22]}),title:vehTitle(v),keyboard:true,riseOnHover:true});
      m.on('click',function(){select(v.key)});
      m.addTo(map);markers.set(v.key,m);
      var e0=m.getElement();
      if(e0){
        e0.dataset.sig=vehSig(v);
        e0.setAttribute('role','button');
        /* Leaflet markers take focus but ignore Enter and Space; selecting is what a click does. */
        e0.addEventListener('keydown',function(e){
          if(e.key==='Enter'||e.key===' '||e.key==='Spacebar'){e.preventDefault();e.stopPropagation();select(v.key,{focus:true})}
        });
      }
    }else{
      var ll=m.getLatLng();
      /* setLatLng moves the existing element, so the CSS transition glides it. Zoom and pan are untouched. */
      if(ll.lat!==v.lat||ll.lng!==v.lng)m.setLatLng([v.lat,v.lng]);
      var el=m.getElement();
      if(el&&el.dataset.sig!==vehSig(v)){
        el.className=el.className.replace(/\bk-(bus|trolley|subway|train)\b/g,'')+' k-'+v.kind;
        el.innerHTML=vehInner(v);el.dataset.sig=vehSig(v);
      }
    }
    var el2=m.getElement();
    if(el2){
      var lbl=vehLabel(v);if(el2.getAttribute('aria-label')!==lbl)el2.setAttribute('aria-label',lbl);
      el2.classList.toggle('stale',!!v.stale);
      el2.classList.toggle('sel',state.selected===v.key);
    }
    m.setZIndexOffset(state.selected===v.key?1000:0);
  });
  markers.forEach(function(m,k){if(!keep.has(k)){m.remove();markers.delete(k)}});
}
$('#empty').addEventListener('click',function(e){
  var b=e.target.closest('#emptyAct');if(!b)return;
  if(b.dataset.act==='widen'){setRadius(Math.min(5,state.radius+1.5),true)}
  else if(b.dataset.act==='routes'){routesStore.onlyMine=false;saveRoutes();clearSelection();apply()}
  else{state.filters={bus:true,trolley:true,subway:true,train:true};syncModeChips();savePrefs();apply()}
});
/* ----- My routes ----- */
function clearSelection(){
  state.selected=null;
  markers.forEach(function(m){var e=m.getElement();if(e)e.classList.remove('sel')});
  var lv=$('#detailLive');if(lv&&lv.textContent)lv.textContent='';
  renderDetail();
}
function toggleStar(k){
  var i=routesStore.stars.indexOf(k);
  if(i>=0)routesStore.stars.splice(i,1);else routesStore.stars.push(k);
  saveRoutes();
  /* Unstarring the open vehicle's route while the filter is on hides it; close the card instead of calling it "not reporting". */
  if(i>=0&&routeFilterOn()&&state.selected)clearSelection();
  apply();
}
function starName(k){return k.indexOf('train:')===0?k.slice(6):(k.indexOf('subway:')===0?k.slice(7):k)}
function renderMyRoutes(){
  var box=$('#myRoutes'),st=routesStore.stars;
  box.replaceChildren();
  if(!st.length){box.appendChild(el('p','hint','Tap a vehicle, then star its route to build your own view.'));return}
  var t=el('button','btn small','');t.type='button';t.id='myToggle';
  t.setAttribute('aria-pressed',routesStore.onlyMine?'true':'false');
  t.textContent=routesStore.onlyMine?'Showing my routes ('+st.length+')':'Showing all routes';
  box.appendChild(t);
  var list=el('div','mylist');
  st.forEach(function(k){
    var c=el('span','chip on'),n=starName(k);
    c.appendChild(el('span',null,k.indexOf('train:')===0?n+' line':n));
    var rm=el('button','btn small ghost','\u00d7');rm.type='button';rm.dataset.remove=k;
    rm.setAttribute('aria-label','Remove route '+n+' from my routes');
    c.appendChild(rm);list.appendChild(c);
  });
  box.appendChild(list);
}
$('#myRoutes').addEventListener('click',function(e){
  if(e.target.closest('#myToggle')){routesStore.onlyMine=!routesStore.onlyMine;saveRoutes();clearSelection();apply();return}
  var rm=e.target.closest('[data-remove]');
  if(rm){toggleStar(rm.dataset.remove)}
});
/* ----- Status line + banner ----- */
function srcState(sr,now){
  if(!sr.err)return 'ok';
  if(sr.ok&&now-sr.ok<=DROP_AFTER_MS)return 'stale';
  return 'down';
}
/* Screen readers get a polite announcement only when the state or the vehicle count changes; the ticking
   "updated Ns ago" text in #statusText is aria-hidden and never announced. */
function syncStatusLive(){
  var d=$('#dot').className,n=state.visible.length,t;
  if(state.paused)t='Paused';
  else if(d.indexOf('live')>=0)t='Live, '+n+' vehicle'+(n===1?'':'s')+' shown';
  else if(d.indexOf('stale')>=0)t='Stale, showing last known positions';
  else if(d.indexOf('err')>=0)t='Live data unavailable';
  else t='Connecting to SEPTA';
  var o=$('#statusLive');if(o.textContent!==t)o.textContent=t;
}
function renderStatus(){renderStatusView();syncStatusLive()}
function renderStatusView(){
  var dot=$('#dot'),txt=$('#statusText'),b=state.src.bus,t=state.src.train,now=Date.now();
  if(state.paused){dot.className='dot';txt.innerHTML='<b>Paused</b>';hideBanner();return}
  var w=wantedSources(),act=['bus','train'].filter(function(k){return w[k]});
  var st={},stale=[],down=[];
  act.forEach(function(k){st[k]=srcState(state.src[k],now);if(st[k]==='stale')stale.push(k);else if(st[k]==='down')down.push(k)});
  var n=state.visible.length;
  if(!b.ok&&!t.ok&&!b.err&&!t.err&&!state.fetchedAt){dot.className='dot';txt.textContent='Connecting to SEPTA…';return}
  if(!act.length){dot.className='dot live';txt.innerHTML='<b>Paused</b> · no vehicle types selected';hideBanner();return}
  if(down.length===act.length){
    dot.className='dot err';
    txt.innerHTML='<b>Live data unavailable</b>';
    showBanner('','<b>Live data unavailable.</b> Couldn\'t reach SEPTA\'s API through the proxy. No vehicle positions are shown, and none are guessed. Retrying automatically.');
    return;
  }
  if(stale.length||down.length){
    var parts=[];
    if(stale.length){
      var which=stale.map(function(k){return k==='bus'?'buses, trolleys and subway':'Regional Rail'}).join(' and ');
      parts.push('<b>Showing last known positions for '+esc(which)+'.</b> The latest refresh failed, so those markers are dimmed and will clear after 2 minutes.');
    }
    if(down.length){
      var gone=down.map(function(k){return k==='bus'?'Bus and trolley':'Regional Rail'}).join(' and ');
      parts.push('<b>'+esc(gone)+' positions are unavailable.</b> No updates for over 2 minutes, so nothing is drawn for '+(down.length>1?'them':(down[0]==='bus'?'them (subway lines come from the same feed)':'it'))+'.');
    }
    if(stale.length){
      var newest=Math.max.apply(null,stale.map(function(k){return state.src[k].ok})),ago0=Math.max(0,Math.round((now-newest)/1000));
      dot.className='dot stale';
      txt.innerHTML='<b>Stale</b> · last good update '+ago0+'s ago';
    }else{
      dot.className='dot stale';
      txt.innerHTML='<b>Partial</b> · '+n+' vehicle'+(n===1?'':'s')+' shown';
    }
    showBanner('warn',parts.join(' '));
    return;
  }
  var ago=Math.max(0,Math.round((now-Math.max(b.ok,t.ok))/1000));
  hideBanner();
  dot.className='dot live';
  txt.innerHTML='<b>Live</b> · updated '+ago+'s ago · '+n+' vehicle'+(n===1?'':'s')+' shown';
}
/* ----- Detail card ----- */
function findVehicle(k){
  var l=state.src.bus.list.concat(state.src.train.list);
  for(var i=0;i<l.length;i++)if(l[i].key===k)return l[i];
  return null;
}
var NARROW=window.matchMedia('(max-width:820px)');
function select(k,opts){
  state.selected=k;
  markers.forEach(function(m,key){var e=m.getElement();if(e)e.classList.toggle('sel',key===k);m.setZIndexOffset(key===k?1000:0)});
  renderDetail();
  var v=findVehicle(k);
  /* The card is not a live region (it is rebuilt on every refresh). Opening it is announced once, here. */
  if(v)$('#detailLive').textContent=vehLabel(v)+'. Vehicle details opened.';
  if(opts&&opts.focus){var h=$('#detailHead');if(h)h.focus()}
  if(NARROW.matches)panAboveCard(k);
}
/* On a phone the vehicle card covers most of the short map. Pan (once, on selection only) so the selected marker
   sits in the strip between the top of the map (or the banner) and the top of the card. Zoom is untouched. */
function panAboveCard(k){
  var m=markers.get(k),card=$('#detail');
  if(!m||card.hidden)return;
  var mr=mapEl.getBoundingClientRect(),cr=card.getBoundingClientRect(),ban=$('#banner');
  var top=4,bottom=cr.top-mr.top-4,half=22;
  if(!ban.hidden)top=Math.max(top,ban.getBoundingClientRect().bottom-mr.top+4);
  var lo=top+half,hi=bottom-half;
  if(hi<lo)hi=lo=(top+bottom)/2; /* strip smaller than a marker: centre it in what is left */
  var p=map.latLngToContainerPoint(m.getLatLng());
  var cy=p.y<lo||p.y>hi?(lo+hi)/2:p.y;
  var cx=Math.min(Math.max(p.x,44),mr.width-44);
  var dx=Math.round(p.x-cx),dy=Math.round(p.y-cy);
  if(dx||dy)map.panBy([dx,dy],{animate:!window.matchMedia('(prefers-reduced-motion: reduce)').matches});
}
function addRow(dl,label,node){
  var dt=el('dt',null,label),dd=el('dd');
  if(typeof node==='string')dd.textContent=node;else dd.appendChild(node);
  dl.appendChild(dt);dl.appendChild(dd);
}
/* The card is rebuilt on every refresh; keep keyboard focus on the same control (matched by id) across the rebuild. */
function renderDetail(){
  var box=$('#detail'),ae=document.activeElement,fid=ae&&ae!==document.body&&box.contains(ae)?ae.id:'';
  buildDetail();
  if(fid){var n=box.querySelector('#'+fid);if(n&&n!==document.activeElement)n.focus({preventScroll:true})}
}
function buildDetail(){
  var box=$('#detail');
  if(!state.selected){box.hidden=true;return}
  var v=findVehicle(state.selected);
  box.hidden=false;box.replaceChildren();
  var head=el('div','dh');
  var close=el('button','btn small ghost','Close');close.type='button';close.id='detailClose';close.setAttribute('aria-label','Close vehicle details');
  close.addEventListener('click',closeDetailFocus);
  if(!v){
    var t0=el('div','dt'),h0=el('b',null,'Vehicle not reporting');h0.id='detailHead';h0.tabIndex=-1;t0.appendChild(h0);t0.appendChild(el('span',null,'It has no recent GPS report.'));
    head.appendChild(t0);head.appendChild(close);box.appendChild(head);
    box.appendChild(el('div','gone','This vehicle stopped sending a live position, so it was removed from the map.'));
    return;
  }
  var badge=el('span','rbadge k-'+v.kind,v.badge);
  var dt=el('div','dt');
  var hd=el('b',null,v.kind==='train'?(v.route||'Regional Rail'):'Route '+v.route);hd.id='detailHead';hd.tabIndex=-1;
  dt.appendChild(hd);
  dt.appendChild(el('span',null,v.kind==='train'?'Regional Rail · Train '+v.badge:MODE_NAME[v.kind]+(v.vid?' · Vehicle '+v.vid:'')));
  var sk=starKey(v),starred=isStarred(sk),rn=starName(sk);
  var star=el('button','btn small',starred?'Starred':'Star route');star.type='button';star.id='starBtn';
  star.setAttribute('aria-pressed',starred?'true':'false');
  star.setAttribute('aria-label',(starred?'Unstar route ':'Star route ')+rn);
  star.addEventListener('click',function(){toggleStar(sk);var b=$('#starBtn');if(b)b.focus()});
  head.appendChild(badge);head.appendChild(dt);head.appendChild(star);head.appendChild(close);box.appendChild(head);
  var dl=el('dl'),c=cardinal(v.heading);
  var dirTxt=(v.direction?v.direction:'Direction not reported')+(c?' · heading '+c+' ('+Math.round(v.heading)+'°)':' · heading unavailable');
  addRow(dl,'Direction',dirTxt);
  addRow(dl,'Destination',v.dest||'Not reported');
  if(v.kind==='train'&&v.cur)addRow(dl,'Last station',v.cur);
  var nextNode=v.next||'Not reported';
  if((v.kind==='bus'||v.kind==='trolley')&&v.nextId&&/^[0-9]{1,8}$/.test(v.nextId)){
    nextNode=el('span');nextNode.appendChild(document.createTextNode((v.next||'Not reported')+' '));
    var vs=el('button','btn small','View stop');vs.type='button';vs.id='viewStop';
    vs.addEventListener('click',function(){
      /* On a phone the stop card is hidden while the vehicle card is open, so close the vehicle card to show it. */
      if(NARROW.matches)clearSelection();
      openStop(v.route,v.nextId,{focus:true,opener:vs});
    });
    nextNode.appendChild(vs);
  }
  addRow(dl,'Next stop',nextNode);
  var li=lateInfo(v.late),pill=el('span','pill '+li.cls,li.txt);
  addRow(dl,'Schedule',pill);
  if(v.kind==='train'){
    if(v.service)addRow(dl,'Service',v.service.charAt(0)+v.service.slice(1).toLowerCase());
    if(v.track)addRow(dl,'Track',v.track);
  }else if(v.seats){
    addRow(dl,'Crowding',SEATS[v.seats]||v.seats.replace(/_/g,' ').toLowerCase());
  }
  if(v.kind!=='train'){
    var live=state.src.bus.stale?'Last report is stale':'GPS fix about '+Math.max(0,Math.round(v.age+(Date.now()-state.src.bus.ok)/1000))+' s old';
    addRow(dl,'Position',live);
  }else{
    addRow(dl,'Position','Live from SEPTA TrainView (no timestamp provided)');
  }
  box.appendChild(dl);
}
/* Closing from the keyboard returns focus to the marker, so it does not fall back to the top of the page. */
function closeDetailFocus(){
  var k=state.selected,had=$('#detail').contains(document.activeElement);
  clearSelection();
  if(had){var m=markers.get(k),e=m&&m.getElement();if(e)e.focus({preventScroll:true})}
}
map.on('click',function(){if(state.selected)clearSelection()});
/* One Escape closes one thing: the stop card when focus is in it, else the vehicle card, else (focus on the page or map) the stop card. */
document.addEventListener('keydown',function(e){
  if(e.key!=='Escape'||e.defaultPrevented)return;
  var a=document.activeElement;
  if(state.stop&&$('#stopCard').contains(a)){closeStop();return}
  if(state.selected){closeDetailFocus();return}
  if(state.stop&&(a===document.body||mapEl.contains(a)))closeStop();
});
/* ----- Search, location, radius, modes ----- */
function setNote(msg,bad){var n=$('#note');n.textContent=msg||'';n.className='note'+(bad?' bad':'')}
function setCenter(c,fit,noSave){
  state.center={lat:c.lat,lng:c.lng,label:c.label||''};
  if(!noSave){savedCenter=state.center;savePrefs()}
  drawCenter();
  if(fit)fitRadius();
  updateSaveForm();apply();
}
function setRadius(r,fit){
  state.radius=r;$('#radius').value=r;$('#radiusOut').textContent=r+' mi';
  savePrefs();drawCenter();if(fit)fitRadius();apply();
}
$('#radius').addEventListener('input',function(e){
  var r=Number(e.target.value);state.radius=r;$('#radiusOut').textContent=r+' mi';drawCenter();apply();
});
$('#radius').addEventListener('change',function(e){setRadius(Number(e.target.value),true)});
function syncModeChips(){
  document.querySelectorAll('#modes .chip').forEach(function(ch){
    var inp=ch.querySelector('input');inp.checked=!!state.filters[inp.dataset.mode];ch.classList.toggle('on',inp.checked);
  });
}
$('#modes').addEventListener('change',function(e){
  var inp=e.target;if(!inp.dataset.mode)return;
  state.filters[inp.dataset.mode]=inp.checked;syncModeChips();savePrefs();apply();
});
function shortLabel(s){return String(s||'').split(',').slice(0,2).join(',').trim()}
/* Shared Nominatim lookup (Philadelphia viewbox, a preference rather than a bound: the trip planner checks the region itself).
   Resolves the first match {lat,lng,label} or null; rejects when the request fails. opts.philly appends ', Philadelphia, PA' to
   text without a comma (used by the trip planner only). Nominatim's policy allows about one request per second, so lookups start at
   least GEO_GAP_MS apart (the slot is reserved when called, so two quick calls queue), and answers, misses included, are kept in
   memory for the page session; failures are not kept. */
var GEO_URL='https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=us&viewbox=-75.80,40.30,-74.60,39.70&q=';
var GEO_GAP_MS=1100,geoNext=0,geoCache={};
function geocode(q,opts){
  if(opts&&opts.philly&&q.indexOf(',')<0)q+=', Philadelphia, PA';
  var key=q.trim().replace(/\s+/g,' ').toLowerCase();
  if(Object.prototype.hasOwnProperty.call(geoCache,key)){var c=geoCache[key];return Promise.resolve(c&&{lat:c.lat,lng:c.lng,label:c.label})}
  var now=Date.now(),at=Math.max(now,geoNext);
  if(at-now>GEO_GAP_MS*20)at=now;                       /* the clock moved backwards: do not wait for a stale slot */
  geoNext=at+GEO_GAP_MS;
  return new Promise(function(res){setTimeout(res,at-now)}).then(function(){
    return fetch(GEO_URL+encodeURIComponent(q),{headers:{'Accept':'application/json'}});
  }).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(function(res){
    var out=null;
    if(res.length){var r=res[0];out={lat:Number(r.lat),lng:Number(r.lon),label:shortLabel(r.display_name)}}
    geoCache[key]=out;
    return out&&{lat:out.lat,lng:out.lng,label:out.label};
  });
}
$('#searchForm').addEventListener('submit',function(e){
  e.preventDefault();
  var q=$('#addr').value.trim();
  if(!q){setNote('Type a street address or intersection first.',true);return}
  var btn=$('#btnSearch');btn.disabled=true;setNote('Looking up that address…');
  geocode(q).then(function(r){
    if(!r){setNote('No match for that address. Try adding a cross street or a ZIP code.',true);return}
    setNote('Showing vehicles near '+r.label+'.');
    setCenter({lat:r.lat,lng:r.lng,label:r.label},true);
  }).catch(function(){setNote('Address lookup failed. Check your connection and try again.',true)}).finally(function(){btn.disabled=false});
});
function getPosition(){
  return new Promise(function(res,rej){
    if(!navigator.geolocation){rej(new Error('unsupported'));return}
    navigator.geolocation.getCurrentPosition(res,rej,{enableHighAccuracy:true,timeout:9000,maximumAge:30000});
  });
}
$('#btnLocate').addEventListener('click',function(){
  var btn=$('#btnLocate');btn.disabled=true;setNote('Finding your location…');
  getPosition().then(function(p){
    setNote('Showing vehicles around your current location.');
    setCenter({lat:p.coords.latitude,lng:p.coords.longitude,label:'Your location'},true);
  }).catch(function(){
    setNote('Location isn\'t available here. Type an address instead.',true);
  }).finally(function(){btn.disabled=false});
});
/* ----- Saved places + Get me home ----- */
function persistPlaces(){store.set('septa.places.v1',state.places)}
function updateSaveForm(){
  var f=$('#saveForm'),has=state.center&&state.center!==PHILLY&&state.center.label!=='Center City (default view)';
  f.hidden=!has;
  if(has&&document.activeElement!==$('#placeName'))$('#placeName').value=state.center.label||'';
}
function savePlace(asHome){
  var name=$('#placeName').value.trim()||state.center.label||'Saved place';
  var p={id:'p'+Date.now(),name:name.slice(0,40),lat:state.center.lat,lng:state.center.lng};
  if(asHome){state.places.home={name:p.name,lat:p.lat,lng:p.lng}}
  else state.places.list.push(p);
  persistPlaces();renderPlaces();drawHome();
}
$('#btnSave').addEventListener('click',function(){savePlace(false)});
$('#btnSaveHome').addEventListener('click',function(){savePlace(true)});
function renderPlaces(){
  var ul=$('#places'),h=state.places.home;
  ul.replaceChildren();
  function goTo(p){setNote('');setCenter({lat:p.lat,lng:p.lng,label:p.name},true);$('#addr').value=''}
  if(h){
    var li=el('li');li.appendChild(el('span','tag','Home'));li.appendChild(el('span','nm',h.name));
    var go=el('button','btn small','Go');go.type='button';go.addEventListener('click',function(){goTo(h)});
    var rm=el('button','btn small ghost','Remove');rm.type='button';rm.setAttribute('aria-label','Remove Home');
    rm.addEventListener('click',function(){state.places.home=null;persistPlaces();renderPlaces();drawHome();$('#gmh').replaceChildren()});
    li.appendChild(go);li.appendChild(rm);ul.appendChild(li);
  }
  state.places.list.forEach(function(p){
    var li=el('li');li.appendChild(el('span','nm',p.name));
    var go=el('button','btn small','Go');go.type='button';go.addEventListener('click',function(){goTo(p)});
    var mk=el('button','btn small ghost','Make Home');mk.type='button';
    mk.addEventListener('click',function(){state.places.home={name:p.name,lat:p.lat,lng:p.lng};persistPlaces();renderPlaces();drawHome()});
    var rm=el('button','btn small ghost','Remove');rm.type='button';rm.setAttribute('aria-label','Remove '+p.name);
    rm.addEventListener('click',function(){state.places.list=state.places.list.filter(function(x){return x.id!==p.id});persistPlaces();renderPlaces()});
    li.appendChild(go);li.appendChild(mk);li.appendChild(rm);ul.appendChild(li);
  });
  $('#placesEmpty').hidden=!!(h||state.places.list.length);
  var hb=$('#btnHome');hb.hidden=!h;
  if(h)$('#homeName').textContent=h.name;
  tripRenderPlaces();
}
$('#btnHome').addEventListener('click',function(){getMeHome()});
function getMeHome(){
  var home=state.places.home;if(!home)return;
  var btn=$('#btnHome');btn.disabled=true;
  var origin=null,usedGps=false;
  getPosition().then(function(p){origin={lat:p.coords.latitude,lng:p.coords.longitude,label:'Your location'};usedGps=true}).catch(function(){origin={lat:state.center.lat,lng:state.center.lng,label:state.center.label||'the current search point'}})
  .then(function(){
    state.center={lat:origin.lat,lng:origin.lng,label:origin.label};savedCenter=state.center;savePrefs();drawCenter();updateSaveForm();
    return refresh();
  }).then(function(){
    var dHome=distMi(origin,home);
    if(gmhLine){gmhLine.remove();gmhLine=null}
    gmhLine=L.polyline([[origin.lat,origin.lng],[home.lat,home.lng]],{className:'gmhline',interactive:false}).addTo(map);
    map.fitBounds(L.latLngBounds([[origin.lat,origin.lng],[home.lat,home.lng]]).pad(0.25),{animate:true});
    var cands=collect().filter(function(v){
      if(v.stale||v.heading==null)return false;
      if(distMi(origin,v)>state.radius)return false;
      return angDiff(v.heading,bearing(v,home))<=50;
    }).sort(function(a,b){return distMi(origin,a)-distMi(origin,b)}).slice(0,6);
    renderGMH(origin,home,dHome,cands,usedGps);
    apply();
  }).finally(function(){btn.disabled=false});
}
function renderGMH(origin,home,dHome,cands,usedGps){
  var box=$('#gmh');box.replaceChildren();
  var wrap=el('div','gmh'),head=el('header');
  var dir=CARD[Math.round(bearing(origin,home)/45)%8];
  head.appendChild(document.createTextNode('Home is '+fmtMi(dHome)+' '+CARD_LONG[dir]+' of '+(usedGps?'you':origin.label)+'.'));
  head.appendChild(document.createElement('br'));
  var a=el('a',null,'Open transit directions ↗');
  a.href='https://www.google.com/maps/dir/?api=1&origin='+origin.lat+','+origin.lng+'&destination='+home.lat+','+home.lng+'&travelmode=transit';
  a.target='_blank';a.rel='noopener';head.appendChild(a);
  var pn=el('span','dir-note','Opens Google Maps with your start and Home locations.');pn.style.cssText='display:block;margin-top:2px;font-weight:400;font-size:12px;color:var(--mute)';head.appendChild(pn);wrap.appendChild(head);
  if(cands.length){
    var ol=el('ol');
    cands.forEach(function(v){
      var li=el('li'),b=el('button');b.type='button';
      b.appendChild(el('span','rbadge k-'+v.kind,v.badge));
      b.appendChild(el('span',null,'To '+(v.dest||'destination not reported')));
      var li2=lateInfo(v.late);
      b.appendChild(el('span','meta',fmtMi(distMi(origin,v))+' away · '+li2.txt+(v.next?' · next: '+v.next:'')));
      b.addEventListener('click',function(){map.panTo([v.lat,v.lng],{animate:true});select(v.key)});
      li.appendChild(b);ol.appendChild(li);
    });
    wrap.appendChild(ol);
    wrap.appendChild(el('div','fine','These are vehicles near you whose heading points toward Home. SEPTA\'s feed has no route shapes, so check the destination before you board.'));
  }else{
    wrap.appendChild(el('div','fine','No vehicle within '+state.radius+' mi is heading toward Home right now. Try a larger radius, or use the transit directions link.'));
  }
  if(!usedGps)wrap.appendChild(el('div','fine','Location wasn\'t available, so this used the current search point as your starting spot.'));
  box.appendChild(wrap);
}
S.ui.map=map;S.ui.mapEl=mapEl;S.ui.drawCenter=drawCenter;S.ui.drawHome=drawHome;S.ui.syncMarkers=syncMarkers;S.ui.renderMyRoutes=renderMyRoutes;/*@split*/
S.ui.renderStatus=renderStatus;S.ui.NARROW=NARROW;S.ui.select=select;S.ui.renderDetail=renderDetail;S.ui.setCenter=setCenter;/*@split*/
S.ui.syncModeChips=syncModeChips;S.ui.geocode=geocode;S.ui.getPosition=getPosition;S.ui.updateSaveForm=updateSaveForm;S.ui.renderPlaces=renderPlaces;/*@split*/
S.ui.radiusCircleBounds=function(){return radiusCircle.getBounds()};/*@split*/
})();/*@split*/
