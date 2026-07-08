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
  universeStatus: null,
  systemStatus: null,
  trainerPollTimer: null,
  pageInstanceId: window.crypto?.randomUUID?.() || `page-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  exposureObserver: null,
  exposureCandidates: new Map(),
  exposureTimers: new Map(),
  exposedPlanIds: new Set(),
  pendingExposures: [],
  exposureFlushTimer: null,
};

const trainerPhaseLabels = {
  STARTING: 'запуск процесса',
  INITIAL_DELAY: 'ожидание первого запуска',
  CHECKING_DATA: 'проверка готовности данных',
  LOADING_DATA: 'загрузка обучающей выборки',
  FITTING: 'обучение модели',
  REGISTERING: 'регистрация кандидата',
  ACTIVATING: 'активация модели',
  WAITING: 'ожидание',
  ERROR: 'ошибка',
  STOPPED: 'остановлено',
  DISABLED: 'отключено',
};

const trainerWaitLabels = {
  not_enough_history_for_bootstrap: 'Исторический bootstrap cohort ещё не набрал минимальную часовую глубину.',
  dynamic_bootstrap_universe_not_ready: 'Нет свежего dynamic snapshot или недостаточно execution-eligible инструментов для безопасного historical bootstrap.',
  insufficient_symbol_history_coverage: 'Недостаточно инструментов с требуемой глубиной истории.',
  not_enough_new_or_changed_training_data: 'После активной модели накоплено недостаточно новых размеченных часов или изменений набора данных.',
  not_enough_new_labeled_time: 'После активной модели накоплено недостаточно новых размеченных часов.',
  training_cooldown_not_elapsed: 'Действует защитная пауза после предыдущей попытки обучения.',
  quality_gate_failed_waiting_for_new_data: 'Предыдущий candidate не прошёл quality gate; trainer ждёт новых размеченных часов перед повтором.',
  training_deferred_waiting_for_new_data: 'Предыдущее обучение отложено из-за недостаточной walk-forward истории; trainer ждёт новых размеченных часов.',
  training_recovery_backoff_not_elapsed: 'Действует короткая защитная пауза после неудачного восстановления.',
  operator_recovery_not_required: 'Активный artifact доступен; восстановительное обучение не требуется.',
  operator_recovery_blocked_by_active_model_path: 'Восстановление заблокировано настройкой ACTIVE_MODEL_PATH.',
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

function latestRecommendationsBySymbol(items) {
  const latest = new Map();
  for (const item of items) {
    const current = latest.get(item.symbol);
    const itemExpiry = Date.parse(item.expires_at || '') || 0;
    const currentExpiry = Date.parse(current?.expires_at || '') || 0;
    if (!current || itemExpiry > currentExpiry) latest.set(item.symbol, item);
  }
  return [...latest.values()];
}

async function loadRecommendations() {
  if (!state.activeProfile) return;
  const symbol = $('#symbol-filter').value.trim().toUpperCase();
  const includeExpired = $('#show-all').checked;
  const params = new URLSearchParams({
    profile_id: state.activeProfile.id,
    include_expired: String(includeExpired),
    limit: '2000',
  });
  if (symbol) params.set('symbol', symbol);
  const result = await api(`/api/v1/recommendations?${params}`);
  // Backend enforces one current recommendation per symbol.  Keep this small
  // client-side guard for rolling upgrades where an old API process may still
  // return overlapping hourly signals for a few seconds.
  state.recommendations = latestRecommendationsBySymbol(result.items);
  $('#last-update').textContent = `Последнее обновление: ${new Date(result.generated_at).toLocaleString('ru-RU')}`;
  updateUniverseState();
  renderRecommendations();
}

async function loadStatus() {
  try {
    const status = await api('/api/v1/status');
    const runtime = status.active_model?.worker_runtime || null;
    const modelNotice = status.active_model?.worker_notice || null;
    const baselineActive = runtime?.baseline === true;
    $('#system-dot').className = baselineActive ? 'status-dot warn' : 'status-dot ok';
    $('#system-state').textContent = baselineActive
      ? 'Система доступна с ограничениями'
      : 'Система доступна';
    state.systemStatus = status;
    const trainer = [...status.heartbeats].filter(item => item.service === 'trainer').sort((a, b) => Date.parse(b.last_seen_at || 0) - Date.parse(a.last_seen_at || 0))[0];
    const trainerPhase = trainer?.details?.phase;
    const waitReason = trainer?.details?.wait_reason || null;
    const lastTrainingResult = trainer?.details?.last_result || null;
    let trainingState = status.auto_training?.enabled
      ? (trainerPhaseLabels[trainerPhase] || 'ожидание trainer')
      : 'отключено';
    if (waitReason?.reason === 'training_cooldown_not_elapsed') {
      const nextDue = waitReason.next_due_at
        ? new Date(waitReason.next_due_at).toLocaleString('ru-RU')
        : null;
      trainingState = nextDue
        ? `пауза до ${nextDue}`
        : 'пауза перед повторной проверкой';
    } else if (waitReason?.reason === 'training_recovery_backoff_not_elapsed') {
      trainingState = 'короткая пауза перед повтором восстановления';
    } else if (trainerPhase === 'ERROR' && lastTrainingResult?.error) {
      trainingState = `ошибка: ${lastTrainingResult.error}`;
    }

    const effectiveVersion = runtime?.version || status.active_model?.version || '—';
    const latestCandidate = status.active_model?.latest_candidate || null;
    const orphanArtifacts = status.active_model?.orphan_artifacts || [];
    let modelDetail = '';
    if (modelNotice?.code === 'ACTIVE_MODEL_ARTIFACT_MISSING') {
      modelDetail = ` · файл ${modelNotice.registry_version || 'активной модели'} отсутствует, используется baseline`;
    } else if (modelNotice?.code === 'NO_ACTIVE_MODEL_REGISTERED') {
      modelDetail = ' · старт с baseline до первой обученной модели';
    } else if (modelNotice?.code === 'REGISTRY_BASELINE_ACTIVE') {
      modelDetail = ' · активен некалиброванный baseline';
    }

    if (baselineActive && latestCandidate?.artifact_exists) {
      if (latestCandidate.quality_gate_passed === false) {
        const reasons = (latestCandidate.quality_gate_reasons || []).slice(0, 2).join(', ');
        modelDetail += ` · кандидат ${latestCandidate.version} не прошёл quality gate${reasons ? `: ${reasons}` : ''}`;
      } else if (latestCandidate.quality_gate_passed === true) {
        modelDetail += ` · кандидат ${latestCandidate.version} прошёл gate, но не активирован`;
      } else {
        modelDetail += ` · кандидат ${latestCandidate.version} зарегистрирован, но не активирован`;
      }
    }
    if (baselineActive && orphanArtifacts.length) {
      modelDetail += ` · файл ${orphanArtifacts[0]} не зарегистрирован в model registry`;
    }
    $('#model-state').textContent = `Модель: ${effectiveVersion}${modelDetail} · дообучение: ${trainingState}`;
    const worker = [...status.heartbeats].filter(item => item.service === 'worker').sort((a, b) => Date.parse(b.last_seen_at || 0) - Date.parse(a.last_seen_at || 0))[0];
    state.universeStatus = worker?.details?.universe || null;
    updateUniverseState();
    renderTrainerDialog(status);
    return status;
  } catch (error) {
    $('#system-dot').className = 'status-dot bad';
    $('#system-state').textContent = 'Ограниченная готовность';
    $('#model-state').textContent = error.message;
  }
}


function trainerDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU');
}

function trainerProgressRow(label, current, required, formatter = value => fmt(value, 0)) {
  const currentNumber = Number(current);
  const requiredNumber = Number(required);
  if (!Number.isFinite(currentNumber) || !Number.isFinite(requiredNumber) || requiredNumber <= 0) return '';
  const percentage = Math.max(0, Math.min(100, currentNumber / requiredNumber * 100));
  return `<div class="trainer-progress-row"><span class="trainer-progress-label">${escapeHtml(label)}</span><div class="trainer-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="${escapeHtml(requiredNumber)}" aria-valuenow="${escapeHtml(currentNumber)}"><div class="trainer-progress-value" style="width:${percentage.toFixed(1)}%"></div></div><span class="trainer-progress-number">${escapeHtml(formatter(currentNumber))} из ${escapeHtml(formatter(requiredNumber))}</span></div>`;
}

