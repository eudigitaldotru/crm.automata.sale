/**
 * forecast.js
 * Line chart — revenue forecast
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderForecastChart(forecast_data) {
    const categories = forecast_data.map(d => {
        const [y, m] = d.month.split('-');
        return `${new Date(y, m - 1).toLocaleString('ru-RU', { month: 'short' })} ${y}`;
    });

    const options = {
        chart: {
            type: 'line',
            height: 250,
            background: 'transparent',
            toolbar: { show: false },
            zoom: { enabled: false }
        },
        series: [
            { name: 'Оптимистичный', data: forecast_data.map(d => d.optimistic) },
            { name: 'Базовый', data: forecast_data.map(d => d.base) },
            { name: 'Пессимистичный', data: forecast_data.map(d => d.pessimistic) },
        ],
        xaxis: {
            categories,
            labels: { style: { colors: '#94a3b8', fontSize: '11px' } },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: {
            labels: {
                style: { colors: '#94a3b8', fontSize: '11px' },
                formatter: v => v >= 1000 ? `${(v / 1000).toFixed(0)}к` : `${v}`,
            },
        },
        colors: ['#34D399', '#2DD4BF', '#F4385C'],
        stroke: {
            width: [2, 3, 2],
            curve: 'smooth',
            dashArray: [4, 0, 4]
        },
        markers: { size: 0 },
        grid: {
            borderColor: 'rgba(255,255,255,0.05)',
            row: { colors: ['transparent'] },
        },
        legend: {
            labels: { colors: '#94a3b8' },
            fontSize: '12px',
            itemMargin: { horizontal: 10, vertical: 0 }
        },
        tooltip: {
            theme: 'dark',
            y: { formatter: v => new Intl.NumberFormat('ru-RU').format(v) + ' ₽' },
        },
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(document.querySelector('#chartForecast'), options);
    chart.render();
}
