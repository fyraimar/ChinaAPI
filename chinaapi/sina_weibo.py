# coding=utf-8
import base64
import hashlib
import hmac
from chinaapi.utils.models import Token
from .utils.api import Client, Method, Parser, OAuth2
from .utils.exceptions import ApiError, ApiResponseError
from .utils import jsonDict
from furl import furl


class EmptyRedirectUriError(ApiError):
    def __init__(self, url):
        super(EmptyRedirectUriError, self).__init__(url, 21305, 'Parameter absent: redirect_uri', 'OAuth2 request')


class ApiParser(Parser):
    def parse(self, response):
        r = super(ApiParser, self).parse(response)
        if 'error_code' in r:
            raise ApiResponseError(response, r.error_code, r.get('error', ''))
        return r


class ApiClient(Client):
    #写入接口
    _post_methods = ['create', 'add', 'destroy', 'update', 'upload', 'repost', 'reply', 'send', 'post', 'invite',
                     'shield', 'order']
    #含下划线的写入接口，如：statuses/upload_url_text
    _underlined_post_methods = ['add', 'upload', 'destroy', 'update', 'set', 'cancel', 'not']

    def __init__(self, app):
        super(ApiClient, self).__init__(app, ApiParser())

    def _prepare_url(self, segments, queries):
        if 'pic' in queries:
            prefix = 'upload.'
        elif 'remind' in segments:
            prefix = 'rm.'
        else:
            prefix = ''
        return 'https://{0}api.weibo.com/2/{1}.json'.format(prefix, '/'.join(segments))

    def _prepare_method(self, segments):
        segment = segments[-1].lower()
        if segment in self._post_methods or segment.split('_')[0] in self._underlined_post_methods:
            return Method.POST
        return Method.GET

    def _prepare_queries(self, queries):
        if self.token.is_expires:
            queries['source'] = self.app.key  # 对于不需要授权的API操作需追加source参数
        else:
            self._session.headers['Authorization'] = 'OAuth2 %s' % self.token.access_token

    def _prepare_body(self, queries):
        files = self._isolated_files(queries, ['pic', 'image'])
        return queries, files


class ApiOAuth2(OAuth2):
    def __init__(self, app):
        super(ApiOAuth2, self).__init__(app, 'https://api.weibo.com/oauth2/')

    def authorize(self, **kwargs):
        if 'response_type' not in kwargs:
            kwargs['response_type'] = 'code'
        if 'redirect_uri' not in kwargs:
            kwargs['redirect_uri'] = self.app.redirect_uri
        kwargs['client_id'] = self.app.key
        url = furl(self.url).join('authorize').set(args=kwargs).url
        if not kwargs['redirect_uri']:
            raise EmptyRedirectUriError(url)
        return url

    def access_token(self, code, **kwargs):
        if 'redirect_uri' not in kwargs:
            kwargs['redirect_uri'] = self.app.redirect_uri
        kwargs.update(client_id=self.app.key, client_secret=self.app.secret, grant_type='authorization_code', code=code)
        url = self.url + 'access_token'
        if not kwargs['redirect_uri']:
            raise EmptyRedirectUriError(url)
        response = self.session.post(url, data=kwargs)
        return ApiParser().parse(response)

    def revoke(self, access_token):
        response = self.session.get(self.url + 'revokeoauth2', params={'access_token': access_token})
        return ApiParser().parse(response).result

    def parse_signed_request(self, signed_request):
        """  用于站内应用
        Returns:
            uid, Token
        """

        def base64decode(s):
            appendix = '=' * (4 - len(s) % 4)
            return base64.b64decode(s.replace('-', '+').replace('_', '/') + appendix)

        sr = str(signed_request)
        encoded_sig, payload = sr.split('.', 1)
        sig = base64decode(encoded_sig)
        data = jsonDict.loads(base64decode(payload))
        if data['algorithm'] != u'HMAC-SHA256':
            return None
        expected_sig = hmac.new(self.app.key, payload, hashlib.sha256).digest()
        if expected_sig == sig:
            token = Token(data.get('oauth_token', None))
            token.set_expires_in(data.get('expires', None))
            token.created_at = data.get('issued_at', None)
            uid = data.get('user_id', None)
            return uid, token
        return None