function trainerWaitDescription(waitReason) {
  if (!waitReason) return { text: 'Trainer еще не сообщил причину ожидания.', progress: '' };
  const reason = waitReason.reason || 'unknown';
  const text = trainerWaitLabels[reason] || `Причина ожидания: ${reason}`;
  let progress = '';
  if (reason === 'not_enough_history_for_bootstrap') {
    progress += trainerProgressRow('Уникальные часовые точки', waitReason.timestamps, waitReason.required_timestamps);
  }
  if (reason === 'dynamic_bootstrap_universe_not_ready') {
    progress += trainerProgressRow('Execution-eligible инструменты', waitReason.available_symbols, waitReason.required_symbols);
  }
  if (reason === 'insufficient_symbol_history_coverage') {
    progress += trainerProgressRow('Инструменты с достаточной историей', waitReason.covered_symbols, waitReason.symbol_count);
    progress += trainerProgressRow('Покрытие universe', Number(waitReason.coverage_ratio || 0) * 100, Number(waitReason.required_coverage_ratio || 0) * 100, value => `${fmt(value, 1)}%`);
  }
  if (['not_enough_new_or_changed_training_data', 'not_enough_new_labeled_time', 'quality_gate_failed_waiting_for_new_data', 'training_deferred_waiting_for_new_data'].includes(reason)) {
    progress += trainerProgressRow('Новые размеченные часы', waitReason.new_timestamps, waitReason.required_new_timestamps);
  }
  const pending = waitReason.pending_trigger;
  if (pending?.new_timestamps !== undefined && pending?.required_new_timestamps !== undefined) {
    progress += trainerProgressRow('Новые размеченные часы', pending.new_timestamps, pending.required_new_timestamps);
  }
  const nextDue = waitReason.next_due_at ? ` Следующая допустимая попытка: ${trainerDate(waitReason.next_due_at)}.` : '';
  return { text: `${text}${nextDue}`, progress };
}

