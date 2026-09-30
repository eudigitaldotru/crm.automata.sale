/**
 * revenue.js
 * Area chart — monthly revenue (paid vs issued)
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderRevenueChart(series_data) {
    const categories = series_data.map(d => {
        const [y, m] = d.month.split('-');
        return `${new Date(y, m - 1).toLocaleString('ru-RU', { month: 'short' })} ${y}`;
    });

    const options = {
        chart: {
            type: 'area',
            height: 250,
            background: 'transparent',
            toolbar: { show: false },
            zoom: { enabled: false },
            animations: { enabled: true, easing: 'easeinout', speed: 600 },
        },
        series: [
            {
                name: 'Оплачено ₽',
                data: series_data.map(d => d.paid),
            },
            {
                name: 'Выставлено ₽',
                data: series_data.map(d => d.issued),
            },
        ],
        xaxis: {
            categories,
            labels: {
                style: { colors: Array(categories.length).fill('#94a3b8'), fontSize: '11px' },
            },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: {
            labels: {
                style: { colors: ['#94a3b8'], fontSize: '11px' },
                formatter: v => v >= 1000 ? `${(v / 1000).toFixed(0)}к₽` : `${v}₽`,
            },
        },
        colors: ['#2DD4BF', '#29A9EA'],
        fill: {
            type: 'gradient',
            gradient: {
                shadeIntensity: 1,
                opacityFrom: 0.35,
                opacityTo: 0.02,
                stops: [0, 100],
            },
        },
        stroke: { curve: 'smooth', width: 2 },
        markers: { size: 3, hover: { size: 5 } },
        grid: {
            borderColor: 'rgba(255,255,255,0.05)',
            row: { colors: ['transparent'] },
        },
        dataLabels: { enabled: false },
        legend: {
            labels: { colors: '#94a3b8' },
            fontSize: '12px',
        },
        tooltip: {
            theme: 'dark',
            y: { formatter: v => new Intl.NumberFormat('ru-RU').format(v) + ' ₽' },
        },
        theme: { mode: 'dark' },
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(document.querySelector('#chartRevenue'), options);
    chart.render();
}
