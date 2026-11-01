from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import path, reverse
from django.utils.html import format_html
from wagtail import hooks
from wagtail.models import Page
from main_app.models import Exhibition, ExhibitionPage, PiecePage
from main_app.access import can_curate, managed_exhibitions, is_administrator, can_manage, can_preview, can_view_content, page_domain_object
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from main_app.template_admin import templates_view, appearance_view

RESTRICTED_ADD_CHILD_PARENT_CLASSES = (ExhibitionPage, PiecePage)


@hooks.register("register_admin_urls")
def register_templates_admin_url():
    return [
        path("Templates/", templates_view, name="templates"),
        path("PresentationAppearance/", appearance_view, name="presentation_appearance"),
    ]


@hooks.register("register_admin_menu_item")
def register_templates_menu_item():
    return SubmenuMenuItem(
        "Templates",
        Menu(items=[
            MenuItem("Presentation Layouts", reverse("templates"), icon_name="form", order=100),
            MenuItem("Museum Branding", reverse("presentation_appearance"), icon_name="image", order=110),
        ]),
        name="templates", icon_name="form", order=100,
    )


@hooks.register("insert_global_admin_css")
def hide_top_right_menu():
    return """
    <style>
        .w-header__account,
        .w-header__user {
            display: none !important;
        }
    </style>
    """
@hooks.register("insert_global_admin_css")
def hide_wagtail_warning_css():
    return """
    <style>
        .help-block {
            display: none !important;
        }
    </style>
    """

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

@hooks.register('construct_main_menu')
def remove_items(request, menu_items):
    menu_items[:] = [item for item in menu_items if item.name not in ['images', 'documents', 'reports', 'settings', 'help']]


@hooks.register("insert_global_admin_js")
def pin_draftail_toolbar_by_default():
    # Set the native toolbar preference before editors (including StreamField
    # rich-text blocks) initialise; the script also handles dynamic additions.
    return format_html(
        '<script src="{}"></script>',
        static("main_app/js/draftail_toolbar_pin.js") + "?v=2",
    )


@hooks.register("insert_global_admin_css")
def global_admin_css():
    return format_html(
        '<link rel="stylesheet" href="{}">',
        static('main_app/css/wagtail_overrides.css') + '?v=2',
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


@hooks.register('before_serve_page')
def enforce_domain_publication(page, request, serve_args, serve_kwargs):
    from django.http import Http404
    ancestors = page.get_ancestors(inclusive=True)
    obj = page_domain_object(page)
    if obj is None:
        return
    if can_preview(request.user, obj):
        return
    if not can_view_content(request.user, obj) or ancestors.filter(live=False).exists():
        raise Http404


@hooks.register('before_move_page')
def restrict_curator_page_moves(request, page, destination):
    if is_administrator(request.user):
        return
    # Moving structural roots would break the relational domain/CMS correspondence.
    from main_app.models import SlideshowSlidePage
    if not isinstance(page.specific, SlideshowSlidePage):
        raise PermissionDenied('Move exhibitions and pieces through the domain workflow.')
    if not destination.permissions_for_user(request.user).can_add_subpage():
        raise PermissionDenied
