"""Upgrade compatibility for device identity, preferences and application links."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop.settings import config_directory
from desktop.native import canonical_app_uri


class UpgradeTests(unittest.TestCase):
    def test_existing_preferences_are_found_on_each_supported_desktop(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            with patch.dict(os.environ,{'APPDATA':str(base),'XDG_CONFIG_HOME':str(base)},clear=True), patch('pathlib.Path.home',return_value=base):
                for platform,new,old,parent in [('linux','credlet','lockbox',base),('win32','Credlet','Lockbox',base),('darwin','Credlet','Lockbox',base/'Library/Application Support')]:
                    with self.subTest(platform=platform), patch('desktop.settings.sys.platform',platform):
                        (parent/old).mkdir(parents=True,exist_ok=True)
                        (parent/old/'settings.json').write_text('{"deviceId":"keep-this-device"}')
                        self.assertEqual(config_directory(),parent/old)
                        (parent/new).mkdir(parents=True,exist_ok=True)
                        (parent/new/'settings.json').write_text('{}')
                        self.assertEqual(config_directory(),parent/new)
                        (parent/new/'settings.json').unlink()

    def test_explicit_directory_takes_precedence_over_legacy_override(self):
        with patch.dict(os.environ,{'CREDLET_CONFIG_DIR':'new-settings','LOCKBOX_CONFIG_DIR':'old-settings'},clear=True):
            self.assertEqual(config_directory(),Path('new-settings'))
        with patch.dict(os.environ,{'LOCKBOX_CONFIG_DIR':'old-settings'},clear=True):
            self.assertEqual(config_directory(),Path('old-settings'))

    def test_legacy_uri_alias_preserves_the_complete_application_identity(self):
        uri='lockbox-app://linux/%2Fopt%2FTest%20App'
        self.assertEqual(canonical_app_uri(uri),'credlet-app://linux/%2Fopt%2FTest%20App')
        self.assertEqual(canonical_app_uri('https://example.com/lockbox-app://'), 'https://example.com/lockbox-app://')
