'use strict';

// Carte de France cliquable par région (écran de saisie) : sélectionner une
// région affiche ses communes de plus de 10 000 habitants, cliquer une
// commune remplit le formulaire de recherche existant. La barre de
// recherche reste l'entrée principale — cette carte est une seconde façon
// d'arriver au même résultat, pas un remplacement.

function _eachCoord(coords, cb) {
  if (typeof coords[0] === 'number') {
    cb(coords);
    return;
  }
  coords.forEach((c) => _eachCoord(c, cb));
}

function _computeBounds(features) {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  features.forEach((f) => {
    _eachCoord(f.geometry.coordinates, ([lon, lat]) => {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    });
  });
  return { minLon, maxLon, minLat, maxLat };
}

async function initFranceMap({ svgEl, hintEl, panelEl, panelHeadEl, panelListEl, onSelectCommune }) {
  let geojson;
  let communes;
  try {
    [geojson, communes] = await Promise.all([
      fetch('/data/regions.geojson').then((r) => r.json()),
      fetch('/api/communes').then((r) => r.json()),
    ]);
  } catch (err) {
    hintEl.textContent = "Carte indisponible pour l'instant — utilise la recherche ci-contre.";
    return;
  }

  const bounds = _computeBounds(geojson.features);
  const midLatRad = ((bounds.minLat + bounds.maxLat) / 2) * (Math.PI / 180);
  const cosLat = Math.cos(midLatRad);
  const spanX = (bounds.maxLon - bounds.minLon) * cosLat;
  const spanY = bounds.maxLat - bounds.minLat;
  const viewW = 600;
  const pad = 12;
  const viewH = Math.round((viewW * spanY) / spanX);
  const scale = Math.min((viewW - 2 * pad) / spanX, (viewH - 2 * pad) / spanY);

  const project = ([lon, lat]) => {
    const x = pad + (lon - bounds.minLon) * cosLat * scale;
    const y = pad + (bounds.maxLat - lat) * scale;
    return [x, y];
  };

  const ringPath = (ring) =>
    ring
      .map((pt, i) => {
        const [x, y] = project(pt);
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ') + 'Z';

  const geometryPath = (geometry) => {
    if (geometry.type === 'Polygon') {
      return geometry.coordinates.map(ringPath).join(' ');
    }
    if (geometry.type === 'MultiPolygon') {
      return geometry.coordinates.map((poly) => poly.map(ringPath).join(' ')).join(' ');
    }
    return '';
  };

  const communesByRegion = {};
  communes.forEach((c) => {
    if (!communesByRegion[c.code_region]) communesByRegion[c.code_region] = [];
    communesByRegion[c.code_region].push(c);
  });
  Object.values(communesByRegion).forEach((list) => list.sort((a, b) => b.population - a.population));

  svgEl.setAttribute('viewBox', `0 0 ${viewW} ${viewH}`);
  const svgNS = 'http://www.w3.org/2000/svg';

  geojson.features.forEach((feature) => {
    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', geometryPath(feature.geometry));
    path.setAttribute('class', 'region-path');
    path.dataset.code = feature.properties.code;
    path.dataset.nom = feature.properties.nom;
    path.addEventListener('click', () => selectRegion(feature.properties.code, feature.properties.nom));
    svgEl.appendChild(path);
  });

  function selectRegion(code, nom) {
    svgEl.querySelectorAll('.region-path').forEach((p) => {
      p.classList.toggle('active', p.dataset.code === code);
    });
    const list = communesByRegion[code] || [];
    renderPanel(nom, list);
  }

  function renderPanel(nom, list) {
    panelHeadEl.textContent = `${list.length} commune${list.length > 1 ? 's' : ''} · ${nom}`;
    panelListEl.innerHTML = list
      .map(
        (c) => `
        <button class="commune-item" data-nom="${_escapeAttr(c.nom)}" data-cp="${_escapeAttr(c.code_postal || '')}">
          <span>${_escapeHtml(c.nom)}</span>
          <span class="pop">${(c.population || 0).toLocaleString('fr-FR')} hab.</span>
        </button>`
      )
      .join('');
    panelListEl.querySelectorAll('.commune-item').forEach((btn) => {
      btn.addEventListener('click', () => onSelectCommune(btn.dataset.nom, btn.dataset.cp));
    });
    panelEl.classList.remove('hidden');
  }
}

function _escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function _escapeAttr(str) {
  return _escapeHtml(str).replace(/"/g, '&quot;');
}

document.addEventListener('DOMContentLoaded', () => {
  const svgEl = document.getElementById('france-map');
  if (!svgEl) return;
  initFranceMap({
    svgEl,
    hintEl: document.getElementById('map-hint'),
    panelEl: document.getElementById('commune-panel'),
    panelHeadEl: document.getElementById('commune-panel-head'),
    panelListEl: document.getElementById('commune-panel-list'),
    onSelectCommune: (nom, codePostal) => {
      const villeEl = document.getElementById('input-ville');
      const cpEl = document.getElementById('input-cp');
      if (villeEl) villeEl.value = nom;
      if (cpEl) cpEl.value = codePostal;
      villeEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },
  });
});
