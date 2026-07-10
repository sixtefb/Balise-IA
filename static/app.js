'use strict';

const QUALITY_STYLE = {
  alerte: { color: '#8f3826', bg: '#f3e2dc', bar: '#a5432f', text: 'Alerte' },
  a_surveiller: { color: '#92671a', bg: '#f4ecd8', bar: '#a9791f', text: 'À surveiller' },
  conforme: { color: '#565861', bg: '#eceae4', bar: '#565861', text: 'Conforme' },
  efficient: { color: '#2f5540', bg: '#e6efe9', bar: '#2f5540', text: 'Efficient' },
  donnee_absente: { color: '#9a9b9f', bg: '#eceae4', bar: '#d8d7d2', text: 'Donnée indisponible' },
};

const VERDICT_STYLE = {
  Efficace: { color: '#2f5540', bg: '#e6efe9' },
  Vigilance: { color: '#92671a', bg: '#f4ecd8' },
  Alerte: { color: '#a5432f', bg: '#f3e2dc' },
};

const LOADING_LABELS = [
  'Résolution de la commune (INSEE)',
  'Collecte des comptes publics (OFGL)',
  "Constitution du groupe de comparaison",
  'Calcul des écarts et du score',
];

const screens = {
  input: document.getElementById('screen-input'),
  loading: document.getElementById('screen-loading'),
  report: document.getElementById('screen-report'),
};

let lastReport = null;
let lastHistory = null;
let loadingTimer = null;

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => el.classList.toggle('hidden', key !== name));
}

function fmtEur(v) {
  if (v === null || v === undefined) return 'n/d';
  return Math.round(v).toLocaleString('fr-FR') + ' €';
}

function fmtPct(v) {
  if (v === null || v === undefined) return 'n/d';
  const pct = Math.round(v * 100);
  return (pct >= 0 ? '+' : '−') + Math.abs(pct) + '%';
}

function fmtPop(v) {
  if (v === null || v === undefined) return 'n/d';
  return Math.round(v).toLocaleString('fr-FR') + ' hab.';
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleDateString('fr-FR');
  } catch {
    return iso || '';
  }
}

