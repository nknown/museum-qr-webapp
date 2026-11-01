"""Visitor history is derived from server records, never trusted browser storage."""
from django.db.models import Q
from django.urls import reverse
from main_app.models import PresentationAccess
from main_app.access import all_visitor_content, visible_exhibitions, visible_pieces, can_view_presentation


def visitor_history(request):
    accesses = PresentationAccess.objects.none()
    if request.user.is_authenticated:
        accesses = PresentationAccess.objects.filter(presentation_session__user=request.user)
    elif request.session.session_key:
        accesses = PresentationAccess.objects.filter(presentation_session__session_key=request.session.session_key, presentation_session__user__isnull=True)
    seen_pieces = set(accesses.values_list('piece_id', flat=True))
    seen_exhibitions = set(accesses.values_list('exhibition_id', flat=True))
    demo = all_visitor_content(request.user)
    current = getattr(request, 'presentation_exhibition_id', None)
    exhibitions = visible_exhibitions(request.user).select_related('museum', 'slideshow_page')
    if not demo:
        exhibitions = exhibitions.filter(Q(pk__in=seen_exhibitions) | Q(pk=current))
    state = {'museums': {}}
    for exhibition in exhibitions:
        if not can_view_presentation(request.user, exhibition):
            continue
        museum_id = f'museum:{exhibition.museum_id}' if exhibition.museum_id else 'not-on-display'
        museum = state['museums'].setdefault(museum_id, {
            'id': museum_id, 'title': exhibition.museum.title if exhibition.museum else 'Not currently on display',
            'path': '', 'visited': True, 'exhibitions': {},
        })
        exhibition_id = f'exhibition:{exhibition.public_id}'
        node = {'id': exhibition_id, 'title': exhibition.title,
            'path': reverse('main_app:exhibition-public-presentation', args=[exhibition.public_id]),
            'visited': demo or exhibition.pk in seen_exhibitions, 'pieces': {}}
        museum['exhibitions'][exhibition_id] = node
        for piece in visible_pieces(request.user).filter(exhibition=exhibition).select_related('slideshow_page'):
            if not can_view_presentation(request.user, piece):
                continue
            piece_id = f'piece:{piece.public_id}'
            node['pieces'][piece_id] = {'id': piece_id, 'title': str(piece),
                'path': reverse('main_app:piece-public-presentation', args=[piece.public_id]),
                'visited': demo or piece.pk in seen_pieces}
    if demo:
        orphans = visible_pieces(request.user).filter(exhibition__isnull=True)
        if orphans.exists():
            museum = state['museums'].setdefault('not-on-display', {
                'id': 'not-on-display', 'title': 'Not currently on display',
                'path': '', 'visited': True, 'exhibitions': {},
            })
            museum['exhibitions']['unassigned'] = {
                'id': 'unassigned', 'title': 'Unassigned pieces', 'path': '', 'visited': True,
                'pieces': {f'piece:{piece.public_id}': {
                    'id': f'piece:{piece.public_id}', 'title': str(piece), 'visited': True,
                    'path': reverse('main_app:piece-public-presentation', args=[piece.public_id]),
                } for piece in orphans},
            }
    return state
