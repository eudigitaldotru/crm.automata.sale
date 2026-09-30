
from sec_guard import guard_open

import os
import re

INVOICES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "30_Invoices")

def repair():
    print(f"Scanning {INVOICES_DIR}...")
    for fname in os.listdir(INVOICES_DIR):
        if not fname.endswith(".md"): continue
        path = os.path.join(INVOICES_DIR, fname)
        
        with guard_open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for corruption: content starts with payment_ keys BEFORE the first ---
        # Pattern: (payment_.*)\n---\n(client:.*)
        
        # We look for lines starting with 'payment_' at the very beginning
        lines = content.split('\n')
        
        stray_lines = []
        clean_lines = []
        frontmatter_start_idx = -1
        
        for i, line in enumerate(lines):
            if line.strip() == '---':
                frontmatter_start_idx = i
                break
            if line.strip() and line.startswith('payment_'):
                stray_lines.append(line)
        
        if stray_lines and frontmatter_start_idx > -1:
            print(f"Repairing {fname}...")
            # We found stray lines before the first ---
            # We need to move them INSIDE the frontmatter (between first and second ---)
            
            # Reconstruct content
            # 1. Remove stray lines from top
            # 2. Find second ---
            # 3. Insert stray lines before second ---
            
            # Simplified approach: Just strip top junk, parsing the rest manually-ish
            
            # Get everything starting from first '---'
            # (assuming strays were strictly before it)
            rest_of_file = '\n'.join(lines[frontmatter_start_idx:])
            
            # Find the closing --- in rest_of_file
            # Skip the first one at index 0
            second_delim_match = re.search(r'\n---', rest_of_file[3:])
            
            if second_delim_match:
                insert_pos = second_delim_match.start() + 3 
                # +3 because search started at [3:]? No.
                # rest_of_file[3:] starts after first '---'. Matches '\n---'.
                # So relative index inside rest_of_file is 3 + match.start()
                
                insertion_point = 3 + second_delim_match.start()
                
                new_block = rest_of_file[:insertion_point] + "\n" + "\n".join(stray_lines) + rest_of_file[insertion_point:]
                
                with guard_open(path, 'w', encoding='utf-8') as f:
                    f.write(new_block)
                print("Fixed.")
            else:
                print("Could not find closing ---, skipping.")

if __name__ == "__main__":
    repair()
