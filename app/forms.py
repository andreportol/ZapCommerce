from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='Usuário ou e-mail',
        widget=forms.TextInput(
            attrs={
                'autofocus': True,
                'autocomplete': 'username',
                'placeholder': 'Digite seu usuário ou e-mail',
            }
        ),
    )

    def clean(self):
        username_or_email = (self.cleaned_data.get('username') or '').strip()
        if username_or_email and '@' in username_or_email:
            user_model = get_user_model()
            user = user_model.objects.filter(email__iexact=username_or_email).first()
            if user is not None:
                self.cleaned_data['username'] = getattr(user, user_model.USERNAME_FIELD)
        return super().clean()
