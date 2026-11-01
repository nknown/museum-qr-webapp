from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from main_app.models import USER_TYPES, Museum, UserProfile


User = get_user_model()


class AdminUserCreationForm(forms.ModelForm):
    LOCAL_ACCOUNT = 'local'
    GOOGLE_ACCOUNT = 'google'
    ACCOUNT_TYPES = (
        (LOCAL_ACCOUNT, _('Simple username and password')),
        (GOOGLE_ACCOUNT, _('Google email')),
    )

    account_type = forms.ChoiceField(
        choices=ACCOUNT_TYPES,
        initial=LOCAL_ACCOUNT,
        widget=forms.RadioSelect,
    )
    username = forms.CharField(
        required=False,
        max_length=150,
        help_text=_('Required for a simple account.'),
    )
    google_email = forms.EmailField(
        required=False,
        label=_('Google email'),
        help_text=_('Required for a Google account. No local password is created.'),
    )
    password1 = forms.CharField(
        required=False,
        label=_('Password'),
        strip=False,
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(
        required=False,
        label=_('Password confirmation'),
        strip=False,
        widget=forms.PasswordInput,
    )
    profile_type = forms.ChoiceField(
        choices=USER_TYPES,
        initial='v',
        label=_('Role'),
    )

    museum = forms.ModelChoiceField(queryset=Museum.objects.all(), required=False, help_text=_('Required for curators.'))

    class Meta:
        model = User
        fields = ('username',)

    def clean(self):
        cleaned_data = super().clean()
        account_type = cleaned_data.get('account_type')
        if cleaned_data.get('profile_type') == 'c' and not cleaned_data.get('museum'):
            self.add_error('museum', _('Select a museum for this curator.'))

        if account_type == self.GOOGLE_ACCOUNT:
            email = (cleaned_data.get('google_email') or '').strip().casefold()
            if not email:
                self.add_error('google_email', _('Enter the Google account email.'))
                return cleaned_data

            duplicate = User.objects.filter(
                Q(username__iexact=email) | Q(email__iexact=email)
            )
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    'google_email',
                    _('A user with this username or email already exists.'),
                )

            cleaned_data['username'] = email
            cleaned_data['google_email'] = email
            self.instance.username = email
            self.instance.email = email
            return cleaned_data

        username = (cleaned_data.get('username') or '').strip()
        if not username:
            self.add_error('username', _('Enter a username.'))

        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if not password1:
            self.add_error('password1', _('Enter a password.'))
        elif password1 != password2:
            self.add_error('password2', _('The two password fields did not match.'))
        else:
            self.instance.username = username
            try:
                password_validation.validate_password(password1, self.instance)
            except ValidationError as error:
                self.add_error('password1', error)

        cleaned_data['username'] = username
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data['account_type'] == self.GOOGLE_ACCOUNT:
            user.username = self.cleaned_data['google_email']
            user.email = self.cleaned_data['google_email']
            user.set_unusable_password()
        else:
            user.username = self.cleaned_data['username']
            user.set_password(self.cleaned_data['password1'])

        if commit:
            user.save()
            user.profile.type = self.cleaned_data['profile_type']
            user.profile.museum = self.cleaned_data.get('museum') if user.profile.type == 'c' else None
            user.profile.save()
        return user


class UserProfileAdminForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['type', 'museum']

    def clean(self):
        data = super().clean()
        if data.get('type') == 'c' and not data.get('museum'):
            self.add_error('museum', _('Select a museum for this curator.'))
        elif data.get('type') != 'c':
            data['museum'] = None
        return data
