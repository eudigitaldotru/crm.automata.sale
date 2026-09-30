import ApexCharts from 'apexcharts';
import { formatRub } from '../utils/data-loader';

export function renderExpensesChart(expenses) {
    if (!expenses || expenses.total === undefined) {
        const ce = document.getElementById('chartExpenses');
        if (ce) ce.innerHTML = '<div class="empty-state">Нет данных о расходах</div>';
        return;
    }

    const { by_category, recent, forecast, analytics, total, total_budget, free_money } = expenses;

    // Define colors for categories
    const categoryColors = {
        'Продукты': '#ff9800',
        'Кафе/Рестораны': '#f44336',
        'Транспорт и Авто': '#2196f3',
        'Сервисы и Услуги': '#9c27b0',
        'Медицина': '#e91e63',
        'Квартира': '#4caf50',
        'Другое': '#78909c'
    };

    // Update Totals Block
    const finFreeMoney = document.getElementById('finFreeMoney');
    const finTotalMoney = document.getElementById('finTotalMoney');
    const finTotalExpenses = document.getElementById('finTotalExpenses');
    
    if (finFreeMoney) finFreeMoney.textContent = formatRub(free_money) + ' ₽';
    if (finTotalMoney) finTotalMoney.textContent = formatRub(total_budget) + ' ₽';
    if (finTotalExpenses) finTotalExpenses.textContent = formatRub(total) + ' ₽';

    // 1. Render Forecast List
    const forecastList = document.getElementById('finForecastList');
    if (forecastList && forecast) {
        let forecastHtml = '';
        forecast.forEach(item => {
            const isOverBudget = item.actual > item.budget && item.budget > 0;
            const pct = item.budget > 0 ? Math.min(100, (item.actual / item.budget) * 100) : 100;
            const color = categoryColors[item.category] || categoryColors['Другое'];
            const actualColor = isOverBudget ? 'var(--danger)' : 'var(--text-primary)';
            
            forecastHtml += `
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="display: flex; align-items: center; gap: 8px;">
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: ${color};"></span>
                            ${item.category}
                        </span>
                        <span style="font-weight: 600; color: ${actualColor};">${formatRub(item.actual)} ₽</span>
                    </div>
                    <div style="height: 6px; background: var(--bg-glass); border-radius: 3px; overflow: hidden; display: flex;">
                        <div style="width: ${pct}%; background: ${color}; height: 100%;"></div>
                        ${isOverBudget ? `<div style="width: ${100 - pct}%; background: var(--danger); height: 100%;"></div>` : ''}
                    </div>
                    <div style="display: flex; justify-content: flex-end; font-size: 0.8em; color: var(--text-muted); margin-top: 2px;">
                        ${item.type === 'planned' ? `из ${formatRub(item.budget)} ₽` : `сверх плана`}
                    </div>
                </div>
            `;
        });
        forecastList.innerHTML = forecastHtml;
    }

    // 2. Render Analytics List
    const analyticsList = document.getElementById('finAnalyticsList');
    if (analyticsList && analytics) {
        let analyticsHtml = '';
        analytics.forEach(item => {
            const isIncrease = item.diff > 0;
            const sign = isIncrease ? '+' : '';
            const colorClass = isIncrease ? 'var(--danger)' : 'var(--success)'; // Increase in expense is bad (danger)
            
            analyticsHtml += `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="width: 12px; height: 12px; border-radius: 50%; background: ${categoryColors[item.category] || categoryColors['Другое']};"></span>
                        <div>
                            <div style="font-weight: 500;">${item.category}</div>
                            <div style="font-size: 0.85em; color: var(--text-muted);">${formatRub(item.current)} ₽</div>
                        </div>
                    </div>
                    <div style="text-align: right; color: ${colorClass};">
                        <div style="font-weight: 600;">${sign}${formatRub(item.diff)} ₽</div>
                        <div style="font-size: 0.8em;">${sign}${item.pct}%</div>
                    </div>
                </div>
            `;
        });
        analyticsList.innerHTML = analyticsHtml;
    }

    // 3. Render Donut Chart
    const ce = document.querySelector("#chartExpenses");
    if (ce && by_category && by_category.length > 0) {
        ce.innerHTML = '';
        const series = by_category.map(c => c.amount);
        const labels = by_category.map(c => c.category);
        const colors = labels.map(l => categoryColors[l] || categoryColors['Другое']);

        const options = {
            series: series,
            chart: {
                type: 'donut',
                height: 300,
                foreColor: 'var(--text-primary)'
            },
            labels: labels,
            colors: colors,
            plotOptions: {
                pie: {
                    donut: {
                        size: '60%',
                        labels: {
                            show: true,
                            name: {
                                show: true,
                                fontSize: '14px',
                                color: 'var(--text-muted)'
                            },
                            value: {
                                show: true,
                                fontSize: '20px',
                                fontWeight: '600',
                                color: 'var(--text-primary)',
                                formatter: (val) => formatRub(val)
                            },
                            total: {
                                show: true,
                                showAlways: true,
                                label: 'Всего',
                                color: 'var(--text-muted)',
                                formatter: function (w) {
                                    return formatRub(expenses.total);
                                }
                            }
                        }
                    }
                }
            },
            dataLabels: {
                enabled: false
            },
            stroke: {
                colors: ['var(--bg-glass)']
            },
            legend: {
                position: 'bottom',
                fontSize: '14px',
                fontFamily: 'Inter, sans-serif'
            },
            tooltip: {
                y: {
                    formatter: function (val) {
                        return formatRub(val);
                    }
                }
            }
        };

        const chart = new ApexCharts(ce, options);
        chart.render();
    }

    // 4. Render Recent Expenses List
    const expenseList = document.getElementById('expenseList');
    if (expenseList && recent && recent.length > 0) {
        let listHtml = '<div class="expense-list-container">';
        recent.forEach(exp => {
            const dateStr = new Date(exp.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
            listHtml += `
                <div class="expense-item">
                    <div class="expense-meta">
                        <div class="expense-cat" style="color: ${categoryColors[exp.category] || '#aaa'}">● ${exp.category}</div>
                        <div class="expense-desc">${exp.description.substring(0, 45)}${exp.description.length > 45 ? '...' : ''}</div>
                    </div>
                    <div class="expense-right">
                        <div class="expense-amount">-${formatRub(exp.amount)}</div>
                        <div class="expense-date">${dateStr}</div>
                    </div>
                </div>
            `;
        });
        listHtml += '</div>';
        expenseList.innerHTML = listHtml;
    }
}