function trainerResultMarkup(status, trainer) {
  const heartbeatResult = trainer?.details?.last_result || null;
  const latestJob = status.trainer_control?.latest_training_job || (status.recent_jobs || []).find(job => job.job === 'model_retraining') || null;
  const result = heartbeatResult || latestJob?.details || null;
  if (!result && !latestJob) return '<p class="trainer-message">Завершенных попыток обучения в доступной истории нет.</p>';

  const gate = result?.quality_gate || result?.training_result?.quality_gate || null;
  const candidate = result?.candidate_version || result?.training_result?.candidate_version || '—';
  const activated = result?.activated ?? result?.training_result?.activated;
  const error = result?.error || result?.training_result?.error || null;
  const statusText = error ? 'Ошибка' : (latestJob?.status || 'Завершено');
  const gateText = gate?.passed === true ? 'пройден' : gate?.passed === false ? 'не пройден' : '—';
  const reasons = Array.isArray(gate?.reasons) ? gate.reasons.slice(0, 6) : [];
  return `<dl class="trainer-result-list">
    <dt>Статус последней попытки</dt><dd>${escapeHtml(statusText)}</dd>
    <dt>Начало</dt><dd>${escapeHtml(trainerDate(latestJob?.started_at))}</dd>
    <dt>Завершение</dt><dd>${escapeHtml(trainerDate(latestJob?.finished_at))}</dd>
    <dt>Кандидат</dt><dd>${escapeHtml(candidate)}</dd>
    <dt>Quality gate</dt><dd>${escapeHtml(gateText)}</dd>
    <dt>Активация</dt><dd>${activated === true ? 'выполнена' : activated === false ? 'не выполнена' : '—'}</dd>
    ${error ? `<dt>Ошибка</dt><dd>${escapeHtml(error)}</dd>` : ''}
  </dl>${reasons.length ? `<ul class="trainer-reasons">${reasons.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}`;
}

function automaticExperimentMarkup(experiment) {
  if (!experiment) {
    return '<p class="trainer-message">Automatic experiment для текущего candidate не запущен.</p>';
  }
  const status = experiment.status || 'UNKNOWN';
  const stage = experiment.stage || '—';
  const index = Number(experiment.configuration_index || 0);
  const total = Number(experiment.configuration_count || 0);
  const configurationProgress = index > 0 && total > 0 ? `${index} из ${total}` : '—';
  const configuration = experiment.configuration || {};
  const thresholdText = configuration.minimum_net_rr !== undefined
    ? `RR ≥ ${fmt(configuration.minimum_net_rr, 3)}; EV/R ≥ ${fmt(configuration.minimum_net_ev_r, 3)}`
    : '—';
  return `<dl class="trainer-result-list">
    <dt>Статус</dt><dd>${escapeHtml(status)}</dd>
    <dt>Этап</dt><dd>${escapeHtml(stage)}</dd>
    <dt>Candidate</dt><dd>${escapeHtml(experiment.candidate_version || '—')}</dd>
    <dt>Experiment family</dt><dd>${escapeHtml(experiment.experiment_family || '—')}</dd>
    <dt>Конфигурация</dt><dd>${escapeHtml(configurationProgress)}</dd>
    <dt>Пороговая policy</dt><dd>${escapeHtml(thresholdText)}</dd>
    <dt>Попытка</dt><dd>${escapeHtml(experiment.attempt || '—')}</dd>
    <dt>Запущен</dt><dd>${escapeHtml(trainerDate(experiment.started_at))}</dd>
    <dt>Обновлён</dt><dd>${escapeHtml(trainerDate(experiment.updated_at))}</dd>
    <dt>Subprocess</dt><dd>${experiment.subprocess_active === true ? 'выполняется' : 'не выполняется'}</dd>
  </dl>`;
}

function renderTrainerDialog(status = state.systemStatus) {
  const content = $('#trainer-content');
  if (!content || !status) return;
  const trainer = [...(status.heartbeats || [])].filter(item => item.service === 'trainer').sort((a, b) => Date.parse(b.last_seen_at || 0) - Date.parse(a.last_seen_at || 0))[0] || null;
  const details = trainer?.details || {};
  const control = status.trainer_control || {};
  const online = control.trainer_online === true;
  const enabled = status.auto_training?.enabled === true;
  const healthy = online && details.healthy !== false && !['ERROR', 'STOPPED', 'DISABLED'].includes(details.phase);
  const bannerClass = healthy ? 'ok' : online ? 'warn' : 'bad';
  const processText = !enabled ? 'Автоматическое обучение отключено' : online ? 'Фоновый trainer работает' : 'Фоновый trainer недоступен';
  const phaseText = trainerPhaseLabels[details.phase] || details.phase || 'нет heartbeat';
  const wait = trainerWaitDescription(details.wait_reason);
  const active = status.active_model || {};
  const runtime = active.worker_runtime || {};
  const notice = active.worker_notice || {};
  const artifactArchive = active.artifact_archive || {};
  const artifactDurability = active.artifact_durability || {};
  const archiveState = active.type === 'deterministic_baseline'
    ? 'не требуется для baseline'
    : artifactArchive.available === true
      ? `доступна (${fmt((artifactArchive.size_bytes || 0) / 1048576, 2)} MiB)`
      : active.version ? 'не создана' : '—';
  const durabilityState = artifactDurability.action === 'restored'
    ? 'файл восстановлен из PostgreSQL'
    : artifactDurability.action === 'archived'
      ? 'файл сохранён в PostgreSQL'
      : artifactDurability.action === 'available'
        ? 'файл и архив проверены'
        : artifactDurability.action === 'unavailable'
          ? 'файл и архив недоступны'
          : artifactDurability.action === 'invalid'
            ? 'проверка целостности не пройдена'
            : '—';
  const latestRequest = control.latest_request || null;
  const requestActive = latestRequest && ['PENDING', 'RUNNING'].includes(latestRequest.status);
  const automaticExperiment = control.automatic_experiment || details.automatic_experiment || null;
  const artifactState = active.type === 'deterministic_baseline'
    ? 'registry baseline'
    : active.artifact_exists === true ? 'файл доступен' : active.version ? 'файл отсутствует' : 'активной модели нет';
  const trainingModeLabels = {
    static_configured: 'static configured cohort',
    historical_frozen_dynamic_bootstrap: 'historical frozen dynamic bootstrap',
    prospective_dynamic_replay: 'exact prospective dynamic replay',
  };
  const waitScope = details.wait_reason || {};
  const trainingMode = waitScope.training_universe_mode || '—';
  const trainingEvidence = waitScope.training_universe_evidence || {};
  const recoveryReasonLabels = {
    no_active_model: 'активная модель не зарегистрирована',
    registry_baseline_active: 'активен baseline',
    active_model_artifact_missing: 'artifact активной модели отсутствует',
    active_model_artifact_missing_fail_closed: 'artifact отсутствует, но baseline recovery в этом режиме запрещен',
    active_model_artifact_available: 'artifact активной модели доступен',
    active_model_path_override: 'задан ACTIVE_MODEL_PATH',
    auto_training_disabled: 'автоматическое обучение отключено',
  };

  content.innerHTML = `<div class="trainer-banner ${bannerClass}">
    <div><strong>${escapeHtml(processText)}</strong><small>${escapeHtml(trainer?.instance || 'trainer heartbeat отсутствует')} · ${escapeHtml(trainer?.status || 'UNKNOWN')}</small></div>
    <span class="trainer-phase">${escapeHtml(phaseText)}</span>
  </div>
  <div class="trainer-grid">
    <div class="trainer-card"><span>Последний heartbeat</span><strong>${escapeHtml(trainerDate(trainer?.last_seen_at))}</strong></div>
    <div class="trainer-card"><span>Следующая штатная проверка</span><strong>${escapeHtml(trainerDate(details.next_check_at))}</strong></div>
    <div class="trainer-card"><span>Эффективная модель</span><strong>${escapeHtml(runtime.version || active.version || '—')}</strong></div>
    <div class="trainer-card"><span>Artifact</span><strong>${escapeHtml(artifactState)}</strong></div>
  </div>
  <section class="trainer-section"><h3>Почему trainer сейчас не обучает</h3><p class="trainer-message">${escapeHtml(wait.text)}</p>${wait.progress}</section>
  <section class="trainer-section"><h3>Модель и режим восстановления</h3>
    <dl class="trainer-result-list">
      <dt>Registry version</dt><dd>${escapeHtml(active.version || '—')}</dd>
      <dt>Runtime source</dt><dd>${escapeHtml(runtime.source || '—')}</dd>
      <dt>Fallback notice</dt><dd>${escapeHtml(notice.code || 'нет')}</dd>
      <dt>PostgreSQL archive</dt><dd>${escapeHtml(archiveState)}</dd>
      <dt>Проверка artifact</dt><dd>${escapeHtml(durabilityState)}</dd>
      <dt>Training universe mode</dt><dd>${escapeHtml(trainingModeLabels[trainingMode] || trainingMode)}</dd>
      <dt>Universe evidence</dt><dd>${escapeHtml(trainingEvidence.status || '—')}</dd>
      <dt>Восстановление доступно</dt><dd>${control.recovery_available === true ? 'да' : 'нет'}</dd>
      <dt>Причина</dt><dd>${escapeHtml(recoveryReasonLabels[control.recovery_reason] || control.recovery_reason || '—')}</dd>
    </dl>
  </section>
  <section class="trainer-section"><h3>Automatic experiment</h3>${automaticExperimentMarkup(automaticExperiment)}</section>
  <section class="trainer-section"><h3>Последняя попытка обучения</h3>${trainerResultMarkup(status, trainer)}</section>
  ${latestRequest ? `<div class="trainer-request"><strong>Последняя команда оператора:</strong> ${escapeHtml(latestRequest.action || '—')} · ${escapeHtml(latestRequest.status || '—')} · ${escapeHtml(trainerDate(latestRequest.requested_at || latestRequest.started_at))}</div>` : ''}`;

  const checkButton = $('#trainer-check-button');
  const recoverButton = $('#trainer-recover-button');
  const cancelButton = $('#trainer-cancel-experiment-button');
  checkButton.disabled = !enabled || !online || requestActive;
  recoverButton.disabled = !enabled || !online || control.recovery_available !== true || requestActive;
  cancelButton.disabled = !enabled || !online || control.cancellation_available !== true || requestActive;
  checkButton.title = !online ? 'Trainer не запущен или heartbeat устарел' : requestActive ? 'Предыдущая команда еще выполняется' : '';
  recoverButton.title = control.recovery_available === true
    ? (requestActive ? 'Предыдущая команда еще выполняется' : '')
    : (recoveryReasonLabels[control.recovery_reason] || 'Восстановительное обучение сейчас не требуется');
  cancelButton.title = control.cancellation_available === true
    ? (requestActive ? 'Предыдущая команда еще выполняется' : 'Будет остановлен только указанный текущий subprocess; evidence останется в журнале')
    : (control.cancellation_reason || 'Сейчас нет выполняющегося automatic experiment subprocess');
}

function startTrainerStatusPolling() {
  clearInterval(state.trainerPollTimer);
  let remaining = 30;
  state.trainerPollTimer = setInterval(async () => {
    remaining -= 1;
    try {
      const status = await loadStatus();
      const request = status?.trainer_control?.latest_request;
      if (!request || !['PENDING', 'RUNNING'].includes(request.status) || remaining <= 0) {
        clearInterval(state.trainerPollTimer);
        state.trainerPollTimer = null;
      }
    } catch (_error) {
      if (remaining <= 0) {
        clearInterval(state.trainerPollTimer);
        state.trainerPollTimer = null;
      }
    }
  }, 2000);
}

async function requestTrainerControl(action) {
  const checkButton = $('#trainer-check-button');
  const recoverButton = $('#trainer-recover-button');
  const cancelButton = $('#trainer-cancel-experiment-button');
  const body = { action };
  if (action === 'CANCEL_EXPERIMENT') {
    const experiment = state.systemStatus?.trainer_control?.automatic_experiment || null;
    if (!experiment?.experiment_family || !experiment?.candidate_version) {
      toast('Текущий automatic experiment не имеет точной цели для отмены', 'error');
      return;
    }
    const confirmed = window.confirm(
      `Остановить subprocess experiment family ${experiment.experiment_family} для candidate ${experiment.candidate_version}? ` +
      'Preregistration и уже записанные результаты останутся неизменными.'
    );
    if (!confirmed) return;
    body.experiment_family = experiment.experiment_family;
    body.candidate_version = experiment.candidate_version;
  }
  checkButton.disabled = true;
  recoverButton.disabled = true;
  cancelButton.disabled = true;
  try {
    const result = await api('/api/v1/admin/trainer-control', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    toast(result.created ? 'Команда передана фоновому trainer' : 'Команда trainer уже ожидает выполнения');
    await loadStatus();
    startTrainerStatusPolling();
  } catch (error) {
    toast(error.message, 'error');
    renderTrainerDialog();
  }
}

function updateUniverseState() {
  const universe = state.universeStatus;
  const cards = state.recommendations.length;
  const summary = state.systemStatus?.recommendation_summary || null;
  const planText = summary
    ? ` · исполнимых ${Number(summary.actionable_or_limited_count || 0)} · без сделки ${Number(summary.no_trade_count || 0)} · блокировано ${Number(summary.blocked_count || 0)}`
    : '';
  if (!universe) {
    $('#universe-state').textContent = `Universe: данные worker еще не получены · карточек ${cards}${planText}`;
    return;
  }
  const selected = Number(universe.selected_count || 0);
  const eligible = Number(universe.eligible_before_limit || selected);
  const mode = universe.mode === 'dynamic' ? 'динамический' : 'статический';
  $('#universe-state').textContent = `Universe: ${selected} из ${eligible} · ${mode} · карточек ${cards}${planText}`;
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
  return `<article class="tile ${cls}" data-signal-id="${item.signal_id}" data-plan-id="${item.plan_id}" data-plan-version="${item.plan_version}" tabindex="0" role="button" aria-label="Открыть ${escapeHtml(item.symbol)} ${direction}">
    <div class="tile-header"><span class="symbol">${escapeHtml(item.symbol)}</span><span class="direction">${direction}</span></div>
    <div class="tile-status"><span class="status-chip ${item.executability_status === 'ACTIONABLE' ? 'actionable' : item.executability_status.startsWith('BLOCKED') ? 'blocked' : ''}">${escapeHtml(statusLabel(item.executability_status))}</span><span class="status-chip">${escapeHtml(entryLabel(item.entry_state))}</span><span>${escapeHtml(timeLeft(item.seconds_to_expiry))}</span></div>
    <div class="level-grid">
      <div class="level"><span>Текущая цена</span><strong>${fmtPrice(item.current_price)}</strong></div>
      <div class="level"><span>Зона входа ${helpButton('entry_zone')}</span><strong>${fmtPrice(item.entry.low)}–${fmtPrice(item.entry.high)}</strong></div>
      <div class="level"><span>SL ${helpButton('sl')}</span><strong>${fmtPrice(item.stop_loss)}</strong></div>
      <div class="level"><span>Основной TP ${helpButton('tp')}</span><strong>${fmtPrice(item.main_take_profit)}</strong></div>
    </div>
    <div class="metric-grid">
      <div class="metric"><span class="help-term">Net R/R сигнала ${helpButton('rr_net')}</span><strong>${fmt(item.net_rr, 2)}</strong></div>
      <div class="metric"><span class="help-term">Net EV сигнала ${helpButton('ev_net_r')}</span><strong>${item.net_ev_r >= 0 ? '+' : ''}${fmt(item.net_ev_r, 2)}R</strong></div>
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
  const inference = state.systemStatus?.recommendation_summary?.latest_hourly_inference;
  const inferenceDetails = inference?.details || {};
  const skipCounts = inferenceDetails.skip_counts || {};
  const topSkip = Object.entries(skipCounts).sort((a, b) => Number(b[1]) - Number(a[1]))[0];
  const activeEmpty = $('#active-empty');
  if (groups.active.length === 0) {
    if (groups.watch.length > 0) {
      activeEmpty.textContent = `Исполнимые планы есть, но ${groups.watch.length} сейчас вне зоны входа — они находятся в разделе «Наблюдение».`;
    } else if (groups['no-trade'].length > 0) {
      activeEmpty.textContent = `Сигналы рассчитаны, но ${groups['no-trade'].length} не прошли пороги чистого RR/EV и находятся в разделе «Без сделки».`;
    } else if (topSkip) {
      activeEmpty.textContent = `Последний инференс не опубликовал сигналы. Основная причина: ${topSkip[0]} (${topSkip[1]}).`;
    } else {
      activeEmpty.textContent = 'Сейчас нет исполнимых рекомендаций в зоне входа.';
    }
  }
  for (const [group, groupItems] of Object.entries(groups)) {
    const id = group === 'no-trade' ? 'no-trade' : group;
    $(`#${id}-grid`).innerHTML = groupItems.map(item => tileHtml(item, group)).join('');
    $(`#${id}-count`).textContent = groupItems.length;
    $(`#${id}-empty`).classList.toggle('visible', groupItems.length === 0);
  }
  bindTileEvents();
  bindHelpEvents();
}

