import { state, navigate } from '../app.js';

export async function renderMore() {
  return `
<div class="screen">
  <div class="page-title">Настройки</div>
  <ul class="menu-list">
    <li class="menu-item" data-nav="limits">
      <span class="menu-icon">📊</span>
      <span class="menu-label">Лимиты расходов</span>
      <span class="menu-chevron">›</span>
    </li>
    <li class="menu-item" data-nav="recurring">
      <span class="menu-icon">🔁</span>
      <span class="menu-label">Регулярные транзакции</span>
      <span class="menu-chevron">›</span>
    </li>
    <li class="menu-item" data-nav="categories">
      <span class="menu-icon">🗂</span>
      <span class="menu-label">Категории</span>
      <span class="menu-chevron">›</span>
    </li>
  </ul>
  <div class="ai-teaser-card" style="margin-top:20px">
    <div class="ai-teaser-header">
      <div class="ai-teaser-icon">◈</div>
      <div class="ai-teaser-title">ИИ-аналитика — скоро</div>
    </div>
    <div class="ai-teaser-body">Персональный анализ расходов, выявление паттернов и подбор инвестиционных инструментов под ваш профиль риска.</div>
    <div class="ai-teaser-tag">В разработке</div>
  </div>

  <div style="padding:24px 0;text-align:center;color:var(--hint);font-size:13px">
    Finance Mini App · ${state.firstName ?? ''}
  </div>
</div>`;
}

document.addEventListener('screenInit', e => {
  if (e.detail !== 'more') return;
  document.querySelectorAll('.menu-item[data-nav]').forEach(item => {
    item.addEventListener('click', () => navigate(item.dataset.nav));
  });
});
