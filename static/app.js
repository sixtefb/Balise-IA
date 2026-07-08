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
let loadingTimer = null;

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => el.classList.toggle('hidden', key !== name));
}

function fmtEur(v) {
  if (v === null || v === undefined) return 'n/d';
  return Math.round(v).toLocaleString('fr-FR') + ' €';
}

function fmtEurM(v) {
  if (v === null || v === undefined) return 'n/d';
  return (v / 1_000_000).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€';
}

function fmtPct(v) {
  if (v === null || v === undefined) return 'n/d';
  const pct = Math.round(v * 100);
  return (pct >= 0 ? '+' : '−') + Math.abs(pct) + '%';
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleDateString('fr-FR');
  } catch {
    return iso || '';
  }
}

// ---- Écran de saisie ----

document.getElementById('form-analyse').addEventListener('submit', (e) => {
  e.preventDefault();
  const ville = document.getElementById('input-ville').value.trim();
  const cp = document.getElementById('input-cp').value.trim();
  const errorEl = document.getElementById('input-error');
  errorEl.classList.add('hidden');
  if (!ville || !cp) return;
  runAnalyse(ville, cp);
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

async function runAnalyse(ville, cp) {
  showScreen('loading');
  startLoadingAnimation(ville, cp);
  try {
    const res = await fetch(`/api/audit?commune=${encodeURIComponent(ville)}&code_postal=${encodeURIComponent(cp)}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `Erreur ${res.status}`);
    }
    stopLoadingAnimation();
    document.getElementById('loading-bar').style.width = '100%';
    lastReport = data;
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

document.getElementById('btn-retry').addEventListener('click', () => {
  showScreen('input');
});

// ---- Rendu du rapport ----

function renderReport(data) {
  const { commune, score, categories, marches_notables: marches } = data;

  document.getElementById('report-ville').textContent = commune.nom;
  document.getElementById('report-cp').textContent = commune.codes_postaux[0] || '';
  document.getElementById('report-strate').textContent =
    `Comparé à ${data.peer_group_size} communes de la même strate — ${data.strate_label}${commune.region ? ', ' + commune.region : ''}${data.exercice ? ' (exercice ' + data.exercice + ')' : ''}`;
  document.getElementById('report-date').innerHTML = `Analyse du<br>${fmtDate(data.generated_at)}`;

  const vs = VERDICT_STYLE[score.verdict] || VERDICT_STYLE.Vigilance;
  document.getElementById('score-donut').style.background =
    `conic-gradient(${vs.color} 0 ${score.global}%, #e4e3de ${score.global}% 100%)`;
  document.getElementById('score-value').textContent = score.global;
  const scoreLabelEl = document.getElementById('score-label');
  scoreLabelEl.textContent = score.verdict;
  scoreLabelEl.style.color = vs.color;
  scoreLabelEl.style.background = vs.bg;

  document.getElementById('score-summary').textContent = buildSummary(data);

  const maxAbsDelta = Math.max(0.05, ...categories.map((c) => Math.abs(c.delta_pct || 0)));
  document.getElementById('categories-list').innerHTML = categories.map((c) => {
    const qs = QUALITY_STYLE[c.qualification] || QUALITY_STYLE.donnee_absente;
    const width = c.delta_pct === null ? 0 : Math.min(100, (Math.abs(c.delta_pct) / maxAbsDelta) * 100);
    return `
      <div style="display:grid; grid-template-columns:1.5fr 1fr auto; align-items:center; gap:22px; padding:13px 0; border-top:1px solid #eceae4;">
        <span style="font-size:15px; font-weight:500;">${escapeHtml(c.label)}</span>
        <div style="height:8px; background:#eceae4; border-radius:999px; overflow:hidden;"><div style="height:100%; width:${width}%; background:${qs.bar};"></div></div>
        <span class="mono" style="font-size:12px; font-weight:600; padding:3px 9px; min-width:60px; text-align:center; color:${qs.color}; background:${qs.bg};">${fmtPct(c.delta_pct)}</span>
      </div>`;
  }).join('');

  const marchesListEl = document.getElementById('marches-list');
  document.getElementById('marches-count').textContent = String(marches.length);
  document.getElementById('marches-section').style.display = marches.length ? '' : 'none';
  marchesListEl.innerHTML = marches.map((m) => `
    <div style="border:1px solid #e2e1db; background:#fff; padding:18px;">
      <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:8px;">
        <span style="font-size:14.5px; font-weight:600; line-height:1.35;">${escapeHtml(m.objet || 'Marché sans objet renseigné')}</span>
      </div>
      <div class="mono" style="font-size:12px; color:#33353c; display:flex; justify-content:space-between; gap:10px;">
        <span>${escapeHtml(m.titulaire || 'Titulaire non renseigné')}</span>
        <span style="font-weight:600;">${fmtEur(m.montant)}</span>
      </div>
      <div class="mono" style="font-size:11px; color:#9a9b9f; margin-top:4px;">${m.date_notification || ''}</div>
    </div>
  `).join('');

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

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

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

  const s2 = wb.addWorksheet('Catégories');
  s2.columns = [{ width: 34 }, { width: 18 }, { width: 18 }, { width: 16 }, { width: 16 }];
  s2.addRow(['Catégorie', 'Commune (€/hab)', 'Médiane strate (€/hab)', 'Écart', 'Statut']);
  styleHeader(s2, ['A1', 'B1', 'C1', 'D1', 'E1']);
  data.categories.forEach((c) => {
    const row = s2.addRow([
      c.label,
      c.commune_par_habitant,
      c.peer_median_par_habitant,
      c.delta_pct,
      QUALITY_STYLE[c.qualification]?.text || c.qualification,
    ]);
    row.getCell(2).numFmt = '#,##0.00" €"';
    row.getCell(3).numFmt = '#,##0.00" €"';
    row.getCell(4).numFmt = PCT;
  });

  const s3 = wb.addWorksheet('Marchés notables');
  s3.columns = [{ width: 50 }, { width: 30 }, { width: 16 }, { width: 14 }];
  s3.addRow(['Objet', 'Titulaire', 'Montant (€)', 'Date']);
  styleHeader(s3, ['A1', 'B1', 'C1', 'D1']);
  data.marches_notables.forEach((m) => {
    const row = s3.addRow([m.objet, m.titulaire, m.montant, m.date_notification]);
    row.getCell(3).numFmt = EUR;
  });

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