function cancelExposureDwell(planId) {
  const pending = state.exposureTimers.get(planId);
  if (pending) clearTimeout(pending.timer);
  state.exposureTimers.delete(planId);
}

function startExposureDwell(planId) {
  const candidate = state.exposureCandidates.get(planId);
  if (!candidate || candidate.ratio < 0.5 || document.visibilityState !== 'visible') return;
  if (state.exposedPlanIds.has(planId) || state.exposureTimers.has(planId)) return;
  const startedAt = Date.now();
  const timer = setTimeout(() => {
    const current = state.exposureCandidates.get(planId);
    state.exposureTimers.delete(planId);
    if (!current || current.ratio < 0.5 || document.visibilityState !== 'visible') return;
    const dwellMs = Date.now() - startedAt;
    state.exposedPlanIds.add(planId);
    state.pendingExposures.push({
      plan_id: planId,
      plan_version: Number(current.element.dataset.planVersion),
      client_event_id: window.crypto?.randomUUID?.() || uid('exposure'),
      page_instance_id: state.pageInstanceId,
      observed_at: new Date().toISOString(),
      viewport_ratio: Math.min(1, Math.max(0.5, current.ratio)),
      dwell_ms: Math.min(600000, Math.max(1000, dwellMs)),
      surface: 'RECOMMENDATION_TILE',
    });
    scheduleExposureFlush();
  }, 1000);
  state.exposureTimers.set(planId, { timer, startedAt });
}

