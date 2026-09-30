
from sec_guard import guard_open
import glob

clients = glob.glob("10_Clients/*.md")
for f in clients:
    with guard_open(f, "r", encoding="utf-8") as file:
        content = file.read()
    
    content = content.replace("`= this.status`", "`= this.lifecycle`")
    content = content.replace("`= this.tariff`", "`= this.support_type` | **План:** `= this.support_plan`")
    
    with guard_open(f, "w", encoding="utf-8") as file:
        file.write(content)
print("✅ Headers updated.")
