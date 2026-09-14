import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bunko_app import cli
from bunko_app.config import Workspace


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'guide').mkdir()
        self.config = self.root / 'workspace.json'
        self.config.write_text(json.dumps({'name':'Test','repositories':{'test':'.'},
            'documentation':[{'id':'guide','label':'Guide','repository':'test','path':'guide'}]}))
        self.workspace = Workspace.load(self.config)
        self.runtime = self.workspace.state / 'runtimes/test'
        self.runtime.mkdir(parents=True)
        (self.runtime / '.ready').write_text('test')

    def test_failed_start_keeps_owner_for_stop(self):
        with patch.object(cli, 'ensure_runtime', return_value=self.runtime), patch.object(cli, 'backup_notes'), \
             patch.object(cli, 'run', side_effect=subprocess.CalledProcessError(1, 'aspire')):
            self.assertEqual(cli.main(['start','--config',str(self.config)]), 1)
        self.assertEqual(cli.active_runtime(self.workspace), self.runtime)
        with patch.object(cli, 'run') as run:
            self.assertEqual(cli.main(['stop','--config',str(self.config)]), 0)
        self.assertIn(str(self.runtime / 'apphost.mts'), [str(arg) for arg in run.call_args.args[0]])
        self.assertIsNone(cli.active_runtime(self.workspace))

    def test_stop_does_not_prepare_or_delete_notes(self):
        self.workspace.database.parent.mkdir(parents=True)
        self.workspace.database.write_bytes(b'preserve')
        with patch.object(cli, 'ensure_runtime') as prepare:
            self.assertEqual(cli.main(['stop','--config',str(self.config)]), 0)
            prepare.assert_not_called()
        self.assertEqual(self.workspace.database.read_bytes(), b'preserve')

    def test_lock_rejects_concurrent_lifecycle_commands(self):
        with cli.workspace_lock(self.workspace):
            with self.assertRaises(ValueError):
                with cli.workspace_lock(self.workspace): pass

    def test_rejects_active_runtime_outside_workspace(self):
        (self.workspace.state / 'active.json').write_text(json.dumps({'runtime':'/tmp/unrelated'}))
        with self.assertRaises(ValueError): cli.active_runtime(self.workspace)


if __name__ == '__main__': unittest.main()
