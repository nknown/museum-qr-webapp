from django.test import RequestFactory, SimpleTestCase, override_settings

from main_app.views.models_views import _build_public_absolute_uri


class PublicAbsoluteUrlTests(SimpleTestCase):
    @override_settings(
        SERVER_NAME='http://127.0.0.1:8000/',
        PUBLIC_HOSTNAME='i7h8',
    )
    def test_uses_configured_hostname_instead_of_request_ip(self):
        request = RequestFactory().get('/', HTTP_HOST='127.0.0.1:8000')

        url = _build_public_absolute_uri(request, '/presentation/exhibition/example')

        self.assertEqual(
            url,
            'http://i7h8:8000/presentation/exhibition/example',
        )

    @override_settings(SERVER_NAME='not-a-url', PUBLIC_HOSTNAME='i7h8')
    def test_falls_back_to_request_host_for_invalid_configuration(self):
        request = RequestFactory().get('/', HTTP_HOST='museum.example')

        url = _build_public_absolute_uri(request, '/presentation/piece/example')

        self.assertEqual(url, 'http://museum.example/presentation/piece/example')
