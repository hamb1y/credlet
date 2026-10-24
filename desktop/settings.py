"""Locate non-secret desktop settings, including preferences from earlier installs."""
import os
from pathlib import Path
import sys


def config_directory():
    override = os.environ.get('CREDLET_CONFIG_DIR') or os.environ.get('LOCKBOX_CONFIG_DIR')
    if override: return Path(override)
    if sys.platform == 'win32': base, name, legacy = Path(os.environ.get('APPDATA',Path.home())), 'Credlet', 'Lockbox'
    elif sys.platform == 'darwin': base, name, legacy = Path.home()/'Library/Application Support', 'Credlet', 'Lockbox'
    else: base, name, legacy = Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config')), 'credlet', 'lockbox'
    # Reuse existing non-secret preferences and the stable device identifier.
    if not (base/name/'settings.json').exists() and (base/legacy/'settings.json').is_file(): return base/legacy
    return base/name
