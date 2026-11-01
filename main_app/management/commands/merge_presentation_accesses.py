from django.core.management.base import BaseCommand
from django.db import transaction
from main_app.models import PresentationAccess


class Command(BaseCommand):
    help = 'Merge multiple PresentationAccess rows for the same user and presentation into a single row (summing accesses and keeping latest last_wagtail_page)'

    def handle(self, *args, **options):
        self.stdout.write('Scanning for duplicate PresentationAccess rows...')
        qs = PresentationAccess.objects.select_related('presentation_session')

        # We'll group both by user (when attached) and by session_key for anonymous
        groups = {}
        for access in qs:
            user_id = access.presentation_session.user_id
            if user_id:
                key = ('user', user_id, access.presentation_type, access.exhibition_id, access.piece_id)
            else:
                key = ('session', access.presentation_session.session_key, access.presentation_type, access.exhibition_id, access.piece_id)
            groups.setdefault(key, []).append(access)

        merged = 0
        removed = 0
        for key, accesses in groups.items():
            if len(accesses) <= 1:
                continue
            accesses_sorted = sorted(accesses, key=lambda a: a.id)
            target = accesses_sorted[-1]
            others = accesses_sorted[:-1]
            total_accesses = sum((a.accesses or 0) for a in accesses_sorted)

            with transaction.atomic():
                target.accesses = total_accesses
                target.save(update_fields=['accesses', 'last_wagtail_page_index', 'last_wagtail_page_title'])
                ids_to_delete = [a.id for a in others]
                PresentationAccess.objects.filter(id__in=ids_to_delete).delete()
                merged += 1
                removed += len(ids_to_delete)

        self.stdout.write(self.style.SUCCESS(f'Merged {merged} grouped presentation accesses; removed {removed} duplicate rows.'))
