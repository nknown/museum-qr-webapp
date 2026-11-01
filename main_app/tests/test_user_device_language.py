from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from main_app.middleware import UserDeviceEnglishMiddleware, _is_user_device_path


class UserDeviceLanguageTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _language_response(self, request):
        return HttpResponse(translation.get_language())

    @override_settings(USER_DEVICE_LANGUAGE_CODE='en')
    def test_public_presentations_ignore_portuguese_browser_preference(self):
        translation.activate('pt')
        request = self.factory.get(
            '/presentation/piece/edc72e14-91f3-47b4-8b49-093fad9d3f34',
            HTTP_ACCEPT_LANGUAGE='pt',
        )

        response = UserDeviceEnglishMiddleware(self._language_response)(request)

        self.assertEqual(response.content, b'en')
        self.assertEqual(response.headers['Content-Language'], 'en')
        self.assertEqual(request.LANGUAGE_CODE, 'en')

    @override_settings(USER_DEVICE_LANGUAGE_CODE='en')
    def test_login_from_presentation_is_english(self):
        translation.activate('pt')
        request = self.factory.get(
            '/login',
            {'next': '/presentation/exhibition/00000000-0000-0000-0000-000000000001'},
        )

        response = UserDeviceEnglishMiddleware(self._language_response)(request)

        self.assertEqual(response.content, b'en')
        self.assertEqual(response.headers['Content-Language'], 'en')

    def test_non_visitor_routes_keep_active_language(self):
        translation.activate('pt')
        request = self.factory.get('/cms/pages/')

        response = UserDeviceEnglishMiddleware(self._language_response)(request)

        self.assertEqual(response.content, b'pt')
        self.assertNotIn('Content-Language', response.headers)

    def test_only_user_device_preview_route_is_forced(self):
        self.assertTrue(_is_user_device_path('/piece/38/presentation/user_device'))
        self.assertFalse(_is_user_device_path('/piece/38/presentation/on_site'))

    def tearDown(self):
        translation.activate(settings.LANGUAGE_CODE)
