"""Focused checks for the production ingress and readiness contract."""
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import AsyncClient, RequestFactory, SimpleTestCase
from deployment.urls import readiness


class DeploymentTests(SimpleTestCase):
    def test_https_redirect_and_untrusted_host(self):
        host = settings.ALLOWED_HOSTS[0]
        response = self.client.get('/health/ready/', HTTP_HOST=host)
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response['Location'].startswith('https://'))
        response = self.client.get('/health/ready/', HTTP_HOST='untrusted.invalid', secure=True)
        self.assertEqual(response.status_code, 400)

    def test_ready_checks_application_schema(self):
        with patch('deployment.urls.connection') as database:
            response = readiness(RequestFactory().get('/health/ready/'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(database.cursor.return_value.__enter__.return_value.execute.call_count, 2)
            self.assertEqual(response['Cache-Control'], 'no-store')

    def test_database_failure_is_unavailable_without_details(self):
        with patch('deployment.urls.connection') as database:
            database.cursor.side_effect = RuntimeError('private database detail')
            with self.assertLogs('deployment.urls', level='ERROR'):
                response = readiness(RequestFactory().get('/health/ready/'))
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(b'private database detail', response.content)

    async def test_asgi_readiness_accepts_proxy_https(self):
        with patch('deployment.urls.connection'):
            response = await AsyncClient().get(
                '/health/ready/',
                headers={
                    'x-forwarded-host': settings.ALLOWED_HOSTS[0],
                    'x-forwarded-proto': 'https',
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Cache-Control'], 'no-store')


class NginxConfigurationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.configuration = Path(__file__).with_name('nginx.conf.template').read_text()

    def test_protected_documents_are_not_served_from_media_storage(self):
        self.assertIn('location ^~ /images/documents/ { return 404; }', self.configuration)

    def test_active_upload_types_are_not_served_from_media_storage(self):
        self.assertIn(r'location ~* ^/images/.*\.(html?|svg|xml|js|mjs|xhtml)$', self.configuration)

    def test_workstation_oauth_bridge_is_absent(self):
        self.assertNotIn('/login/google-oauth2/', self.configuration)
        self.assertNotIn('/complete/google-oauth2/', self.configuration)