async function flushRecommendationExposures() {
  state.exposureFlushTimer = null;
  if (state.pendingExposures.length === 0) return;
  const batch = state.pendingExposures.splice(0, 100);
  let retryDelay = 200;
  try {
    const result = await api('/api/v1/recommendations/exposures', {
      method: 'POST',
      body: JSON.stringify({ exposures: batch }),
      keepalive: true,
    });
    const nonRecorded = (result?.recorded || []).filter(
      item => !['RECORDED', 'ALREADY_RECORDED'].includes(item.status),
    );
    if (nonRecorded.length > 0) {
      console.warn('Some recommendation exposure events were terminally classified', nonRecorded);
    }
  } catch (error) {
    const status = Number(error?.response?.status || 0);
    const retryable = status === 0 || status === 429 || status >= 500;
    console.warn('Recommendation exposure evidence was not recorded', error);
    if (retryable) {
      // Preserve the original client_event_id/page_instance_id for true idempotency.
      state.pendingExposures.unshift(...batch);
      retryDelay = 5000;
    }
  }
  if (state.pendingExposures.length > 0) scheduleExposureFlush(retryDelay);
}

function scheduleExposureFlush(delayMs = 200) {
  if (state.exposureFlushTimer) return;
  state.exposureFlushTimer = setTimeout(flushRecommendationExposures, delayMs);
}

