import json
from config import TEMPLATES_DIR

def load_announcement_template(template_id, lang, **kwargs):
    template_path = TEMPLATES_DIR / "announcements.json"
    if not template_path.exists():
        return None
        
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            templates = json.load(f)
            
        template = templates.get(template_id, {}).get(lang)
        if not template:
            # Fallback to English if language not found
            template = templates.get(template_id, {}).get('en')
            
        if template:
            return template.format(**kwargs)
    except Exception as e:
        print(f"Error loading announcement template: {e}")
        
    return None
