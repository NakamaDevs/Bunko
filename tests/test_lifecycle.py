import json
from pathlib import Path
import subprocess
import sys
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

    def unclean_database(self):
        """A notes database whose writer ended without a close, so a WAL file remains."""
        self.workspace.database.parent.mkdir(parents=True)
        script = ("import duckdb,os,sys; c=duckdb.connect(sys.argv[1]); c.execute('CREATE TABLE note (body TEXT)'); "
                  "c.execute(\"INSERT INTO note VALUES ('kept')\"); os._exit(0)")
        subprocess.run([sys.executable, '-c', script, str(self.workspace.database)], check=True)
        self.assertTrue(Path(str(self.workspace.database) + '.wal').exists())

    def backup(self):
        """Run the backup with this interpreter in place of the runtime's Python."""
        real = cli.run
        with patch.object(cli, 'runtime_path', return_value=self.runtime), \
             patch.object(cli, 'run', side_effect=lambda args, cwd, env=None: real([sys.executable, *args[1:]], cwd, env)):
            cli.backup_notes(self.workspace)
        return self.workspace.state / 'backups' / f'notes-before-{cli.version()}.duckdb'

    def test_backup_keeps_notes_that_are_only_in_the_wal_file(self):
        import duckdb
        self.unclean_database()
        backup = self.backup()
        self.assertFalse(Path(str(backup) + '.wal').exists())
        connection = duckdb.connect(str(backup), read_only=True)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute('SELECT body FROM note').fetchall(), [('kept',)])
        self.assertTrue(Path(str(self.workspace.database) + '.wal').exists(), 'the original stays unchanged')
        self.assertEqual([path.name for path in backup.parent.iterdir()], [backup.name])

    def test_backup_refuses_a_database_with_a_live_writer(self):
        import duckdb
        self.workspace.database.parent.mkdir(parents=True)
        writer = subprocess.Popen([sys.executable, '-c',
            "import duckdb,sys,time; c=duckdb.connect(sys.argv[1]); print('open', flush=True); time.sleep(60)",
            str(self.workspace.database)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(writer.wait)
        self.addCleanup(writer.kill)
        self.assertEqual(writer.stdout.readline().strip(), 'open')
        with self.assertRaises(ValueError):
            self.backup()
        self.assertFalse((self.workspace.state / 'backups' / f'notes-before-{cli.version()}.duckdb').exists())

    def test_stop_waits_until_the_notes_database_is_free(self):
        import duckdb
        self.workspace.database.parent.mkdir(parents=True)
        duckdb.connect(str(self.workspace.database)).close()
        (self.workspace.state / 'active.json').write_text(json.dumps({'runtime': str(self.runtime)}))
        writer = subprocess.Popen([sys.executable, '-c',
            "import duckdb,sys,time; c=duckdb.connect(sys.argv[1]); print('open', flush=True); time.sleep(1.5); c.close()",
            str(self.workspace.database)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(writer.wait)
        self.assertEqual(writer.stdout.readline().strip(), 'open')
        real = cli.run
        def run(args, cwd, env=None):
            if str(args[0]).endswith('aspire'): return
            real([sys.executable, *args[1:]], cwd, env)
        with patch.object(cli, 'run', side_effect=run):
            self.assertEqual(cli.main(['stop', '--config', str(self.config)]), 0)
        self.assertIsNotNone(writer.poll(), 'stop returned while the writer still had the database')

    def test_lock_rejects_concurrent_lifecycle_commands(self):
        with cli.workspace_lock(self.workspace):
            with self.assertRaises(ValueError):
                with cli.workspace_lock(self.workspace): pass

    def test_rejects_active_runtime_outside_workspace(self):
        (self.workspace.state / 'active.json').write_text(json.dumps({'runtime':'/tmp/unrelated'}))
        with self.assertRaises(ValueError): cli.active_runtime(self.workspace)


if __name__ == '__main__': unittest.main()
