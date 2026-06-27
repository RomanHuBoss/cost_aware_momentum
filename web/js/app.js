const state = {
  profiles: [],
  activeProfile: null,
  recommendations: [],
  glossary: new Map(),
  glossaryVersion: null,
  detail: null,
  detailTab: 'plan',
  decisionAction: null,
  csrf: readCookie('cam_csrf'),
  eventSource: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function readCookie(name) {
  return document.cookie.split('; ').find(v => v.startsWith(`${name}=`))?.split('=').slice(1).join('=') || null;
}

function uid(prefix = 'id') {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(Number(value));
}

function fmtPrice(value) {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  const digits = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 6;
  return fmt(n, digits);
}

function timeLeft(seconds) {
  if (seconds <= 0) return 'срок истек';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `еще ${minutes} мин`;
  return `еще ${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
}

function statusLabel(status) {
  const labels = {
    ACTIONABLE: 'Можно исполнить', LIMITED: 'Размер ограничен', NO_TRADE: 'Без сделки',
    BLOCKED_MIN_SIZE: 'Меньше min order', BLOCKED_MARGIN: 'Недостаточно маржи',
    BLOCKED_PORTFOLIO: 'Портфельный лимит', BLOCKED_LIQUIDITY: 'Недостаточно ликвидности',
    BLOCKED_STALE_DATA: 'Устаревшие данные', BLOCKED_DATA: 'Неполные данные',
    BLOCKED_LIQUIDATION: 'Риск ликвидации', CAPITAL_UNVERIFIED: 'Капитал не подтвержден',
    ACCEPTED: 'Принято оператором', ENTERED: 'Вход записан', REJECTED: 'Отклонено',
    SUPERSEDED: 'Заменено новым планом', EXPIRED: 'Срок истек', PARTIAL: 'Частично исполнено', CLOSED: 'Закрыто',
  };
  return labels[status] || status.replaceAll('_', ' ');
}

function entryLabel(stateName) {
  const labels = {
    IN_ENTRY_ZONE: 'В зоне входа', WAITING_ENTRY: 'Ожидание входа', MISSED_ENTRY: 'Вход упущен',
    EXPIRED: 'Срок истек', NO_PRICE: 'Нет текущей цены',
  };
  return labels[stateName] || stateName;
}

async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) {
    state.csrf = readCookie('cam_csrf') || state.csrf;
    if (state.csrf) headers.set('X-CSRF-Token', state.csrf);
  }
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  if (response.status === 401) {
    showLogin();
    throw new Error('Требуется вход оператора');
  }
  let payload = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('json')) payload = await response.json();
  else payload = await response.text();
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || payload || `HTTP ${response.status}`;
    throw Object.assign(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)), { response, payload });
  }
  return payload;
}

function toast(message, type = 'info') {
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.textContent = message;
  $('#toast-region').append(element);
  setTimeout(() => element.remove(), 5000);
}

function showLogin() {
  const dialog = $('#login-dialog');
  if (!dialog.open) dialog.showModal();
  $('#login-password').focus();
}

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('#login-error').textContent = '';
  try {
    const result = await api('/api/v1/session/login', {
      method: 'POST', body: JSON.stringify({ password: $('#login-password').value }),
    });
    state.csrf = result.csrf_token;
    $('#login-dialog').close();
    $('#login-password').value = '';
    toast('Вход выполнен');
  } catch (error) {
    $('#login-error').textContent = error.message;
  }
});

async function loadGlossary() {
  const result = await api('/api/v1/ui/glossary?locale=ru');
  state.glossary = new Map(result.items.map(item => [item.help_key, item]));
  state.glossaryVersion = result.version;
  $('#glossary-version').textContent = `Версия словаря: ${result.version || '—'}`;
  renderHelp();
}

async function loadProfiles() {
  const result = await api('/api/v1/capital-profiles');
  state.profiles = result.items;
  state.activeProfile = state.profiles.find(item => item.active) || state.profiles[0] || null;
  const select = $('#profile-select');
  select.innerHTML = state.profiles.map(item => `<option value="${item.id}" ${item.active ? 'selected' : ''}>${escapeHtml(item.name)} · ${fmt(item.allocated_capital)} USDT</option>`).join('');
  updateProfileSummary();
  renderProfiles();
}

function updateProfileSummary() {
  const p = state.activeProfile;
  $('#profile-summary').textContent = p
    ? `${p.mode} · риск ${fmt(p.risk_rate_pct, 2)}% · ${p.capital_verified ? 'подтвержден' : 'не подтвержден'}`
    : 'Профиль не выбран';
}

async function loadRecommendations() {
  if (!state.activeProfile) return;
  const symbol = $('#symbol-filter').value.trim().toUpperCase();
  const includeExpired = $('#show-all').checked;
  const params = new URLSearchParams({ profile_id: state.activeProfile.id, include_expired: String(includeExpired) });
  if (symbol) params.set('symbol', symbol);
  const result = await api(`/api/v1/recommendations?${params}`);
  state.recommendations = result.items;
  $('#last-update').textContent = `Последнее обновление: ${new Date(result.generated_at).toLocaleString('ru-RU')}`;
  renderRecommendations();
}

async function loadStatus() {
  try {
    const status = await api('/api/v1/status');
    $('#system-dot').className = 'status-dot ok';
    $('#system-state').textContent = 'Система доступна';
    $('#model-state').textContent = `Модель: ${status.active_model.version}`;
  } catch (error) {
    $('#system-dot').className = 'status-dot bad';
    $('#system-state').textContent = 'Ограниченная готовность';
    $('#model-state').textContent = error.message;
  }
}

async function loadAll() {
  try {
    await Promise.all([loadGlossary(), loadProfiles(), loadStatus()]);
    await loadRecommendations();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function helpButton(key) {
  if (!state.glossary.has(key)) return '';
  const id = uid('help');
  return `<button class="help-icon" type="button" data-help-key="${key}" aria-label="Пояснение" aria-describedby="${id}">i</button>`;
}

function tileClass(item, section) {
  if (section === 'blocked') return 'blocked';
  if (section === 'watch') return 'watch';
  if (section === 'no-trade') return 'no-trade';
  return item.market_direction === 'LONG' ? 'long' : 'short';
}

function tileHtml(item, section) {
  const direction = item.direction === 'NO_TRADE' ? 'NO TRADE' : item.direction;
  const cls = tileClass(item, section);
  const warning = item.primary_warning ? `<div class="warning">⚠ ${escapeHtml(item.primary_warning)}</div>` : '';
  return `<article class="tile ${cls}" data-signal-id="${item.signal_id}" tabindex="0" role="button" aria-label="Открыть ${escapeHtml(item.symbol)} ${direction}">
    <div class="tile-header"><span class="symbol">${escapeHtml(item.symbol)}</span><span class="direction">${direction}</span></div>
    <div class="tile-status"><span class="status-chip ${item.executability_status === 'ACTIONABLE' ? 'actionable' : item.executability_status.startsWith('BLOCKED') ? 'blocked' : ''}">${escapeHtml(statusLabel(item.executability_status))}</span><span class="status-chip">${escapeHtml(entryLabel(item.entry_state))}</span><span>${escapeHtml(timeLeft(item.seconds_to_expiry))}</span></div>
    <div class="level-grid">
      <div class="level"><span>Текущая цена</span><strong>${fmtPrice(item.current_price)}</strong></div>
      <div class="level"><span>Зона входа ${helpButton('entry_zone')}</span><strong>${fmtPrice(item.entry.low)}–${fmtPrice(item.entry.high)}</strong></div>
      <div class="level"><span>SL ${helpButton('sl')}</span><strong>${fmtPrice(item.stop_loss)}</strong></div>
      <div class="level"><span>Основной TP ${helpButton('tp')}</span><strong>${fmtPrice(item.main_take_profit)}</strong></div>
    </div>
    <div class="metric-grid">
      <div class="metric"><span class="help-term">Чистый доход/риск ${helpButton('rr_net')}</span><strong>${fmt(item.net_rr, 2)}</strong></div>
      <div class="metric"><span class="help-term">Ожидаемый результат ${helpButton('ev_net_r')}</span><strong>${item.net_ev_r >= 0 ? '+' : ''}${fmt(item.net_ev_r, 2)}R</strong></div>
      <div class="metric"><span class="help-term">Риск ${helpButton('risk_usdt')}</span><strong>${fmt(item.risk_usdt, 2)} USDT</strong></div>
      <div class="metric"><span class="help-term">Позиция ${helpButton('notional')}</span><strong>${fmt(item.notional, 2)} USDT</strong></div>
    </div>${warning}
  </article>`;
}

function classify(item) {
  if (item.direction === 'NO_TRADE' || item.executability_status === 'NO_TRADE') return 'no-trade';
  if (item.executability_status.startsWith('BLOCKED') || ['EXPIRED', 'SUPERSEDED'].includes(item.executability_status)) return 'blocked';
  if (['WAITING_ENTRY', 'MISSED_ENTRY', 'NO_PRICE'].includes(item.entry_state)) return 'watch';
  return 'active';
}

function renderRecommendations() {
  const sort = $('#sort-select').value;
  const items = [...state.recommendations];
  if (sort === 'expiry') items.sort((a, b) => a.seconds_to_expiry - b.seconds_to_expiry);
  else if (sort === 'symbol') items.sort((a, b) => a.symbol.localeCompare(b.symbol));
  else items.sort((a, b) => b.net_ev_r - a.net_ev_r);
  const groups = { active: [], watch: [], blocked: [], 'no-trade': [] };
  items.forEach(item => groups[classify(item)].push(item));
  for (const [group, groupItems] of Object.entries(groups)) {
    const id = group === 'no-trade' ? 'no-trade' : group;
    $(`#${id}-grid`).innerHTML = groupItems.map(item => tileHtml(item, group)).join('');
    $(`#${id}-count`).textContent = groupItems.length;
    $(`#${id}-empty`).classList.toggle('visible', groupItems.length === 0);
  }
  bindTileEvents();
  bindHelpEvents();
}

