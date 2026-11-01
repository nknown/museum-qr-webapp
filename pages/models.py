from django.db import models

# Create your models here.
from django.db import models
from wagtail.models import Page
from wagtail.admin.panels import FieldPanel


class ContentPage(Page):
    piece = models.ForeignKey(
        'main_app.Piece',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='wagtail_pages',
        help_text='Associate this page with a Piece'
    )
    body = models.TextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("piece"),
        FieldPanel("body"),
    ]

    