"""Test the inbound email handlers."""

import email
import email.message

from google.appengine.api import mail
from google.appengine.ext import testbed

import pytest

import main

TRIVIAL = '''Received: from mail-router.example.net
               (mail-router.example.net [192.0.2.1])
          by server.example.com (8.11.6/8.11.6)
              with ESMTP id g1G0r1kA003489;
          Fri, Feb 15 2002 17:19:07 -0800
From: sender@example.net
Date: Fri, Feb 15 2002 16:54:30 -0800
To: receiver@example.com
Message-Id: <12345.abc@example.net>
Subject: here's a sample

Hello!  Goodbye!'''
"""String trivial case; Authentication-Results header field not present."""

NEARLY_TRIVIAL = 'Authentication-Results: example.org 1; none\n' + TRIVIAL
"""String Authentication-Results header present but no authentication done."""

AUTHENTICATION_DONE = '''Authentication-Results: mx.google.com;
          spf=pass smtp.mailfrom=example.net
Received: from dialup-1-2-3-4.example.net
              (dialup-1-2-3-4.example.net [192.0.2.200])
          by mail-router.example.com (8.11.6/8.11.6)
              with ESMTP id g1G0r1kA003489;
          Fri, Feb 15 2002 17:19:07 -0800
From: sender@example.net
Date: Fri, Feb 15 2002 16:54:30 -0800
To: receiver@example.com
Message-Id: <12345.abc@example.net>
Subject: here's a sample

Hello!  Goodbye!'''
"""String Authentication-Results header reporting results."""

MULTIPLE = '''Authentication-Results: mx.google.com;
          auth=pass (cram-md5) smtp.auth=sender@example.net;
          spf=pass smtp.mailfrom=example.net
Authentication-Results: mx.google.com;
          sender-id=pass header.from=example.net
Received: from dialup-1-2-3-4.example.net (8.11.6/8.11.6)
              (dialup-1-2-3-4.example.net [192.0.2.200])
          by mail-router.example.com (8.11.6/8.11.6)
              with ESMTPA id g1G0r1kA003489;
          Fri, Feb 15 2002 17:19:07 -0800
Date: Fri, Feb 15 2002 16:54:30 -0800
To: receiver@example.com
From: sender@example.net
Message-Id: <12345.abc@example.net>
Subject: here's a sample

Hello!  Goodbye!'''
"""String multiple Authentication-Results headers reporting results."""

DIFFERENT = '''Authentication-Results: example.com;
          sender-id=fail header.from=example.com;
          dkim=pass (good signature) header.d=example.com
Received: from mail-router.example.com
              (mail-router.example.com [192.0.2.1])
          by auth-checker.example.com (8.11.6/8.11.6)
              with ESMTP id i7PK0sH7021929;
          Fri, Feb 15 2002 17:19:22 -0800
DKIM-Signature:  v=1; a=rsa-sha256; s=gatsby; d=example.com;
          t=1188964191; c=simple/simple; h=From:Date:To:Subject:
          Message-Id:Authentication-Results;
          bh=sEuZGD/pSr7ANysbY3jtdaQ3Xv9xPQtS0m70;
          b=EToRSuvUfQVP3Bkz ... rTB0t0gYnBVCM=
Authentication-Results: mx.google.com;
          auth=pass (cram-md5) smtp.auth=sender@example.com;
          spf=fail smtp.mailfrom=example.com
Received: from dialup-1-2-3-4.example.net
              (dialup-1-2-3-4.example.net [192.0.2.200])
          by mail-router.example.com (8.11.6/8.11.6)
              with ESMTPA id g1G0r1kA003489;
          Fri, Feb 15 2002 17:19:07 -0800
From: sender@example.net
Date: Fri, Feb 15 2002 16:54:30 -0800
To: receiver@example.com
Message-Id: <12345.abc@example.net>
Subject: here's a sample

Hello!  Goodbye!'''
"""String multiple Authentication-Results headers from different domains."""

COMMENT_HEAVY = '''Authentication-Results: mx.google.com (foobar) 1 (baz);
           dkim (Because I like it) / 1 (One yay) = (wait for it) pass
             policy (A dot can go here) . (like that) expired
             (this surprised me) = (as I wasn't expecting it) 1362471462
Received: from dialup-1-2-3-4.example.net
              (dialup-1-2-3-4.example.net [192.0.2.200])
          by mail-router.example.com (8.11.6/8.11.6)
              with ESMTP id g1G0r1kA003489;
          Fri, Feb 15 2002 17:19:07 -0800
From: sender@example.net
Date: Fri, Feb 15 2002 16:54:30 -0800
To: receiver@example.com
Message-Id: <12345.abc@example.net>
Subject: here's a sample

Hello!  Goodbye!'''
"""String Authentication-Results header that is very comment heavy."""

ALL_EMAILS = [TRIVIAL, NEARLY_TRIVIAL, AUTHENTICATION_DONE,
              MULTIPLE, DIFFERENT, COMMENT_HEAVY]
