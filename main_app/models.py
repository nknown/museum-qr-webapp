from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from django.utils import timezone
from datetime import timedelta
from countries_plus.models import Country
import uuid

import environ
env = environ.Env()
environ.Env.read_env()
from django.core.cache import cache

from wagtail.models import Page, Orderable
from wagtail.fields import RichTextField, StreamField
from main_app.blocks import PresentationBlocks
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.images import get_image_model_string
from modelcluster.fields import ParentalKey


def delete_piece_presentation_favorites(piece):
    PresentationFavorite.objects.filter(presentation_path__in=[
        f'/presentation/piece/{piece.public_id}',
        f'/piece/{piece.pk}/presentation/user_device',
    ]).delete()


def delete_exhibition_presentation_favorites(exhibition):
    paths = {
        f'/presentation/exhibition/{exhibition.public_id}',
        f'/exhibition/{exhibition.pk}/presentation/user_device',
    }
    for piece in exhibition.pieces.all():
        paths.add(f'/presentation/piece/{piece.public_id}')
        paths.add(f'/piece/{piece.pk}/presentation/user_device')

    PresentationFavorite.objects.filter(presentation_path__in=paths).delete()


SESSION_FAVORITES_KEY = 'presentation_favorites'


class PresentationAppearance(models.Model):
    appearance_enabled = models.BooleanField(default=False)
    background_image = models.ForeignKey(
        get_image_model_string(), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    overlay_colour = models.CharField(max_length=7, default='#ffffff')
    overlay_opacity = models.PositiveSmallIntegerField(default=85)

    class Meta:
        abstract = True


class Museum(PresentationAppearance):
    presentation_templates = models.JSONField(default=dict, blank=True)
    title = models.CharField(max_length=255, blank=False, default='New Museum')
    description = models.TextField(blank=True, default='')
    admins = models.ManyToManyField(
        User,
        related_name="managed_museums",
        blank=True,
    )

    class Meta:
        verbose_name = "Museum"
        verbose_name_plural = "Museums"

    def __str__(self):
        return self.title


class Exhibition(PresentationAppearance):
    inherit_museum_appearance = models.BooleanField(default=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=255, blank=False, default='New Exhibition')
    description = models.TextField(blank=False, default='Exhibition description')
    show_on_site_qr = models.BooleanField(default=True)
    Exhibition_attributes = models.JSONField(_('Exhibition_attributes'), default=dict, blank=True)

    pieces_attributes = models.JSONField(_('Pieces_attributes'), default=list, blank=True)

    museum = models.ForeignKey(
        Museum,
        related_name='exhibitions',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )


    slideshow_page = models.OneToOneField(
        'ExhibitionPage',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='exhibition_object',
    )

    # Optional: keep if you really want explicit exposition managers
    admins = models.ManyToManyField(
        User,
        related_name="managed_exhibitions",
        blank=True,
    )

    #parent_page_types = ["wagtailcore.Page"]
    #subpage_types = ["main_app.Piece"]

    #content_panels = Page.content_panels + [
    #    FieldPanel("description"),
    #    FieldPanel("admins"),
    #]

    class Meta:
        verbose_name = "Exhibition"
        verbose_name_plural = "Exhibitions"

class DomainPageAccessMixin:
    def route(self, request, path_components):
        if not path_components and not self.live:
            from main_app.access import can_preview, page_domain_object
            from wagtail.url_routing import RouteResult
            if can_preview(request.user, page_domain_object(self)):
                return RouteResult(self.get_latest_revision_as_object())
        return super().route(request, path_components)


class ExhibitionPage(DomainPageAccessMixin, Page):
    description = RichTextField(blank=True)
    template = "main_app/models/wagtail/exhibition_page.html"

    parent_page_types = ["wagtailcore.Page"]
    subpage_types = [
        "main_app.ExhibitionOnSitePage",
        "main_app.ExhibitionUserDevicePage",
        "main_app.ExhibitionPiecesListPage",
    ]
    is_creatable = False

    content_panels = Page.content_panels + [
        FieldPanel("description"),
    ]

    class Meta:
        verbose_name = "Exhibition slideshow"
        verbose_name_plural = "Exhibition slideshows"


class slideshowContentMixin(models.Model):
    content = StreamField(PresentationBlocks(), blank=True)
    body = RichTextField(blank=True)


    hero_image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    class Meta:
        abstract = True


class ExhibitionOnSitePage(slideshowContentMixin, DomainPageAccessMixin, Page):
    time_seconds = models.PositiveIntegerField(blank=True, null=True)
    parent_page_types = ["main_app.ExhibitionPage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/exhibition_on_site_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("content"),
        FieldPanel("time_seconds"),
        FieldPanel("hero_image"),
    ]


class ExhibitionUserDevicePage(slideshowContentMixin, DomainPageAccessMixin, Page):
    parent_page_types = ["main_app.ExhibitionPage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/exhibition_user_device_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("content"),
        FieldPanel("hero_image"),
    ]


class ExhibitionPiecesListPage(DomainPageAccessMixin, Page):
    parent_page_types = ["main_app.ExhibitionPage"]
    subpage_types = ["main_app.PiecePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/exhibition_pieces_page.html"

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['piece_pages'] = self.get_children().live().specific()
        return context


class PiecePage(DomainPageAccessMixin, Page):
    description = RichTextField(blank=True)
    parent_page_types = ["main_app.ExhibitionPiecesListPage"]
    subpage_types = ["main_app.PieceOnSitePage", "main_app.PieceUserDevicePage"]
    is_creatable = False
    template = "main_app/models/wagtail/piece_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("description"),
    ]

    class Meta:
        verbose_name = "Piece slideshow"
        verbose_name_plural = "Piece slideshows"


class PieceOnSitePage(slideshowContentMixin, DomainPageAccessMixin, Page):
    time_seconds = models.PositiveIntegerField(blank=True, null=True)
    parent_page_types = ["main_app.PiecePage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/piece_on_site_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("content"),
        FieldPanel("time_seconds"),
        FieldPanel("hero_image"),
    ]


class PieceUserDevicePage(slideshowContentMixin, DomainPageAccessMixin, Page):
    parent_page_types = ["main_app.PiecePage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/piece_user_device_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("content"),
        FieldPanel("hero_image"),
    ]


class SlideshowSlidePage(DomainPageAccessMixin, Page):
    content = StreamField(PresentationBlocks(), blank=True)
    body = RichTextField(blank=True)
    time_seconds = models.PositiveIntegerField(blank=True, null=True)
    show_details = models.BooleanField(default=True, help_text="Display exhibition/piece details on this slide")

    parent_page_types = [
        "main_app.ExhibitionOnSitePage",
        "main_app.ExhibitionUserDevicePage",
        "main_app.PieceOnSitePage",
        "main_app.PieceUserDevicePage",
    ]
    subpage_types = []
    template = "main_app/models/wagtail/slideshow_slide_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("content"),
        FieldPanel("time_seconds"),
        FieldPanel("show_details"),
        InlinePanel("gallery_images", label="Images"),
    ]

    def get_context(self, request, *args, **kwargs):
        from main_app.views.models_views import _piece_value_map, _ordered_attributes
        context = super().get_context(request, *args, **kwargs)


        # Get the grandparent page (PiecePage or ExhibitionPage)
        try:
            parent = self.get_parent()
            if parent:
                grandparent = parent.get_parent()
                if grandparent:
                    grandparent = grandparent.specific

                    # Handle Piece data
                    if isinstance(grandparent, PiecePage):
                        try:
                            piece = grandparent.piece_object
                            context['piece'] = piece
                            context['piece_name'] = str(piece)
                            # Build attribute rows like PieceView does
                            ordered_attributes = _ordered_attributes(piece.exhibition)
                            value_map = _piece_value_map(piece)
                            context['attribute_rows'] = [
                                (attribute, value_map.get(attribute.lower(), ''))
                                for attribute in ordered_attributes
                            ]
                        except Piece.DoesNotExist:
                            pass

                    # Handle Exhibition data
                    elif isinstance(grandparent, ExhibitionPage):
                        try:
                            exhibition = grandparent.exhibition_object
                            context['exhibition'] = exhibition
                            from main_app.access import visible_pieces
                            context['visible_pieces'] = visible_pieces(request.user).filter(exhibition=exhibition)
                        except Exhibition.DoesNotExist:
                            pass
        except Exception:
            # Handle any errors gracefully
            pass

        return context


