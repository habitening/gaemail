"""Forward support emails to the administrators."""

import cgi
import datetime
import email.message
from functools import wraps
import logging
import os
import urllib.parse

from google.appengine.api import mail
from google.appengine.api import wrap_wsgi_app
from google.appengine.runtime import apiproxy_errors

import flask

_APP_NAME = os.environ.get('GOOGLE_CLOUD_PROJECT', 'testbed-test')
"""String name of the application."""

_AUTHENTICATION_HEADER_NAME = 'Authentication-Results'
"""String name of the Authentication-Results header."""

_DEFAULT_ACCEPT = ('pass',)
"""Tuple of string default authentication result values to accept."""

_MAIL_DOMAIN = '@{app_id}.appspotmail.com'.format(
    app_id=_APP_NAME.lower())
"""String domain of the email addresses for this application."""

_ROUTE_PREFIX = mail.INCOMING_MAIL_URL_PATTERN[
    :mail.INCOMING_MAIL_URL_PATTERN.rfind('/')]
"""String URL prefix for the inbound email routes."""

def get_mail_headers(mail_message, header_name=_AUTHENTICATION_HEADER_NAME):
    """Return a list of all the values for header_name from mail_message.

    This is essentially a wrapper around get_all() with the proper
    dereferencing beforehand.

    Args:
        mail_message: mail.InboundEmailMessage or email.message.Message object
            to the received email.
        header_name: String name of the header to return.
            Defaults to _AUTHENTICATION_HEADER_NAME.
    Returns:
        List of all the values for header_name from mail_message.
    """
    if isinstance(mail_message, mail.InboundEmailMessage):
        mail_message = mail_message.original
    if not isinstance(mail_message, email.message.Message):
        return []
    if not isinstance(header_name, str):
        return []
    return mail_message.get_all(header_name, [])

def remove_comments(content):
    """Return the first portion of content that is not a comment.

    A comment is whitespace or text in parentheses.

    Args:
        content: String header value whose comments to ignore.
    Returns:
        String first portion of content that is not a comment.
    """
    if not isinstance(content, str):
        raise TypeError('content must be a string.')
    length = len(content)
    if length <= 0:
        return ''

    # Iterate past the comments preceding the actual content
    i = 0
    nesting_count = 0
    while i < length:
        if content[i] == '(':
            nesting_count += 1
        elif content[i] == ')':
            nesting_count -= 1
        elif (not content[i].isspace()) and (nesting_count <= 0):
            break
        i += 1
    start_index = i

    # Iterate to the comment following the actual content
    i = start_index
    while (i < length) and (not content[i].isspace()) and (content[i] != '('):
        i += 1
    end_index = i

    # The actual content is sandwiched between the 2 comments
    return content[start_index:end_index]

def verify_headers(headers, method, accepted=_DEFAULT_ACCEPT,
                   authserv_domain='mx.google.com'):
    """Return whether method had an accepted result in Authentication-Results.

    This function follows the Authentication-Results header specified in
    RFC 7601 (http://tools.ietf.org/html/rfc7601).

    We have to parse the headers ourselves because the helper methods in the
    email package do not handle multiple headers.

    Args:
        headers: List of string Authentication-Results header values.
        method: String authentication method to check such as "spf" or "dkim".
        accepted: Optional iterable of string accepted result values.
            Consult the RFC for the result values of each method.
            Defaults to _DEFAULT_ACCEPT.
        authserv_domain: Optional string DNS domain name of the authentication
            service identifier. Defaults to "mx.google.com"
            which matches both "gmr-mx.google.com" and "mx.google.com",
            the 2 authentication services encountered by appspotmail.com.
    Returns:
        True if the authentication method had one of the results in accepted.
        False otherwise.
    """
    if len(headers) <= 0:
        return False
    if not isinstance(method, str):
        return False
    if len(method) <= 0:
        return False
    method = method.lower()
    accepted_set = frozenset(
        result.lower() for result in accepted
        if isinstance(result, str) and (len(result) > 0))
    if len(accepted_set) <= 0:
        return False
    if not isinstance(authserv_domain, str):
        return False
    authserv_domain = authserv_domain.lower()

    for header in headers:
        if not isinstance(header, str):
            continue
        authserv_id, result_info = cgi.parse_header(header)
        if not isinstance(authserv_id, str):
            continue
        authserv_id = remove_comments(authserv_id).lower()
        if authserv_id.endswith(authserv_domain):
            # Use authentication service identifier field to determine whether
            # the contents are of interest (and are safe to use)
            for auth_method, auth_result in result_info.items():
                if (isinstance(auth_method, str) and
                    isinstance(auth_result, str)):
                    clean_method = remove_comments(auth_method).lower()
                    if clean_method == method:
                        clean_result = remove_comments(auth_result).lower()
                        if clean_result in accepted_set:
                            return True
    return False

