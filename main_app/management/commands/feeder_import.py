import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from main_app.utils.feeder import FeederImporter, FeederImportError


class Command(BaseCommand):
    help = 'Import or update exhibitions with pieces from ODS/Excel files in the Feeder folder'

    def add_arguments(self, parser):
        parser.add_argument(
            'file',
            type=str,
            nargs='?',
            default=None,
            help='Filename to import. If omitted, imports every supported file in Feeder.',
        )
        parser.add_argument(
            '--admin',
            type=str,
            default=None,
            help='Username or email of the curator who should manage the imported exhibition.',
        )

    def _find_files_in_feeder(self):
        feeder_dir = 'Feeder'
        if not os.path.isdir(feeder_dir):
            raise CommandError(f'Feeder directory not found at {feeder_dir}')

        files = sorted(
            (
            filename
            for filename in os.listdir(feeder_dir)
            if os.path.isfile(os.path.join(feeder_dir, filename))
            and filename.lower().endswith(FeederImporter.supported_extensions)
            and not filename.startswith('.')
            ),
            key=str.casefold,
        )

        if not files:
            raise CommandError(f'No ODS/Excel files found in {feeder_dir}')

        return [os.path.join(feeder_dir, filename) for filename in files]

    def handle(self, *args, **options):
        file_arg = options['file']
        import_all = file_arg is None
        if import_all:
            file_paths = self._find_files_in_feeder()
            self.stdout.write(f'Found {len(file_paths)} spreadsheet(s) in Feeder.')
        elif os.sep not in file_arg and '/' not in file_arg:
            file_paths = [os.path.join('Feeder', file_arg)]
        else:
            file_paths = [file_arg]

        admin_user = None
        if options['admin']:
            User = get_user_model()
            admin_user = (
                User.objects.filter(username=options['admin']).first()
                or User.objects.filter(email=options['admin']).first()
            )
            if admin_user is None:
                raise CommandError(f'No user found for --admin={options["admin"]}')

        importer = FeederImporter(writer=self.stdout.write)
        imported = 0
        failures = []

        for file_path in file_paths:
            if import_all:
                self.stdout.write(f'Importing {file_path}...')

            try:
                result = importer.import_path(
                    file_path,
                    admin_user=admin_user,
                    assign_superusers=True,
                )
            except FeederImportError as exc:
                if not import_all:
                    raise CommandError(str(exc))
                failures.append((file_path, str(exc)))
                self.stderr.write(self.style.ERROR(f'Failed {file_path}: {exc}'))
                continue

            imported += 1
            self.stdout.write(self.style.SUCCESS(
                f'Imported "{result.exhibition.title}": '
                f'{result.created} created, {result.updated} updated, '
                f'{result.ignored} ignored, {result.attributes} attributes.'
            ))

        if import_all:
            summary = f'Feeder batch complete: {imported} imported, {len(failures)} failed.'
            if failures:
                failed_names = ', '.join(os.path.basename(path) for path, _ in failures)
                raise CommandError(f'{summary} Failed files: {failed_names}')
            self.stdout.write(self.style.SUCCESS(summary))
