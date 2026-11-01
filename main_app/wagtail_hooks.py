from django.core.exceptions import PermissionDenied
from django.templatetags.static import static
from django.utils.html import format_html
from wagtail import hooks
from wagtail.models import Page
from main_app.models import ExhibitionPage, PiecePage


RESTRICTED_ADD_CHILD_PARENT_CLASSES = (ExhibitionPage, PiecePage)


def _is_restricted_parent(page):
    return isinstance(page.specific, RESTRICTED_ADD_CHILD_PARENT_CLASSES)


def _iter_descendants(page):
    return page.get_descendants().specific().order_by("depth", "path")


def _publish_descendants_recursively(page, user=None):
    for descendant in _iter_descendants(page):
        # Skip pages that are already live with no pending draft changes.
        if descendant.live and not descendant.has_unpublished_changes:
            continue

        revision = descendant.get_latest_revision()
        if revision is None:
            revision = descendant.save_revision(user=user)

        revision.publish(user=user, skip_permission_checks=True)


def _unpublish_descendants_recursively(page, user=None):
    live_descendants = (
        page.get_descendants().live().specific().order_by("-depth", "path")
    )
    for descendant in live_descendants:
        descendant.unpublish(user=user)


def _is_page_like(obj):
    return isinstance(obj, Page)


@hooks.register("before_create_page")
def block_manual_page_creation(request, parent_page, page_class):
    # Keep structure roots managed by main_app; slideshow detail pages can be added manually.
    if _is_restricted_parent(parent_page):
        raise PermissionDenied("Create Exhibition and Piece pages from main_app views.")


@hooks.register("construct_page_listing_buttons")
def hide_add_child_listing_button(buttons, page, user, context=None):
    if not _is_restricted_parent(page):
        return

    buttons[:] = [
        button
        for button in buttons
        if getattr(button, "name", "") not in {"add_subpage", "add_child_page"}
    ]


@hooks.register("construct_page_action_menu")
def hide_add_child_action_menu(menu_items, request, context):
    page = context.get("page")
    if not page or not _is_restricted_parent(page):
        return

    menu_items[:] = [
        item
        for item in menu_items
        if getattr(item, "name", "") not in {"add_subpage", "add_child_page"}
    ]


@hooks.register("insert_editor_js")
def pin_draftail_toolbar_by_default():
    return format_html(
        '<script src="{}"></script>',
        static("main_app/js/draftail_toolbar_pin.js"),
    )


@hooks.register("insert_global_admin_css")
def global_admin_css():
    return format_html(
        '<link rel="stylesheet" href="{}">',
        static('main_app/css/wagtail_overrides.css'),
    )


@hooks.register("after_publish_page")
def publish_descendants_when_parent_published(request, page):
    _publish_descendants_recursively(page, user=getattr(request, "user", None))


@hooks.register("after_unpublish_page")
def unpublish_descendants_when_parent_unpublished(request, page):
    _unpublish_descendants_recursively(page, user=getattr(request, "user", None))


@hooks.register("after_bulk_action")
def cascade_descendants_for_bulk_publish_unpublish(request, action_type, objects, action):
    user = getattr(request, "user", None)

    if action_type == "publish":
        for obj in objects:
            if not _is_page_like(obj):
                continue
            page = obj.specific
            for descendant in _iter_descendants(page):
                if user and not descendant.permissions_for_user(user).can_publish():
                    continue
                if descendant.live and not descendant.has_unpublished_changes:
                    continue

                revision = descendant.get_latest_revision()
                if revision is None:
                    revision = descendant.save_revision(user=user)
                revision.publish(user=user, skip_permission_checks=True)

    if action_type == "unpublish":
        for obj in objects:
            if not _is_page_like(obj):
                continue
            page = obj.specific
            for descendant in page.get_descendants().live().specific().order_by("-depth", "path"):
                if user and not descendant.permissions_for_user(user).can_unpublish():
                    continue
                descendant.unpublish(user=user)