class SlideshowSlideImage(Orderable):
    page = ParentalKey(
        "main_app.SlideshowSlidePage",
        on_delete=models.CASCADE,
        related_name="gallery_images",
    )
    image = models.ForeignKey(
        get_image_model_string(),
        on_delete=models.CASCADE,
        related_name="+",
    )
    caption = models.CharField(max_length=255, blank=True)

    panels = [
        FieldPanel("image"),
        FieldPanel("caption"),
    ]


class Piece(models.Model):
    presentation_templates = models.JSONField(default=dict, blank=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date_created = models.DateTimeField(auto_now_add=True)
    attributes = models.JSONField(_('Piece attributes'), default=list, blank=True)
    slideshow_page = models.OneToOneField(
        'PiecePage',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='piece_object',
    )
    # uma pecao so pertence a uma exhibiytion.
    exhibition = models.ForeignKey(Exhibition, related_name='pieces', on_delete=models.CASCADE, null=True, blank=True)
#   exhibitions = models.ManyToManyField(
#        Exhibition,
#        related_name='pieces',
#        blank=True
#    )

    class Meta:
        verbose_name = "Piece"
        verbose_name_plural = "Pieces"

    def __str__(self):
        entries = self.attributes if isinstance(self.attributes, list) else []
        first_non_name = ''

        for item in entries:
            if not isinstance(item, dict):
                continue

            name = str(item.get('name', '')).strip()
            value = str(item.get('value', '')).strip()
            if not value:
                continue

            if name.lower() == 'name':
                return value

            if not first_non_name:
                first_non_name = value

        if first_non_name:
            return first_non_name

        return f"Piece {self.pk or ''}".strip()


class PresentationSession(models.Model):
    # allow multiple session rows per session_key (one per visit)
    # but only one can be attached to a user, and we attach the user to all of them on login
    # multiple sessions rows per key allow us to track multiple visits by the same user (or anonymous session) over time, and we can use the created_at timestamp to determine the most recent one
    session_key = models.CharField(max_length=40)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='presentation_sessions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Presentation session')
        verbose_name_plural = _('Presentation sessions')

    def __str__(self):
        return self.user.username if self.user else 'none'

    @property
    def display_user(self):
        return self.user.username if self.user else 'none'

    @property
    def display_session_or_user(self):
        return self.user.username if self.user else self.session_key


