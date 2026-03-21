import { api } from '../api.js';
import { state, fmtAmount, showToast } from '../app.js';

export async function renderRecurring() {
  return `
<div class="screen">
  <div class="screen-header">
    <button class="btn btn-ghost" id="btn-back" style="padding:8px 12px">←</button>
    <h2>Регулярные</h2>
  </div>
  <div id="recurring-list"><div class="spinner"></div></div>
  <div class="card" style="margin-top:16px">
    <div class="section-title" style="margin-top:0">Добавить шаблон</div>
    <div class="form-group">
      <label>Категория</label>
      <select id="rec-cat"></select>
    </div>
    <div class="form-group">
      <label>Сумма (L)</label>
      <input type="number" id="rec-amount" placeholder="1 000" min="1" />
    </div>
    <div class="form-group">
      <label>День месяца (1–31)</label>
      <input type="number" id="rec-day" placeholder="1" min="1" max="31" />
    </div>
    <button class="btn btn-primary btn-full" id="btn-add-rec">Добавить</button>
  </div>
</div>`;
}

async function load(userId) {
  const [items, cats] = await Promise.all([
    api.getRecurring(userId),
    api.getCategories(userId),
  ]);

  const list = document.getElementById('recurring-list');
  if (items.length === 0) {
    list.innerHTML = '<div class="empty"><div class="empty-icon">🔁</div><div class="empty-text">Шаблонов нет</div></div>';
  } else {
    list.innerHTML = `<div class="card">${items.map(r => `
      <div class="tx-item">
        <div class="tx-emoji">${r.category_emoji}</div>
        <div class="tx-info">
          <div class="tx-name">${r.category_name}</div>
          <div class="tx-meta">Каждое ${r.day_of_month}-е число</div>
        </div>
        <div class="tx-amount ${r.category_type}">${fmtAmount(r.amount)}</div>
        <button class="tx-delete" data-del="${r.id}">✕</button>
      </div>`).join('')}</div>`;
  }

  const sel = document.getElementById('rec-cat');
  sel.innerHTML = cats.map(c => `<option value="${c.id}">${c.emoji} ${c.name}</option>`).join('');

  list.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api.deleteRecurring(Number(btn.dataset.del), userId);
      showToast('Удалено');
      load(userId);
    });
  });
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'recurring') return;
  document.getElementById('btn-back')?.addEventListener('click', () => import('../app.js').then(m => m.navigate('more')));
  load(state.userId);

  document.getElementById('btn-add-rec')?.addEventListener('click', async () => {
    const catId  = Number(document.getElementById('rec-cat').value);
    const amount = parseFloat(document.getElementById('rec-amount').value);
    const day    = parseInt(document.getElementById('rec-day').value);
    if (!catId || !(amount > 0) || !(day >= 1 && day <= 31)) {
      showToast('Заполните все поля корректно', 'warning');
      return;
    }
    try {
      await api.addRecurring({ user_id: state.userId, category_id: catId, amount, day_of_month: day });
      showToast('✅ Добавлено');
      document.getElementById('rec-amount').value = '';
      document.getElementById('rec-day').value = '';
      load(state.userId);
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'critical');
    }
  });
});
