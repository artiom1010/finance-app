import { api } from '../api.js';
import { state, fmtAmount, fmtDate, showToast } from '../app.js';

const MONTHS_NOM = ['Январь','Февраль','Март','Апрель','Май','Июнь',
                    'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

const PAGE = 20;
let offset  = 0;
let loading = false;
let curYear  = new Date().getFullYear();
let curMonth = new Date().getMonth();

function getYearMonth() {
  return `${curYear}-${String(curMonth + 1).padStart(2, '0')}`;
}

export async function renderHistory() {
  offset  = 0;
  loading = false;
  return `
<div class="screen" style="padding:0">
  <div style="padding:20px 16px 12px">
    <div class="stats-month-nav" style="margin-bottom:0">
      <button class="stats-nav-arrow" id="hist-prev">‹</button>
      <div class="stats-month-label" id="hist-month-label"></div>
      <button class="stats-nav-arrow" id="hist-next">›</button>
    </div>
  </div>
  <div id="tx-list"></div>
  <div id="load-more-wrap" style="padding:16px;text-align:center"></div>

  <!-- Delete confirmation sheet -->
  <div class="confirm-overlay hidden" id="confirm-overlay">
    <div class="confirm-sheet">
      <div class="confirm-title">Удалить транзакцию?</div>
      <div class="confirm-body">Это действие нельзя отменить</div>
      <div class="confirm-actions">
        <button class="btn btn-ghost btn-full" id="confirm-cancel">Отмена</button>
        <button class="btn btn-danger btn-full" id="confirm-ok">Удалить</button>
      </div>
    </div>
  </div>
</div>`;
}

function updateLabel() {
  const el = document.getElementById('hist-month-label');
  if (el) el.textContent = `${MONTHS_NOM[curMonth]} ${curYear} г.`;
}

async function reload() {
  offset = 0;
  loading = false;
  const list = document.getElementById('tx-list');
  const wrap = document.getElementById('load-more-wrap');
  if (list) list.innerHTML = '';
  if (wrap) wrap.innerHTML = '';
  await loadMore();
}

async function loadMore() {
  if (loading) return;
  loading = true;
  const list = document.getElementById('tx-list');
  const wrap = document.getElementById('load-more-wrap');
  if (!list) { loading = false; return; }

  try {
    const items = await api.getTransactions(state.userId, PAGE, offset, getYearMonth());
    offset += items.length;

    if (items.length === 0 && offset === 0) {
      list.innerHTML = '<div class="empty"><div class="empty-icon">📭</div><div class="empty-text">Транзакций нет</div></div>';
      if (wrap) wrap.innerHTML = '';
      loading = false;
      return;
    }

    items.forEach(tx => {
      const div = document.createElement('div');
      div.className = 'tx-item';
      div.dataset.id = tx.id;
      const sign = tx.category_type === 'income' ? '+' : '−';
      div.innerHTML = `
        <div class="tx-emoji">${tx.category_emoji}</div>
        <div class="tx-info">
          <div class="tx-name">${tx.category_name}</div>
          <div class="tx-meta">${fmtDate(tx.created_at)}</div>
          ${tx.note ? `<div class="tx-note">${tx.note}</div>` : ''}
        </div>
        <div class="tx-amount ${tx.category_type}">${sign}${fmtAmount(tx.amount)}</div>
        <button class="tx-delete" data-id="${tx.id}" title="Удалить">✕</button>`;
      list.appendChild(div);
    });

    if (wrap) {
      wrap.innerHTML = items.length === PAGE
        ? '<button class="btn btn-ghost" id="btn-load-more">Загрузить ещё</button>'
        : '<div style="color:var(--hint);font-size:13px;padding:8px">Все транзакции загружены</div>';
      document.getElementById('btn-load-more')?.addEventListener('click', () => loadMore());
    }
  } catch (err) {
    if (list) list.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><div class="empty-text">Ошибка: ${err.message}</div></div>`;
  } finally {
    loading = false;
  }
}

// Confirmation dialog
let pendingDeleteId   = null;
let pendingDeleteItem = null;

function showConfirm(id, item) {
  pendingDeleteId   = id;
  pendingDeleteItem = item;
  document.getElementById('confirm-overlay')?.classList.remove('hidden');
}

function hideConfirm() {
  pendingDeleteId   = null;
  pendingDeleteItem = null;
  document.getElementById('confirm-overlay')?.classList.add('hidden');
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'history') return;

  updateLabel();
  loadMore();

  document.getElementById('hist-prev')?.addEventListener('click', () => {
    curMonth--;
    if (curMonth < 0) { curMonth = 11; curYear--; }
    updateLabel();
    reload();
  });

  document.getElementById('hist-next')?.addEventListener('click', () => {
    const n = new Date();
    if (curYear === n.getFullYear() && curMonth === n.getMonth()) return;
    curMonth++;
    if (curMonth > 11) { curMonth = 0; curYear++; }
    updateLabel();
    reload();
  });

  document.getElementById('tx-list')?.addEventListener('click', ev => {
    const btn = ev.target.closest('.tx-delete');
    if (!btn) return;
    showConfirm(Number(btn.dataset.id), btn.closest('.tx-item'));
  });

  document.getElementById('confirm-cancel')?.addEventListener('click', hideConfirm);

  document.getElementById('confirm-overlay')?.addEventListener('click', ev => {
    if (ev.target === document.getElementById('confirm-overlay')) hideConfirm();
  });

  document.getElementById('confirm-ok')?.addEventListener('click', async () => {
    const id   = pendingDeleteId;
    const item = pendingDeleteItem;
    hideConfirm();
    if (!id) return;
    try {
      await api.deleteTransaction(id, state.userId);
      item?.remove();
      showToast('Удалено');
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'critical');
    }
  });
});
