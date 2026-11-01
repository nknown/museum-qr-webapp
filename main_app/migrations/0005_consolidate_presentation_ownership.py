from django.db import migrations


PRESENTATION_MODES = ('on_site', 'user_device')


def consolidate_presentation_ownership(apps, schema_editor):
    """Move inherited layout defaults onto exhibitions and clear piece overrides."""
    Exhibition = apps.get_model('main_app', 'Exhibition')
    Piece = apps.get_model('main_app', 'Piece')

    for exhibition in Exhibition.objects.select_related('museum').order_by('pk'):
        attributes = (
            dict(exhibition.Exhibition_attributes)
            if isinstance(exhibition.Exhibition_attributes, dict)
            else {}
        )
        selected = attributes.get('presentation_templates')
        selected = dict(selected) if isinstance(selected, dict) else {}
        museum_templates = (
            exhibition.museum.presentation_templates
            if exhibition.museum_id
            and isinstance(exhibition.museum.presentation_templates, dict)
            else {}
        )
        first_piece_templates = {}
        for piece_templates in Piece.objects.filter(
            exhibition_id=exhibition.pk
        ).order_by('pk').values_list('presentation_templates', flat=True):
            if isinstance(piece_templates, dict):
                for mode in PRESENTATION_MODES:
                    if piece_templates.get(mode) and mode not in first_piece_templates:
                        first_piece_templates[mode] = piece_templates[mode]

        for mode in PRESENTATION_MODES:
            if not selected.get(mode):
                selected[mode] = (
                    museum_templates.get(mode)
                    or first_piece_templates.get(mode)
                    or ''
                )
            if not selected[mode]:
                selected.pop(mode, None)

        attributes['presentation_templates'] = selected
        exhibition.Exhibition_attributes = attributes
        exhibition.save(update_fields=['Exhibition_attributes'])

    Piece.objects.exclude(presentation_templates={}).update(presentation_templates={})


class Migration(migrations.Migration):
    dependencies = [('main_app', '0004_exhibition_appearance_enabled_and_more')]

    operations = [
        migrations.RunPython(consolidate_presentation_ownership, migrations.RunPython.noop),
    ]
