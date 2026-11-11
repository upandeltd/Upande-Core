/* Replay a tile's animated mark when the tile is hovered. The marks (public/images/upande-*-logo.svg, Work Management's and
   Irrigation's too) play once when they load, and the desk never loads them again; changing the query string makes the
   browser start the picture afresh. A tile that is still playing is left alone. */
(function () {
  var SEL = 'img.app-icon, .desktop-icon img';
  var MARK = /\/assets\/[^/]+\/images\/[^?#]*(logo|cogs)[^?#]*\.svg/;
  var PLAY_MS = 2600;
  var busy = new WeakMap();

  function replay(img) {
    var src = img.getAttribute('src') || '';
    if (!MARK.test(src)) return;
    var last = busy.get(img) || 0;
    if (Date.now() - last < PLAY_MS) return;
    busy.set(img, Date.now());
    img.setAttribute('src', src.replace(/[?#].*$/, '') + '?play=' + Date.now());
  }

  document.addEventListener('mouseover', function (e) {
    var tile = e.target && e.target.closest ? e.target.closest('.desktop-icon') : null;
    if (!tile) return;
    var img = tile.querySelector(SEL);
    if (img) replay(img);
  });
})();
