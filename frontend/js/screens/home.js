import { api } from '../api.js';
import { state, fmtAmount, showToast } from '../app.js';

const MONTHS_NOM = ['Январь','Февраль','Март','Апрель','Май','Июнь',
                    'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

const now = new Date();
let curYear  = now.getFullYear();
let curMonth = now.getMonth();

function getYearMonth() {
  return `${curYear}-${String(curMonth + 1).padStart(2, '0')}`;
}

function makeCatBtns(cats, type) {
  return cats.map(c => `
    <button class="home-cat-item" data-id="${c.id}" data-type="${type}" data-name="${c.name}" data-emoji="${c.emoji}">
      <span class="home-cat-emoji">${c.emoji}</span>
      <span class="home-cat-name">${c.name}</span>
    </button>`).join('');
}

export async function renderHome() {
  const [expCats, incCats] = await Promise.all([
    api.getCategories(state.userId, 'expense'),
    api.getCategories(state.userId, 'income'),
  ]);

  return `
<div class="screen">
  <div class="stats-month-nav">
    <button class="stats-nav-arrow" id="home-prev">‹</button>
    <div class="stats-month-label" id="home-month-label"></div>
    <button class="stats-nav-arrow" id="home-next">›</button>
  </div>

  <div id="home-stats"><div class="spinner" style="padding:32px"></div></div>

  <div class="card" style="padding:16px 12px 12px">
    <div class="home-cat-section-title exp">Расходы</div>
    <div class="home-cat-grid">${makeCatBtns(expCats, 'expense')}</div>
    <div class="home-cat-divider"></div>
    <div class="home-cat-section-title inc">Доходы</div>
    <div class="home-cat-grid">${makeCatBtns(incCats, 'income')}</div>
  </div>

  <!-- Quick-add bottom sheet -->
  <div class="quick-add-overlay hidden" id="qa-overlay">
    <div class="quick-add-sheet">
<div class="quick-add-header">
        <div class="quick-add-emoji" id="qa-emoji"></div>
        <div>
          <div class="quick-add-type" id="qa-type"></div>
          <div class="quick-add-name" id="qa-cat-name"></div>
        </div>
      </div>
      <div class="form-group">
        <label>Сумма (L)</label>
        <input type="number" id="qa-amount" class="amount-big" placeholder="0" min="0.01" step="0.01" inputmode="decimal" />
      </div>
      <div class="form-group">
        <label>Заметка (необязательно)</label>
        <input type="text" id="qa-note" placeholder="Описание..." maxlength="200" />
      </div>
      <button class="btn btn-primary btn-full" id="qa-save" disabled>Сохранить</button>
    </div>
  </div>
</div>`;
}

function updateLabel() {
  const el = document.getElementById('home-month-label');
  if (el) el.textContent = `${MONTHS_NOM[curMonth]} ${curYear} г.`;
}

async function loadStats() {
  const el = document.getElementById('home-stats');
  if (!el) return;
  el.innerHTML = '<div class="spinner" style="padding:32px"></div>';

  const stats = await api.getStats(state.userId, 'month', getYearMonth());
  const sign = stats.balance >= 0 ? '+' : '−';
  const balClass = stats.balance >= 0 ? 'positive' : 'negative';

  el.innerHTML = `
    <div class="card balance-card">
      <div class="balance-label">Баланс</div>
      <div class="balance-amount ${balClass}">${sign}${fmtAmount(Math.abs(stats.balance))}</div>
      <div class="balance-sub">
        <div class="balance-sub-item">
          <div class="balance-sub-label">Расходы</div>
          <div class="balance-sub-val exp">−${fmtAmount(stats.expense)}</div>
        </div>
        <div class="balance-sub-item">
          <div class="balance-sub-label">Доходы</div>
          <div class="balance-sub-val inc">+${fmtAmount(stats.income)}</div>
        </div>
      </div>
    </div>`;
}

// Quick-add state
let qaId = null;

function openQuickAdd(id, type, name, emoji) {
  qaId = id;
  document.getElementById('qa-emoji').textContent    = emoji;
  document.getElementById('qa-cat-name').textContent = name;
  const typeEl = document.getElementById('qa-type');
  typeEl.textContent = type === 'expense' ? 'Расход' : 'Доход';
  typeEl.className   = `quick-add-type ${type}`;
  document.getElementById('qa-amount').value  = '';
  document.getElementById('qa-note').value    = '';
  document.getElementById('qa-save').disabled = true;
  document.getElementById('qa-overlay').classList.remove('hidden');
  document.getElementById('qa-amount')?.focus();
}

function closeQuickAdd() {
  document.activeElement?.blur();
  document.getElementById('qa-overlay')?.classList.add('hidden');
  window.scrollTo(0, 0);
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'home') return;

  updateLabel();
  loadStats();

  document.getElementById('home-prev')?.addEventListener('click', () => {
    curMonth--;
    if (curMonth < 0) { curMonth = 11; curYear--; }
    updateLabel();
    loadStats();
  });

  document.getElementById('home-next')?.addEventListener('click', () => {
    const n = new Date();
    if (curYear === n.getFullYear() && curMonth === n.getMonth()) return;
    curMonth++;
    if (curMonth > 11) { curMonth = 0; curYear++; }
    updateLabel();
    loadStats();
  });

  // Category tap → open quick-add popup
  document.querySelectorAll('.home-cat-grid').forEach(grid => {
    grid.addEventListener('click', ev => {
      const btn = ev.target.closest('.home-cat-item');
      if (!btn) return;
      openQuickAdd(Number(btn.dataset.id), btn.dataset.type, btn.dataset.name, btn.dataset.emoji);
    });
  });

  // Close on backdrop tap
  document.getElementById('qa-overlay')?.addEventListener('click', ev => {
    if (ev.target === document.getElementById('qa-overlay')) closeQuickAdd();
  });

  // Enable save when amount is valid
  document.getElementById('qa-amount')?.addEventListener('input', () => {
    const v = parseFloat(document.getElementById('qa-amount').value);
    document.getElementById('qa-save').disabled = !(v > 0);
  });

  // Save transaction
  document.getElementById('qa-save')?.addEventListener('click', async () => {
    const amount = parseFloat(document.getElementById('qa-amount').value);
    const note   = document.getElementById('qa-note').value.trim() || null;
    const btn    = document.getElementById('qa-save');

    btn.disabled    = true;
    btn.textContent = 'Сохраняем...';

    try {
      const res = await api.addTransaction({ user_id: state.userId, category_id: qaId, amount, note });

      if (res.limit_warning) {
        const w = res.limit_warning;
        const icon = w.level === 'critical' ? '🚨' : '⚠️';
        showToast(`${icon} Лимит ${w.percent}%: ${fmtAmount(w.spent)} из ${fmtAmount(w.limit)}`, w.level);
      } else {
        showToast('✅ Сохранено');
      }

      closeQuickAdd();
      loadStats();
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'critical');
      btn.disabled    = false;
      btn.textContent = 'Сохранить';
    }
  });
});