function bindTileEvents() {
  $$('.tile').forEach(tile => {
    const open = () => openDetail(tile.dataset.signalId);
    tile.addEventListener('click', event => { if (!event.target.closest('.help-icon')) open(); });
    tile.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); open(); } });
  });
}

async function openDetail(signalId) {
  try {
    state.detail = await api(`/api/v1/recommendations/${signalId}?profile_id=${state.activeProfile.id}`);
    state.detailTab = 'plan';
    $('#detail-title').textContent = `${state.detail.symbol} · ${state.detail.direction}`;
    $('#detail-subtitle').textContent = `${statusLabel(state.detail.executability_status)} · версия плана ${state.detail.plan_version}`;
    $$('#detail-tabs .tab').forEach(tab => tab.classList.toggle('active', tab.dataset.tab === 'plan'));
    renderDetail();
    updateDetailActions();
    $('#detail-dialog').showModal();
  } catch (error) { toast(error.message, 'error'); }
}

function dataList(rows) {
  return `<dl class="data-list">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v ?? '—'}</dd>`).join('')}</dl>`;
}

function renderDetail() {
  const d = state.detail;
  if (!d) return;
  let html = '';
  if (state.detailTab === 'plan') {
    const tp = d.trading_plan.take_profits.map((x, i) => `TP${i + 1}: ${fmtPrice(x.price)} (${fmt(x.weight * 100, 0)}%)`).join('<br>');
    html = `<div class="detail-grid">
      <section class="detail-card"><h3>Уровни сделки</h3>${dataList([
        ['Направление', d.trading_plan.direction], ['Текущая цена', fmtPrice(d.current_price)],
        ['Зона входа', `${fmtPrice(d.entry.low)}–${fmtPrice(d.entry.high)}`], ['Stop Loss', fmtPrice(d.stop_loss)],
        ['Take Profit', tp], ['Горизонт', `${d.trading_plan.horizon_hours} ч`], ['Тип ордера', d.trading_plan.recommended_order_type],
      ])}</section>
      <section class="detail-card"><h3>Условия отмены</h3><ul class="reason-list">${d.trading_plan.cancellation_conditions.map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></section>
      <section class="detail-card" style="grid-column:1/-1"><h3>График</h3><canvas id="price-chart" width="900" height="260" aria-label="График цены с уровнями"></canvas></section>
    </div>`;
  } else if (state.detailTab === 'risk') {
    html = `<div class="detail-grid"><section class="detail-card"><h3>Капитал и размер</h3>${dataList([
      ['Профиль', d.profile.name], ['Расчетный капитал', `${fmt(d.risk.effective_capital, 2)} USDT`],
      ['Риск на сделку', `${fmt(d.risk.risk_rate_pct, 2)}%`], ['Риск-бюджет', `${fmt(d.risk.risk_budget_usdt, 2)} USDT`],
      ['Фактический stress loss', `${fmt(d.risk.actual_stress_loss_usdt, 2)} USDT`], ['Количество', fmt(d.risk.qty, 8)],
      ['Notional', `${fmt(d.risk.notional, 2)} USDT`], ['Плечо', `${d.risk.leverage}×`], ['Оценочная маржа', `${fmt(d.risk.margin_estimate, 2)} USDT`],
      ['Запас до ликвидации', `${fmt(d.risk.liquidation_buffer_rate * 100, 2)}%`], ['Ограничивающий фактор', d.risk.limiting_cap || 'Риск-бюджет'],
    ])}</section><section class="detail-card"><h3>Предупреждения</h3><ul class="reason-list">${(d.risk.warnings.length ? d.risk.warnings : ['Ограничений не зафиксировано']).map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></section></div>`;
  } else if (state.detailTab === 'economics') {
    html = `<div class="detail-grid"><section class="detail-card"><h3>Доход и риск</h3>${dataList([
      ['Gross R/R', fmt(d.economics.gross_rr, 2)], ['Net R/R', fmt(d.economics.net_rr, 2)],
      ['Net EV', `${d.economics.net_ev_r >= 0 ? '+' : ''}${fmt(d.economics.net_ev_r, 3)}R`], ['Break-even вероятность', `${fmt(d.economics.break_even_probability * 100, 1)}%`],
      ['Стресс-downside', `${fmt(d.economics.stress_downside_rate * 100, 3)}%`],
    ])}</section><section class="detail-card"><h3>Издержки</h3>${dataList([
      ['Комиссии round-trip', `${fmt(d.economics.fee_rate_round_trip * 100, 4)}%`], ['Slippage', `${fmt(d.economics.slippage_rate * 100, 4)}%`],
      ['Funding-сценарий', `${fmt(d.economics.funding_rate_scenario * 100, 4)}%`], ['Gross edge', `${fmt(d.economics.gross_edge_rate * 100, 3)}%`],
    ])}<p class="section-note">Spread не прибавляется повторно, когда он уже отражен в исполнимой цене.</p></section></div>`;
  } else if (state.detailTab === 'why') {
    html = `<section class="detail-card"><h3>Факторы рекомендации</h3><ul class="reason-list">${d.model.reasons.map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul><p class="section-note">Факторы описывают вклад в решение модели и не доказывают причинность.</p></section>`;
  } else if (state.detailTab === 'reliability') {
    html = `<div class="detail-grid"><section class="detail-card"><h3>Вероятности исходов</h3>${dataList([
      ['P(TP раньше SL)', `${fmt(d.model.p_tp_before_sl * 100, 1)}%`], ['P(SL раньше TP)', `${fmt(d.model.p_sl_before_tp * 100, 1)}%`],
      ['P(timeout)', `${fmt(d.model.p_timeout * 100, 1)}%`], ['Модель', d.model.model_version], ['Калибровка', d.model.calibration_version], ['Схема признаков', d.model.feature_schema_version],
    ])}</section><section class="detail-card"><h3>Ограничение интерпретации</h3><p>Вероятность относится к конкретным барьерам, горизонту и версии модели. Она не гарантирует исход отдельной сделки.</p></section></div>`;
  } else if (state.detailTab === 'audit') {
    const events = d.audit.events || [];
    html = `<div class="detail-grid"><section class="detail-card"><h3>Идентификаторы и версии</h3>${dataList([
      ['Signal ID', d.signal_id], ['Plan ID', d.plan_id], ['Natural key', d.audit.signal_natural_key], ['Plan version', d.audit.plan_version],
      ['Profile version', d.audit.profile_version], ['Data cutoff', new Date(d.audit.data_cutoff).toLocaleString('ru-RU')], ['Publish time', new Date(d.audit.publish_time).toLocaleString('ru-RU')],
    ])}</section><section class="detail-card"><h3>История событий</h3><div class="audit-list">${events.map(e => `<div class="audit-item"><strong>${escapeHtml(e.type)}</strong><br><small>${new Date(e.time).toLocaleString('ru-RU')} · ${escapeHtml(e.actor)}</small><br><code>${escapeHtml(JSON.stringify(e.payload))}</code></div>`).join('') || 'Событий нет'}</div></section></div>`;
  }
  $('#detail-content').innerHTML = html;
  if (state.detailTab === 'plan') drawChart();
}

async function drawChart() {
  const canvas = $('#price-chart');
  if (!canvas || !state.detail) return;
  try {
    const data = await api(`/api/v1/symbols/${state.detail.symbol}/chart?bars=120`);
    const points = data.series.last || [];
    if (points.length < 2) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.clientWidth || 900, height = canvas.clientHeight || 260;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr; canvas.height = height * dpr; ctx.scale(dpr, dpr);
    const values = points.map(p => p.close).concat([state.detail.stop_loss, state.detail.main_take_profit, state.detail.entry.low, state.detail.entry.high]);
    const min = Math.min(...values), max = Math.max(...values), pad = (max - min) * .1 || 1;
    const x = i => 35 + i * (width - 60) / (points.length - 1);
    const y = v => 15 + (max + pad - v) * (height - 35) / (max - min + 2 * pad);
    ctx.clearRect(0, 0, width, height); ctx.strokeStyle = '#2b3d50'; ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) { const yy = 15 + i * (height - 35) / 4; ctx.beginPath(); ctx.moveTo(35, yy); ctx.lineTo(width - 25, yy); ctx.stroke(); }
    ctx.strokeStyle = '#8dc5ff'; ctx.lineWidth = 2; ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(x(i), y(p.close)) : ctx.moveTo(x(i), y(p.close))); ctx.stroke();
    const levels = [[state.detail.stop_loss, '#ef6b73', 'SL'], [state.detail.main_take_profit, '#26c281', 'TP'], [state.detail.entry.low, '#e7b64a', 'ENTRY'], [state.detail.entry.high, '#e7b64a', 'ENTRY']];
    ctx.font = '11px system-ui'; levels.forEach(([value, color, label]) => { ctx.strokeStyle = color; ctx.setLineDash([5,4]); ctx.beginPath(); ctx.moveTo(35, y(value)); ctx.lineTo(width - 25, y(value)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = color; ctx.fillText(`${label} ${fmtPrice(value)}`, 40, y(value) - 4); });
  } catch (error) { toast(`График: ${error.message}`, 'error'); }
}

function updateDetailActions() {
  const d = state.detail;
  const allowed = ['ACTIONABLE', 'LIMITED', 'VIEWED'].includes(d.executability_status) && d.seconds_to_expiry > 0;
  $('#accept-button').disabled = !allowed;
  $('#reject-button').disabled = ['ACCEPTED', 'ENTERED', 'CLOSED', 'REJECTED'].includes(d.executability_status);
}

$('#detail-tabs').addEventListener('click', event => {
  const tab = event.target.closest('.tab'); if (!tab) return;
  state.detailTab = tab.dataset.tab; $$('#detail-tabs .tab').forEach(x => x.classList.toggle('active', x === tab)); renderDetail();
});

$('#copy-plan-button').addEventListener('click', async () => {
  const d = state.detail; if (!d) return;
  const text = `${d.symbol} ${d.market_direction}\nВход: ${fmtPrice(d.entry.low)}–${fmtPrice(d.entry.high)}\nSL: ${fmtPrice(d.stop_loss)}\nTP: ${fmtPrice(d.main_take_profit)}\nQty: ${d.qty}\nNotional: ${d.notional} USDT\nПлечо: ${d.leverage}x\nPlan ID: ${d.plan_id} v${d.plan_version}`;
  await navigator.clipboard.writeText(text); toast('Параметры скопированы');
});

$('#open-bybit-button').addEventListener('click', () => {
  if (!state.detail) return;
  window.open(`https://www.bybit.com/trade/usdt/${encodeURIComponent(state.detail.symbol)}`, '_blank', 'noopener');
});

function openDecision(action) {
  state.decisionAction = action;
  $('#decision-title').textContent = action === 'accept' ? 'Принять рекомендацию' : 'Отклонить рекомендацию';
  $('#decision-submit').textContent = action === 'accept' ? 'Принять' : 'Отклонить';
  $('#decision-submit').className = `button ${action === 'accept' ? 'primary' : 'danger'}`;
  $('#decision-dialog').showModal();
}
$('#accept-button').addEventListener('click', () => openDecision('accept'));
$('#reject-button').addEventListener('click', () => openDecision('reject'));

$('#decision-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!state.detail || !state.decisionAction) return;
  const action = state.decisionAction;
  const payload = { plan_id: state.detail.plan_id, reason_code: $('#decision-reason').value || null, comment: $('#decision-comment').value || null };
  try {
    const result = await api(`/api/v1/recommendations/${state.detail.signal_id}/${action}`, {
      method: 'POST', headers: { 'Idempotency-Key': uid(action) }, body: JSON.stringify(payload),
    });
    $('#decision-dialog').close(); $('#detail-dialog').close();
    toast(result.message || (action === 'accept' ? 'Рекомендация принята' : 'Рекомендация отклонена'));
    if (action === 'accept') {
      $('#entry-price').value = state.detail.current_price || state.detail.entry.reference;
      $('#entry-qty').value = state.detail.qty;
      $('#entry-leverage').value = state.detail.leverage;
      $('#entry-dialog').showModal();
    }
    await loadRecommendations();
  } catch (error) {
    if (error.response?.status === 409 && error.payload?.new_plan_id) {
      toast(`${error.payload.detail}. Создан новый план.`, 'error'); await loadRecommendations(); $('#decision-dialog').close(); $('#detail-dialog').close();
    } else toast(error.message, 'error');
  }
});