function bindExposureObserver() {
  if (state.exposureObserver) state.exposureObserver.disconnect();
  state.exposureTimers.forEach(value => clearTimeout(value.timer));
  state.exposureTimers.clear();
  state.exposureCandidates.clear();
  state.exposureObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      const planId = entry.target.dataset.planId;
      if (!planId) return;
      state.exposureCandidates.set(planId, { element: entry.target, ratio: entry.intersectionRatio });
      if (entry.isIntersecting && entry.intersectionRatio >= 0.5) startExposureDwell(planId);
      else cancelExposureDwell(planId);
    });
  }, { threshold: [0, 0.5, 0.75, 1] });
  $$('.tile[data-plan-id]').forEach(tile => state.exposureObserver.observe(tile));
}

function bindTileEvents() {
  $$('.tile').forEach(tile => {
    const open = () => openDetail(tile.dataset.signalId);
    tile.addEventListener('click', event => { if (!event.target.closest('.help-icon')) open(); });
    tile.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); open(); } });
  });
  bindExposureObserver();
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') {
    [...state.exposureTimers.keys()].forEach(cancelExposureDwell);
    return;
  }
  state.exposureCandidates.forEach((_candidate, planId) => startExposureDwell(planId));
});

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
    const outcome = d.counterfactual_outcome;
    const planOutcome = outcome?.plan;
    const planEconomics = d.economics.execution_plan || {};
    const signalBreakEven = d.economics.break_even_tp_probability;
    const signalBreakEvenText = signalBreakEven === null || signalBreakEven === undefined
      ? '—'
      : `${fmt(signalBreakEven * 100, 1)}%`;
    const planBreakEven = planEconomics.break_even_tp_probability;
    const planCard = planEconomics.available ? `<section class="detail-card"><h3>Execution plan · сохраненный расчет</h3>${dataList([
      ['Цена расчета', fmtPrice(planEconomics.entry_price)], ['Net R/R плана', fmt(planEconomics.net_rr, 3)],
      ['Net EV плана', `${planEconomics.net_ev_r >= 0 ? '+' : ''}${fmt(planEconomics.net_ev_r, 3)}R`],
      ['Порог P(TP) при текущем P(timeout)', planBreakEven === null || planBreakEven === undefined ? '—' : `${fmt(planBreakEven * 100, 1)}%`],
      ['Стресс-downside плана', `${fmt(planEconomics.stress_downside_rate * 100, 3)}%`],
      ['Целевой net outcome', `${fmt(planEconomics.upside_rate * 100, 3)}%`],
      ['Timeout net outcome', `${fmt(planEconomics.timeout_net_rate * 100, 3)}%`],
    ])}<p class="section-note">Эти значения пересчитаны из immutable snapshot выбранной версии плана и проверены против сохраненных Net R/R, EV и downside.</p></section>`
      : `<section class="detail-card"><h3>Execution plan · сохраненный расчет</h3><p>Экономика плана не показана: snapshot отсутствует, поврежден или не проходит проверку целостности.</p></section>`;
    const valuationLabels = { VALUED: 'Рассчитано', NOT_SIZED: 'Без безопасного размера', FUNDING_UNAVAILABLE: 'Funding timeline недоступен', PATH_UNAVAILABLE: 'Нет ценового пути от времени плана', INVALID_INPUT: 'Некорректный snapshot плана' };
    const planOutcomePnl = planOutcome?.valuation_status === 'VALUED'
      ? `${fmt(planOutcome.estimated_net_pnl, 4)} USDT`
      : '—';
    const outcomeCard = outcome ? `<section class="detail-card" style="grid-column:1/-1"><h3>Контрфактический исход</h3>${dataList([
      ['Исход первичного барьера', escapeHtml(outcome.outcome)], ['Цена выхода', fmtPrice(outcome.exit_price)],
      ['Время исхода', new Date(outcome.exit_time).toLocaleString('ru-RU')], ['Неоднозначный часовой бар', outcome.ambiguous ? 'Да, консервативно SL' : 'Нет'],
      ['Оценка плана', planOutcome ? escapeHtml(valuationLabels[planOutcome.valuation_status] || planOutcome.valuation_status) : 'Ожидает расчета'],
      ['Оценочный net P&L', planOutcomePnl],
      ['Контрфактический результат', planOutcome?.counterfactual_r === null || planOutcome?.counterfactual_r === undefined ? '—' : `${fmt(planOutcome.counterfactual_r, 4)}R`],
    ])}<p class="section-note">Это автоматическая оценка TP1/SL/TIMEOUT по подтвержденным часовым свечам и сохраненным предположениям плана, а не фактический P&L ручного исполнения.</p></section>` : `<section class="detail-card" style="grid-column:1/-1"><h3>Контрфактический исход</h3><p>Еще не определен: горизонт не завершен, барьер не достигнут либо не хватает подтвержденной свечи.</p></section>`;
    html = `<div class="detail-grid"><section class="detail-card"><h3>Market signal · reference</h3>${dataList([
      ['Gross R/R сигнала', fmt(d.economics.gross_rr, 2)], ['Net R/R сигнала', fmt(d.economics.net_rr, 2)],
      ['Net EV сигнала', `${d.economics.net_ev_r >= 0 ? '+' : ''}${fmt(d.economics.net_ev_r, 3)}R`], ['Порог P(TP) при текущем P(timeout)', signalBreakEvenText],
      ['Стресс-downside сигнала', `${fmt(d.economics.stress_downside_rate * 100, 3)}%`],
    ])}<p class="section-note">Порог безубыточности решает трехисходное уравнение TP/SL/TIMEOUT при фиксированном P(timeout); это не бинарная формула 1/(1+R/R).</p></section>${planCard}<section class="detail-card"><h3>Издержки сигнала</h3>${dataList([
      ['Комиссии round-trip', `${fmt(d.economics.fee_rate_round_trip * 100, 4)}%`], ['Slippage', `${fmt(d.economics.slippage_rate * 100, 4)}%`],
      ['Funding-сценарий', `${fmt(d.economics.funding_rate_scenario * 100, 4)}%`], ['Gross edge', `${fmt(d.economics.gross_edge_rate * 100, 3)}%`],
    ])}<p class="section-note">Spread не прибавляется повторно, когда он уже отражен в исполнимой цене.</p></section>${outcomeCard}</div>`;
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
  $('#profiles-list').innerHTML = state.profiles.map(p => `<div class="profile-row"><div><strong>${escapeHtml(p.name)} ${p.active ? '· активен' : ''}</strong><small>${fmt(p.allocated_capital)} USDT · риск ${fmt(p.risk_rate_pct)}% · общий лимит ${fmt(p.max_total_risk_rate_pct)}% · ${p.default_leverage}× · v${p.version}<br>${p.capital_verified ? 'Капитал подтвержден' : 'Капитал не подтвержден биржей'}</small></div><button class="button secondary activate-profile" data-id="${p.id}" ${p.active ? 'disabled' : ''}>Активировать</button></div>`).join('');
  $$('.activate-profile').forEach(button => button.addEventListener('click', async () => {
    try { await api(`/api/v1/capital-profiles/${button.dataset.id}/activate`, { method: 'POST', body: '{}' }); await loadProfiles(); await loadRecommendations(); } catch (e) { toast(e.message, 'error'); }
  }));
}

