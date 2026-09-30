/**
 * pipeline.js
 * Renders the Kanban board for Deals
 */

export function renderPipeline(pipeline) {
    const wrapper = document.getElementById('pipelineKanban');
    if (!wrapper) return;
    
    wrapper.innerHTML = '';
    
    if (!pipeline || Object.keys(pipeline).length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет активных сделок 📂</div>';
        return;
    }
    
    const cols = [
        { key: 'presentation', label: 'Презентация' },
        { key: 'negotiation', label: 'Переговоры' },
        { key: 'won', label: 'Успех (Won)' },
        { key: 'lost', label: 'Отказ (Lost)' }
    ];
    
    cols.forEach(col => {
        const items = pipeline[col.key] || [];
        const colDiv = document.createElement('div');
        colDiv.className = 'kanban-col';
        
        let revenueSum = 0;
        items.forEach(i => revenueSum += i.expected_revenue || 0);
        
        colDiv.innerHTML = `
            <div class="kanban-col-header">
                <span>${col.label} (${items.length})</span>
                <span style="color: var(--text-muted)">${revenueSum.toLocaleString()} ₽</span>
            </div>
            <div class="kanban-items">
                ${items.map(item => `
                    <div class="kanban-card" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${encodeURIComponent('30_Deals/' + item.id)}')">
                        <div class="kanban-card-title">${item.title.replace('.md', '')}</div>
                        <div class="kanban-card-client">${item.client}</div>
                        <div class="kanban-card-rev">${(item.expected_revenue || 0).toLocaleString()} ₽</div>
                    </div>
                `).join('')}
            </div>
        `;
        wrapper.appendChild(colDiv);
    });
}
