"""Small, non-gameplay credit included inside generated mod archives."""
import hashlib
import json
from datetime import datetime, timezone

VERSION = '2.2.0'


def add_credits(files):
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode('utf-8') + b'\0')
        digest.update(hashlib.sha256(files[name]).digest())
    signature = digest.hexdigest()
    credit = {
        'watermark': 'ASTRO',
        'tool_creator': 'ASTRO',
        'generator': 'MHUR VFX Color Swapper',
        'version': VERSION,
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'modified_assets': len(files) // 2,
        'content_sha256': signature,
        'note': 'Generated using the VFX Color Swapper created by ASTRO.',
    }
    # An unused metadata path, unique to this content, never replaces a game asset.
    path = f'ModCredits/ASTRO/{signature[:16]}/credits.json'
    files[path] = (json.dumps(credit, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return path