$('#entry-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!state.detail) return;
  try {
    const payload = {
      plan_id: state.detail.plan_id, entry_time: new Date().toISOString(), entry_price: $('#entry-price').value,
      qty: $('#entry-qty').value, leverage: Number($('#entry-leverage').value), fee: $('#entry-fee').value || 0, notes: $('#entry-notes').value || null,
    };
    await api('/api/v1/trades/manual-entry', { method: 'POST', headers: { 'Idempotency-Key': uid('entry') }, body: JSON.stringify(payload) });
    $('#entry-dialog').close(); toast('Ручной вход записан'); await loadRecommendations();
  } catch (error) { toast(error.message, 'error'); }
});

$('#profile-select').addEventListener('change', async event => {
  const id = event.target.value;
  try {
    await api(`/api/v1/capital-profiles/${id}/activate`, { method: 'POST', body: '{}' });
    await loadProfiles(); await loadRecommendations(); toast('Профиль активирован, планы пересчитаны');
  } catch (error) { toast(error.message, 'error'); }
});

function renderProfiles() {
  $('#profiles-list').innerHTML = state.profiles.map(p => `<div class="profile-row"><div><strong>${escapeHtml(p.name)} ${p.active ? '· активен' : ''}</strong><small>${fmt(p.allocated_capital)} USDT · риск ${fmt(p.risk_rate_pct)}% · ${p.default_leverage}× · v${p.version}<br>${p.capital_verified ? 'Капитал подтвержден' : 'Капитал не подтвержден биржей'}</small></div><button class="button secondary activate-profile" data-id="${p.id}" ${p.active ? 'disabled' : ''}>Активировать</button></div>`).join('');
  $$('.activate-profile').forEach(button => button.addEventListener('click', async () => {
    try { await api(`/api/v1/capital-profiles/${button.dataset.id}/activate`, { method: 'POST', body: '{}' }); await loadProfiles(); await loadRecommendations(); } catch (e) { toast(e.message, 'error'); }
  }));
}