"""List of string Authentication-Results test emails."""

@pytest.fixture
def client():
    app = main.app
    app.config.update({'TESTING': True})

    return app.test_client()

@pytest.fixture
def stub():
    tb = testbed.Testbed()
    tb.activate()

    tb.init_mail_stub()

    yield tb

    tb.deactivate()

def test_constants():
    """Test the constants."""
    assert main._AUTHENTICATION_HEADER_NAME == 'Authentication-Results'
    assert 'pass' in main._DEFAULT_ACCEPT
    assert main._MAIL_DOMAIN == \
           '@' + main._APP_NAME.lower() + '.appspotmail.com'
    assert main._ROUTE_PREFIX == '/_ah/mail'

def test_get_mail_headers():
    """Test getting a list of mail headers."""
    for value in [None, 42, '', []]:
        for header in ['Date', 'Message-Id',
                       main._AUTHENTICATION_HEADER_NAME]:
            assert main.get_mail_headers(value, header) == []

    expected = [[], ['example.org 1; none'], ['''mx.google.com;
          spf=pass smtp.mailfrom=example.net'''], ['''mx.google.com;
          auth=pass (cram-md5) smtp.auth=sender@example.net;
          spf=pass smtp.mailfrom=example.net''', '''mx.google.com;
          sender-id=pass header.from=example.net'''], ['''example.com;
          sender-id=fail header.from=example.com;
          dkim=pass (good signature) header.d=example.com''', '''mx.google.com;
          auth=pass (cram-md5) smtp.auth=sender@example.com;
          spf=fail smtp.mailfrom=example.com'''],
                    ['''mx.google.com (foobar) 1 (baz);
           dkim (Because I like it) / 1 (One yay) = (wait for it) pass
             policy (A dot can go here) . (like that) expired
             (this surprised me) = (as I wasn't expecting it) 1362471462''']]
    for text, auth_headers in zip(ALL_EMAILS, expected):
        for mail_message in [mail.InboundEmailMessage(text),
                             email.message_from_string(text)]:
            for value in [None, 42, '', []]:
                assert main.get_mail_headers(mail_message, value) == []
            assert main.get_mail_headers(mail_message, 'Date') == [
                'Fri, Feb 15 2002 16:54:30 -0800']
            assert main.get_mail_headers(mail_message, 'Message-Id') == [
                '<12345.abc@example.net>']
            assert main.get_mail_headers(
                mail_message, main._AUTHENTICATION_HEADER_NAME) == auth_headers

def test_remove_comments():
    """Test removing comments from header values."""
    for value in [None, 42, []]:
        pytest.raises(TypeError, main.remove_comments, value)

    expected = ''
    for value in [expected,
                  '(all comments)',
                  ' (all comments)',
                  '(all comments) ',
                  ' (all comments) ']:
        assert main.remove_comments(value) == expected

    expected = 'foo.example.net'
    for value in [expected,
                  'foo.example.net ',
                  'foo.example.net (foobar)',
                  'foo.example.net (foobar) 1 (baz)',
                  ' foo.example.net',
                  ' foo.example.net ',
                  ' foo.example.net (foobar)',
                  ' foo.example.net (foobar) 1 (baz)',
                  '(example) foo.example.net',
                  '(example) foo.example.net ',
                  '(example) foo.example.net (foobar)',
                  '(example) foo.example.net (foobar) 1 (baz)']:
        assert main.remove_comments(value) == expected

    expected = 'dkim'
    for value in [expected,
                  'dkim ',
                  'dkim (Because I like it)',
                  'dkim (Because I like it) / 1',
                  ' dkim',
                  ' dkim ',
                  ' dkim (Because I like it)',
                  ' dkim (Because I like it) / 1',
                  '(example) dkim',
                  '(example) dkim ',
                  '(example) dkim (Because I like it)',
                  '(example) dkim (Because I like it) / 1',
                  '(Because I like it) dkim / (One yay) 1',
                  '(Because I like it) dkim / 1 (One yay)']:
        assert main.remove_comments(value) == expected

    expected = 'fail'
    for value in [expected,
                  'fail ',
                  'fail (legendary)',
                  ' fail',
                  ' fail ',
                  ' fail (legendary)',
                  '(wait for it) fail',
                  '(wait for it) fail ',
                  '(wait for it) fail (legendary)']:
        assert main.remove_comments(value) == expected

