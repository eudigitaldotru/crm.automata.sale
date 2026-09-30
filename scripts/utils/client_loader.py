import os
import re
import yaml

def load_client_emails(clients_dir):
    """
    Scans the clients directory and returns a dictionary of {email: client_name}.
    Normalizes emails to lowercase.
    """
    client_emails = {}
    
    if not os.path.exists(clients_dir):
        print(f"Warning: Clients directory not found: {clients_dir}")
        return {}

    for filename in os.listdir(clients_dir):
        if not filename.endswith(".md"):
            continue
            
        filepath = os.path.join(clients_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse Frontmatter
            match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
            if match:
                meta = yaml.safe_load(match.group(1))
                if meta:
                    email_raw = meta.get('email')
                    
                    # Handle single email or list of emails
                    emails = []
                    if isinstance(email_raw, str):
                        emails = [e.strip() for e in email_raw.split(',')]
                    elif isinstance(email_raw, list):
                        emails = [str(e).strip() for e in email_raw]
                        
                    for email in emails:
                        if email and '@' in email:
                            client_emails[email.lower()] = filename.replace('.md', '')
                            
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            
    return client_emails

if __name__ == "__main__":
    # Test run
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    clients_path = os.path.join(base_dir, "10_Clients")
    emails = load_client_emails(clients_path)
    print(f"Found {len(emails)} emails:")
    for email, client in emails.items():
        print(f" - {email} ({client})")
