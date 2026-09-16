/**
 * Trend Chart — Mission Completion Duration vs Baseline
 * SIH 26123 — Bharat Electronics Limited (BEL)
 * Uses Chart.js (loaded from CDN in index.html)
 */

class TrendChart {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.chart  = null;
    if (this.canvas && typeof Chart !== 'undefined') {
      this._init();
    }
  }

  _init() {
    Chart.defaults.color = '#8fa3c4';
    Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
    Chart.defaults.font.size   = 11;

    this.chart = new Chart(this.canvas, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Decentralized DSS',
            data: [],
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56,189,248,0.08)',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#38bdf8',
            tension: 0.4,
            fill: true,
          },
          {
            label: 'Naive Baseline',
            data: [],
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245,158,11,0.06)',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#f59e0b',
            tension: 0.4,
            fill: true,
          },
        ],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        animation:           { duration: 200 },
        interaction:         { intersect: false, mode: 'index' },
        plugins: {
          legend: {
            display: true,
            labels: { boxWidth: 10, padding: 14 },
          },
          tooltip: {
            backgroundColor: 'rgba(8,12,22,0.92)',
            borderColor:     'rgba(148,163,184,0.18)',
            borderWidth:     1,
            titleColor:      '#f0f4fc',
            bodyColor:       '#8fa3c4',
          },
        },
        scales: {
          x: {
            grid:  { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#5a7099', maxTicksLimit: 10 },
            title: { display: true, text: 'Task #', color: '#5a7099' },
          },
          y: {
            grid:  { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#5a7099' },
            title: { display: true, text: 'Duration (ticks)', color: '#5a7099' },
          },
        },
      },
    });
  }

  update(trendHistory) {
    if (!this.chart || !Array.isArray(trendHistory) || trendHistory.length === 0) return;
    const labels = trendHistory.map(d => `#${d.task_number}`);
    const dssData = trendHistory.map(d => d.running_avg_decentralized);
    const baseData = trendHistory.map(d => d.running_avg_baseline);

    this.chart.data.labels             = labels;
    this.chart.data.datasets[0].data   = dssData;
    this.chart.data.datasets[1].data   = baseData;
    this.chart.update('none');
  }
}