PRESENTATION_ACCESS_TYPES = (
    ('exhibition_on_site', _('Exhibition on site')),
    ('exhibition_user_device', _('Exhibition user device')),
    ('piece_on_site', _('Piece on site')),
    ('piece_user_device', _('Piece user device')),
)


class PresentationAccess(models.Model):
    presentation_session = models.ForeignKey(
        PresentationSession,
        related_name='accesses',
        on_delete=models.CASCADE,
    )
    presentation_type = models.CharField(max_length=32, choices=PRESENTATION_ACCESS_TYPES)
    presentation_title = models.CharField(max_length=255)
    presentation_path = models.CharField(max_length=255, blank=True, default='')
    last_accessed_at = models.DateTimeField(default=timezone.now)
    exhibition = models.ForeignKey(
        Exhibition,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='presentation_accesses',
    )
    piece = models.ForeignKey(
        Piece,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='presentation_accesses',
    )
    last_wagtail_page_title = models.CharField(max_length=255, blank=True, default='')
    last_wagtail_page_index = models.PositiveIntegerField(null=True, blank=True)
    accesses = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = _('Presentation access')
        verbose_name_plural = _('Presentation accesses')
        ordering = ['-id']

    def __str__(self):
        return f'{self.presentation_title} - {self.presentation_session}'

    @property
    def display_session_or_user(self):
        return self.presentation_session.display_session_or_user

    @property
    def session_or_user_history_kind(self):
        return 'user' if self.presentation_session.user_id else 'session'

    @property
    def session_or_user_history_pk(self):
        return self.presentation_session.user_id or self.presentation_session.pk

    @property
    def presentation_history_kind(self):
        # prefer piece when this access refers to a piece; otherwise exhibition
        return 'piece' if self.piece_id else 'exhibition'

    @property
    def presentation_history_pk(self):
        # return the piece id when available, otherwise the exhibition id
        return self.piece_id or self.exhibition_id

    @property
    def pages_visited(self):
        if self.last_wagtail_page_index is None:
            return 0
        return self.last_wagtail_page_index + 1

    @property
    def display_presentation_mode(self):
        return _('User Device') if self.presentation_type.endswith('user_device') else _('On Site')


