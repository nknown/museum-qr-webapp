"""Provision only museum-scoped CMS permissions for curator accounts."""
from django.contrib.auth.models import Group, Permission, User
from django.db.models import Q
from django.db import transaction
from wagtail.models import GroupPagePermission, GroupCollectionPermission, Collection

PREFIX = 'MIYP curator '


@transaction.atomic
def sync_user_access(profile):
    user = profile.user
    from main_app.models import Museum
    for museum in Museum.objects.filter(admins=user):
        if profile.type != 'c' or museum.pk != profile.museum_id:
            museum.admins.remove(user)
    if profile.type == 'c' and profile.museum_id:
        profile.museum.admins.add(user)
    administrator = profile.type == 'a'
    User.objects.filter(pk=user.pk).update(is_staff=administrator, is_superuser=administrator)
    user.is_staff = user.is_superuser = administrator
    # Roles are authoritative: old staff/editor grants must not survive demotion.
    if not administrator:
        user.user_permissions.clear()
        user.groups.remove(*user.groups.filter(
            Q(permissions__isnull=False) | Q(page_permissions__isnull=False)
            | Q(collection_permissions__isnull=False) | Q(name__startswith=PREFIX)
        ).distinct())
    if profile.type != 'c' or not profile.museum_id:
        return
    group, _ = Group.objects.get_or_create(name=f'{PREFIX}{profile.user_id}')
    group.permissions.set(Permission.objects.filter(content_type__app_label='wagtailadmin', codename='access_admin'))
    user.groups.add(group)
    sync_page_access(profile, group)
    collection = Collection.get_first_root_node()
    if collection:
        # Upload and choose shared media; no right to edit other curators' uploads.
        for permission in Permission.objects.filter(
            content_type__app_label__in=['wagtailimages', 'wagtaildocs'],
            codename__in=['add_image', 'choose_image', 'add_document', 'choose_document'],
        ):
            GroupCollectionPermission.objects.get_or_create(group=group, collection=collection, permission=permission)


def sync_page_access(profile, group):
    from main_app.models import Exhibition
    GroupPagePermission.objects.filter(group=group).delete()
    permissions = Permission.objects.filter(content_type__app_label='wagtailcore', content_type__model='page',
        codename__in=['add_page', 'change_page', 'publish_page', 'bulk_delete_page', 'lock_page', 'unlock_page'])
    roots = Exhibition.objects.filter(museum_id=profile.museum_id, slideshow_page__isnull=False).values_list('slideshow_page_id', flat=True)
    GroupPagePermission.objects.bulk_create([
        GroupPagePermission(group=group, page_id=root, permission=permission)
        for root in roots for permission in permissions
    ])


def sync_museum_access():
    from main_app.models import UserProfile
    for profile in UserProfile.objects.filter(type='c', museum__isnull=False).select_related('user'):
        group = Group.objects.filter(name=f'{PREFIX}{profile.user_id}').first()
        if group:
            sync_page_access(profile, group)