$('#profile-form').addEventListener('submit', async event => {
  event.preventDefault();
  const payload = {
    name: $('#profile-name').value, mode: $('#profile-mode').value, allocated_capital: $('#profile-capital').value,
    risk_rate: Number($('#profile-risk').value) / 100, max_total_risk_rate: 0.02,
    default_leverage: Number($('#profile-leverage').value), max_leverage: Number($('#profile-max-leverage').value), margin_reserve_rate: 0.25,
    source_account_id: $('#profile-mode').value === 'bybit_read_only' ? 'bybit-unified' : null,
  };
  try { await api('/api/v1/capital-profiles', { method: 'POST', body: JSON.stringify(payload) }); event.target.reset(); await loadProfiles(); toast('Профиль создан'); } catch (error) { toast(error.message, 'error'); }
});

function renderHelp(filter = '') {
  const needle = filter.trim().toLowerCase();
  const items = [...state.glossary.entries()].filter(([key, item]) => !needle || `${key} ${item.short_text} ${item.long_text}`.toLowerCase().includes(needle));
  $('#help-list').innerHTML = items.map(([key, item]) => `<article class="help-item"><h3>${escapeHtml(key)}</h3><p>${escapeHtml(item.short_text)}</p><small>${escapeHtml(item.long_text)}</small></article>`).join('');
}
$('#help-search').addEventListener('input', event => renderHelp(event.target.value));