class PresentationFavorite(models.Model):
    user = models.ForeignKey(
        User,
        related_name='presentation_favorites',
        on_delete=models.CASCADE,
    )
    presentation_path = models.CharField(max_length=255)
    presentation_title = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Presentation favorite')
        verbose_name_plural = _('Presentation favorites')
        unique_together = ('user', 'presentation_path')
        ordering = ['presentation_title']

    def __str__(self):
        return f'{self.presentation_title} - {self.user}'


EXECUTION_STATUS_CHOICES = (
    ('N',_('New')),        # After clicking on start execution
    ('C',_('Configured')), # After creation by user
    ('Q',_('In queue')),   # After used approved that execution could be run
    ('R',_('Running')),    # After requesting /nextexecution from RPI
    ('E',_('Error')),      # After request /execution/<int:id>/status change from RPI
    ('F',_('Finished')),   # After request /execution/<int:id>/status from RPI, or writing final result
    ('A',_('Aborted')),    # Not used now, in future triggered by user (needs endpoint)
    ('T',_('Timeout'))     # Not used now, possibly in future triggered by django
)

class Execution(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name = models.CharField(max_length=128, blank=True, default='')
    config = models.JSONField(_('Configuration'), default=dict, blank=True)
    status = models.CharField(_('Status'), max_length=1, choices=EXECUTION_STATUS_CHOICES)
    created_at = models.DateField(auto_now_add=True)
    queue_time = models.DateTimeField(null=True, blank=True)
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    client_country = models.ForeignKey(Country, related_name='executions', on_delete=models.RESTRICT, null = True)
    client_city = models.CharField(max_length=100, null=True)
    client_organization = models.CharField(max_length=200, null=True)
    client_long = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    client_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    client_ip_address = models.GenericIPAddressField(null=True)

    @property
    def order(self):
        if self.status == 'Q':
            lst_exec = Execution.objects.filter(status='Q', apparatus=self.apparatus, queue_time__lte= self.queue_time)
            return len(lst_exec)
        else:
            return None

    def __str__(self):
         return _('Execution of %(user)s') % {'user': str(self.user)}

    class Meta:
        verbose_name = _('Execution')
        verbose_name_plural = _('Executions')

    def save(self, *args, **kwargs):
        if self.status == 'Q' and not self.queue_time:
            self.queue_time = timezone.now()

        if self.status == 'R' and not self.start:
            self.start = timezone.now()

        if self.status in ['F','A','E'] and not self.end:
            self.end = timezone.now()

        super().save(*args, **kwargs)

RESULT_TYPES = {
    ('p', _('Partial')),
    ('f', _('Final')),
}



class Thing(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name = models.CharField(max_length=128, null=False)
    config = models.JSONField(_('Configuration'), default=dict, blank=True)
    created_at = models.DateField(auto_now_add=True)
    client_country = models.ForeignKey(Country, related_name='things', on_delete=models.RESTRICT, null = True, blank=True)
    client_city = models.CharField(max_length=100, null=True, blank=True)
    client_organization = models.CharField(max_length=200, null=True, blank=True)
    client_long = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    client_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    client_ip_address = models.GenericIPAddressField(blank=False, default = "127.0.0.1")

    def __str__(self):
         return _('Thing %(name)s belonging to %(user)s') % {'name': self.name, 'user': str(self.user)}

    class Meta:
        verbose_name = _('Thing')
        verbose_name_plural = _('Things')







USER_TYPES = (
    ('c', _('curator')),
    ('v', _('visitor')),
    ('p', _('VIP visitor')),
    ('a', _('Administrator'))
)


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete = models.CASCADE, related_name='profile')
    type = models.CharField(max_length=1, choices=USER_TYPES, default='v')
    museum = models.ForeignKey(Museum, null=True, blank=True, on_delete=models.SET_NULL, related_name='curator_profiles')

    def __str__(self):
        return _('Profile of ') + self.user.username

@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    UserProfile.objects.get_or_create(
        user=instance, defaults={'type': 'a' if instance.is_superuser else 'v'},
    )


@receiver(post_save, sender=UserProfile)
def update_role_permissions(sender, instance, raw=False, **kwargs):
    if not raw:
        from main_app.role_permissions import sync_user_access
        sync_user_access(instance)


@receiver(post_save, sender=Exhibition)
def update_exhibition_permissions(sender, instance, raw=False, **kwargs):
    if not raw:
        from main_app.role_permissions import sync_museum_access
        sync_museum_access()


@receiver(pre_delete, sender=Exhibition)
def cleanup_exhibition_wagtail_pages(sender, instance, **kwargs):
    """Delete associated Wagtail ExhibitionPage and all its child pages when Exhibition is deleted."""
    delete_exhibition_presentation_favorites(instance)
    if instance.slideshow_page:
        try:
            # Delete the ExhibitionPage, which will cascade delete all child pages
            # (pieces list page, piece pages, on-site pages, user device pages, etc.)
            instance.slideshow_page.delete()
        except Exception as e:
            # Log the error but don't fail the Exhibition deletion
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting Wagtail pages for exhibition '{instance.title}': {e}")


@receiver(pre_delete, sender=Piece)
def cleanup_piece_presentation_favorites(sender, instance, **kwargs):
    delete_piece_presentation_favorites(instance)
    if instance.slideshow_page_id:
        Page.objects.filter(pk=instance.slideshow_page_id).delete()


@receiver(user_logged_in)
def attach_presentation_session_to_user(sender, request, user, **kwargs):
    display_name = user.first_name.strip() if user.first_name else user.username
    request.session['auth_notyf'] = {
        'type': 'success',
        'message': f'Welcome {display_name}.',
    }

    current_session_key = request.session.session_key
    previous_session_key = request.session.get('presentation_pre_login_session_key')

    session_keys = {key for key in [current_session_key, previous_session_key] if key}
    if not session_keys:
        return

    # Attach the authenticated user to any prior anonymous presentation sessions.
    # We check both the pre-login key (before rotation) and the current key.
    PresentationSession.objects.filter(session_key__in=session_keys, user__isnull=True).update(user=user)

    if 'presentation_pre_login_session_key' in request.session:
        del request.session['presentation_pre_login_session_key']

    favorites = request.session.get(SESSION_FAVORITES_KEY, [])
    if isinstance(favorites, list):
        for favorite in favorites:
            if not isinstance(favorite, dict):
                continue
            path = str(favorite.get('path', '')).strip()
            title = str(favorite.get('title', '')).strip() or path
            if not path or title == 'FREE |':
                continue
            PresentationFavorite.objects.update_or_create(
                user=user,
                presentation_path=path[:255],
                defaults={'presentation_title': title[:255]},
            )
        request.session[SESSION_FAVORITES_KEY] = []
        request.session.modified = True



@receiver(pre_delete, sender=Museum)
def detach_museum_curators(sender, instance, **kwargs):
    for profile in instance.curator_profiles.select_related('user'):
        profile.museum = None
        profile.save()
