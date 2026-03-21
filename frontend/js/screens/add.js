import { api } from '../api.js';
import { state, navigate, fmtAmount, showToast } from '../app.js';

export async function renderAdd(type) {
  const cats = await api.getCategories(state.userId, type);
  const title = type === 'expense' ? '➕ Расход' : '➕ Доход';
  const color = type === 'expense' ? 'var(--danger)' : 'var(--success)';

  const catButtons = cats.map(c => `
    <button class="cat-btn" data-id="${c.id}" data-name="${c.name}">
      <span class="cat-emoji">${c.emoji}</span>
      <span class="cat-name">${c.name}</span>
    </button>`).join('');

  return `
<div class="screen">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
    <button class="btn btn-ghost" id="btn-back" style="padding:8px 12px">←</button>
    <h2 style="font-size:20px;font-weight:700;color:${color}">${title}</h2>
  </div>

  <div id="limit-banner"></div>

  <div class="form-group">
    <label>Сумма (L)</label>
    <input type="number" id="amount-input" class="amount-big" placeholder="0" min="0.01" step="0.01" inputmode="decimal" />
  </div>

  <div class="section-title">Категория</div>
  <div class="cat-grid" id="cat-grid">${catButtons}</div>

  <div class="form-group" style="margin-top:16px">
    <label>Заметка (необязательно)</label>
    <input type="text" id="note-input" placeholder="Описание..." maxlength="200" />
  </div>

  <button class="btn btn-primary btn-full" id="btn-save" style="margin-top:8px" disabled>Сохранить</button>
</div>`;
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'add-expense' && e.detail !== 'add-income') return;
  const type = e.detail === 'add-expense' ? 'expense' : 'income';

  let selectedCatId = null;

  document.getElementById('btn-back')?.addEventListener('click', () => navigate('home'));

  // Auto-focus amount input so keyboard opens immediately
  setTimeout(() => document.getElementById('amount-input')?.focus(), 200);

  document.getElementById('cat-grid')?.addEventListener('click', async ev => {
    const btn = ev.target.closest('.cat-btn');
    if (!btn) return;
    // Dismiss keyboard before selecting category
    document.activeElement?.blur();
    document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
    selectedCatId = Number(btn.dataset.id);
    checkSave();

    // Check limit preview for expense
    if (type === 'expense') {
      try {
        const limits = await api.getLimits(state.userId);
        const lim = limits.find(l => l.category_id === selectedCatId);
        const banner = document.getElementById('limit-banner');
        if (lim) {
          const pct = lim.spent / lim.limit_amount * 100;
          if (pct >= 100) {
            banner.innerHTML = `<div class="limit-banner critical">🚨 Лимит исчерпан: потрачено ${fmtAmount(lim.spent)} из ${fmtAmount(lim.limit_amount)}</div>`;
          } else if (pct >= 80) {
            banner.innerHTML = `<div class="limit-banner warning">⚠️ Лимит на 80%: потрачено ${fmtAmount(lim.spent)} из ${fmtAmount(lim.limit_amount)}</div>`;
          } else {
            banner.innerHTML = '';
          }
        } else {
          banner.innerHTML = '';
        }
      } catch (_) { /* ignore */ }
    }
  });

  document.getElementById('amount-input')?.addEventListener('input', checkSave);

  function checkSave() {
    const amount = parseFloat(document.getElementById('amount-input')?.value);
    document.getElementById('btn-save').disabled = !(selectedCatId && amount > 0);
  }

  document.getElementById('btn-save')?.addEventListener('click', async () => {
    const amount = parseFloat(document.getElementById('amount-input').value);
    const note   = document.getElementById('note-input').value.trim() || null;
    const btn    = document.getElementById('btn-save');

    btn.disabled = true;
    btn.textContent = 'Сохраняем...';

    try {
      const res = await api.addTransaction({ user_id: state.userId, category_id: selectedCatId, amount, note });

      if (res.limit_warning) {
        const w = res.limit_warning;
        const icon = w.level === 'critical' ? '🚨' : '⚠️';
        showToast(`${icon} Лимит ${w.percent}%: ${fmtAmount(w.spent)} из ${fmtAmount(w.limit)}`, w.level);
      } else {
        showToast('✅ Сохранено');
      }

      navigate('home');
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'critical');
      btn.disabled = false;
      btn.textContent = 'Сохранить';
    }
  });
});