function showTooltip(target) {
  const item = state.glossary.get(target.dataset.helpKey); if (!item) return;
  const tooltip = $('#tooltip'); tooltip.textContent = item.short_text; tooltip.hidden = false;
  const rect = target.getBoundingClientRect(); const margin = 10;
  let left = Math.min(window.innerWidth - tooltip.offsetWidth - margin, Math.max(margin, rect.left + rect.width / 2 - tooltip.offsetWidth / 2));
  let top = rect.top - tooltip.offsetHeight - 8; if (top < margin) top = rect.bottom + 8;
  tooltip.style.left = `${left}px`; tooltip.style.top = `${top}px`; target.setAttribute('aria-expanded', 'true');
}
function hideTooltip(target) { $('#tooltip').hidden = true; if (target) target.setAttribute('aria-expanded', 'false'); }
function bindHelpEvents() {
  $$('.help-icon').forEach(button => {
    if (button.dataset.bound) return; button.dataset.bound = '1';
    let timer;
    button.addEventListener('mouseenter', () => timer = setTimeout(() => showTooltip(button), 300));
    button.addEventListener('mouseleave', () => { clearTimeout(timer); hideTooltip(button); });
    button.addEventListener('focus', () => showTooltip(button)); button.addEventListener('blur', () => hideTooltip(button));
    button.addEventListener('click', event => { event.stopPropagation(); $('#tooltip').hidden ? showTooltip(button) : hideTooltip(button); });
  });
}
document.addEventListener('keydown', event => { if (event.key === 'Escape') hideTooltip(); });

