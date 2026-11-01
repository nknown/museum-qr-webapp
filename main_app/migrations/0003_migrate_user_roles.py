from django.db import migrations


def migrate_roles(apps, schema_editor):
    Profile = apps.get_model('main_app', 'UserProfile')
    User = apps.get_model('auth', 'User')
    Museum = apps.get_model('main_app', 'Museum')
    Exhibition = apps.get_model('main_app', 'Exhibition')
    alias = schema_editor.connection.alias
    Profile.objects.using(alias).filter(type='s').update(type='v')
    Profile.objects.using(alias).filter(type='t').update(type='c')
    for user in User.objects.using(alias).all():
        profile, _ = Profile.objects.using(alias).get_or_create(user_id=user.pk, defaults={'type': 'v'})
        if user.is_superuser:
            profile.type = 'a'
        if profile.type == 'c':
            ids = set(Museum.objects.using(alias).filter(admins=user.pk).values_list('pk', flat=True))
            ids.update(Exhibition.objects.using(alias).filter(admins=user.pk, museum__isnull=False).values_list('museum_id', flat=True))
            # Ambiguous assignments stay empty for an administrator to resolve.
            if len(ids) == 1:
                profile.museum_id = ids.pop()
        profile.save(using=alias)
        User.objects.using(alias).filter(pk=user.pk).update(is_staff=profile.type == 'a', is_superuser=profile.type == 'a')


class Migration(migrations.Migration):
    dependencies = [('main_app', '0002_exhibitiononsitepage_content_and_more')]
    operations = [migrations.RunPython(migrate_roles, migrations.RunPython.noop)]
