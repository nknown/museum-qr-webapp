from django.contrib.auth import logout as auth_logout
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.conf import settings
from pydoc import locate

class LoginView(auth_views.LoginView):
    template_name = 'main_app/layout/login.html'

    def get(self, request, *args, **kwargs):
        # Social-auth does not submit this view's form, so preserve the
        # anonymous presentation session as soon as the login page opens.
        if request.session.session_key:
            request.session['presentation_pre_login_session_key'] = (
                request.session.session_key
            )
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        # Preserve the pre-login session key so anonymous PresentationSession rows
        # created before authentication can be linked after Django rotates the key.
        if self.request.session.session_key:
            self.request.session['presentation_pre_login_session_key'] = self.request.session.session_key
        return super().form_valid(form)

        
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
    def post(self, request, *args, **kwargs):
        auth_logout(request)
        request.session['auth_notyf'] = {
            'type': 'success',
            'message': 'Logged out successfully.',
        }
        return HttpResponseRedirect(self.get_success_url())
