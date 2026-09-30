/**
 * tariffs.js
 * Donut chart — clients by tariff
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderTariffsChart(tariff_distribution) {
    const labels = Object.keys(tariff_distribution);
    const series = Object.values(tariff_distribution);

    const options = {
        chart: {
            type: 'donut',
            height: 250,
            background: 'transparent',
            animations: { enabled: true, easing: 'easeinout', speed: 600 },
        },
        series: series,
        labels: labels,
        colors: ['#2DD4BF', '#29A9EA', '#34D399', '#FBBF24', '#22B8A5'],
        plotOptions: {
            pie: {
                donut: {
                    size: '65%',
                    background: 'transparent',
                    labels: {
                        show: true,
                        name: { color: '#94a3b8' },
                        value: { color: '#f1f5f9', fontSize: '24px', fontWeight: 800 },
                        total: {
                            show: true,
                            showAlways: true,
                            label: 'Всего',
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
            labels: { colors: '#94a3b8' },
            fontSize: '12px',
            markers: { width: 8, height: 8, radius: 4 },
            itemMargin: { vertical: 4 }
        },
        tooltip: { theme: 'dark' },
        theme: { mode: 'dark' },
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(document.querySelector('#chartTariffs'), options);
    chart.render();
}