def test_verify_headers():
    """Test verifying Authentication-Results headers."""
    methods = ['auth', 'spf', 'dkim']
    for value in ['', []]:
        for method in methods:
            assert main.verify_headers(value, method) == False

    for headers in [['example.org 1; none'], ['mx.google.com; none']]:
        for method in [None, 42, '', [], 'fo\u00f6b\u00e4r'] + methods:
            assert main.verify_headers(headers, method) == False
            for value in [None, 42, '', [], 'example.org',
                          'mx.google.com', 'gmr-mx.google.com']:
                assert main.verify_headers(
                    headers, method, authserv_domain=value) == False

    headers = ['example.com; spf=pass smtp.mailfrom=example.net']
    for method in [None, 42, '', [], 'fo\u00f6b\u00e4r']:
        assert main.verify_headers(headers, method) == False
    for method in methods:
        assert main.verify_headers(headers, method) == False
        for value in [None, 42, [], 'example.org']:
            assert main.verify_headers(
                headers, method, authserv_domain=value) == False
            if method == 'spf':
                # An empty string authserv_domain matches "example.com"
                assert main.verify_headers(
                    headers, method, authserv_domain='') == True
                assert main.verify_headers(
                    headers, method, authserv_domain='example.com') == True
            else:
                assert main.verify_headers(
                    headers, method, authserv_domain='') == False
                assert main.verify_headers(
                    headers, method, authserv_domain='example.com') == False

    # Test the default Google DNS domain name
    for headers in [['gmr-mx.google.com; auth=pass (cram-md5) \
smtp.auth=sender@example.net; spf=pass smtp.mailfrom=example.net'],
                    ['mx.google.com; auth=pass (cram-md5) \
smtp.auth=sender@example.net; spf=pass smtp.mailfrom=example.net',
                     'mx.google.com; sender-id=pass \
header.from=example.net']]:
        for method in methods:
            if method == 'dkim':
                assert main.verify_headers(headers, method) == False
            else:
                assert main.verify_headers(headers, method) == True
                assert main.verify_headers(
                    headers, method, authserv_domain='example.com') == False
                assert main.verify_headers(
                    headers, method, authserv_domain='mx.google.com') == True

    # Test the accepted results
    header_template = 'mx.google.com; spf={0} smtp.mailfrom=example.net'
    for result in ['none', 'neutral', 'policy', 'fail']:
        headers = [header_template.format(result)]
        assert main.verify_headers(headers, 'spf') == False
        assert main.verify_headers(headers, 'spf', []) == False
        assert main.verify_headers(headers, 'spf', ['pass']) == False
        assert main.verify_headers(headers, 'spf', [result]) == True
        assert main.verify_headers(headers, 'spf', ('pass', result)) == True
        assert main.verify_headers(
            headers, 'spf', [result, 'temperror']) == True

def test_get_first_body():
    """Test getting the first body from a mail.InboundEmailMessage."""
    for value in [None, 42, '', [], 'foobar', TRIVIAL]:
        assert main.get_first_body(value) == ''
        assert main.get_first_body(NEARLY_TRIVIAL, value) == ''

def test_echo_message():
    """Test creating a mail.InboundEmailMessage from text."""
    for value in [None, 42, '', []]:
        main.echo_message(value)

    for text in ALL_EMAILS:
        mail_message = mail.InboundEmailMessage(text)
        assert mail_message.date == \
               'Fri, Feb 15 2002 16:54:30 -0800'
        assert mail_message.sender == 'sender@example.net'
        assert mail_message.to == 'receiver@example.com'
        assert mail_message.subject == "here's a sample"
        assert main.get_first_body(mail_message) == 'Hello!  Goodbye!'
        assert main.get_first_body(mail_message, 'text/plain') == \
               'Hello!  Goodbye!'
        assert main.get_first_body(mail_message, 'text/html') == ''
        assert isinstance(mail_message.original, email.message.Message)
        main.echo_message(mail_message)
        main.echo_message(mail_message, False)
        main.echo_message(mail_message, True)

def test_catchall(client, stub):
    """Test the catchall route."""
    for name in ['foo', 'foo@bar', 'foo bar baz', 'Barbaz', 'random', 'admin']:
        url = main._ROUTE_PREFIX + '/' + name + main._MAIL_DOMAIN
        assert client.get(url).status_code == 405

        mail_stub = stub.get_stub(testbed.MAIL_SERVICE_NAME)
        messages = mail_stub.get_sent_messages(body='Hello!  Goodbye!')
        assert len(messages) == 0
        for text in ALL_EMAILS:
            assert client.post(url, data=text).status_code == 200
            messages = mail_stub.get_sent_messages(body='Hello!  Goodbye!')
            assert len(messages) == 0

def test_support(client, stub):
    """Test the support route."""
    url = main._ROUTE_PREFIX + '/support' + main._MAIL_DOMAIN
    assert client.get(url).status_code == 405

    mail_stub = stub.get_stub(testbed.MAIL_SERVICE_NAME)
    messages = mail_stub.get_sent_messages(body='Hello!  Goodbye!')
    assert len(messages) == 0
    for expected, text in enumerate(ALL_EMAILS, 1):
        assert client.post(url, data=text).status_code == 200
        messages = mail_stub.get_sent_messages(body='Hello!  Goodbye!')
        assert len(messages) == expected
