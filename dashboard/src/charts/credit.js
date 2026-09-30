/**
 * credit.js
 * Radial bar chart — credit load vs capacity
 */
import ApexCharts from 'apexcharts';

let chart = null;

export function renderCreditChart(credit_summary) {
    const ratio = credit_summary.credit_to_mrr_ratio || 0;

    // Color logic based on ratio (lower is better, >30% is warning, >50% is danger)
    let color = '#10b981'; // success
    if (ratio > 30) color = '#f59e0b'; // warning
    if (ratio > 50) color = '#ef4444'; // danger

    const options = {
        chart: {
            type: 'radialBar',
            height: 250,
            background: 'transparent',
        },
        series: [ratio],
        colors: [color],
        plotOptions: {
            radialBar: {
                startAngle: -135,
                endAngle: 135,
                hollow: {
                    margin: 15,
                    size: '65%',
                    background: 'transparent',
                },
                track: {
                    background: 'rgba(255, 255, 255, 0.05)',
                    strokeWidth: '100%',
                },
                dataLabels: {
                    show: true,
                    name: {
                        offsetY: -10,
                        show: true,
                        color: '#94a3b8',
                        fontSize: '12px',
                        fontFamily: 'Inter',
                    },
                    value: {
                        offsetY: 5,
                        color: '#f1f5f9',
                        fontSize: '28px',
                        fontWeight: 800,
                        fontFamily: 'Inter',
                        formatter: (val) => val + '%',
                    }
                }
            }
        },
        fill: {
            type: 'gradient',
            gradient: {
                shade: 'dark',
                type: 'horizontal',
                shadeIntensity: 0.5,
                gradientToColors: [color],
                inverseColors: true,
                opacityFrom: 1,
                opacityTo: 1,
                stops: [0, 100]
            }
        },
        stroke: { lineCap: 'round' },
        labels: ['Доля платежей в MRR'],
    };

    if (chart) chart.destroy();
    chart = new ApexCharts(document.querySelector('#chartCredit'), options);
    chart.render();
}
