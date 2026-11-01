from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from django.utils import timezone
from datetime import timedelta
from countries_plus.models import Country

import environ
env = environ.Env()
environ.Env.read_env()
from django.core.cache import cache

from wagtail.models import Page, Orderable
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.images import get_image_model_string
from modelcluster.fields import ParentalKey




class Exhibition(models.Model):
    title = models.CharField(max_length=255, blank=False, default='New Exhibition')
    description = models.TextField(blank=False, default='Exhibition description')
    Exhibition_attributes = models.JSONField(_('Exhibition_attributes'), default=dict, blank=True)

    pieces_attributes = models.JSONField(_('Pieces_attributes'), default=list, blank=True)


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

class ExhibitionPage(Page):
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


class ExhibitionOnSitePage(slideshowContentMixin, Page):
    time_seconds = models.PositiveIntegerField(blank=True, null=True)
    parent_page_types = ["main_app.ExhibitionPage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/exhibition_on_site_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("time_seconds"),
        FieldPanel("hero_image"),
    ]


class ExhibitionUserDevicePage(slideshowContentMixin, Page):
    parent_page_types = ["main_app.ExhibitionPage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/exhibition_user_device_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("hero_image"),
    ]


class ExhibitionPiecesListPage(Page):
    parent_page_types = ["main_app.ExhibitionPage"]
    subpage_types = ["main_app.PiecePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/exhibition_pieces_page.html"

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['piece_pages'] = self.get_children().live().specific()
        return context


class PiecePage(Page):
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


class PieceOnSitePage(slideshowContentMixin, Page):
    time_seconds = models.PositiveIntegerField(blank=True, null=True)
    parent_page_types = ["main_app.PiecePage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/piece_on_site_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("time_seconds"),
        FieldPanel("hero_image"),
    ]


class PieceUserDevicePage(slideshowContentMixin, Page):
    parent_page_types = ["main_app.PiecePage"]
    subpage_types = ["main_app.SlideshowSlidePage"]
    admin_default_ordering = "ord"
    is_creatable = False
    template = "main_app/models/wagtail/piece_user_device_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("hero_image"),
    ]


class SlideshowSlidePage(Page):
    body = RichTextField(blank=True)
    time_seconds = models.PositiveIntegerField(blank=True, null=True)

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
        FieldPanel("time_seconds"),
        InlinePanel("gallery_images", label="Images"),
    ]


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
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Presentation access')
        verbose_name_plural = _('Presentation accesses')
        ordering = ['-accessed_at']

    def __str__(self):
        return f'{self.presentation_title} - {self.presentation_session}'


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
    ('s', _('Student')),
    ('t', _('Teacher')),
    ('a', _('Administrator'))
)


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete = models.CASCADE, related_name='profile')
    type = models.CharField(max_length=1, choices=USER_TYPES)

    def __str__(self):
        return _('Profile of ') + self.user.username

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user = instance, type='s')
    instance.profile.save()

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()


@receiver(pre_delete, sender=Exhibition)
def cleanup_exhibition_wagtail_pages(sender, instance, **kwargs):
    """Delete associated Wagtail ExhibitionPage and all its child pages when Exhibition is deleted."""
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


@receiver(user_logged_in)
def attach_presentation_session_to_user(sender, request, user, **kwargs):
    session_key = request.session.session_key
    if not session_key:
        return
    # Attach the authenticated user to any prior anonymous presentation sessions
    # for this session_key. We update all matching rows that have no user yet.
    PresentationSession.objects.filter(session_key=session_key, user__isnull=True).update(user=user)

