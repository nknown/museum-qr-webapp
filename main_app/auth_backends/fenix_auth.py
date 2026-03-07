from social_core.backends.oauth import BaseOAuth2

class fenixOAuth2(BaseOAuth2):
    """GitHub OAuth authentication backend"""
    name = 'fenix-auth'
    AUTHORIZATION_URL = 'https://fenix.tecnico.ulisboa.pt/oauth/userdialog'
    ACCESS_TOKEN_URL = 'https://fenix.tecnico.ulisboa.pt/oauth/access_token'
    ACCESS_TOKEN_METHOD = 'POST'
    SCOPE_SEPARATOR = ','
    EXTRA_DATA = [
#    ('id', 'id'),
    ('expires', 'expires'),
        ('refresh_token', 'refresh_token', True),
        ('expires_in', 'expires'),
        ('token_type', 'token_type', True)

    ]
    SOCIAL_AUTH_FENIX_AUTH_STATE_PARAMETER = True
    REDIRECT_STATE = False
    
    def get_user_details(self, response):
        """Return user details from GitHub account"""
        return {
             'id': response.get('username'),
             'username': response.get('username'),
             'email': response.get('institutionalEmail') ,
             'first_name': response.get('displayName')}
    
    def user_data(self, access_token, *args, **kwargs):
        """Loads user data from service"""
        url = 'https://fenix.tecnico.ulisboa.pt/api/fenix/v1/person'
        #        url = 'https://api.github.com/user?' + urlencode({
        #        'access_token': access_token
        #        })
        
        response = self.get_json( 'https://fenix.tecnico.ulisboa.pt/api/fenix/v1/person',
        params={'access_token': access_token}
        )
        self.process_error(response)
        return response


    def get_user_id(self, details, response):
        return  response.get('username')