function buildFreshnessLine(freshness) {
  if (!freshness) return '';
  const parts = [
    freshness.ofgl && `comptes OFGL récupérés le ${fmtDate(freshness.ofgl)}`,
    freshness.decp_marches && `marchés DECP récupérés le ${fmtDate(freshness.decp_marches)}`,
    freshness.decp_entretien && `poste "Entretien" récupéré le ${fmtDate(freshness.decp_entretien)}`,
  ].filter(Boolean);
  return parts.length ? `Fraîcheur des données — ${parts.join(' · ')}.` : '';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

// ---- Écran de saisie ----

document.getElementById('form-analyse').addEventListener('submit', (e) => {
  e.preventDefault();
  const ville = document.getElementById('input-ville').value.trim();
  const cp = document.getElementById('input-cp').value.trim();
  const annee = document.getElementById('input-annee').value.trim();
  const errorEl = document.getElementById('input-error');
  errorEl.classList.add('hidden');
  if (!ville || !cp) return;
  runAnalyse(ville, cp, annee);
});

// ---- Écran de chargement ----

function startLoadingAnimation(ville, cp) {
  document.getElementById('loading-subtitle').textContent = `${ville} · ${cp}`;
  document.getElementById('loading-error').classList.add('hidden');
  document.getElementById('btn-retry').classList.add('hidden');
  const stepsEl = document.getElementById('loading-steps');
  stepsEl.innerHTML = LOADING_LABELS.map((label, i) => `
    <div style="display:flex; align-items:center; gap:12px; padding:9px 0;" data-step="${i}">
      <span class="mono" style="width:19px; height:19px; border-radius:999px; display:flex; align-items:center; justify-content:center; font-size:11px; color:#fff; flex:none; background:#d8d7d2;"></span>
      <span style="font-size:14px; color:#a8a9af;">${label}</span>
    </div>
  `).join('');

  let step = 0;
  const render = () => {
    document.getElementById('loading-bar').style.width = `${(step / LOADING_LABELS.length) * 100}%`;
    stepsEl.querySelectorAll('[data-step]').forEach((row, i) => {
      const dot = row.querySelector('span.mono');
      const label = row.querySelector('span:last-child');
      const done = i < step;
      const active = i === step;
      dot.style.background = done ? '#2f5540' : (active ? '#2b3a4a' : '#d8d7d2');
      dot.textContent = done ? '✓' : '';
      label.style.color = done || active ? '#1c1d21' : '#a8a9af';
    });
  };
  render();
  loadingTimer = setInterval(() => {
    if (step < LOADING_LABELS.length - 1) {
      step += 1;
      render();
    }
  }, 700);
}

function stopLoadingAnimation() {
  if (loadingTimer) {
    clearInterval(loadingTimer);
    loadingTimer = null;
  }
}

// ---- Lancement de l'analyse ----

async function runAnalyse(ville, cp, annee) {
  showScreen('loading');
  startLoadingAnimation(ville, cp);
  try {
    let url = `/api/audit?commune=${encodeURIComponent(ville)}&code_postal=${encodeURIComponent(cp)}`;
    if (annee) url += `&exercice=${encodeURIComponent(annee)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `Erreur ${res.status}`);
    }
    stopLoadingAnimation();
    document.getElementById('loading-bar').style.width = '100%';
    lastReport = data;
    lastHistory = null;
    resetEvolutionSection();
    renderReport(data);
    showScreen('report');
  } catch (err) {
    stopLoadingAnimation();
    const errorEl = document.getElementById('loading-error');
    errorEl.textContent = `Échec de l'analyse : ${err.message}`;
    errorEl.classList.remove('hidden');
    document.getElementById('btn-retry').classList.remove('hidden');
  }
}

document.getElementById('btn-reset').addEventListener('click', () => {
  showScreen('input');
});

document.getElementById('btn-change-annee').addEventListener('click', async () => {
  if (!lastReport) return;
  const commune = lastReport.commune;
  const cp = commune.codes_postaux[0] || '';
  const yearRaw = document.getElementById('input-change-annee').value.trim();
  const errorEl = document.getElementById('annee-error');
  errorEl.classList.add('hidden');
  const btn = document.getElementById('btn-change-annee');
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = '…';
  try {
    let url = `/api/audit?commune=${encodeURIComponent(commune.nom)}&code_postal=${encodeURIComponent(cp)}`;
    if (yearRaw) url += `&exercice=${encodeURIComponent(yearRaw)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Erreur ${res.status}`);
    lastReport = data;
    lastHistory = null;
    resetEvolutionSection();
    renderReport(data);
  } catch (err) {
    errorEl.textContent = `Je n'ai pas accès aux données pour cette année : ${err.message}`;
    errorEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

document.getElementById('btn-retry').addEventListener('click', () => {
  showScreen('input');
});

// ---- Distribution du groupe de comparaison (mini histogramme SVG) ----

function renderDistributionSvg(peerValues, communeValue, color) {
  if (!peerValues || peerValues.length === 0 || communeValue === null || communeValue === undefined) {
    return '<p class="mono" style="font-size:11px; color:#9a9b9f; margin:6px 0;">Distribution indisponible.</p>';
  }
  const width = 400;
  const height = 44;
  const allValues = peerValues.concat([communeValue]);
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const span = (max - min) || 1;
  const bins = 28;
  const counts = new Array(bins).fill(0);
  peerValues.forEach((v) => {
    let idx = Math.floor(((v - min) / span) * bins);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    counts[idx] += 1;
  });
  const maxCount = Math.max(...counts, 1);
  const barW = width / bins;
  const bars = counts.map((c, i) => {
    const h = (c / maxCount) * (height - 8);
    const x = i * barW;
    const y = height - h;
    return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${Math.max(0, barW - 1).toFixed(2)}" height="${h.toFixed(2)}" fill="#e2e1db"></rect>`;
  }).join('');
  const markerX = ((communeValue - min) / span) * width;
  const marker = `
    <line x1="${markerX.toFixed(2)}" y1="0" x2="${markerX.toFixed(2)}" y2="${height}" stroke="${color}" stroke-width="2"></line>
    <path d="M ${markerX - 4},0 L ${markerX + 4},0 L ${markerX},7 Z" fill="${color}"></path>
  `;
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="width:100%; height:44px; display:block;">${bars}${marker}</svg>`;
}

// ---- Rendu du rapport ----

function renderReport(data) {
  const { commune, score, categories, marches_notables: marches } = data;

  document.getElementById('report-ville').textContent = commune.nom;
  document.getElementById('report-cp').textContent = commune.codes_postaux[0] || '';
  const peerBtn = document.getElementById('btn-peer-list');
  peerBtn.textContent =
    `${data.peer_group_size} communes de la même strate — ${data.strate_label}${commune.region ? ', ' + commune.region : ''}${data.exercice ? ' (exercice ' + data.exercice + ')' : ''}`;
  const peerNoteEl = document.getElementById('peer-group-note');
  if (data.peer_group_note) {
    peerNoteEl.textContent = data.peer_group_note;
    peerNoteEl.classList.remove('hidden');
  } else {
    peerNoteEl.classList.add('hidden');
  }
  document.getElementById('report-date').innerHTML = `Analyse du<br>${fmtDate(data.generated_at)}`;
  document.getElementById('input-change-annee').value = data.exercice || '';
  document.getElementById('annee-error').classList.add('hidden');

  const vs = VERDICT_STYLE[score.verdict] || VERDICT_STYLE.Vigilance;
  document.getElementById('score-donut').style.background =
    `conic-gradient(${vs.color} 0 ${score.global}%, #e4e3de ${score.global}% 100%)`;
  document.getElementById('score-value').textContent = score.global;
  const scoreLabelEl = document.getElementById('score-label');
  scoreLabelEl.textContent = score.verdict;
  scoreLabelEl.style.color = vs.color;
  scoreLabelEl.style.background = vs.bg;

  document.getElementById('score-summary').textContent = buildSummary(data);

  document.getElementById('categories-list').innerHTML = categories.map((c) => {
    const qs = QUALITY_STYLE[c.qualification] || QUALITY_STYLE.donnee_absente;
    const isMaintenance = c.key === 'entretien';
    return `
      <div style="padding:16px 0; border-top:1px solid #eceae4;">
        <div style="display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:8px;">
          <span style="font-size:15px; font-weight:500;">${escapeHtml(c.label)}</span>
          <span class="mono" style="font-size:12px; font-weight:600; padding:3px 9px; text-align:center; color:${qs.color}; background:${qs.bg};">${fmtPct(c.delta_pct)}</span>
        </div>
        ${isMaintenance ? `<p class="mono" style="font-size:10.5px; color:#9a9b9f; margin:0 0 8px; font-style:italic;">Source différente des 5 postes ci-dessus : cumul des marchés publics DECP notifiés (voirie, espaces verts, bâtiments, nettoyage), pas une dépense annuelle OFGL — comparable entre communes, mais pas à lire comme un budget annuel.</p>` : ''}
        ${renderDistributionSvg(c.peer_values, c.commune_par_habitant, qs.bar)}
        <div class="mono" style="display:flex; justify-content:space-between; font-size:10.5px; color:#9a9b9f; margin-top:5px; flex-wrap:wrap; gap:6px;">
          <span>médiane strate&nbsp;: ${fmtEur(c.peer_median_par_habitant)}/hab</span>
          <span style="color:${qs.color}; font-weight:600;">cette commune&nbsp;: ${fmtEur(c.commune_par_habitant)}/hab</span>
          <span>${c.peer_count} communes comparées</span>
        </div>
      </div>`;
  }).join('');

  renderMarkets(marches);
  const coverageNoteEl = document.getElementById('decp-coverage-note');
  if (data.decp_coverage_note) {
    coverageNoteEl.textContent = data.decp_coverage_note;
    coverageNoteEl.classList.remove('hidden');
  } else {
    coverageNoteEl.classList.add('hidden');
  }
  document.getElementById('data-freshness').textContent = buildFreshnessLine(data.data_freshness);
  renderDemographie(data.demographie);

  const forts = categories.filter((c) => c.qualification === 'efficient' || (c.qualification === 'conforme' && (c.delta_pct || 0) <= 0));
  const vigilance = categories.filter((c) => c.qualification === 'alerte' || c.qualification === 'a_surveiller');

  document.getElementById('points-forts').innerHTML = (forts.length ? forts : [null]).map((c) => {
    if (!c) return `<p style="margin:0; font-size:14px; line-height:1.55; color:#33353c;">Aucun poste nettement en dessous de la médiane de strate cette année.</p>`;
    return `<p style="margin:0; font-size:14px; line-height:1.55; color:#33353c;">${escapeHtml(c.label)} : ${fmtPct(c.delta_pct)} vs médiane de strate.</p>`;
  }).join('');

  document.getElementById('points-vigilance').innerHTML = (vigilance.length ? vigilance : [null]).map((c) => {
    if (!c) return `<p style="margin:0; font-size:14px; line-height:1.55; color:#33353c;">Aucun poste de dépense significativement au-dessus de la médiane de strate.</p>`;
    return `<p style="margin:0; font-size:14px; line-height:1.55; color:#33353c;">${escapeHtml(c.label)} : ${fmtPct(c.delta_pct)} vs médiane de strate, à examiner.</p>`;
  }).join('');
}

function renderMarkets(marches) {
  const marchesListEl = document.getElementById('marches-list');
  document.getElementById('marches-count').textContent = String(marches.length);
  document.getElementById('marches-section').style.display = marches.length ? '' : 'none';
  marchesListEl.innerHTML = marches.map((m) => {
    const titulaires = (m.titulaires && m.titulaires.length) ? m.titulaires.join(', ') : 'Titulaire non renseigné';
    const lotsBadge = m.lot_count > 1
      ? `<span class="mono" style="font-size:10.5px; color:#565861; background:#eceae4; padding:2px 6px; margin-left:6px;">${m.lot_count} lots</span>`
      : '';
    const outlier = !!m.montant_exceptionnel;
    return `
    <div style="border:1px solid ${outlier ? '#a5432f' : '#e2e1db'}; background:#fff; padding:18px;">
      <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:8px;">
        <span style="font-size:14.5px; font-weight:600; line-height:1.35;">${escapeHtml(m.objet || 'Marché sans objet renseigné')}${lotsBadge}</span>
      </div>
      <div class="mono" style="font-size:12px; color:#33353c; display:flex; justify-content:space-between; gap:10px;">
        <span>${escapeHtml(titulaires)}</span>
        <span style="font-weight:600; white-space:nowrap; color:${outlier ? '#8f3826' : 'inherit'};">${fmtEur(m.montant)}</span>
      </div>
      <div class="mono" style="font-size:11px; color:#9a9b9f; margin-top:4px;">${m.reference ? 'Réf. ' + escapeHtml(m.reference) + ' · ' : ''}${m.date_notification || ''}</div>
      ${outlier ? `<div class="mono" style="font-size:10.5px; color:#8f3826; background:#f3e2dc; padding:5px 8px; margin-top:8px;">⚠ Montant exceptionnel — supérieur au budget de fonctionnement annuel de la commune. Probablement une anomalie de saisie de la source ; à vérifier avant d'être pris au pied de la lettre.</div>` : ''}
    </div>
  `;
  }).join('');
}

function renderDemographie(demographie) {
  const section = document.getElementById('demographie-section');
  if (!demographie || !demographie.brackets || !demographie.brackets.length) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  document.getElementById('demographie-millesime').textContent = `Recensement ${demographie.millesime}`;

  const total = demographie.population_totale || 1;
  const maxPop = Math.max(...demographie.brackets.map((b) => b.population));
  const rows = demographie.brackets.map((b) => {
    const pct = (b.population / total) * 100;
    const width = maxPop ? (b.population / maxPop) * 100 : 0;
    return `
      <div style="display:grid; grid-template-columns:110px 1fr auto; align-items:center; gap:14px; padding:6px 0;">
        <span style="font-size:13px; color:#33353c;">${escapeHtml(b.label)}</span>
        <div style="height:16px; background:#eceae4;"><div style="height:100%; width:${width}%; background:#2b3a4a;"></div></div>
        <span class="mono" style="font-size:11.5px; color:#565861; width:120px; text-align:right;">${b.population.toLocaleString('fr-FR')} hab. (${pct.toFixed(0)}%)</span>
      </div>`;
  }).join('');

  document.getElementById('demographie-chart').innerHTML = rows;
}

function buildSummary(data) {
  const { score, categories } = data;
  const vigilance = categories.filter((c) => c.qualification === 'alerte' || c.qualification === 'a_surveiller');
  const efficient = categories.filter((c) => c.qualification === 'efficient');

  let text = `La commune présente un indice d'efficacité budgétaire de ${score.global}/100 (${score.verdict.toLowerCase()}) vis-à-vis des ${data.peer_group_size} communes de sa strate démographique.`;
  if (vigilance.length) {
    text += ` Les écarts se concentrent sur ${vigilance.map((c) => c.label.toLowerCase()).join(', ')}, au-dessus de la médiane de strate.`;
  }
  if (efficient.length) {
    text += ` À l'inverse, ${efficient.map((c) => c.label.toLowerCase()).join(', ')} apparaissent maîtrisés.`;
  }
  return text;
}

// ---- Modal : liste des communes comparées ----

document.getElementById('btn-peer-list').addEventListener('click', () => {
  if (!lastReport) return;
  const listEl = document.getElementById('modal-peers-list');
  listEl.innerHTML = lastReport.peer_communes.map((p) => `
    <div class="peer-row"><span>${escapeHtml(p.nom || p.code_insee)}</span><span class="pop mono">${fmtPop(p.population)}</span></div>
  `).join('');
  document.getElementById('modal-peers').classList.remove('hidden');
});

document.getElementById('modal-peers-close').addEventListener('click', closePeerModal);
document.getElementById('modal-peers').addEventListener('click', (e) => {
  if (e.target.id === 'modal-peers') closePeerModal();
});
function closePeerModal() {
  document.getElementById('modal-peers').classList.add('hidden');
}

// ---- Évolution multi-années (à la demande) ----

function resetEvolutionSection() {
  document.getElementById('evolution-chart').innerHTML = '';
  document.getElementById('evolution-table-wrap').innerHTML = '';
  document.getElementById('evolution-error').classList.add('hidden');
  document.getElementById('evolution-loading').classList.add('hidden');
}

function renderEvolutionChart(points) {
  const width = 760;
  const height = 180;
  const padL = 32;
  const padR = 12;
  const padT = 14;
  const padB = 24;
  const xs = points.map((p) => p.exercice);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const mapX = (x) => padL + (maxX === minX ? (width - padL - padR) / 2 : ((x - minX) / (maxX - minX)) * (width - padL - padR));
  const mapY = (score) => padT + (1 - score / 100) * (height - padT - padB);

  const gridLines = [0, 50, 100].map((v) => `
    <line x1="${padL}" y1="${mapY(v).toFixed(1)}" x2="${width - padR}" y2="${mapY(v).toFixed(1)}" stroke="#e2e1db" stroke-width="1"></line>
    <text x="${padL - 6}" y="${(mapY(v) + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="#9a9b9f" font-family="'IBM Plex Mono', monospace">${v}</text>
  `).join('');

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${mapX(p.exercice).toFixed(1)},${mapY(p.global_score).toFixed(1)}`).join(' ');

  const dots = points.map((p) => {
    const vs = VERDICT_STYLE[p.verdict] || VERDICT_STYLE.Vigilance;
    return `
      <circle cx="${mapX(p.exercice).toFixed(1)}" cy="${mapY(p.global_score).toFixed(1)}" r="4.5" fill="${vs.color}"></circle>
      <text x="${mapX(p.exercice).toFixed(1)}" y="${height - 6}" text-anchor="middle" font-size="10.5" fill="#565861" font-family="'IBM Plex Mono', monospace">${p.exercice}</text>
      <text x="${mapX(p.exercice).toFixed(1)}" y="${(mapY(p.global_score) - 10).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="600" fill="#1c1d21" font-family="'IBM Plex Mono', monospace">${p.global_score}</text>
    `;
  }).join('');

  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%; height:auto; background:#fff; border:1px solid #e2e1db;">
    ${gridLines}
    <path d="${pathD}" fill="none" stroke="#2b3a4a" stroke-width="2"></path>
    ${dots}
  </svg>`;
}

function renderEvolutionTable(points) {
  if (!points.length) return '';
  const refCategories = points[points.length - 1].categories;
  let html = '<table style="width:100%; border-collapse:collapse; margin-top:16px; font-size:12.5px; min-width:480px;">';
  html += '<thead><tr><th style="text-align:left; padding:6px 8px; border-bottom:1px solid #e2e1db; font-weight:600;">Poste (écart vs médiane)</th>'
    + points.map((p) => `<th class="mono" style="text-align:right; padding:6px 8px; border-bottom:1px solid #e2e1db; color:#8a8c94; font-weight:600;">${p.exercice}</th>`).join('')
    + '</tr></thead><tbody>';
  refCategories.forEach(({ key, label }) => {
    html += `<tr><td style="padding:6px 8px; border-bottom:1px solid #eceae4;">${escapeHtml(label)}</td>`;
    points.forEach((p) => {
      const c = p.categories.find((cat) => cat.key === key);
      const v = c ? c.delta_pct : null;
      const color = v === null || v === undefined ? '#9a9b9f' : (v > 0 ? '#8f3826' : '#2f5540');
      html += `<td class="mono" style="text-align:right; padding:6px 8px; border-bottom:1px solid #eceae4; color:${color};">${fmtPct(v)}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  return html;
}

document.getElementById('btn-evolution').addEventListener('click', async () => {
  if (!lastReport) return;
  const years = document.getElementById('select-years').value;
  const btn = document.getElementById('btn-evolution');
  const loadingEl = document.getElementById('evolution-loading');
  const errorEl = document.getElementById('evolution-error');
  errorEl.classList.add('hidden');
  loadingEl.classList.remove('hidden');
  btn.disabled = true;
  try {
    const commune = lastReport.commune;
    const cp = commune.codes_postaux[0] || '';
    const res = await fetch(`/api/audit/history?commune=${encodeURIComponent(commune.nom)}&code_postal=${encodeURIComponent(cp)}&years=${encodeURIComponent(years)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Erreur ${res.status}`);
    if (!data.years.length) throw new Error("Aucun exercice exploitable trouvé sur la période.");
    lastHistory = data;
    document.getElementById('evolution-chart').innerHTML = renderEvolutionChart(data.years);
    document.getElementById('evolution-table-wrap').innerHTML = renderEvolutionTable(data.years);
  } catch (err) {
    errorEl.textContent = `Échec du chargement de l'évolution : ${err.message}`;
    errorEl.classList.remove('hidden');
  } finally {
    loadingEl.classList.add('hidden');
    btn.disabled = false;
  }
});

// ---- Export XLSX ----

document.getElementById('btn-export').addEventListener('click', async () => {
  if (!lastReport) return;
  const ExcelJS = window.ExcelJS;
  if (!ExcelJS) {
    alert('Export indisponible : bibliothèque Excel non chargée.');
    return;
  }
  const data = lastReport;
  const EUR = '#,##0" €"';
  const PCT = '+0%;-0%';
  const INK = 'FF2B3A4A';

  const styleHeader = (ws, cells) => cells.forEach((a) => {
    const c = ws.getCell(a);
    c.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 };
    c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: INK } };
  });

  const wb = new ExcelJS.Workbook();
  wb.creator = 'Balise IA';
  wb.created = new Date();

  const s1 = wb.addWorksheet('Synthèse', { views: [{ showGridLines: false }] });
  s1.columns = [{ width: 34 }, { width: 55 }];
  s1.mergeCells('A1:B1');
  const t = s1.getCell('A1');
  t.value = "Balise IA — Rapport d'analyse budgétaire";
  t.font = { bold: true, size: 15, color: { argb: INK } };
  s1.getRow(1).height = 24;
  [
    ['Commune', data.commune.nom],
    ['Code INSEE', data.commune.code_insee],
    ['Code postal', data.commune.codes_postaux[0] || ''],
    ['Exercice', data.exercice],
    ['Strate de comparaison', `${data.peer_group_size} communes — ${data.strate_label}`],
    ["Date d'analyse", fmtDate(data.generated_at)],
    [],
    ["Indice d'efficacité (/100)", data.score.global],
    ['Verdict', data.score.verdict],
  ].forEach((r) => {
    const row = s1.addRow(r);
    row.getCell(1).font = { bold: true, color: { argb: 'FF565861' } };
  });
  s1.getCell('B9').font = { bold: true, size: 13, color: { argb: INK } };
  if (data.peer_group_note) {
    s1.addRow([]);
    const noteRow = s1.addRow(['Remarque', data.peer_group_note]);
    noteRow.getCell(1).font = { bold: true, color: { argb: 'FF565861' } };
    noteRow.getCell(2).alignment = { wrapText: true };
  }
  if (data.decp_coverage_note) {
    s1.addRow([]);
    const covRow = s1.addRow(['Couverture DECP', data.decp_coverage_note]);
    covRow.getCell(1).font = { bold: true, color: { argb: 'FF565861' } };
    covRow.getCell(2).alignment = { wrapText: true };
  }
  const freshnessLine = buildFreshnessLine(data.data_freshness);
  if (freshnessLine) {
    s1.addRow([]);
    const freshRow = s1.addRow(['Fraîcheur des données', freshnessLine.replace('Fraîcheur des données — ', '')]);
    freshRow.getCell(1).font = { bold: true, color: { argb: 'FF565861' } };
    freshRow.getCell(2).alignment = { wrapText: true };
  }

  const s2 = wb.addWorksheet('Catégories');
  s2.columns = [{ width: 34 }, { width: 18 }, { width: 18 }, { width: 16 }, { width: 16 }, { width: 14 }];
  s2.addRow(['Catégorie', 'Commune (€/hab)', 'Médiane strate (€/hab)', 'Écart', 'Statut', 'Communes comparées']);
  styleHeader(s2, ['A1', 'B1', 'C1', 'D1', 'E1', 'F1']);
  data.categories.forEach((c) => {
    const row = s2.addRow([
      c.label,
      c.commune_par_habitant,
      c.peer_median_par_habitant,
      c.delta_pct,
      QUALITY_STYLE[c.qualification]?.text || c.qualification,
      c.peer_count,
    ]);
    row.getCell(2).numFmt = '#,##0.00" €"';
    row.getCell(3).numFmt = '#,##0.00" €"';
    row.getCell(4).numFmt = PCT;
  });

  const s3 = wb.addWorksheet('Marchés notables');
  s3.columns = [{ width: 50 }, { width: 30 }, { width: 16 }, { width: 14 }, { width: 8 }];
  s3.addRow(['Objet', 'Titulaire(s)', 'Montant total (€)', 'Date', 'Lots']);
  styleHeader(s3, ['A1', 'B1', 'C1', 'D1', 'E1']);
  data.marches_notables.forEach((m) => {
    const row = s3.addRow([m.objet, (m.titulaires || []).join(', '), m.montant, m.date_notification, m.lot_count]);
    row.getCell(3).numFmt = EUR;
  });

  const s4 = wb.addWorksheet('Communes comparées');
  s4.columns = [{ width: 34 }, { width: 16 }, { width: 14 }];
  s4.addRow(['Commune', 'Code INSEE', 'Population']);
  styleHeader(s4, ['A1', 'B1', 'C1']);
  (data.peer_communes || []).forEach((p) => {
    s4.addRow([p.nom, p.code_insee, p.population]);
  });

  if (data.demographie && data.demographie.brackets && data.demographie.brackets.length) {
    const s6 = wb.addWorksheet('Démographie');
    s6.columns = [{ width: 20 }, { width: 14 }, { width: 10 }];
    s6.addRow([`Tranche d'âge (recensement ${data.demographie.millesime})`, 'Population', '% du total']);
    styleHeader(s6, ['A1', 'B1', 'C1']);
    data.demographie.brackets.forEach((b) => {
      const row = s6.addRow([b.label, b.population, b.population / data.demographie.population_totale]);
      row.getCell(3).numFmt = '0%';
    });
  }

  if (lastHistory && lastHistory.years.length) {
    const s5 = wb.addWorksheet('Évolution');
    const cats = lastHistory.years[lastHistory.years.length - 1].categories;
    s5.columns = [{ width: 34 }, ...lastHistory.years.map(() => ({ width: 12 }))];
    s5.addRow(['Poste (écart vs médiane)', ...lastHistory.years.map((y) => y.exercice)]);
    styleHeader(s5, lastHistory.years.map((_, i) => String.fromCharCode(66 + i) + '1').concat(['A1']));
    s5.addRow(['Score global (/100)', ...lastHistory.years.map((y) => y.global_score)]);
    cats.forEach(({ key, label }) => {
      const row = s5.addRow([label, ...lastHistory.years.map((y) => {
        const c = y.categories.find((cat) => cat.key === key);
        return c ? c.delta_pct : null;
      })]);
      for (let i = 2; i <= lastHistory.years.length + 1; i++) {
        row.getCell(i).numFmt = PCT;
      }
    });
  }

  const buf = await wb.xlsx.writeBuffer();
  const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const safe = `${data.commune.nom} ${data.commune.codes_postaux[0] || ''}`.replace(/[\\/:*?"<>|]/g, '');
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `Balise IA - ${safe}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
});

// ---- Export PDF ----

document.getElementById('btn-export-pdf').addEventListener('click', async () => {
  if (!lastReport) return;
  const btn = document.getElementById('btn-export-pdf');
  const label = btn.querySelector('span');
  const originalLabel = label.textContent;
  btn.disabled = true;
  label.textContent = '...';
  try {
    const data = lastReport;
    const cp = data.commune.codes_postaux[0] || '';
    let url = `/api/audit/pdf?commune=${encodeURIComponent(data.commune.nom)}&code_postal=${encodeURIComponent(cp)}`;
    if (data.exercice) url += `&exercice=${encodeURIComponent(data.exercice)}`;
    const res = await fetch(url);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `Erreur ${res.status}`);
    }
    const blob = await res.blob();
    const safe = `${data.commune.nom} ${cp}`.replace(/[\\/:*?"<>|]/g, '');
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = `Balise IA - ${safe}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
  } catch (err) {
    alert(`Export PDF impossible : ${err.message}`);
  } finally {
    btn.disabled = false;
    label.textContent = originalLabel;
  }
});
