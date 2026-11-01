from types import SimpleNamespace

from django.test import RequestFactory, TestCase
from django.urls import reverse

from main_app.models import Exhibition, Piece
from main_app.presentation_style import assigned_template, presentation_appearance
from main_app.tests import test_roles
from main_app.wagtail_hooks import remove_items


class PresentationStyleTests(TestCase):
    account = staticmethod(test_roles.RoleWorkflowTests.account)
    exhibit = staticmethod(test_roles.RoleWorkflowTests.exhibit)
    setUpTestData = classmethod(test_roles.RoleWorkflowTests.setUpTestData.__func__)

    def layout_data(self, exhibition=None, **changes):
        data = {
            'target': f'exhibition:{(exhibition or self.exhibition).pk}',
            'on_site_template': 'fomantic_on_site_widescreen_v1',
            'user_device_template': 'fomantic_user_device_v1',
        }
        data.update(changes)
        return data

    def branding_data(self, museum=None, **changes):
        data = {
            'target': f'museum:{(museum or self.museum).pk}',
            'appearance_enabled': 'on',
            'overlay_colour': '#163442',
            'overlay_opacity': 85,
        }
        data.update(changes)
        return data

    def test_layout_belongs_to_exhibition_and_all_pieces_inherit_it(self):
        self.client.force_login(self.curator)
        self.piece.presentation_templates = {'on_site': 'fomantic_on_site_standard_v1'}
        self.piece.save(update_fields=['presentation_templates'])
        self.museum.presentation_templates = {'on_site': 'fomantic_on_site_standard_v1'}
        self.museum.save(update_fields=['presentation_templates'])

        response = self.client.post(reverse('templates'), self.layout_data())
        self.assertEqual(response.status_code, 302)
        self.exhibition.refresh_from_db()
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.presentation_templates, {})
        self.assertEqual(
            assigned_template(self.exhibition, 'on_site', self.piece),
            'fomantic_on_site_widescreen_v1',
        )
        future_piece = Piece.objects.create(exhibition=self.exhibition)
        self.assertEqual(
            assigned_template(self.exhibition, 'on_site', future_piece),
            'fomantic_on_site_widescreen_v1',
        )

        other = Exhibition.objects.create(title='No layout', museum=self.museum)
        self.assertEqual(assigned_template(other, 'on_site'), '')

    def test_branding_belongs_to_museum_and_exhibitions_inherit_it(self):
        self.client.force_login(self.curator)
        response = self.client.post(
            reverse('presentation_appearance'), self.branding_data()
        )
        self.assertEqual(response.status_code, 302)
        self.museum.refresh_from_db()
        self.assertTrue(self.museum.appearance_enabled)
        self.assertEqual(presentation_appearance(self.exhibition)['colour'], '#163442')
        self.assertEqual(presentation_appearance(self.piece.exhibition)['colour'], '#163442')

        self.exhibition.appearance_enabled = True
        self.exhibition.overlay_colour = '#ffffff'
        self.exhibition.inherit_museum_appearance = False
        self.exhibition.save(update_fields=[
            'appearance_enabled', 'overlay_colour', 'inherit_museum_appearance'
        ])
        self.assertEqual(presentation_appearance(self.exhibition)['colour'], '#163442')
        self.assertIsNone(presentation_appearance(self.foreign))

    def test_layout_and_branding_pages_do_not_change_each_other(self):
        self.client.force_login(self.curator)
        self.client.post(reverse('presentation_appearance'), self.branding_data())
        self.client.post(reverse('templates'), self.layout_data())
        self.museum.refresh_from_db()
        self.exhibition.refresh_from_db()
        self.assertEqual(self.museum.overlay_colour, '#163442')
        self.assertEqual(
            self.exhibition.Exhibition_attributes['presentation_templates']['on_site'],
            'fomantic_on_site_widescreen_v1',
        )

    def test_each_page_lists_only_its_owner_type(self):
        self.client.force_login(self.admin)
        layout = self.client.get(reverse('templates'))
        branding = self.client.get(reverse('presentation_appearance'))
        self.assertTrue(all(key.startswith('exhibition:') for key, _ in layout.context['targets']))
        self.assertTrue(all(key.startswith('museum:') for key, _ in branding.context['targets']))
        self.assertNotContains(layout, 'id_overlay_colour')
        self.assertNotContains(branding, 'name="on_site_template"')
        self.assertNotContains(branding, 'id_inherit_museum_appearance')

    def test_branding_uses_one_form_with_the_visible_museum(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('presentation_appearance'))
        html = response.content.decode()
        self.assertEqual(html.count('<form'), 1)
        self.assertContains(response, 'select id="target" name="target"')
        self.assertNotContains(response, 'type="hidden" name="target"')

        response = self.client.post(
            reverse('presentation_appearance'),
            self.branding_data(self.other_museum, overlay_colour='#334455'),
        )
        self.assertEqual(response.status_code, 302)
        self.other_museum.refresh_from_db()
        self.museum.refresh_from_db()
        self.assertEqual(self.other_museum.overlay_colour, '#334455')
        self.assertFalse(self.museum.appearance_enabled)

    def test_invalid_or_foreign_targets_are_rejected(self):
        self.client.force_login(self.curator)
        response = self.client.post(
            reverse('presentation_appearance'), self.branding_data(self.other_museum)
        )
        self.assertIn(response.status_code, [302, 403])
        self.other_museum.refresh_from_db()
        self.assertFalse(self.other_museum.appearance_enabled)

        response = self.client.post(reverse('templates'), self.layout_data(self.foreign))
        self.assertIn(response.status_code, [302, 403])
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.Exhibition_attributes, {})

        for changes in (
            {'overlay_colour': 'invalid'},
            {'overlay_opacity': 20},
            {'background_image': 999999},
        ):
            response = self.client.post(
                reverse('presentation_appearance'), self.branding_data(**changes)
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)

    def test_rendering_combines_exhibition_layout_and_museum_branding(self):
        self.client.force_login(self.curator)
        self.client.post(reverse('templates'), self.layout_data())
        self.client.post(reverse('presentation_appearance'), self.branding_data())
        for kind, obj in [('exhibition', self.exhibition), ('piece', self.piece)]:
            response = self.client.get(f'/{kind}/{obj.pk}/presentation/on_site')
            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response,
                'data-presentation-template="fomantic_on_site_widescreen_v1"',
            )
            self.assertContains(response, 'mip-on-site-widescreen-template')
            self.assertContains(response, '--museum-colour:#163442')
            self.assertNotContains(response, 'ui stackable grid mip-on-site-template')

    def test_hidden_menu_items_for_all_roles(self):
        for user in (self.admin, self.curator):
            request = RequestFactory().get('/cms/')
            request.user = user
            items = [SimpleNamespace(name=name) for name in [
                'images', 'documents', 'reports', 'settings', 'help',
                'explorer', 'templates',
            ]]
            remove_items(request, items)
            self.assertEqual([item.name for item in items], ['explorer', 'templates'])
