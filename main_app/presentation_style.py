"""Resolve exhibition-owned layouts and museum-owned branding."""
import re

ON_SITE_CHOICES = (
    ('', 'Built-in default layout'),
    ('fomantic_on_site_widescreen_v1', 'On Site 16:9 widescreen'),
    ('fomantic_on_site_standard_v1', 'On Site 4:3 standard / square'),
)
USER_DEVICE_CHOICES = (('', 'Built-in default layout'), ('fomantic_user_device_v1', 'Handheld Device'))


def exhibition_templates(exhibition):
    attrs = exhibition.Exhibition_attributes
    value = attrs.get('presentation_templates', {}) if isinstance(attrs, dict) else {}
    return value if isinstance(value, dict) else {}


def assigned_template(exhibition, presentation_type, piece=None):
    template = exhibition_templates(exhibition).get(presentation_type) if exhibition else None
    return 'fomantic_on_site_standard_v1' if template == 'fomantic_on_site_v1' else (template or '')


def presentation_appearance(exhibition):
    source = exhibition.museum if exhibition and exhibition.museum_id else None
    if not source or not source.appearance_enabled:
        return None
    colour = source.overlay_colour
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', colour):
        colour = '#ffffff'
    rgb = [int(colour[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    luminance = sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
    return {'image': source.background_image, 'colour': colour,
            'opacity': f'{max(65, min(100, source.overlay_opacity)) / 100:.2f}',
            'ink': '#000000' if luminance > .179 else '#ffffff'}
