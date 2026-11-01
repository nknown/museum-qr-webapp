from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RoleMigrationTests(TransactionTestCase):
    def test_legacy_roles_and_unambiguous_museums_are_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('main_app', '0001_initial')])
        old = executor.loader.project_state([('main_app', '0001_initial')]).apps
        User = old.get_model('auth', 'User')
        Profile = old.get_model('main_app', 'UserProfile')
        Museum = old.get_model('main_app', 'Museum')
        first = Museum.objects.create(title='First')
        second = Museum.objects.create(title='Second')
        for name, role in [('student', 's'), ('teacher', 't'), ('ambiguous', 'c'), ('superuser', 'v')]:
            user = User.objects.create(username=name, is_superuser=name == 'superuser')
            Profile.objects.create(user=user, type=role)
            if name in {'teacher', 'ambiguous'}:
                first.admins.add(user)
            if name == 'ambiguous':
                second.admins.add(user)
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([('main_app', '0003_migrate_user_roles')])
            new = executor.loader.project_state([('main_app', '0003_migrate_user_roles')]).apps
            Profile = new.get_model('main_app', 'UserProfile')
            self.assertEqual(Profile.objects.get(user__username='student').type, 'v')
            self.assertEqual(Profile.objects.get(user__username='teacher').type, 'c')
            self.assertEqual(Profile.objects.get(user__username='teacher').museum_id, first.pk)
            self.assertIsNone(Profile.objects.get(user__username='ambiguous').museum_id)
            self.assertEqual(Profile.objects.get(user__username='superuser').type, 'a')
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
