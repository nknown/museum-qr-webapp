from django.contrib.auth import get_user_model
from django.test import TestCase

from main_app.admin_forms import AdminUserCreationForm


User = get_user_model()


class AdminUserCreationFormTests(TestCase):
    def test_creates_local_user_with_hashed_password(self):
        form = AdminUserCreationForm(data={
            'account_type': 'local',
            'username': 'museum-user',
            'password1': 'A-strong-local-password-2026',
            'password2': 'A-strong-local-password-2026',
            'profile_type': 'v',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.username, 'museum-user')
        self.assertTrue(user.check_password('A-strong-local-password-2026'))

    def test_creates_google_user_with_email_and_no_local_password(self):
        form = AdminUserCreationForm(data={
            'account_type': 'google',
            'google_email': 'Museum.User@Gmail.com',
            'profile_type': 'v',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.username, 'museum.user@gmail.com')
        self.assertEqual(user.email, 'museum.user@gmail.com')
        self.assertFalse(user.has_usable_password())

    def test_rejects_google_email_already_used_by_an_account(self):
        User.objects.create_user(
            username='existing-user',
            email='visitor@gmail.com',
        )
        form = AdminUserCreationForm(data={
            'account_type': 'google',
            'google_email': 'VISITOR@gmail.com',
            'profile_type': 'v',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('google_email', form.errors)
