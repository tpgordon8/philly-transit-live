/* js/landmarks.js: well-known Philadelphia places for the address suggestions (ARCHITECTURE.md section 15.1).
   One string per place, "name|aliases (comma separated)|address|lat|lng". Coordinates were checked against OpenStreetMap
   (Nominatim, with Photon as a cross-check) and are the point OpenStreetMap gives for the place. Re-check them with
   `python3 tests/live_suggest.py --landmarks`. js/suggest.js parses the list. */
(function () {
  'use strict';
  var S = window.SEPTA;
  S.landmarks.LIST = [
    'Philadelphia City Hall|city hall,philly city hall|1 Penn Square, Philadelphia, PA|39.95240|-75.16299',
    '30th Street Station|thirtieth street station,philadelphia 30th street station,amtrak|2955 Market St, Philadelphia, PA|39.95528|-75.18214',
    'Suburban Station||1617 John F Kennedy Blvd, Philadelphia, PA|39.95430|-75.16856',
    'Jefferson Station|market east station|1001 Market St, Philadelphia, PA|39.95278|-75.15803',
    'Reading Terminal Market||51 N 12th St, Philadelphia, PA|39.95314|-75.15905',
    'Liberty Bell Center|liberty bell|526 Market St, Philadelphia, PA|39.94995|-75.15021',
    'Independence Hall||520 Chestnut St, Philadelphia, PA|39.94889|-75.15003',
    'Philadelphia Museum of Art|art museum,pma,rocky steps|2600 Benjamin Franklin Pkwy, Philadelphia, PA|39.96557|-75.18152',
    'Franklin Institute||222 N 20th St, Philadelphia, PA|39.95824|-75.17308',
    'LOVE Park|love park,jfk plaza|1599 John F Kennedy Blvd, Philadelphia, PA|39.95415|-75.16574',
    'Rittenhouse Square||210 W Rittenhouse Sq, Philadelphia, PA|39.94947|-75.17189',
    'Washington Square||210 W Washington Sq, Philadelphia, PA|39.94704|-75.15232',
    "Penn's Landing|penns landing|101 S Columbus Blvd, Philadelphia, PA|39.94622|-75.13963",
    'Lincoln Financial Field|the linc,eagles stadium|1 Lincoln Financial Field Way, Philadelphia, PA|39.90091|-75.16749',
    'Xfinity Mobile Arena (Wells Fargo Center)|wells fargo center,wells fargo,xfinity mobile arena,sixers arena,flyers arena|3601 S Broad St, Philadelphia, PA|39.90110|-75.17202',
    'Citizens Bank Park|phillies stadium|1 Citizens Bank Way, Philadelphia, PA|39.90592|-75.16648',
    'Philadelphia International Airport|phl,airport|8000 Essington Ave, Philadelphia, PA|39.87502|-75.23521',
    'University of Pennsylvania|upenn,penn,penn campus|University City, Philadelphia, PA|39.95221|-75.19557',
    'Drexel University||3141 Chestnut St, Philadelphia, PA|39.95453|-75.18657',
    'Temple University||1801 N Broad St, Philadelphia, PA|39.98119|-75.15628',
    'Italian Market|9th street italian market|9th St and Washington Ave, Philadelphia, PA|39.93901|-75.15784',
    'Eastern State Penitentiary||2027 Fairmount Ave, Philadelphia, PA|39.96834|-75.17266',
    'Please Touch Museum||4231 Avenue of the Republic, Philadelphia, PA|39.97947|-75.20913',
    'Philadelphia Zoo|philly zoo|3400 W Girard Ave, Philadelphia, PA|39.97173|-75.19599',
    'Barnes Foundation||2025 Benjamin Franklin Pkwy, Philadelphia, PA|39.96055|-75.17266',
    "Philadelphia's Magic Gardens|magic gardens|1020 South St, Philadelphia, PA|39.94277|-75.15941",
    'Franklin Square||200 N 6th St, Philadelphia, PA|39.95566|-75.15044',
    'Betsy Ross House||239 Arch St, Philadelphia, PA|39.95229|-75.14463',
    'Museum of the American Revolution||101 S 3rd St, Philadelphia, PA|39.94837|-75.14584',
    'National Constitution Center||525 Arch St, Philadelphia, PA|39.95355|-75.14916',
    'Boathouse Row||1 Boathouse Row, Philadelphia, PA|39.96941|-75.18711',
    'Kimmel Center|kimmel cultural campus,marian anderson hall|300 S Broad St, Philadelphia, PA|39.94675|-75.16574',
    'Pennsylvania Convention Center|convention center|1101 Arch St, Philadelphia, PA|39.95511|-75.16024',
    "Children's Hospital of Philadelphia|chop,childrens hospital|3401 Civic Center Blvd, Philadelphia, PA|39.94770|-75.19498",
    'Hospital of the University of Pennsylvania|hup,penn hospital|3400 Spruce St, Philadelphia, PA|39.94995|-75.19410',
    'Thomas Jefferson University Hospital|jefferson hospital|111 S 11th St, Philadelphia, PA|39.94928|-75.15803',
    'Penn Museum|university of pennsylvania museum|3260 South St, Philadelphia, PA|39.94929|-75.19203',
    'Fashion District Philadelphia|the gallery,fashion district|901 Market St, Philadelphia, PA|39.95199|-75.15583',
    'Dilworth Park|dilworth plaza|1 S 15th St, Philadelphia, PA|39.95288|-75.16465',
    'Fairmount Water Works|water works|640 Waterworks Dr, Philadelphia, PA|39.96672|-75.18346',
    '69th Street Transportation Center|69th street terminal,69th street station|6901 Market St, Upper Darby, PA|39.96224|-75.25933',
    'Frankford Transportation Center|frankford terminal|5200 Frankford Ave, Philadelphia, PA|40.02281|-75.07813',
    'Chinatown Friendship Gate|chinatown gate|10th and Arch St, Philadelphia, PA|39.95372|-75.15627'
  ];
})();
