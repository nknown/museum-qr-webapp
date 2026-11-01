from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render, redirect
from wagtail.images.widgets import AdminImageChooser
from wagtail.images.permissions import permission_policy
from main_app.models import Museum, Piece
from main_app.access import can_curate, managed_exhibitions, is_administrator
from main_app.presentation_style import ON_SITE_CHOICES, USER_DEVICE_CHOICES, exhibition_templates


class LayoutForm(forms.Form):
    on_site_template = forms.ChoiceField(choices=ON_SITE_CHOICES, required=False)
    user_device_template = forms.ChoiceField(choices=USER_DEVICE_CHOICES, required=False)


class AppearanceForm(forms.Form):
    appearance_enabled = forms.BooleanField(required=False, label='Enable background appearance')
    background_image = forms.ModelChoiceField(queryset=permission_policy.model.objects.none(), required=False, widget=AdminImageChooser)
    overlay_colour = forms.RegexField(regex=r'^#[0-9a-fA-F]{6}$', initial='#ffffff', widget=forms.TextInput(attrs={'type': 'color'}), label='Overlay colour')
    overlay_opacity = forms.IntegerField(min_value=65, max_value=100, initial=85, label='Overlay opacity (%)', help_text='Higher values soften the texture. Text also has a solid colour surface for readability.')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['background_image'].queryset = permission_policy.instances_user_has_any_permission_for(user, ['choose'])


def templates_view(request):
    return settings_view(request, appearance=False)


def appearance_view(request):
    return settings_view(request, appearance=True)


def settings_view(request, *, appearance):
    if not can_curate(request.user):
        raise PermissionDenied
    exhibitions = managed_exhibitions(request.user).select_related('museum').order_by('title')
    museums = Museum.objects.all() if is_administrator(request.user) else Museum.objects.filter(curator_profiles__user=request.user)
    if appearance:
        targets = {f'museum:{m.pk}': (m, True) for m in museums.order_by('title')}
    else:
        targets = {f'exhibition:{e.pk}': (e, False) for e in exhibitions}
    selected = request.POST.get('target') if request.method == 'POST' else request.GET.get('target')
    # Retain the previous exhibition-only form contract.
    legacy = request.method == 'POST' and not selected and 'exhibition_id' in request.POST
    if legacy:
        selected = 'exhibition:' + request.POST.get('exhibition_id', '')
    if request.method == 'POST' and selected not in targets:
        raise PermissionDenied('Select a museum or exhibition you manage.')
    if selected not in targets:
        selected = next(iter(targets), None)
    target, museum = targets[selected] if selected else (None, False)
    form = None
    if target:
        if appearance:
            initial = {name: getattr(target, name) for name in ('appearance_enabled', 'background_image', 'overlay_colour', 'overlay_opacity')}
            form = AppearanceForm(request.POST if request.method == 'POST' else None, initial=initial, user=request.user)
        else:
            templates = exhibition_templates(target)
            initial = {mode + '_template': templates.get(mode, '') for mode in ('on_site', 'user_device')}
            if initial['on_site_template'] == 'fomantic_on_site_v1':
                initial['on_site_template'] = 'fomantic_on_site_standard_v1'
            form = LayoutForm(request.POST if request.method == 'POST' else None, initial=initial)
        if request.method == 'POST' and form.is_valid():
            values = form.cleaned_data
            with transaction.atomic():
                if appearance:
                    fields = ['appearance_enabled', 'background_image', 'overlay_colour', 'overlay_opacity']
                    for name in fields:
                        setattr(target, name, values[name])
                    target.save(update_fields=fields)
                else:
                    templates = {mode: values[mode + '_template'] for mode in ('on_site', 'user_device') if values[mode + '_template']}
                    attrs = dict(target.Exhibition_attributes) if isinstance(target.Exhibition_attributes, dict) else {}
                    attrs['presentation_templates'] = templates
                    target.Exhibition_attributes = attrs
                    target.save(update_fields=['Exhibition_attributes'])
                    target.pieces.update(presentation_templates={})
            messages.success(request, f'{"Background appearance" if appearance else "Templates"} updated for "{target.title}".')
            from django.urls import reverse
            return redirect(reverse('presentation_appearance' if appearance else 'templates') + '?target=' + selected)
    assignment_rows = []
    if not appearance:
        for key, (obj, is_museum) in targets.items():
            own_templates = exhibition_templates(obj)
            layouts = []
            for mode, choices in [('on_site', ON_SITE_CHOICES), ('user_device', USER_DEVICE_CHOICES)]:
                template_id = own_templates.get(mode, '')
                if template_id == 'fomantic_on_site_v1':
                    template_id = 'fomantic_on_site_standard_v1'
                source = 'Exhibition layout' if template_id else ''
                layouts.append({'label': dict(choices).get(template_id, template_id) if template_id else 'Not applied (default layout)',
                                'enabled': bool(template_id), 'source': source})
            assignment_rows.append({
                'target': key, 'title': obj.title, 'kind': 'Exhibition',
                'museum': obj.museum.title if obj.museum_id else '',
                'layouts': layouts,
            })
    return render(request, 'main_app/wagtail_admin/appearance.html' if appearance else 'main_app/wagtail_admin/templates.html', {
        'assignment_rows': assignment_rows,
        'form': form, 'selected': selected, 'target': target, 'museum_scope': museum,
        'targets': [(key, ('Museum: ' if appearance else 'Exhibition: ') + obj.title) for key, (obj, is_museum) in targets.items()],
    })
