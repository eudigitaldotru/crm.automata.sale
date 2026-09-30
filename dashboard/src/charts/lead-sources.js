/**
 * lead-sources.js
 * Donut chart for Lead Sources
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderLeadSources(sourcesData) {
    const wrapper = document.querySelector('#chartLeadSources');
    if (!wrapper) return;
    
    const labels = Object.keys(sourcesData);
    const series = Object.values(sourcesData);

    const options = {
        chart: {
            type: 'donut',
            height: 250,
            background: 'transparent',
            animations: { enabled: true, easing: 'easeinout', speed: 600 },
        },
        series: series.length > 0 ? series : [1],
        labels: labels.length > 0 ? labels : ['Нет данных'],
        colors: ['#29A9EA', '#22B8A5', '#34D399', '#FBBF24', '#F4385C'],
        plotOptions: {
            pie: {
                donut: {
                    size: '65%',
                    labels: {
                        show: true,
                        name: { color: '#94a3b8' },
                        value: { color: '#f1f5f9', fontSize: '24px', fontWeight: 800 },
                        total: {
                            show: true,
                            label: 'Лидов',
                            color: '#94a3b8',
                            formatter: function (w) {
                                return w.globals.seriesTotals.reduce((a, b) => a + b, 0);
                            }
                        }
                    }
                }
            }
        },
        dataLabels: { enabled: false },
        stroke: { show: true, colors: ['#0b0e1a'], width: 2 },
        legend: {
            position: 'right',
            labels: { colors: '#94a3b8' }
        },
        tooltip: { theme: 'dark' },
        theme: { mode: 'dark' }
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(wrapper, options);
    chart.render();
}
