"""Portable appearance settings; no registry, account or external dependencies."""
import json
import os
import tempfile
import threading
from pathlib import Path

THEMES = ('midnight', 'amoled', 'ocean', 'forest', 'crimson', 'sunset', 'light', 'system')
DEFAULTS = {'theme': 'midnight', 'compact': False, 'reduce_motion': False,
            'game_folder': '', 'game_aes': '', 'auto_game_update': True}


class Preferences:
    def __init__(self, base):
        self.path = Path(base) / 'settings.json'
        self.lock = threading.Lock()
        self.values = dict(DEFAULTS)
        try:
            self.values.update(self.validate(json.loads(self.path.read_text(encoding='utf-8'))))
        except (OSError, ValueError, TypeError):
            pass

    @staticmethod
    def validate(data):
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ValueError('Unknown appearance setting.')
        if 'theme' in data and data['theme'] not in THEMES:
            raise ValueError('Unknown theme.')
        for key in ('compact', 'reduce_motion', 'auto_game_update'):
            if key in data and not isinstance(data[key], bool):
                raise ValueError(f'{key} must be true or false.')
        for key in ('game_folder', 'game_aes'):
            if key in data and (not isinstance(data[key], str) or len(data[key]) > 2048):
                raise ValueError(f'Invalid {key}.')
        return data

    def read(self):
        with self.lock:
            return dict(self.values)

    def update(self, data):
        data = self.validate(data)
        with self.lock:
            updated = dict(self.values, **data)
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.settings-', suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(updated, stream, indent=2)
                    stream.write('\n')
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
            self.values = updated
            return dict(updated)