$('#profiles-button').addEventListener('click', () => $('#profiles-dialog').showModal());
$('#help-button').addEventListener('click', () => $('#help-dialog').showModal());
$('#refresh-button').addEventListener('click', loadAll);
$('#symbol-filter').addEventListener('input', debounce(loadRecommendations, 300));
$('#show-all').addEventListener('change', loadRecommendations);
$('#sort-select').addEventListener('change', renderRecommendations);
$('#demo-button').addEventListener('click', async () => {
  try { const result = await api('/api/v1/admin/demo-seed', { method: 'POST', body: JSON.stringify({ symbols: ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT'] }) }); toast(`Демонстрационные данные созданы, сигналов: ${result.signals_published}`); await loadAll(); } catch (error) { toast(error.message, 'error'); }
});

$$('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$$('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));

function connectEvents() {
  state.eventSource?.close();
  const source = new EventSource('/api/v1/events'); state.eventSource = source;
  let timer;
  source.onmessage = () => { clearTimeout(timer); timer = setTimeout(() => { loadStatus(); loadRecommendations(); }, 400); };
  ['MARKET_SIGNAL_PUBLISHED','EXECUTION_PLAN_UPDATED','ACTIVE_PROFILE_CHANGED','MANUAL_TRADE_UPDATED'].forEach(type => source.addEventListener(type, source.onmessage));
  source.onerror = () => { $('#system-dot').className = 'status-dot'; };
}

function escapeHtml(value) { const div = document.createElement('div'); div.textContent = String(value ?? ''); return div.innerHTML; }
function debounce(fn, wait) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; }

window.addEventListener('resize', () => hideTooltip());
loadAll().then(connectEvents);
setInterval(() => { renderRecommendations(); }, 30000);
