from django.db import models
from django.contrib.gis.db import models as geomodels
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.contrib.postgres.fields import JSONField
from countries_plus.models import Country

import environ
env = environ.Env()
environ.Env.read_env()
from django.core.cache import cache


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


class SpatialThing(geomodels.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name = models.CharField(max_length=128, null=False)
    created_at = models.DateField(auto_now_add=True)
    client_ip_address = models.GenericIPAddressField(blank=False, default = "127.0.0.1") 
    points = geomodels.MultiPointField(null=True)
    limits = geomodels.MultiPolygonField(null=True)

    def __str__(self):
         return _('SpatialThing %(name)s belonging to %(user)s') % {'name': self.name, 'user': str(self.user)}

    class Meta:
        verbose_name = _('SpatialThing')
        verbose_name_plural = _('SpatialThings')





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

#added this part below for creating the database already with described UML

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Exposition(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    admins = models.ManyToManyField(
        User,
        related_name="expositions",
        blank=True,
    )

    pieces = models.ManyToManyField(
        "Piece",
        related_name="expositions",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Piece(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Útil para QR: /p/<qr_slug> ou semelhante
    qr_slug = models.SlugField(max_length=120, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Slide(models.Model):
    piece = models.ForeignKey(Piece, on_delete=models.CASCADE, related_name="slides")
    order = models.PositiveIntegerField(default=0)

    title = models.CharField(max_length=200, blank=True)
    text = models.TextField(blank=True)
    image = models.ImageField(upload_to="slides/", blank=True, null=True)
    # opcional:
    # video_url = models.URLField(blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.piece.title} / slide {self.order}"