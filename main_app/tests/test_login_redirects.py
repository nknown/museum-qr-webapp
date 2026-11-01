from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(
    GOOGLE_OAUTH_USE_LOOPBACK_REDIRECT=True,
    GOOGLE_OAUTH_LOOPBACK_HOST='localhost:8000',
    SERVER_NAME='https://i7h8:8000/',
    SOCIAL_AUTH_REDIRECT_IS_HTTPS=True,
)
class LoginRedirectTests(TestCase):
    destination = '/presentation/exhibition/00000000-0000-0000-0000-000000000001'

    def setUp(self):
        self.user = User.objects.create_user(
            username='redirect-user',
            password='password',
        )

    def test_login_page_passes_next_to_google_oauth(self):
        response = self.client.get(
            reverse('main_app:login'),
            {'next': self.destination},
        )

        self.assertContains(
            response,
            'By logging in, users can build a personal museum profile',
        )
        self.assertNotContains(response, 'Please login to see this page.')
        self.assertContains(
            response,
            f'/login/google-oauth2/?next={self.destination}',
        )
        self.assertContains(response, 'Sign in with Google')
        self.assertNotContains(response, 'GOOGLE OAUTH2')

    def test_google_begin_stores_presentation_destination(self):
        response = self.client.get(
            reverse('social:begin', args=['google-oauth2']),
            {'next': self.destination},
        )

        self.assertEqual(response.status_code, 302)
        google_query = parse_qs(urlparse(response['Location']).query)
        self.assertEqual(google_query['redirect_uri'], [
            'https://localhost:8000/complete/google-oauth2/',
        ])
        self.assertEqual(self.client.session['next'], self.destination)

    def test_google_loopback_callback_returns_to_public_host(self):
        response = self.client.get(
            reverse('social:complete', args=['google-oauth2']),
            {'code': 'example', 'state': 'example'},
            HTTP_X_FORWARDED_HOST='localhost:8000',
            secure=True,
        )

        self.assertRedirects(
            response,
            'https://i7h8:8000/complete/google-oauth2/?code=example&state=example',
            fetch_redirect_response=False,
        )

    def test_password_login_returns_to_presentation(self):
        response = self.client.post(
            reverse('main_app:login'),
            {
                'username': self.user.username,
                'password': 'password',
                'next': self.destination,
            },
        )

        self.assertRedirects(
            response,
            self.destination,
            fetch_redirect_response=False,
        )

    def test_authenticated_login_page_does_not_show_access_warning(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('main_app:login'),
            {'next': self.destination},
        )

        self.assertNotContains(
            response,
            "Your account doesn't have access to this page.",
        )

    def test_presentation_menu_switches_login_to_logout(self):
        anonymous_response = self.client.get(
            reverse('main_app:login'),
            {'next': self.destination},
        )
        request = anonymous_response.wsgi_request
        anonymous_menu = render_to_string(
            'main_app/models/presentation/_user_device_controls.html',
            request=request,
        )
        self.assertIn('>Login</a>', anonymous_menu)
        self.assertNotIn('>Logout</button>', anonymous_menu)

        self.client.force_login(self.user)
        authenticated_response = self.client.get('/')
        authenticated_menu = render_to_string(
            'main_app/models/presentation/_user_device_controls.html',
            request=authenticated_response.wsgi_request,
        )
        self.assertIn('>Logout</button>', authenticated_menu)
        self.assertNotIn('>Login</a>', authenticated_menu)

    def test_login_and_logout_render_one_time_notyf_notifications(self):
        self.user.first_name = 'GoogleName'
        self.user.save(update_fields=['first_name'])

        login_response = self.client.post(
            reverse('main_app:login'),
            {
                'username': self.user.username,
                'password': 'password',
                'next': reverse('main_app:index'),
            },
            follow=True,
        )
        self.assertContains(login_response, 'Welcome GoogleName.')
        self.assertContains(login_response, 'duration: 3000')

        next_response = self.client.get(reverse('main_app:index'))
        self.assertNotContains(next_response, 'Welcome GoogleName.')

        logout_response = self.client.post(
            reverse('main_app:logout'),
            {'next': reverse('main_app:index')},
            follow=True,
        )
        self.assertContains(logout_response, 'Logged out successfully.')
        self.assertContains(logout_response, 'duration: 3000')

        final_response = self.client.get(reverse('main_app:index'))
        self.assertNotContains(final_response, 'Logged out successfully.')
