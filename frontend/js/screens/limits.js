import { api } from '../api.js';
import { state, fmtAmount, showToast } from '../app.js';

export async function renderLimits() {
  return `
<div class="screen">
  <div class="screen-header">
    <button class="btn btn-ghost" id="btn-back" style="padding:8px 12px">←</button>
    <h2>Лимиты</h2>
  </div>
  <div id="limits-list"><div class="spinner"></div></div>
  <div class="card" style="margin-top:16px">
    <div class="section-title" style="margin-top:0">Добавить лимит</div>
    <div class="form-group">
      <label>Категория расходов</label>
      <select id="limit-cat"></select>
    </div>
    <div class="form-group">
      <label>Сумма (L)</label>
      <input type="number" id="limit-amount" placeholder="5 000" min="1" />
    </div>
    <button class="btn btn-primary btn-full" id="btn-add-limit">Установить лимит</button>
  </div>
</div>`;
}

async function load(userId) {
  const [limits, cats] = await Promise.all([
    api.getLimits(userId),
    api.getCategories(userId, 'expense'),
  ]);

  const list = document.getElementById('limits-list');
  if (limits.length === 0) {
    list.innerHTML = '<div class="empty"><div class="empty-icon">📋</div><div class="empty-text">Лимитов нет</div></div>';
  } else {
    list.innerHTML = `<div class="card">${limits.map(l => {
      const pct = Math.min(l.spent / l.limit_amount * 100, 100);
      const cls = pct >= 100 ? 'critical' : pct >= 80 ? 'warning' : 'ok';
      return `
      <div class="limit-item">
        <div class="limit-header">
          <div class="limit-name">${l.emoji} ${l.name}</div>
          <button class="btn btn-ghost" style="padding:4px 10px;font-size:12px" data-del="${l.category_id}">✕</button>
        </div>
        <div class="limit-amounts">${fmtAmount(l.spent)} / ${fmtAmount(l.limit_amount)}</div>
        <div class="limit-bar" style="margin-top:6px">
          <div class="limit-fill ${cls}" style="width:${pct}%"></div>
        </div>
      </div>`;
    }).join('')}</div>`;
  }

  // Populate category select
  const sel = document.getElementById('limit-cat');
  sel.innerHTML = cats.map(c => `<option value="${c.id}">${c.emoji} ${c.name}</option>`).join('');

  // Delete buttons
  list.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api.deleteLimit(Number(btn.dataset.del), userId);
      showToast('Лимит удалён');
      load(userId);
    });
  });
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'limits') return;

  const { navigate } = window; // not available, use back button only
  document.getElementById('btn-back')?.addEventListener('click', () => history.back?.() ?? location.reload());

  // Override back to navigate home
  document.getElementById('btn-back')?.addEventListener('click', () => {
    import('../app.js').then(m => m.navigate('more'));
  });

  load(state.userId);

  document.getElementById('btn-add-limit')?.addEventListener('click', async () => {
    const catId  = Number(document.getElementById('limit-cat').value);
    const amount = parseFloat(document.getElementById('limit-amount').value);
    if (!catId || !(amount > 0)) { showToast('Заполните все поля', 'warning'); return; }
    try {
      await api.setLimit({ user_id: state.userId, category_id: catId, amount });
      showToast('✅ Лимит установлен');
      document.getElementById('limit-amount').value = '';
      load(state.userId);
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'critical');
    }
  });
});
