from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from django.conf import settings
from pydoc import locate

class LoginView(auth_views.LoginView):
    template_name = 'main_app/layout/login.html'

        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        auth_backends = []
        for b in settings.AUTHENTICATION_BACKENDS:
            if b == 'django.contrib.auth.backends.ModelBackend':
                continue
            try:
                my_class = locate(b)
                auth_backends.append({ 'classname':my_class.name, 'name': my_class.name.replace('-', " ").upper()})
            except:
                pass
        context['back_ends'] = auth_backends
        return context

class LogoutView(auth_views.LogoutView):
    pass
