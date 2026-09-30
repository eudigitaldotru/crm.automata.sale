/**
 * inbox.js
 * Stacked bar or standard bar chart for communications
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderInboxChart(inbox_data) {
    // Aggregate by source
    const counts = { telegram: 0, email: 0, other: 0 };

    inbox_data.forEach(item => {
        const s = (item.source || '').toLowerCase();
        if (s.includes('tg') || s.includes('telegram')) counts.telegram++;
        else if (s.includes('mail') || s.includes('email')) counts.email++;
        else counts.other++;
    });

    const options = {
        chart: {
            type: 'bar',
            height: 250,
            background: 'transparent',
            toolbar: { show: false },
        },
        series: [{
            name: 'Сообщения',
            data: [counts.telegram, counts.email, counts.other]
        }],
        xaxis: {
            categories: ['Telegram', 'Email', 'Другое'],
            labels: { style: { colors: '#94a3b8', fontSize: '11px' } },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: {
            labels: { style: { colors: '#94a3b8', fontSize: '11px' } },
            forceNiceScale: true,
            decimalsInFloat: 0,
        },
        plotOptions: {
            bar: {
                borderRadius: 4,
                columnWidth: '40%',
                distributed: true,
            }
        },
        dataLabels: {
            enabled: true,
            style: { fontSize: '12px', colors: ['#fff'] }
        },
        colors: ['#29A9EA', '#2DD4BF', '#FBBF24'],
        legend: { show: false },
        grid: {
            borderColor: 'rgba(255,255,255,0.05)',
            strokeDashArray: 4,
        },
        tooltip: { theme: 'dark' },
        theme: { mode: 'dark' },
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(document.querySelector('#chartInbox'), options);
    chart.render();
}
