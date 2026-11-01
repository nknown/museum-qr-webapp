from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PresentationOwnershipMigrationTests(TransactionTestCase):
    reset_sequences = True

    def test_layout_defaults_are_consolidated_on_exhibitions(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('main_app', '0004_exhibition_appearance_enabled_and_more')])
        old = executor.loader.project_state([
            ('main_app', '0004_exhibition_appearance_enabled_and_more')
        ]).apps
        Museum = old.get_model('main_app', 'Museum')
        Exhibition = old.get_model('main_app', 'Exhibition')
        Piece = old.get_model('main_app', 'Piece')

        museum = Museum.objects.create(
            title='Museum',
            presentation_templates={
                'on_site': 'fomantic_on_site_widescreen_v1',
                'user_device': 'fomantic_user_device_v1',
            },
        )
        own = Exhibition.objects.create(
            title='Own layout', museum=museum,
            Exhibition_attributes={'presentation_templates': {
                'on_site': 'fomantic_on_site_standard_v1',
            }},
        )
        inherited = Exhibition.objects.create(title='Museum layout', museum=museum)
        orphan = Exhibition.objects.create(title='Piece layout')
        override = Piece.objects.create(
            exhibition=own,
            presentation_templates={'on_site': 'fomantic_on_site_widescreen_v1'},
        )
        promoted = Piece.objects.create(
            exhibition=orphan,
            presentation_templates={'user_device': 'fomantic_user_device_v1'},
        )

        executor = MigrationExecutor(connection)
        executor.migrate([('main_app', '0005_consolidate_presentation_ownership')])
        new = executor.loader.project_state([
            ('main_app', '0005_consolidate_presentation_ownership')
        ]).apps
        Exhibition = new.get_model('main_app', 'Exhibition')
        Piece = new.get_model('main_app', 'Piece')

        self.assertEqual(
            Exhibition.objects.get(pk=own.pk).Exhibition_attributes['presentation_templates'],
            {
                'on_site': 'fomantic_on_site_standard_v1',
                'user_device': 'fomantic_user_device_v1',
            },
        )
        self.assertEqual(
            Exhibition.objects.get(pk=inherited.pk).Exhibition_attributes['presentation_templates']['on_site'],
            'fomantic_on_site_widescreen_v1',
        )
        self.assertEqual(
            Exhibition.objects.get(pk=orphan.pk).Exhibition_attributes['presentation_templates']['user_device'],
            'fomantic_user_device_v1',
        )
        self.assertEqual(Piece.objects.get(pk=override.pk).presentation_templates, {})
        self.assertEqual(Piece.objects.get(pk=promoted.pk).presentation_templates, {})

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()