def get_first_body(mail_message, content_type='text/plain'):
    """Return the first body of type content_type in mail_message or "".

    Args:
        mail_message: mail.InboundEmailMessage object to the received email.
        content_type: Optional string content type to filter on.
            Defaults to "text/plain".
    Returns:
        String first body of type content_type in mail_message or
        the empty string.
    """
    if isinstance(mail_message, mail.InboundEmailMessage):
        for body_type, body in mail_message.bodies(content_type):
            result = body
            while not isinstance(result, str):
                result = result.decode()
            return result
    return ''

def get_email_address_for_route(name):
    """Return the corresponding email address for the route named name.

    This function helps us avoid hardcoding the email address in more than
    one place.

    Args:
        name: String name of the route.
    Returns:
        String corresponding email address for the route named name.
    """
    # The returned URI %xx escapes "@"
    uri = flask.url_for(name)
    uri = urllib.parse.unquote(uri)
    if not uri.startswith(_ROUTE_PREFIX + '/'):
        # Sanity check
        logging.error('Invalid mail handler route: ' + uri)
        raise ValueError('Invalid mail handler route: ' + uri)
    # The email address is the part after _ROUTE_PREFIX + '/'
    return uri[10:]

def echo_message(mail_message, echo_body=False):
    """Echo the received email to the log.

    Args:
        mail_message: mail.InboundEmailMessage object to the received email.
        echo_body: Optional boolean flag indicating whether to echo the body
            of the received email. Defaults to False.
    """
    if isinstance(mail_message, mail.InboundEmailMessage):
        logging.info('Date: ' + mail_message.date)
        logging.info('From: ' + mail_message.sender)
        logging.info('Subject: ' + mail_message.subject)
        if echo_body:
            logging.info('Email body:')
            logging.info(get_first_body(mail_message))


def timeit():
    """Decorator to time how long it takes to handle a request."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start = datetime.datetime.utcnow()
            f(*args, **kwargs)
            duration = datetime.datetime.utcnow() - start
            logging.info('Processed email in {0}s.'.format(
                duration.total_seconds()))
            return ''
        return decorated_function
    return decorator

@timeit()
def deflect():
    """Forward valid emails to the administrators."""
    mail_message = mail.InboundEmailMessage(flask.request.get_data())
    sender = getattr(mail_message, 'sender', '')
    subject = getattr(mail_message, 'subject', '')
    if ((not isinstance(sender, str)) or (len(sender) <= 0) or
        (not isinstance(subject, str)) or (len(subject) <= 0)):
        return

    # Only process emails with non-empty sender and subject
    origin = getattr(mail_message, 'reply_to', mail_message.sender)
    if not mail.is_email_valid(origin):
        return
    # Put the original sender under reply_to to make it easy to reply
    kwargs = {'reply_to': origin}

    # Build the email text body with authentication results
    text_body = []
    headers = get_mail_headers(mail_message)
    for method in ['spf', 'dkim']:
        if not verify_headers(headers, method):
            if len(text_body) > 0:
                text_body.append('\n')
            text_body.append('This email failed {0} authentication.\n'.format(
                method.upper()))
    if len(text_body) <= 0:
        text_body = get_first_body(mail_message, 'text/plain')
    else:
        text_body.append('\n')
        text_body.append(get_first_body(mail_message, 'text/plain'))
        text_body = ''.join(text_body)

    # Optional additional message fields
    # Simply passing mime_message does not work - mail does not detect it
    html_body = get_first_body(mail_message, 'text/html')
    if len(html_body) > 0:
        kwargs['html'] = html_body
    if hasattr(mail_message, 'attachments'):
        kwargs['attachments'] = mail_message.attachments
    try:
        mail.send_mail_to_admins(
            get_email_address_for_route('email.support'),
            mail_message.subject, text_body, **kwargs)
    except apiproxy_errors.OverQuotaError:
        logging.error('Mail API is over quota.')

@timeit()
def sink(name):
    """Log emails sent to unsupported addresses."""
    logging.warning('Email sent to unsupported address: {0}'.format(name))


blueprint = flask.Blueprint('email', __name__, url_prefix=_ROUTE_PREFIX)
"""The Flask Blueprint."""

blueprint.add_url_rule('/support' + _MAIL_DOMAIN, 'support',
                       deflect, methods=['POST'])
blueprint.add_url_rule('/<string:name>' + _MAIL_DOMAIN, 'catchall',
                       sink, methods=['POST'])

app = flask.Flask(__name__)
"""The Flask application."""

app.register_blueprint(blueprint)
app.wsgi_app = wrap_wsgi_app(app.wsgi_app)
