
from sec_guard import guard_open
import re

with guard_open("dashboard/index.html", "r", encoding="utf-8") as f:
    content = f.read()

# Extract rowTopInbox
top_inbox_pattern = r'(<section class="charts-row" id="rowTopInbox">.*?</section>)'
top_inbox_match = re.search(top_inbox_pattern, content, flags=re.DOTALL)
if top_inbox_match:
    row_top_inbox_html = top_inbox_match.group(1)
    content = content.replace(row_top_inbox_html, "")
    
    # Insert it into tab-business at the top
    tab_bus_pattern = r'(<div class="tab-content" id="tab-business">\s*)'
    content = re.sub(tab_bus_pattern, r'\1' + row_top_inbox_html + '\n', content)

# Find rowSchedule end
sched_pattern = r'(<section class="tables-row" id="rowSchedule">.*?</section>)'
risk_html = """
            <!-- Risk Section Placeholder -->
            <section class="tables-row">
                <div class="table-card table-card--full" style="opacity: 0.7;">
                    <div class="chart-header">
                        <h2>🚨 Топ-3 клиента по риску</h2>
                    </div>
                    <div class="table-wrapper">
                        <div class="empty-state">
                            Раздел в разработке<br>
                            Появится в Этапе 6
                        </div>
                    </div>
                </div>
            </section>
"""
content = re.sub(sched_pattern, r'\1\n' + risk_html, content, flags=re.DOTALL)

with guard_open("dashboard/index.html", "w", encoding="utf-8") as f:
    f.write(content)