$('#profile-form').addEventListener('submit', async event => {
  event.preventDefault();
  const payload = {
    name: $('#profile-name').value, mode: $('#profile-mode').value, allocated_capital: $('#profile-capital').value,
    risk_rate: Number($('#profile-risk').value) / 100,
    default_leverage: Number($('#profile-leverage').value), max_leverage: Number($('#profile-max-leverage').value),
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
$('#trainer-button').addEventListener('click', async () => { $('#trainer-dialog').showModal(); await loadStatus(); });
$('#trainer-refresh-button').addEventListener('click', loadStatus);
$('#trainer-check-button').addEventListener('click', () => requestTrainerControl('CHECK_NOW'));
$('#trainer-recover-button').addEventListener('click', () => requestTrainerControl('RECOVER_NOW'));
$('#trainer-cancel-experiment-button').addEventListener('click', () => requestTrainerControl('CANCEL_EXPERIMENT'));
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
  ['MARKET_SIGNAL_PUBLISHED','EXECUTION_PLAN_UPDATED','ACTIVE_PROFILE_CHANGED','MANUAL_TRADE_UPDATED','COUNTERFACTUAL_OUTCOME_RESOLVED','COUNTERFACTUAL_PLAN_OUTCOME_RECORDED','TRAINER_CONTROL_REQUESTED','TRAINER_CONTROL_COMPLETED'].forEach(type => source.addEventListener(type, source.onmessage));
  source.onerror = () => { $('#system-dot').className = 'status-dot'; };
}

function escapeHtml(value) { const div = document.createElement('div'); div.textContent = String(value ?? ''); return div.innerHTML; }
function debounce(fn, wait) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; }

window.addEventListener('resize', () => hideTooltip());
loadAll().then(connectEvents);
setInterval(() => { renderRecommendations(); }, 30000);
setInterval(() => { loadStatus(); }, 30000);
