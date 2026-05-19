// =========================================================
// MUSIC DL — frontend logic
// =========================================================

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const api = () => window.pywebview && window.pywebview.api;

const state = {
  rows: [],            // [{id, url, platform, kind, el}]
  config: null,
  progressPollId: null,
};

const notifiedJobs = new Set();

let rowSeq = 0;

const STRINGS = {
  status: {
    queued: 'Queued', running: 'Starting', resolving: 'Resolving',
    downloading: 'Downloading', done: 'Done', error: 'Error',
    cancelled: 'Cancelled', cancelling: 'Cancelling…',
  },
  worker: {
    resolve_tag: 'Resolving',
    download_tag: '↓ Downloading',
    all_resolved: 'All tracks resolved',
  },
  card: {
    cancel: 'Cancel', dismiss: 'Close',
    open_folder: 'Open folder',
    retry: (n) => `↺ Retry (${n})`,
    loading: 'Loading…', track: 'Track',
  },
  notification: {
    body: (name, n) => `${name} — ${n} track${n !== 1 ? 's' : ''} downloaded`,
  },
};

// ---------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------

window.addEventListener('pywebviewready', init);
if (window.pywebview && window.pywebview.api) init();

async function init() {
  if (state._inited) return;
  state._inited = true;

  applyTheme();
  bindEvents();
  await loadConfig();
  addRow();
  updateActionBar();
  applySpotifyState();

  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

async function loadConfig() {
  try {
    state.config = await api().get_config();
  } catch (e) {
    state.config = { spotify_configured: false, music_updater: true };
  }
  $('#music-updater').checked = !!state.config.music_updater;
}

function applySpotifyState() {
  const card = document.querySelector('.platform-card[data-platform="spotify"]');
  const hint = $('#spotify-hint');
  const banner = $('#spotify-banner');
  if (state.config && state.config.spotify_configured) {
    card.classList.add('active');
    hint.textContent = 'Playlists & tracks';
    banner.hidden = true;
  } else {
    card.classList.remove('active');
    hint.textContent = 'Credentials required';
    banner.hidden = false;
  }
}

// ---------------------------------------------------------
// Event binding
// ---------------------------------------------------------

function applyTheme() {
  const saved = localStorage.getItem('music-dl-theme') || '';
  document.documentElement.dataset.theme = saved;
  updateThemeIcon(saved === 'dark');
}

function toggleTheme() {
  const isDark = document.documentElement.dataset.theme === 'dark';
  const next = isDark ? '' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('music-dl-theme', next);
  updateThemeIcon(!isDark);
}

function updateThemeIcon(dark) {
  $('#icon-moon').hidden = dark;
  $('#icon-sun').hidden = !dark;
}

function bindEvents() {
  $('#theme-toggle').addEventListener('click', toggleTheme);
  $('#open-settings').addEventListener('click', openSettings);
  $('#banner-open-settings').addEventListener('click', openSettings);
  $$('#settings-modal [data-close]').forEach(el => el.addEventListener('click', closeSettings));
  $('#save-spotify').addEventListener('click', saveSpotifyCreds);
  $('#clear-spotify').addEventListener('click', clearSpotifyCreds);
  $('#pick-folder').addEventListener('click', pickFolder);
  $('#audio-quality').addEventListener('change', saveAudioQuality);
  $('#toggle-secret').addEventListener('click', toggleSecretReveal);
  $('#music-updater').addEventListener('change', saveMusicUpdater);
  $('#open-logs').addEventListener('click', () => api().open_log_folder().catch(() => {}));
  $('#start-btn').addEventListener('click', startDownloads);
  $('#reset-btn').addEventListener('click', resetAllRows);
  $('#clear-done-btn').addEventListener('click', clearCompletedJobs);

  // Spotify setup helpers
  $('#open-spotify-dev').addEventListener('click', () => {
    api().open_url('https://developer.spotify.com/dashboard');
  });

  $('#copy-redirect-uri').addEventListener('click', () => {
    const btn = $('#copy-redirect-uri');
    const text = btn.dataset.copy;
    navigator.clipboard.writeText(text).then(() => {
      btn.classList.add('copied');
      clearTimeout(btn._copyTimer);
      btn._copyTimer = setTimeout(() => btn.classList.remove('copied'), 2200);
    }).catch(() => {
      // Fallback: select the text for manual copy
      const mono = btn.querySelector('.mono');
      const range = document.createRange();
      range.selectNodeContents(mono);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeSettings();
  });
}

// ---------------------------------------------------------
// Dynamic playlist rows
// ---------------------------------------------------------

function addRow() {
  const id = ++rowSeq;
  const row = document.createElement('div');
  row.className = 'playlist-row';
  row.dataset.rowId = id;
  row.innerHTML = `
    <div class="playlist-input-wrap">
      <input type="text" class="playlist-input"
             placeholder="Paste a Spotify, SoundCloud or YouTube playlist or track URL"
             autocomplete="off" spellcheck="false" />
      <span class="platform-chip" hidden></span>
    </div>
    <button class="remove-row-btn" type="button" aria-label="Remove">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M18 6L6 18M6 6l12 12"/>
      </svg>
    </button>
  `;

  const input = row.querySelector('.playlist-input');
  const wrap = row.querySelector('.playlist-input-wrap');
  const chip = row.querySelector('.platform-chip');
  const removeBtn = row.querySelector('.remove-row-btn');

  const entry = { id, url: '', platform: null, kind: null, el: row };
  state.rows.push(entry);

  input.addEventListener('input', () => handleRowInput(entry, input, wrap, chip));
  input.addEventListener('paste', () => setTimeout(() => handleRowInput(entry, input, wrap, chip), 0));
  chip.addEventListener('click', () => {
    if (chip.classList.contains('config')) openSettings();
  });
  removeBtn.addEventListener('click', () => removeRow(entry));

  $('#playlist-list').appendChild(row);
  input.focus();
  return entry;
}

const TYPE_LABELS = { playlist: 'PLAYLIST', album: 'ALBUM', track: 'TRACK' };
function shortLabel(p) { return { spotify: 'SP', soundcloud: 'SC', youtube: 'YT' }[p] || '?'; }

async function handleRowInput(entry, input, wrap, chip) {
  const url = input.value.trim();
  entry.url = url;
  entry.el.classList.toggle('has-value', url.length > 0);

  if (!url) {
    chip.hidden = true;
    chip.className = 'platform-chip';
    wrap.classList.remove('valid', 'invalid');
    entry.platform = null;
    entry.kind = null;
    updateActionBar();
    return;
  }

  let info = null;
  try { info = await api().detect_url(url); } catch (e) { /* ignore */ }
  entry.platform = info && info.platform;
  entry.kind = info && info.kind;

  wrap.classList.remove('valid', 'invalid');
  chip.className = 'platform-chip';

  if (entry.platform) {
    // Spotify not configured — show warning
    if (entry.platform === 'spotify' && state.config && !state.config.spotify_configured) {
      wrap.classList.add('invalid');
      chip.classList.add('config');
      chip.innerHTML = 'CONFIG';
      chip.title = 'Click to open Settings';
      chip.hidden = false;
    } else {
      wrap.classList.add('valid');
      const typeLabel = TYPE_LABELS[entry.kind] || (entry.kind || 'PLAYLIST').toUpperCase();
      chip.innerHTML = `<span class="chip-platform chip-${entry.platform}">${shortLabel(entry.platform)}</span><span class="chip-type">${typeLabel}</span>`;
      chip.title = '';
      chip.hidden = false;
    }
  } else {
    wrap.classList.add('invalid');
    chip.classList.add('invalid');
    chip.textContent = '?';
    chip.hidden = false;
  }

  ensureTrailingEmptyRow();
  updateActionBar();
}

function removeRow(entry) {
  if (state.rows.length <= 1) {
    const input = entry.el.querySelector('.playlist-input');
    input.value = '';
    input.dispatchEvent(new Event('input'));
    return;
  }
  entry.el.classList.add('leaving');
  setTimeout(() => {
    entry.el.remove();
    state.rows = state.rows.filter(r => r.id !== entry.id);
    ensureTrailingEmptyRow();
    updateActionBar();
  }, 180);
}

function ensureTrailingEmptyRow() {
  const last = state.rows[state.rows.length - 1];
  if (!last) { addRow(); return; }
  if (last.url && last.url.trim().length > 0) addRow();
}

function resetAllRows() {
  // Remove everything then add one empty row
  for (const r of [...state.rows]) {
    r.el.remove();
  }
  state.rows = [];
  addRow();
  updateActionBar();
}

// ---------------------------------------------------------
// Action bar
// ---------------------------------------------------------

function updateActionBar() {
  const filled = state.rows.filter(r => r.url && r.platform);
  const valid = filled.filter(r => !(r.platform === 'spotify' && state.config && !state.config.spotify_configured));

  const btn = $('#start-btn');
  const meta = $('#action-meta');
  const reset = $('#reset-btn');

  btn.disabled = valid.length === 0;
  reset.hidden = filled.length === 0;

  if (filled.length === 0) {
    meta.textContent = 'Paste a URL to begin';
  } else if (valid.length < filled.length) {
    const blocked = filled.length - valid.length;
    meta.textContent = `${valid.length} ready · ${blocked} blocked (Spotify creds)`;
  } else {
    const trackCount    = valid.filter(v => v.kind === 'track').length;
    const albumCount    = valid.filter(v => v.kind === 'album').length;
    const playlistCount = valid.filter(v => v.kind === 'playlist').length;
    const parts = [];
    if (playlistCount) parts.push(`${playlistCount} playlist${playlistCount > 1 ? 's' : ''}`);
    if (albumCount)    parts.push(`${albumCount} album${albumCount > 1 ? 's' : ''}`);
    if (trackCount)    parts.push(`${trackCount} track${trackCount > 1 ? 's' : ''}`);
    meta.textContent = parts.join(' · ') + ' queued';
  }
}

// ---------------------------------------------------------
// Downloads
// ---------------------------------------------------------

async function startDownloads() {
  const urls = state.rows
    .filter(r => r.url && r.platform)
    .filter(r => !(r.platform === 'spotify' && state.config && !state.config.spotify_configured))
    .map(r => r.url);

  if (!urls.length) return;

  // First launch: prompt for output folder if not configured
  const cfg = await api().get_config().catch(() => ({}));
  if (!cfg.output_dir) {
    $('#action-meta').textContent = 'Select a download folder…';
    const folder = await api().pick_folder().catch(() => null);
    if (!folder) {
      $('#action-meta').textContent = 'No folder selected.';
      updateActionBar();
      return;
    }
    await api().update_settings(null, folder).catch(() => {});
    state.config = await api().get_config().catch(() => state.config);
  }

  $('#start-btn').disabled = true;
  $('#progress-panel').hidden = false;
  $('#clear-done-btn').hidden = false;

  let result;
  try {
    result = await api().start_downloads(urls);
  } catch (e) {
    showError(e && e.message || String(e));
    $('#start-btn').disabled = false;
    return;
  }

  if (!result || !result.ok) {
    showError((result && result.error) || 'Could not start downloads');
    $('#start-btn').disabled = false;
    return;
  }

  // Clear the URL rows now that jobs are queued — fresh slate for next batch
  resetAllRows();
  $('#action-meta').textContent = `${result.jobs.length} job(s) running...`;

  startProgressPolling();
}

function showError(msg) {
  $('#action-meta').textContent = 'Error: ' + msg;
}

function startProgressPolling() {
  if (state.progressPollId) return;
  state.progressPollId = setInterval(pollProgress, 400);
  pollProgress();
}

async function pollProgress() {
  let jobs;
  try { jobs = await api().get_progress(); } catch (e) { return; }
  renderProgress(jobs || []);

  const active = (jobs || []).filter(j => !j.done);
  if (active.length === 0) {
    if (state.progressPollId) {
      clearInterval(state.progressPollId);
      state.progressPollId = null;
    }
    // Re-enable start button when at least one valid row exists
    updateActionBar();
    if ((jobs || []).length) {
      $('#action-meta').textContent = 'All jobs finished — paste new URLs to continue';
    }
  } else {
    $('#action-meta').textContent = `${active.length} job(s) running · ${jobs.length - active.length} done`;
  }
}

function renderProgress(jobs) {
  const list = $('#progress-list');

  // Remove dismissed cards
  const validIds = new Set(jobs.map(j => j.job_id));
  for (const card of Array.from(list.children)) {
    if (!validIds.has(card.dataset.jobId)) card.remove();
  }

  for (const job of jobs) {
    // Desktop notification on first done
    if (job.done && !notifiedJobs.has(job.job_id)) {
      notifiedJobs.add(job.job_id);
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification('MUSIC DL', {
          body: STRINGS.notification.body(job.playlist_name || 'Download', job.downloaded),
          icon: 'logo.png',
        });
      }
    }

    let card = list.querySelector(`[data-job-id="${job.job_id}"]`);
    if (!card) {
      card = document.createElement('div');
      card.className = 'progress-card';
      card.dataset.jobId = job.job_id;
      card.innerHTML = `
        <div class="progress-head">
          <div class="progress-titles">
            <div class="progress-title"></div>
            <div class="progress-subtitle"></div>
          </div>
          <div class="progress-head-actions">
            <div class="progress-status"></div>
            <button class="progress-card-btn cancel-btn danger" title="${STRINGS.card.cancel}" type="button">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8">
                <rect x="6" y="6" width="12" height="12" rx="1"/>
              </svg>
            </button>
            <button class="progress-card-btn dismiss-btn" title="${STRINGS.card.dismiss}" type="button" hidden>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="worker-row resolve-worker" hidden>
          <div class="worker-label-row">
            <span class="worker-tag">
              <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" style="flex-shrink:0"><circle cx="10" cy="10" r="6"/><path d="M20 20l-4.35-4.35"/></svg>
              ${STRINGS.worker.resolve_tag}
            </span>
            <span class="worker-track-label"></span>
            <span class="worker-count"></span>
          </div>
          <div class="worker-bar"><div class="worker-bar-fill resolve-fill"></div></div>
        </div>
        <div class="worker-row download-worker">
          <div class="worker-label-row">
            <span class="worker-tag">${STRINGS.worker.download_tag}</span>
            <span class="worker-track-label"></span>
            <span class="worker-count"></span>
          </div>
          <div class="worker-bar"><div class="worker-bar-fill download-fill"></div></div>
        </div>
        <div class="progress-error" hidden></div>
        <div class="progress-footer">
          <div class="progress-counters"></div>
          <div class="progress-footer-actions">
            <button class="ghost-btn small open-folder-btn" type="button" hidden>${STRINGS.card.open_folder}</button>
            <button class="ghost-btn small warn retry-btn" type="button" hidden></button>
          </div>
        </div>
      `;
      card.querySelector('.cancel-btn').addEventListener('click', () => cancelJob(job.job_id));
      card.querySelector('.dismiss-btn').addEventListener('click', () => dismissJob(job.job_id));
      card.querySelector('.open-folder-btn').addEventListener('click', () => {
        const path = card.dataset.folderPath;
        if (path) api().open_folder(path).catch(() => {});
      });
      card.querySelector('.retry-btn').addEventListener('click', async () => {
        const res = await api().retry_failed(card.dataset.jobId).catch(() => null);
        if (res && res.ok) startProgressPolling();
      });
      list.appendChild(card);
    }

    // Persist folder path for open-folder button
    if (job.folder_path) card.dataset.folderPath = job.folder_path;

    // State classes
    card.classList.toggle('done', job.status === 'done');
    card.classList.toggle('error', job.status === 'error');
    card.classList.toggle('cancelled', job.status === 'cancelled' || job.status === 'cancelling');

    // Header
    const title = job.playlist_name || (job.kind === 'track' ? STRINGS.card.track : STRINGS.card.loading);
    card.querySelector('.progress-title').textContent = title;
    const kindLabel = { track: 'Track', album: 'Album', playlist: 'Playlist' }[job.kind] || 'Playlist';
    card.querySelector('.progress-subtitle').textContent = [job.platform_label, kindLabel].join(' · ');

    const statusEl = card.querySelector('.progress-status');
    statusEl.textContent = STRINGS.status[job.status] || job.status;
    statusEl.className = 'progress-status ' + (job.status || '');

    // ── Resolve worker (Spotify only) ──────────────────────
    const resolveWorker = card.querySelector('.resolve-worker');
    const showResolve = job.platform === 'spotify' && job.total > 0 &&
      ['resolving', 'downloading', 'done'].includes(job.status);
    resolveWorker.hidden = !showResolve;
    if (showResolve) {
      const allResolved = job.resolved >= job.total;
      resolveWorker.querySelector('.worker-track-label').textContent =
        allResolved ? STRINGS.worker.all_resolved : (job.resolve_current_label || '');
      resolveWorker.querySelector('.worker-count').textContent =
        `${job.resolved} / ${job.total}`;
      resolveWorker.querySelector('.resolve-fill').style.width =
        (job.resolved / job.total * 100).toFixed(1) + '%';
      resolveWorker.querySelector('.resolve-fill').classList.toggle('resolve-done', allResolved);
    }

    // ── Download worker ─────────────────────────────────────
    const done = job.downloaded + job.failed + job.skipped;
    const dlPct = job.total > 0 ? Math.min(done / job.total * 100, 100) : 0;
    const dlWorker = card.querySelector('.download-worker');
    dlWorker.querySelector('.worker-track-label').textContent = job.current_label || '';
    dlWorker.querySelector('.worker-count').textContent =
      job.total ? `${done} / ${job.total}` : '';
    dlWorker.querySelector('.download-fill').style.width =
      (job.status === 'done' ? 100 : dlPct).toFixed(1) + '%';

    // ── Footer ──────────────────────────────────────────────
    card.querySelector('.progress-counters').textContent = formatCounters(job);

    // ── Error message ────────────────────────────────────────
    const errEl = card.querySelector('.progress-error');
    if (job.error_message) {
      errEl.textContent = job.error_message;
      errEl.hidden = false;
    } else {
      errEl.hidden = true;
    }

    const cancelBtn    = card.querySelector('.cancel-btn');
    const dismissBtn   = card.querySelector('.dismiss-btn');
    const openFolderBtn = card.querySelector('.open-folder-btn');
    const retryBtn     = card.querySelector('.retry-btn');

    cancelBtn.hidden    = !!job.done;
    dismissBtn.hidden   = !job.done;
    openFolderBtn.hidden = !job.done || !job.folder_path;
    retryBtn.hidden     = !job.done || !job.failed;
    if (job.failed) retryBtn.textContent = STRINGS.card.retry(job.failed);
  }
}

function formatCounters(job) {
  if (!job.total) return '';
  const done = job.downloaded + job.skipped;
  let txt = `${done}/${job.total} Tracks downloaded`;
  if (job.failed) txt += ` | ${job.failed} Failed`;
  return txt;
}

async function cancelJob(jobId) {
  try { await api().cancel_job(jobId); } catch (e) { /* ignore */ }
}

async function dismissJob(jobId) {
  const card = document.querySelector(`[data-job-id="${jobId}"]`);
  if (card) card.classList.add('leaving');
  setTimeout(async () => {
    try { await api().dismiss_job(jobId); } catch (e) { /* ignore */ }
    pollProgress();
  }, 160);
}

async function clearCompletedJobs() {
  try { await api().clear_completed(); } catch (e) { /* ignore */ }
  pollProgress();
  // If list is now empty, hide panel
  setTimeout(() => {
    if (!$('#progress-list').children.length) {
      $('#progress-panel').hidden = true;
      $('#clear-done-btn').hidden = true;
    }
  }, 200);
}

// ---------------------------------------------------------
// Settings modal
// ---------------------------------------------------------

async function openSettings() {
  const cfg = await api().get_config();
  state.config = cfg;
  $('#spotify-id').value = cfg.spotify_client_id || '';
  $('#spotify-secret').value = cfg.spotify_client_secret || '';
  $('#spotify-secret').type = 'password';
  setEyeIcon(false);
  $('#output-dir').value = cfg.output_dir || '';
  $('#audio-quality').value = cfg.audio_quality || '320';
  $('#settings-modal').hidden = false;
}

function closeSettings() {
  $('#settings-modal').hidden = true;
}

function toggleSecretReveal() {
  const input = $('#spotify-secret');
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  setEyeIcon(reveal);
}

function setEyeIcon(revealed) {
  $('#toggle-secret .eye-show').hidden = revealed;
  $('#toggle-secret .eye-hide').hidden = !revealed;
}

async function saveSpotifyCreds() {
  const id = $('#spotify-id').value.trim();
  const secret = $('#spotify-secret').value.trim();
  if (!id || !secret) {
    alert('Client ID and Client Secret are required.');
    return;
  }
  await api().save_spotify_creds(id, secret);
  state.config = await api().get_config();
  applySpotifyState();
  // Re-validate any visible rows
  for (const r of state.rows) {
    const input = r.el.querySelector('.playlist-input');
    if (input && input.value) input.dispatchEvent(new Event('input'));
  }
  updateActionBar();
  closeSettings();
}

async function clearSpotifyCreds() {
  await api().clear_spotify_creds();
  state.config = await api().get_config();
  applySpotifyState();
  $('#spotify-id').value = '';
  $('#spotify-secret').value = '';
  for (const r of state.rows) {
    const input = r.el.querySelector('.playlist-input');
    if (input && input.value) input.dispatchEvent(new Event('input'));
  }
  updateActionBar();
}

async function pickFolder() {
  const res = await api().pick_folder();
  if (res && res.ok) {
    $('#output-dir').value = res.path;
    state.config = await api().get_config();
  }
}

async function saveAudioQuality() {
  const q = $('#audio-quality').value;
  await api().update_settings(q, null);
  state.config = await api().get_config();
}

async function saveMusicUpdater() {
  const on = $('#music-updater').checked;
  await api().set_music_updater(on);
  state.config = await api().get_config();
}
