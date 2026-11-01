from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from main_app.models import Museum
from main_app.role_permissions import sync_user_access


class Command(BaseCommand):
    help = 'Synchronise administrator access, or assign an existing curator to one museum.'

    def add_arguments(self, parser):
        parser.add_argument('--admin', help='Username or email of an existing curator.')
        parser.add_argument('--museum', type=int, help='Museum ID (required with --admin).')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options['admin']:
            user = (User.objects.filter(username=options['admin']).first()
                    or User.objects.filter(email=options['admin']).first())
            if user is None or user.profile.type != 'c':
                raise CommandError('Select an existing curator account.')
            museum = Museum.objects.filter(pk=options['museum']).first()
            if museum is None:
                raise CommandError('Specify a valid --museum ID.')
            user.profile.museum = museum
            user.profile.save()
            self.stdout.write(self.style.SUCCESS('Curator museum assignment updated.'))
            return
        for user in User.objects.filter(is_superuser=True):
            user.profile.type = 'a'
            user.profile.save()
        self.stdout.write(self.style.SUCCESS('Administrator access synchronised. Administrators have global access.'))
