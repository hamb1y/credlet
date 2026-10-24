import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import lockbox


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state'
        lockbox.init(self.root, 'vault.example.com', 'owner@example.com')

    def account(self, *emails):
        with contextlib.closing(sqlite3.connect(self.root / 'data/db.sqlite3')) as db, db:
            db.execute('CREATE TABLE users (email TEXT)')
            db.executemany('INSERT INTO users VALUES (?)', [(email,) for email in emails])

    def test_production_has_no_backend_port_or_signup(self):
        cfg = json.loads((self.root / 'compose.json').read_text())
        vault = cfg['services']['vault']
        self.assertNotIn('ports', vault)
        env = vault['environment']
        self.assertEqual(env['SIGNUPS_ALLOWED'], 'false')
        self.assertEqual(env['INVITATIONS_ALLOWED'], 'false')
        self.assertEqual(env['ORG_CREATION_USERS'], 'none')
        self.assertNotIn('ADMIN_TOKEN', env)
        self.assertIn('@sha256:', vault['image'])

    def test_enrollment_is_loopback_only(self):
        cfg = json.loads((self.root / 'enroll.json').read_text())
        self.assertEqual(list(cfg['services']), ['vault'])
        self.assertEqual(cfg['services']['vault']['ports'], ['127.0.0.1:8222:8080'])
        self.assertEqual(cfg['services']['vault']['restart'], 'no')

    def test_owner_gate_rejects_missing_extra_or_wrong_account(self):
        with self.assertRaises(ValueError): lockbox.check_owner(self.root)
        self.account('other@example.com')
        with self.assertRaises(ValueError): lockbox.check_owner(self.root)
        with contextlib.closing(sqlite3.connect(self.root / 'data/db.sqlite3')) as db, db:
            db.execute("UPDATE users SET email = 'owner@example.com'")
        lockbox.check_owner(self.root)
        with contextlib.closing(sqlite3.connect(self.root / 'data/db.sqlite3')) as db, db:
            db.execute("INSERT INTO users VALUES ('extra@example.com')")
        with self.assertRaises(ValueError): lockbox.check_owner(self.root)

    def test_admin_override_is_rejected(self):
        self.account('owner@example.com')
        (self.root / 'data/config.json').write_text('{"signups_allowed":true}')
        with self.assertRaises(ValueError): lockbox.check_owner(self.root)

    def test_round_trip_preserves_database_keys_and_attachments(self):
        self.account('owner@example.com')
        (self.root / 'data/rsa_key.pem').write_bytes(b'test-private-key')
        (self.root / 'data/attachments').mkdir()
        (self.root / 'data/attachments/encrypted').write_bytes(b'encrypted-attachment')
        archive = lockbox.backup(self.root)
        if os.name != 'nt':
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        target = Path(self.tmp.name) / 'restored'
        target.mkdir()
        lockbox.restore(target, archive)
        lockbox.check_owner(target)
        self.assertEqual((target / 'data/rsa_key.pem').read_bytes(), b'test-private-key')
        self.assertEqual((target / 'data/attachments/encrypted').read_bytes(), b'encrypted-attachment')
        compose = json.loads((target / 'compose.json').read_text())
        self.assertEqual(compose['services']['vault']['volumes'][0],
                         lockbox.bind(target / 'data', '/data'))
        self.assertTrue(lockbox.backup(target).is_file())
        for directory in ('backups', 'caddy-data', 'caddy-config'):
            if os.name != 'nt':
                self.assertEqual((target / directory).stat().st_mode & 0o777, 0o700)
        with self.assertRaises(ValueError): lockbox.restore(target, archive)

    def test_restore_cli_accepts_fresh_directory_without_compose_files(self):
        import subprocess
        self.account('owner@example.com')
        archive = lockbox.backup(self.root)
        target = Path(self.tmp.name) / 'fresh'
        original_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == 'docker':
                return subprocess.CompletedProcess(command, 0, stdout='')
            return original_run(command, **kwargs)
        with patch('sys.argv', ['lockbox.py', '--state', str(target), 'restore', str(archive)]), \
             patch('lockbox.subprocess.run', side_effect=run) as calls, \
             contextlib.redirect_stdout(io.StringIO()):
            lockbox.main()
        lockbox.check_owner(target)
        docker = [call for call in calls.call_args_list if call.args[0][0] == 'docker']
        self.assertEqual(len(docker), 2)
        for project, call in zip(('lockbox-enroll', 'lockbox'), docker):
            self.assertIn('label=com.docker.compose.project=' + project, call.args[0])

    def test_unsafe_archive_cannot_escape(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('data/link', tarfile.SYMTYPE), ('/tmp/escape', tarfile.REGTYPE)]:
            with self.subTest(name=name):
                path = Path(self.tmp.name) / 'unsafe.tar.gz'
                with tarfile.open(path, 'w:gz') as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    if kind == tarfile.SYMTYPE: member.linkname = '/tmp'
                    archive.addfile(member, io.BytesIO(b''))
                with self.assertRaises(ValueError): lockbox.restore(self.root, path)
        self.assertFalse((Path(self.tmp.name) / 'outside').exists())

    def test_backup_refuses_live_stack(self):
        import subprocess
        with patch('lockbox.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='running-container\n')):
            with self.assertRaises(ValueError): lockbox.stopped(self.root)

    def test_init_preserves_existing_state(self):
        before = (self.root / 'config.json').read_bytes()
        with self.assertRaises(ValueError): lockbox.init(self.root, 'other.example.com', 'a@example.com')
        self.assertEqual(before, (self.root / 'config.json').read_bytes())

    def test_hostname_rejects_caddy_injection(self):
        for name in ('https://example.com', 'foo.com\nrespond 200', '../example.com', 'localhost', 'x.com:443'):
            with self.assertRaises(ValueError):
                lockbox.init(Path(self.tmp.name) / 'invalid', name, 'a@example.com')


if __name__ == '__main__':
    unittest.main()
