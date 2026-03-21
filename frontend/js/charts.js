// Pastel maritime palette
export const PASTEL = [
  '#7eb5c4', '#c4a47a', '#8aaa8e', '#c48880', '#9a8ec4',
  '#c4b078', '#7ec4a8', '#c47e98', '#7e9ac4', '#a8c47e',
  '#c4907a', '#7ec4be', '#b4c478', '#c47eb2', '#88b0c4',
];

// Create a grainy canvas pattern for a given base color
function grainPattern(ctx2d, hexColor) {
  const sz = 80;
  const pc = document.createElement('canvas');
  pc.width  = sz;
  pc.height = sz;
  const c = pc.getContext('2d');
  c.fillStyle = hexColor;
  c.fillRect(0, 0, sz, sz);
  // Scatter semi-transparent noise pixels
  for (let i = 0; i < sz * sz * 0.55; i++) {
    const x = (Math.random() * sz) | 0;
    const y = (Math.random() * sz) | 0;
    const bright = Math.random() > 0.5;
    const a = Math.random() * 0.18;
    c.fillStyle = bright ? `rgba(255,255,255,${a})` : `rgba(0,0,0,${a})`;
    c.fillRect(x, y, 1, 1);
  }
  return ctx2d.createPattern(pc, 'repeat');
}

// Chart.js plugin: draw emoji + percent labels outside each segment
function makeEmojiPlugin(emojis, percents) {
  return {
    id: 'emojiLabels',
    afterDraw(chart) {
      const { ctx, chartArea } = chart;
      const meta = chart.getDatasetMeta(0);
      if (!meta?.data?.length) return;

      const cx = (chartArea.left + chartArea.right)  / 2;
      const cy = (chartArea.top  + chartArea.bottom) / 2;
      const outerR = meta.data[0]?.outerRadius ?? 80;
      const labelR  = outerR + 28; // distance from center to label

      ctx.save();
      meta.data.forEach((arc, i) => {
        // Skip tiny slices (< 4%)
        if ((percents[i] ?? 0) < 4) return;

        const midAngle = (arc.startAngle + arc.endAngle) / 2;
        const x = cx + Math.cos(midAngle) * labelR;
        const y = cy + Math.sin(midAngle) * labelR;

        // Emoji
        ctx.font = '15px serif';
        ctx.textAlign    = 'center';
        ctx.textBaseline = 'alphabetic';
        ctx.globalAlpha  = 0.8;
        ctx.fillStyle    = '#c8c2b6';
        ctx.fillText(emojis[i] ?? '', x, y - 3);

        // Percent
        ctx.font         = '500 10px -apple-system, sans-serif';
        ctx.globalAlpha  = 0.65;
        ctx.fillStyle    = '#7a7268';
        ctx.textBaseline = 'top';
        ctx.fillText(`${percents[i]}%`, x, y + 2);
      });
      ctx.restore();
    },
  };
}

export function renderDoughnut(canvasId, labels, data, opts = {}) {
  const { emojis = [], percents = [] } = opts;

  const ctx = document.getElementById(canvasId)?.getContext('2d');
  if (!ctx) return;
  destroyChart(canvasId);
  window._charts = window._charts ?? {};

  // Build grain patterns for each slice
  const bgColors = PASTEL.slice(0, data.length).map(c => grainPattern(ctx, c));

  window._charts[canvasId] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: bgColors,
        borderColor: '#1c2229',
        borderWidth: 3,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '68%',
      layout: { padding: 48 },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const abs = Math.abs(Math.round(ctx.parsed));
              return ' ' + abs.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' L';
            },
          },
          backgroundColor: '#1c2229',
          borderColor: 'rgba(200,192,178,0.07)',
          borderWidth: 1,
          titleColor: '#c8c2b6',
          bodyColor:  '#7a7268',
          padding: 10,
          cornerRadius: 8,
        },
      },
      animation: { duration: 500, easing: 'easeInOutQuart' },
    },
    plugins: emojis.length ? [makeEmojiPlugin(emojis, percents)] : [],
  });
}

export function destroyChart(id) {
  window._charts?.[id]?.destroy();
  if (window._charts) delete window._charts[id];
}
