import { api } from '../api.js';
import { state, showToast } from '../app.js';

export async function renderCategories() {
  return `
<div class="screen">
  <div class="screen-header">
    <button class="btn btn-ghost" id="btn-back" style="padding:8px 12px">←</button>
    <h2>Категории</h2>
  </div>
  <div id="cats-content"><div class="spinner"></div></div>
  <div class="card" style="margin-top:16px">
    <div class="section-title" style="margin-top:0">Добавить личную категорию</div>
    <div class="form-group">
      <label>Название</label>
      <input type="text" id="cat-name" placeholder="Мой кофе" maxlength="40" />
    </div>
    <div class="form-group">
      <label>Тип</label>
      <select id="cat-type">
        <option value="expense">Расход</option>
        <option value="income">Доход</option>
      </select>
    </div>
    <div class="form-group">
      <label>Эмодзи</label>
      <input type="text" id="cat-emoji" placeholder="☕" maxlength="2" style="width:80px" />
    </div>
    <button class="btn btn-primary btn-full" id="btn-add-cat">Добавить</button>
  </div>
</div>`;
}

async function load(userId) {
  const [visible, hidden] = await Promise.all([
    api.getCategories(userId),
    api.getHiddenCategories(userId),
  ]);

  const system   = visible.filter(c => c.user_id === null);
  const personal = visible.filter(c => c.user_id !== null);

  const catRow = (c, actions) => `
    <div class="tx-item">
      <div class="tx-emoji">${c.emoji}</div>
      <div class="tx-info">
        <div class="tx-name">${c.name}</div>
        <div class="tx-meta">${c.type === 'income' ? 'Доход' : 'Расход'}</div>
      </div>
      ${actions}
    </div>`;

  const hiddenRows = hidden.map(c => catRow(c, `
    <button class="btn btn-ghost" style="padding:6px 12px;font-size:13px" data-unhide="${c.id}">Показать</button>`)).join('');

  document.getElementById('cats-content').innerHTML = `
    <div class="card">
      <div class="section-title" style="margin-top:0">Системные</div>
      ${system.map(c => catRow(c, `
        <button class="btn btn-ghost" style="padding:6px 12px;font-size:13px" data-hide="${c.id}">Скрыть</button>
      `)).join('')}
    </div>
    ${personal.length ? `<div class="card">
      <div class="section-title" style="margin-top:0">Личные</div>
      ${personal.map(c => catRow(c, `
        <button class="tx-delete" data-del="${c.id}">✕</button>
      `)).join('')}
    </div>` : ''}
    ${hidden.length ? `<div class="card">
      <div class="section-title" style="margin-top:0">Скрытые</div>
      ${hiddenRows}
    </div>` : ''}`;

  document.querySelectorAll('[data-hide]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api.hideCategory(Number(btn.dataset.hide), userId);
      showToast('Скрыто'); load(userId);
    });
  });
  document.querySelectorAll('[data-unhide]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api.unhideCategory(Number(btn.dataset.unhide), userId);
      showToast('Показано'); load(userId);
    });
  });
  document.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api.deleteCategory(Number(btn.dataset.del), userId);
      showToast('Удалено'); load(userId);
    });
  });
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'categories') return;
  document.getElementById('btn-back')?.addEventListener('click', () => import('../app.js').then(m => m.navigate('more')));
  load(state.userId);

  document.getElementById('btn-add-cat')?.addEventListener('click', async () => {
    const name  = document.getElementById('cat-name').value.trim();
    const type  = document.getElementById('cat-type').value;
    const emoji = document.getElementById('cat-emoji').value.trim() || '📌';
    if (!name) { showToast('Введите название', 'warning'); return; }
    try {
      await api.addCategory({ user_id: state.userId, name, type, emoji });
      showToast('✅ Добавлено');
      document.getElementById('cat-name').value = '';
      document.getElementById('cat-emoji').value = '';
      load(state.userId);
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'critical');
    }
  });
});
