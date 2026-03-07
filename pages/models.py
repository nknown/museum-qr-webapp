from django.db import models

# Create your models here.
from django.db import models
from wagtail.models import Page
from wagtail.admin.panels import FieldPanel


class ContentPage(Page):
    body = models.TextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("body"),
    ]

    