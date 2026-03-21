import { api } from './api.js?v=9';
import { renderHome } from './screens/home.js?v=10';
import { renderAdd } from './screens/add.js?v=9';
import { renderStats } from './screens/stats.js?v=10';
import { renderHistory } from './screens/history.js?v=9';
import { renderLimits } from './screens/limits.js?v=9';
import { renderRecurring } from './screens/recurring.js?v=9';
import { renderCategories } from './screens/categories.js?v=9';
import { renderMore } from './screens/more.js?v=9';

// ── State ──────────────────────────────────────────────────────────────────
export const state = {
  userId: null,
  firstName: null,
  currentScreen: 'home',
};

// ── Toast ──────────────────────────────────────────────────────────────────
export function showToast(msg, type = '') {
  let el = document.querySelector('.toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = `toast ${type}`;
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2800);
}

// ── Format helpers (exported for screens) ─────────────────────────────────
export function fmtAmount(n) {
  const abs = Math.abs(Math.round(n));
  return abs.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' L';
}

const MONTHS = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];

export function fmtDate(iso) {
  const d = new Date(iso.includes('T') ? iso : iso + 'Z');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hh}:${mm}`;
}

// ── Router ─────────────────────────────────────────────────────────────────
const screens = { home: renderHome, stats: renderStats, history: renderHistory, more: renderMore };
const subScreens = {
  'add-expense':  () => renderAdd('expense'),
  'add-income':   () => renderAdd('income'),
  limits:         renderLimits,
  recurring:      renderRecurring,
  categories:     renderCategories,
};

export function navigate(screen) {
  state.currentScreen = screen;
  const container = document.getElementById('screen-container');
  container.innerHTML = '<div class="spinner"></div>';

  const render = screens[screen] ?? subScreens[screen];
  if (!render) return;

  // Update active nav tab
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.screen === screen);
  });

  Promise.resolve(render()).then(html => {
    container.innerHTML = html;
    initScreen(screen);
  }).catch(err => {
    container.innerHTML = `<div class="screen"><div class="empty"><div class="empty-icon">⚠️</div><div class="empty-text">${err.message}</div></div></div>`;
  });
}

function initScreen(screen) {
  // Delegate to per-screen init functions via custom event
  document.dispatchEvent(new CustomEvent('screenInit', { detail: screen }));
}

// ── Boot ───────────────────────────────────────────────────────────────────
async function boot() {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const container = document.getElementById('screen-container');
  container.innerHTML = '<div class="spinner"></div>';

  try {
    let initData = tg?.initData ?? '';

    // Local dev fallback
    if (!initData) {
      const debugId = localStorage.getItem('debugUserId') ?? '123456';
      initData = `debug:${debugId}:Dev User:devuser`;
    }

    const user = await api.auth(initData);
    state.userId = user.user_id;
    state.firstName = user.first_name;

    document.getElementById('bottom-nav').classList.remove('hidden');

    document.getElementById('bottom-nav').addEventListener('click', e => {
      const btn = e.target.closest('.nav-btn');
      if (btn) navigate(btn.dataset.screen);
    });

    navigate('home');
  } catch (err) {
    container.innerHTML = `<div class="screen"><div class="empty"><div class="empty-icon">❌</div><div class="empty-text">Ошибка входа: ${err.message}</div></div></div>`;
  }
}

boot();
