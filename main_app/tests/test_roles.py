from django.contrib.auth.models import User, Group, Permission
from django.test import TestCase, RequestFactory
from django.urls import reverse
from wagtail.models import Page, GroupPagePermission
from main_app.models import (
    Museum, Exhibition, Piece, SlideshowSlidePage, PresentationAccess,
    PresentationSession,
)
from main_app.access import can_manage, can_view_presentation
from main_app.views.models_views import ExhibitionCreateView, PieceCreateView
from main_app.utils.feeder import FeederImporter, FeederImportError
from main_app.admin_forms import AdminUserCreationForm


class RoleWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.museum = Museum.objects.create(title='Museum A')
        cls.other_museum = Museum.objects.create(title='Museum B')
        cls.admin = cls.account('administrator', 'a')
        cls.curator = cls.account('curator', 'c', cls.museum)
        cls.other = cls.account('other-curator', 'c', cls.other_museum)
        cls.visitor = cls.account('visitor', 'v')
        cls.vip = cls.account('vip', 'p')
        cls.exhibition = cls.exhibit('Private exhibition', cls.museum)
        cls.foreign = cls.exhibit('Other exhibition', cls.other_museum)
        cls.piece = Piece.objects.create(exhibition=cls.exhibition, attributes=[{'name': 'Name', 'value': 'Hidden piece'}])
        builder = PieceCreateView()
        builder.exhibition = cls.exhibition
        builder.object = cls.piece
        builder._ensure_piece_slideshow_tree()

    @staticmethod
    def account(name, role, museum=None):
        user = User.objects.create_user(name, password='Role-test-password-2026')
        user.profile.type = role
        user.profile.museum = museum
        user.profile.save()
        user.refresh_from_db()
        return user

    @staticmethod
    def exhibit(title, museum):
        exhibition = Exhibition.objects.create(title=title, museum=museum)
        builder = ExhibitionCreateView()
        builder.object = exhibition
        builder._ensure_exhibition_slideshow_tree()
        return exhibition

    def login(self, user):
        self.client.force_login(user)

    def public_url(self, obj=None):
        obj = obj or self.piece
        kind = 'piece' if isinstance(obj, Piece) else 'exhibition'
        return reverse(f'main_app:{kind}-public-presentation', args=[obj.public_id])

    def publish(self, obj=None):
        obj = obj or self.exhibition
        self.login(self.curator)
        kind = 'piece' if isinstance(obj, Piece) else 'exhibition'
        response = self.client.post(reverse(f'main_app:{kind}-publication', args=[obj.pk]), {'action': 'publish'})
        self.assertEqual(response.status_code, 302)
        self.client.logout()

    def test_visitors_cannot_create_or_edit_even_with_legacy_membership(self):
        self.exhibition.admins.add(self.visitor, self.vip)
        for user in [self.visitor, self.vip]:
            self.login(user)
            for url in ['/museum/create', '/exhibition/create', f'/exhibition/{self.exhibition.pk}/update', f'/piece/{self.piece.pk}/update']:
                with self.subTest(user=user.username, url=url):
                    self.assertIn(self.client.post(url, {'title': 'Attack'}).status_code, [403, 404])
        self.exhibition.refresh_from_db()
        self.assertEqual(self.exhibition.title, 'Private exhibition')

    def test_only_administrator_manages_museums(self):
        for user in [self.curator, self.vip, self.visitor]:
            self.login(user)
            self.assertEqual(self.client.post('/museum/create', {'title': 'Denied'}).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.post('/museum/create', {'title': 'Created'}).status_code, 302)
        self.assertTrue(Museum.objects.filter(title='Created').exists())

    def test_curator_create_inherits_museum_and_ignores_posted_museum(self):
        self.login(self.curator)
        response = self.client.post('/exhibition/create', {'title': 'New exhibition', 'description': 'A test', 'museum': self.other_museum.pk})
        self.assertEqual(response.status_code, 302)
        exhibition = Exhibition.objects.get(title='New exhibition')
        self.assertEqual(exhibition.museum, self.museum)
        self.assertFalse(exhibition.slideshow_page.live)
        self.assertTrue(exhibition.slideshow_page.permissions_for_user(User.objects.get(pk=self.curator.pk)).can_edit())

    def test_unassigned_curator_cannot_create(self):
        self.curator.profile.museum = None
        self.curator.profile.save()
        self.login(self.curator)
        self.assertEqual(self.client.post('/exhibition/create', {'title': 'Denied', 'description': 'test'}).status_code, 403)
        self.assertFalse(Exhibition.objects.filter(title='Denied').exists())

    def test_curator_cannot_modify_another_museum(self):
        self.login(self.curator)
        for suffix in ['update', 'delete', 'attributes/create', 'add-pieces', 'publication']:
            self.assertIn(self.client.post(f'/exhibition/{self.foreign.pk}/{suffix}', {'title': 'Attack', 'action': 'publish'}).status_code, [403, 404])
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.title, 'Other exhibition')

    def test_admin_has_global_access_without_memberships(self):
        self.login(self.admin)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertEqual(self.client.get(f'/exhibition/{self.foreign.pk}/update').status_code, 200)
        self.assertEqual(self.client.get(f'/piece/{self.piece.pk}/update').status_code, 200)
        self.assertEqual(self.client.get(self.public_url()).status_code, 200)

    def test_drafts_hidden_from_anonymous_and_regular_visitors(self):
        self.assertEqual(self.client.get(self.public_url()).status_code, 404)
        self.login(self.visitor)
        self.assertEqual(self.client.get(self.public_url(self.exhibition)).status_code, 404)
        self.assertEqual(PresentationAccess.objects.count(), 0)

    def test_publication_and_unpublication_gate_qr_urls(self):
        self.publish()
        self.assertEqual(self.client.get(self.public_url()).status_code, 200)
        self.login(self.curator)
        self.assertEqual(self.client.post(f'/exhibition/{self.exhibition.pk}/publication', {'action': 'unpublish'}).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.public_url()).status_code, 404)

    def test_unpublished_slide_is_not_rendered_in_published_presentation(self):
        self.publish()
        folder = self.piece.slideshow_page.get_children().get(slug='user_device')
        hidden = SlideshowSlidePage(title='Secret slide', slug='secret', body='<p>CLASSIFIED DRAFT</p>', live=False)
        folder.add_child(instance=hidden)
        response = self.client.get(self.public_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'CLASSIFIED DRAFT')
        self.login(self.vip)
        self.assertContains(self.client.get(self.public_url()), 'CLASSIFIED DRAFT')

    def test_vip_draft_access_and_complete_history_without_fabricated_visits(self):
        self.login(self.vip)
        history = self.client.get('/visit/history')
        self.assertContains(history, 'Hidden piece')
        self.assertContains(history, 'Other exhibition')
        self.assertEqual(PresentationAccess.objects.count(), 0)
        self.assertEqual(self.client.get(self.public_url()).status_code, 200)
        self.assertEqual(self.client.get('/cms/pages/').status_code, 403)
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)
        self.assertFalse(self.vip.is_staff)
        self.assertFalse(self.vip.is_superuser)

    def test_curator_cms_permissions_are_limited_to_museum(self):
        user = User.objects.get(pk=self.curator.pk)
        self.assertTrue(user.has_perm('wagtailadmin.access_admin'))
        self.assertTrue(self.exhibition.slideshow_page.permissions_for_user(user).can_publish())
        self.assertFalse(self.foreign.slideshow_page.permissions_for_user(user).can_edit())
        self.login(user)
        self.assertEqual(self.client.get(f'/cms/pages/{self.exhibition.slideshow_page_id}/edit/').status_code, 200)
        self.assertNotEqual(self.client.get(f'/cms/pages/{self.foreign.slideshow_page_id}/edit/').status_code, 200)

    def test_demotion_removes_legacy_cms_permissions(self):
        group = Group.objects.create(name='Legacy editors')
        group.permissions.add(Permission.objects.get(content_type__app_label='wagtailadmin', codename='access_admin'))
        GroupPagePermission.objects.create(group=group, page=Page.get_first_root_node(), permission_type='change')
        self.curator.groups.add(group)
        self.curator.profile.type = 'p'
        self.curator.profile.save()
        user = User.objects.get(pk=self.curator.pk)
        self.assertFalse(user.has_perm('wagtailadmin.access_admin'))
        self.assertFalse(self.exhibition.slideshow_page.permissions_for_user(user).can_edit())

    def test_museum_reassignment_revokes_previous_page_access(self):
        self.curator.profile.museum = self.other_museum
        self.curator.profile.save()
        user = User.objects.get(pk=self.curator.pk)
        self.assertFalse(self.exhibition.slideshow_page.permissions_for_user(user).can_edit())
        self.assertTrue(self.foreign.slideshow_page.permissions_for_user(user).can_edit())

    def test_import_matching_title_is_scoped_to_museum(self):
        result = FeederImporter().import_data(self.foreign.title, {}, ['Name'], {1: {'attributes': {'name': 'Imported'}}}, admin_user=self.curator)
        self.assertNotEqual(result.exhibition.pk, self.foreign.pk)
        self.assertEqual(result.exhibition.museum, self.museum)

    def test_import_rejects_foreign_exhibition_and_visitor(self):
        for user, exhibition in [(self.curator, self.foreign), (self.vip, self.exhibition)]:
            with self.assertRaises(FeederImportError):
                FeederImporter().import_data(exhibition.title, {}, ['Name'], {1: {'attributes': {'name': 'Imported'}}}, exhibition=exhibition, admin_user=user)

    def test_creation_form_requires_curator_museum_and_provisions_role(self):
        data = {'account_type': 'local', 'username': 'new-curator', 'password1': 'Another-password-2026', 'password2': 'Another-password-2026', 'profile_type': 'c'}
        self.assertFalse(AdminUserCreationForm(data=data).is_valid())
        data['museum'] = self.museum.pk
        form = AdminUserCreationForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.profile.museum, self.museum)
        self.assertTrue(user.has_perm('wagtailadmin.access_admin'))

    def test_visitor_history_is_scoped_and_filters_unpublished_content(self):
        self.publish()
        self.login(self.visitor)
        self.assertNotContains(self.client.get('/visit/history'), 'Hidden piece')
        self.client.get(self.public_url())
        self.assertContains(self.client.get('/visit/history'), 'Hidden piece')
        self.client.logout()
        self.assertNotContains(self.client.get('/visit/history'), 'Hidden piece')
        self.login(self.curator)
        self.client.post(f'/piece/{self.piece.pk}/publication', {'action': 'unpublish'})
        self.login(self.visitor)
        self.assertNotContains(self.client.get('/visit/history'), 'Hidden piece')

    def test_template_management_rejects_vip_and_foreign_exhibition(self):
        self.login(self.vip)
        self.assertEqual(self.client.post('/cms/Templates/', {'exhibition_id': self.exhibition.pk}).status_code, 403)
        self.login(self.curator)
        self.client.post('/cms/Templates/', {'exhibition_id': self.foreign.pk, 'on_site_template': 'fomantic_on_site_standard_v1'})
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.Exhibition_attributes, {})

    def test_piece_editor_updates_name_and_can_move_within_museum(self):
        target = self.exhibit('Second exhibition', self.museum)
        self.login(self.curator)
        response = self.client.post(f'/piece/{self.piece.pk}/update', {
            'exhibition': target.pk, 'default_piece_name': 'Renamed piece',
            'on_site_template': 'fomantic_on_site_widescreen_v1',
        })
        self.assertEqual(response.status_code, 302)
        self.piece.refresh_from_db()
        self.assertEqual(str(self.piece), 'Renamed piece')
        self.assertEqual(self.piece.exhibition, target)
        self.assertTrue(self.piece.slideshow_page.is_descendant_of(target.slideshow_page))
        self.assertEqual(self.piece.presentation_templates, {})
        self.assertNotContains(
            self.client.get(f'/piece/{self.piece.pk}/update'),
            'name="on_site_template"',
        )

    def test_piece_cannot_be_moved_to_another_museum(self):
        self.login(self.curator)
        response = self.client.post(f'/piece/{self.piece.pk}/update', {
            'exhibition': self.foreign.pk, 'default_piece_name': 'Renamed piece',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('exhibition', response.context['form'].errors)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.exhibition, self.exhibition)

    def test_interactive_content_is_rendered_in_visitor_presentation(self):
        folder = self.piece.slideshow_page.get_children().get(slug='user_device')
        slide = folder.get_children().first().specific
        slide.content = [('question', {'question': 'Who made this?', 'answer': '<p>A local craftsperson.</p>'})]
        slide.save_revision()
        self.publish()
        response = self.client.get(self.public_url())
        self.assertContains(response, 'Who made this?')
        self.assertContains(response, '<details>')
        self.assertContains(response, 'A local craftsperson.')

    def test_piece_publication_controls_are_not_on_django_editor(self):
        self.login(self.curator)
        self.assertNotContains(self.client.get(f'/piece/{self.piece.pk}/update'), f'/piece/{self.piece.pk}/publication')

    def test_admin_account_creation_assigns_curator_museum(self):
        self.login(self.admin)
        response = self.client.post('/admin/auth/user/add/', {
            'account_type': 'local', 'username': 'admin-created-curator',
            'password1': 'A-purple-lantern-7319!', 'password2': 'A-purple-lantern-7319!',
            'profile_type': 'c', 'museum': self.museum.pk, '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302, response.context['adminform'].form.errors if response.status_code == 200 else '')
        user = User.objects.get(username='admin-created-curator')
        self.assertEqual(user.profile.type, 'c')
        self.assertEqual(user.profile.museum, self.museum)
        self.assertTrue(user.has_perm('wagtailadmin.access_admin'))
        self.assertFalse(user.is_staff)

    def test_museum_deletion_revokes_curator_cms_permissions(self):
        self.museum.delete()
        user = User.objects.get(pk=self.curator.pk)
        self.assertIsNone(user.profile.museum_id)
        self.assertFalse(user.has_perm('wagtailadmin.access_admin'))

    def test_unpublished_favorite_is_hidden_but_retained(self):
        from main_app.models import PresentationFavorite
        favorite = PresentationFavorite.objects.create(user=self.visitor,
            presentation_path=self.public_url(), presentation_title='Piece | Hidden piece')
        self.login(self.visitor)
        self.assertEqual(self.client.get('/presentation-favorites').json()['favorites'], [])
        self.assertTrue(PresentationFavorite.objects.filter(pk=favorite.pk).exists())

    def test_direct_wagtail_route_obeys_roles_and_ancestor_publication(self):
        from wagtail.models import Site
        Site.objects.all().update(root_page=Page.get_first_root_node())
        folder = self.piece.slideshow_page.get_children().get(slug='user_device')
        slide = folder.get_children().first().specific
        slide.live = True
        slide.save(update_fields=['live'])
        path = '/pages/' + slide.url_path.strip('/') + '/'
        self.assertEqual(self.client.get(path).status_code, 404)
        self.login(self.vip)
        self.assertEqual(self.client.get(path).status_code, 200)
        root_path = '/pages/' + self.exhibition.slideshow_page.slug + '/'
        self.assertEqual(self.client.get(root_path).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(root_path).status_code, 404)

    def test_vip_can_access_orphaned_piece(self):
        orphan = Piece.objects.create(attributes=[{'name': 'Name', 'value': 'Orphaned piece'}])
        self.login(self.vip)
        self.assertContains(self.client.get('/visit/history'), 'Orphaned piece')
        self.assertEqual(self.client.get(self.public_url(orphan)).status_code, 200)

    def test_vip_preview_uses_latest_unpublished_revision(self):
        folder = self.piece.slideshow_page.get_children().get(slug='user_device')
        slide = folder.get_children().first().specific
        slide.body = '<p>Latest draft content</p>'
        slide.save_revision()
        self.login(self.vip)
        self.assertContains(self.client.get(self.public_url()), 'Latest draft content')

    def _statistics_access(self, exhibition, title, *, user=None, piece=None):
        session = PresentationSession.objects.create(
            session_key=f'statistics-{exhibition.pk}-{PresentationSession.objects.count()}',
            user=user,
        )
        return PresentationAccess.objects.create(
            presentation_session=session,
            exhibition=exhibition,
            piece=piece,
            presentation_type='piece_user_device' if piece else 'exhibition_user_device',
            presentation_title=title,
        )

    def test_administrator_can_access_all_statistics_views(self):
        foreign_piece = Piece.objects.create(
            exhibition=self.foreign,
            attributes=[{'name': 'Name', 'value': 'Foreign piece'}],
        )
        self._statistics_access(
            self.foreign,
            'Foreign exhibition statistics',
            user=self.visitor,
        )

        self.login(self.admin)
        self.assertContains(self.client.get(reverse('main_app:statistics')), self.foreign.title)
        self.assertContains(
            self.client.get(reverse('main_app:statistics-history', args=['user', self.visitor.pk])),
            'Foreign exhibition statistics',
        )
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-presentation', args=['exhibition', self.foreign.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-presentation', args=['piece', foreign_piece.pk])).status_code,
            200,
        )

    def test_curator_can_access_statistics_for_assigned_museum(self):
        self._statistics_access(
            self.exhibition,
            'Assigned museum statistics',
            user=self.visitor,
        )

        self.login(self.curator)
        self.assertContains(self.client.get(reverse('main_app:statistics')), self.exhibition.title)
        self.assertContains(
            self.client.get(reverse('main_app:statistics-history', args=['user', self.visitor.pk])),
            'Assigned museum statistics',
        )
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-presentation', args=['exhibition', self.exhibition.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-presentation', args=['piece', self.piece.pk])).status_code,
            200,
        )

    def test_curator_cannot_access_statistics_for_unrelated_museum(self):
        foreign_piece = Piece.objects.create(
            exhibition=self.foreign,
            attributes=[{'name': 'Name', 'value': 'Foreign statistics piece'}],
        )
        self._statistics_access(
            self.foreign,
            'Unrelated museum statistics',
            user=self.visitor,
            piece=foreign_piece,
        )

        self.login(self.curator)
        self.assertNotContains(self.client.get(reverse('main_app:statistics')), self.foreign.title)
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-history', args=['user', self.visitor.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-presentation', args=['exhibition', self.foreign.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('main_app:statistics-presentation', args=['piece', foreign_piece.pk])).status_code,
            404,
        )

    def test_ordinary_visitor_cannot_access_statistics(self):
        self._statistics_access(
            self.exhibition,
            'Visitor-denied statistics',
            user=self.visitor,
        )
        urls = [
            reverse('main_app:statistics'),
            reverse('main_app:statistics-history', args=['user', self.visitor.pk]),
            reverse('main_app:statistics-presentation', args=['exhibition', self.exhibition.pk]),
            reverse('main_app:statistics-presentation', args=['piece', self.piece.pk]),
        ]

        self.login(self.visitor)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
