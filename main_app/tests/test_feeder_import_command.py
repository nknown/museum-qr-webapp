import os
import tempfile
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from main_app.management.commands.feeder_import import Command
from main_app.utils.feeder import FeederImportError


class FeederImportCommandTests(SimpleTestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(os.chdir, self.original_cwd)
        os.chdir(self.temp_dir.name)
        os.mkdir('Feeder')

    def _command(self):
        command = Command()
        command.stdout = StringIO()
        command.stderr = StringIO()
        return command

    @staticmethod
    def _result(title):
        return SimpleNamespace(
            exhibition=SimpleNamespace(title=title),
            created=1,
            updated=2,
            ignored=3,
            attributes=4,
        )

    def test_no_filename_imports_all_supported_files_in_sorted_order(self):
        for filename in ('z-last.xlsx', 'A-first.ods', 'notes.txt', '.hidden.ods'):
            open(os.path.join('Feeder', filename), 'w').close()

        command = self._command()
        with patch(
            'main_app.management.commands.feeder_import.FeederImporter.import_path',
            side_effect=[self._result('First'), self._result('Last')],
        ) as import_path:
            command.handle(file=None, admin=None)

        imported_paths = [call.args[0] for call in import_path.call_args_list]
        self.assertEqual(imported_paths, ['Feeder/A-first.ods', 'Feeder/z-last.xlsx'])
        self.assertIn('Feeder batch complete: 2 imported, 0 failed.', command.stdout.getvalue())

    def test_batch_continues_after_feeder_error_and_reports_failure(self):
        for filename in ('bad.ods', 'good.xlsx'):
            open(os.path.join('Feeder', filename), 'w').close()

        command = self._command()
        with patch(
            'main_app.management.commands.feeder_import.FeederImporter.import_path',
            side_effect=[FeederImportError('broken sheet'), self._result('Good')],
        ) as import_path:
            with self.assertRaisesMessage(
                CommandError,
                'Feeder batch complete: 1 imported, 1 failed. Failed files: bad.ods',
            ):
                command.handle(file=None, admin=None)

        self.assertEqual(import_path.call_count, 2)
        self.assertIn('Failed Feeder/bad.ods: broken sheet', command.stderr.getvalue())

    def test_explicit_filename_keeps_fail_fast_behavior(self):
        command = self._command()
        with patch(
            'main_app.management.commands.feeder_import.FeederImporter.import_path',
            side_effect=FeederImportError('broken sheet'),
        ) as import_path:
            with self.assertRaisesMessage(CommandError, 'broken sheet'):
                command.handle(file='one.ods', admin=None)

        import_path.assert_called_once()
