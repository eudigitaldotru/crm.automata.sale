/**
 * lead-funnel.js
 * Bar chart representing Lead Funnel
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderLeadFunnel(funnelData) {
    const wrapper = document.querySelector('#chartLeadFunnel');
    if (!wrapper) return;
    
    // Convert funnel data into sequential array
    const categories = ['Новый', 'В контакте', 'Квалифицирован', 'Отказ'];
    const values = [
        funnelData.new || 0,
        funnelData.contacted || 0,
        funnelData.qualified || 0,
        funnelData.lost || 0
    ];

    const options = {
        chart: {
            type: 'bar',
            height: 250,
            background: 'transparent',
            toolbar: { show: false }
        },
        plotOptions: {
            bar: {
                borderRadius: 4,
                horizontal: true,
                distributed: true,
                barHeight: '60%'
            }
        },
        colors: ['#3b82f6', '#f59e0b', '#10b981', '#ef4444'],
        dataLabels: {
            enabled: true,
            style: { colors: ['#fff'], fontSize: '14px', fontWeight: 700 }
        },
        series: [{
            name: 'Лидов',
            data: values
        }],
        xaxis: {
            categories: categories,
            labels: { style: { colors: '#94a3b8' } },
            axisBorder: { show: false },
            axisTicks: { show: false }
        },
        yaxis: {
            labels: { style: { colors: '#cbd5e1', fontSize: '13px' } }
        },
        grid: {
            borderColor: 'rgba(255,255,255,0.05)',
            xaxis: { lines: { show: true } },
            yaxis: { lines: { show: false } }
        },
        legend: { show: false },
        tooltip: { theme: 'dark' },
        theme: { mode: 'dark' }
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(wrapper, options);
    chart.render();
}
