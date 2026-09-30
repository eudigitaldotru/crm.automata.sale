/**
 * top-clients.js
 * Horizontal bar chart — top clients by revenue
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderTopClientsChart(top_clients_data) {
    const categories = top_clients_data.map(d => d.client);
    const data = top_clients_data.map(d => d.revenue);

    const options = {
        chart: {
            type: 'bar',
            height: 250,
            background: 'transparent',
            toolbar: { show: false },
        },
        series: [{
            name: 'Выручка',
            data: data,
        }],
        plotOptions: {
            bar: {
                horizontal: true,
                borderRadius: 4,
                barHeight: '60%',
                colors: {
                    backgroundBarColors: ['rgba(255,255,255,0.02)'],
                    backgroundBarRadius: 4,
                }
            }
        },
        colors: ['#29A9EA'],
        dataLabels: {
            enabled: true,
            textAnchor: 'start',
            style: { colors: ['#fff'], fontSize: '10px', fontFamily: 'Inter' },
            formatter: function (val, opt) {
                return new Intl.NumberFormat('ru-RU').format(val) + ' ₽';
            },
            offsetX: 10,
        },
        xaxis: {
            categories: categories,
            labels: { show: false },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: {
            labels: {
                style: { colors: '#94a3b8', fontSize: '11px', fontFamily: 'Inter' },
                maxWidth: 150,
            }
        },
        grid: { show: false },
        tooltip: {
            theme: 'dark',
            y: { formatter: v => new Intl.NumberFormat('ru-RU').format(v) + ' ₽' },
        },
        theme: { mode: 'dark' },
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(document.querySelector('#chartTopClients'), options);
    chart.render();
}
