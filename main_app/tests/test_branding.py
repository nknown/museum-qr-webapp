from django.contrib.auth.models import User
from django.test import TestCase


class BrandingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='branding-admin',
            email='admin@example.com',
            password='password',
        )

    def test_public_and_admin_pages_use_miyp_title_and_favicon(self):
        for path, title in (
            ('/', 'MIYP |'),
            ('/login', 'MIYP | Login'),
            ('/admin/login/', 'MIYP'),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'<title>{title}', html=False)
            self.assertContains(response, 'wagtailadmin/images/favicon.ico')

    def test_wagtail_root_uses_content_title_without_exploring_root(self):
        self.client.force_login(self.admin)

        response = self.client.get('/cms/pages/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>MIYP - Content</title>', html=True)
        self.assertContains(response, 'MIYP - Content')
        self.assertNotContains(response, 'Exploring: Root')
        self.assertContains(response, 'wagtailadmin/images/favicon.ico')

    def test_django_admin_title_is_only_miyp(self):
        self.client.force_login(self.admin)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>MIYP</title>', html=False)

    def test_topbar_uses_first_name_without_changing_username(self):
        self.admin.first_name = 'GoogleName'
        self.admin.save(update_fields=['first_name'])
        original_username = self.admin.username
        self.client.force_login(self.admin)

        response = self.client.get('/')

        self.assertContains(response, 'Hi, GoogleName', count=2)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.username, original_username)
