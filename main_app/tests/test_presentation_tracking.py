import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from main_app.models import Exhibition, PresentationAccess, PresentationSession


class PresentationSlideTrackingTests(TestCase):
    def setUp(self):
        session = self.client.session
        session['tracking-test'] = True
        session.save()

        self.exhibition = Exhibition.objects.create(title='Tracked exhibition')
        self.presentation_session = PresentationSession.objects.create(
            session_key=session.session_key,
        )
        self.initial_access = PresentationAccess.objects.create(
            presentation_session=self.presentation_session,
            presentation_type='exhibition_user_device',
            presentation_title=self.exhibition.title,
            presentation_path=f'/presentation/exhibition/{self.exhibition.public_id}',
            exhibition=self.exhibition,
            last_wagtail_page_index=0,
            last_wagtail_page_title='Slide 1',
        )
        self.url = reverse(
            'main_app:presentation-access-slide',
            kwargs={'pk': self.initial_access.pk},
        )

    def test_batch_creates_ordered_events_and_drops_consecutive_duplicates(self):
        first_event_at = timezone.now() - timedelta(seconds=3)
        events = [
            {'slide_index': 1, 'occurred_at': first_event_at.isoformat()},
            {'slide_index': 1, 'occurred_at': first_event_at.isoformat()},
            {'slide_index': 2, 'occurred_at': (first_event_at + timedelta(seconds=1)).isoformat()},
            {'slide_index': 1, 'occurred_at': (first_event_at + timedelta(seconds=2)).isoformat()},
        ]

        response = self.client.post(
            self.url,
            data=json.dumps({'events': events}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['created'], 3)
        tracked = list(
            PresentationAccess.objects.exclude(pk=self.initial_access.pk)
            .order_by('last_accessed_at', 'id')
        )
        self.assertEqual(
            [event.last_wagtail_page_index for event in tracked],
            [1, 2, 1],
        )
        self.assertEqual(
            [event.last_wagtail_page_title for event in tracked],
            ['Slide 2', 'Slide 3', 'Slide 2'],
        )

    def test_batch_size_is_limited(self):
        response = self.client.post(
            self.url,
            data=json.dumps({
                'events': [
                    {'slide_index': index, 'occurred_at': timezone.now().isoformat()}
                    for index in range(21)
                ],
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PresentationAccess.objects.count(), 1)

    def test_different_anonymous_session_cannot_write_events(self):
        other_client = self.client_class()
        other_session = other_client.session
        other_session['tracking-test'] = True
        other_session.save()

        response = other_client.post(
            self.url,
            data=json.dumps({
                'events': [
                    {'slide_index': 1, 'occurred_at': timezone.now().isoformat()},
                ],
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(PresentationAccess.objects.count(), 1)
