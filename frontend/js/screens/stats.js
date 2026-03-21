import { api } from '../api.js';
import { state, fmtAmount } from '../app.js';
import { renderDoughnut, destroyChart, PASTEL } from '../charts.js?v=10';

const MONTHS_NOM = ['Январь','Февраль','Март','Апрель','Май','Июнь',
                    'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

const now = new Date();
let curYear  = now.getFullYear();
let curMonth = now.getMonth(); // 0-indexed
let curType  = 'expense';

function getYearMonth() {
  return `${curYear}-${String(curMonth + 1).padStart(2, '0')}`;
}

export async function renderStats() {
  return `
<div class="screen">
  <div class="stats-month-nav">
    <button class="stats-nav-arrow" id="stats-prev">‹</button>
    <div class="stats-month-label" id="stats-month-label"></div>
    <button class="stats-nav-arrow" id="stats-next">›</button>
  </div>

  <div class="stats-type-tabs">
    <button class="stats-type-btn ${curType==='expense'?'active':''}" data-type="expense">Расходы</button>
    <button class="stats-type-btn ${curType==='income' ?'active':''}" data-type="income">Доходы</button>
  </div>

  <div id="stats-content"><div class="spinner"></div></div>
</div>`;
}

function updateMonthLabel() {
  const el = document.getElementById('stats-month-label');
  if (el) el.textContent = `${MONTHS_NOM[curMonth]} ${curYear} г.`;
}

async function loadStats() {
  destroyChart('chart-main');
  const content = document.getElementById('stats-content');
  if (!content) return;
  content.innerHTML = '<div class="spinner"></div>';

  const s = await api.getStats(state.userId, 'month', getYearMonth());
  const items = s.by_category.filter(c => c.type === curType);
  const total = curType === 'expense' ? s.expense : s.income;
  const accentColor = curType === 'expense' ? 'var(--expense-t)' : 'var(--income-t)';

  if (items.length === 0) {
    content.innerHTML = `
      <div class="stats-summary-row">
        <div class="stats-summary-item">
          <div class="stats-summary-label">Расходы</div>
          <div class="stats-summary-val exp">−${fmtAmount(s.expense)}</div>
        </div>
        <div class="stats-summary-divider"></div>
        <div class="stats-summary-item">
          <div class="stats-summary-label">Доходы</div>
          <div class="stats-summary-val inc">+${fmtAmount(s.income)}</div>
        </div>
        <div class="stats-summary-divider"></div>
        <div class="stats-summary-item">
          <div class="stats-summary-label">Баланс</div>
          <div class="stats-summary-val ${s.balance>=0?'inc':'exp'}">${s.balance>=0?'+':'−'}${fmtAmount(Math.abs(s.balance))}</div>
        </div>
      </div>
      <div class="empty"><div class="empty-icon">📭</div><div class="empty-text">Нет данных</div></div>`;
    return;
  }

  const catRows = items.map((c, i) => `
    <div class="stats-cat-row">
      <div class="stats-cat-dot" style="background:${PASTEL[i % PASTEL.length]}"></div>
      <div class="stats-cat-emoji">${c.emoji}</div>
      <div class="stats-cat-info">
        <div class="stats-cat-name">${c.name}</div>
        <div class="stats-cat-bar">
          <div class="stats-cat-fill" style="width:${c.percent}%;background:${PASTEL[i % PASTEL.length]}"></div>
        </div>
      </div>
      <div class="stats-cat-right">
        <div class="stats-cat-amount">${fmtAmount(c.amount)}</div>
        <div class="stats-cat-pct">${c.percent}%</div>
      </div>
    </div>`).join('');

  content.innerHTML = `
    <div class="stats-summary-row">
      <div class="stats-summary-item">
        <div class="stats-summary-label">Расходы</div>
        <div class="stats-summary-val exp">−${fmtAmount(s.expense)}</div>
      </div>
      <div class="stats-summary-divider"></div>
      <div class="stats-summary-item">
        <div class="stats-summary-label">Доходы</div>
        <div class="stats-summary-val inc">+${fmtAmount(s.income)}</div>
      </div>
      <div class="stats-summary-divider"></div>
      <div class="stats-summary-item">
        <div class="stats-summary-label">Баланс</div>
        <div class="stats-summary-val ${s.balance>=0?'inc':'exp'}">${s.balance>=0?'+':'−'}${fmtAmount(Math.abs(s.balance))}</div>
      </div>
    </div>

    <div class="card" style="padding:20px 16px">
      <div class="chart-wrap" style="position:relative">
        <canvas id="chart-main"></canvas>
        <div class="chart-center">
          <div class="chart-center-label">${curType === 'expense' ? 'Расходы' : 'Доходы'}</div>
          <div class="chart-center-amount" style="color:${accentColor}">${fmtAmount(total)}</div>
        </div>
      </div>
      <div class="stats-cat-list">${catRows}</div>
    </div>`;

  renderDoughnut('chart-main', items.map(c => c.name), items.map(c => c.amount), {
    emojis:   items.map(c => c.emoji),
    percents: items.map(c => c.percent),
  });
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'stats') return;

  updateMonthLabel();
  loadStats();

  document.getElementById('stats-prev')?.addEventListener('click', () => {
    curMonth--;
    if (curMonth < 0) { curMonth = 11; curYear--; }
    updateMonthLabel();
    loadStats();
  });

  document.getElementById('stats-next')?.addEventListener('click', () => {
    const n = new Date();
    if (curYear === n.getFullYear() && curMonth === n.getMonth()) return; // don't go into future
    curMonth++;
    if (curMonth > 11) { curMonth = 0; curYear++; }
    updateMonthLabel();
    loadStats();
  });

  document.querySelector('.stats-type-tabs')?.addEventListener('click', ev => {
    const btn = ev.target.closest('.stats-type-btn');
    if (!btn) return;
    curType = btn.dataset.type;
    document.querySelectorAll('.stats-type-btn').forEach(b => b.classList.toggle('active', b.dataset.type === curType));
    loadStats();
  });
});
