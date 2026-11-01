"""Role and object access rules shared by the application and CMS."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from main_app.models import Exhibition, Piece, PresentationAccess


def role(user):
    if user is None or not user.is_authenticated or not user.is_active:
        return None
    if user.is_superuser:
        return 'a'
    return getattr(getattr(user, 'profile', None), 'type', 'v')


def is_administrator(user):
    return role(user) == 'a'


def is_curator(user):
    return role(user) == 'c'


def can_curate(user):
    return role(user) in {'a', 'c'}


def all_visitor_content(user):
    return role(user) in {'a', 'p'}


def curator_museum(user):
    museum = getattr(getattr(user, 'profile', None), 'museum', None)
    if not is_curator(user) or museum is None:
        raise PermissionDenied('An administrator must assign your curator account to a museum first.')
    return museum


def managed_exhibitions(user):
    if is_administrator(user):
        return Exhibition.objects.all()
    if is_curator(user) and user.profile.museum_id:
        return Exhibition.objects.filter(museum_id=user.profile.museum_id)
    return Exhibition.objects.none()


def managed_pieces(user):
    if is_administrator(user):
        return Piece.objects.all()
    return Piece.objects.filter(exhibition__in=managed_exhibitions(user))


def can_manage(user, exhibition):
    return is_administrator(user) or (exhibition is not None and managed_exhibitions(user).filter(pk=exhibition.pk).exists())


def visible_exhibitions(user):
    if all_visitor_content(user):
        return Exhibition.objects.all()
    return Exhibition.objects.filter(Q(slideshow_page__live=True) | Q(pk__in=managed_exhibitions(user)))


def visible_pieces(user):
    if all_visitor_content(user):
        return Piece.objects.all()
    return Piece.objects.filter(
        Q(slideshow_page__live=True, exhibition__slideshow_page__live=True)
        | Q(pk__in=managed_pieces(user))
    )


def can_view_content(user, obj):
    if obj is None:
        return False
    qs = visible_pieces(user) if isinstance(obj, Piece) else visible_exhibitions(user)
    return qs.filter(pk=obj.pk).exists()


def can_preview(user, obj):
    exhibition = obj.exhibition if isinstance(obj, Piece) else obj
    return all_visitor_content(user) or can_manage(user, exhibition)


def presentation_folder(obj, mode):
    if not obj.slideshow_page_id:
        return None
    return obj.slideshow_page.get_children().filter(slug=mode).specific().first()


def can_view_presentation(user, obj, mode='user_device'):
    if can_preview(user, obj):
        return True
    folder = presentation_folder(obj, mode)
    return can_view_content(user, obj) and folder is not None and folder.live


class CuratorRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not can_curate(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class AdministratorRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not is_administrator(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def managed_accesses(user):
    if is_administrator(user):
        return PresentationAccess.objects.all()
    return PresentationAccess.objects.filter(exhibition__in=managed_exhibitions(user))


def page_domain_object(page):
    ancestors = page.get_ancestors(inclusive=True)
    return (Piece.objects.filter(slideshow_page__in=ancestors).first()
            or Exhibition.objects.filter(slideshow_page__in=ancestors).first())
