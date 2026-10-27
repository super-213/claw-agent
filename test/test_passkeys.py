import hashlib
import json
import secrets
import struct
import pytest
import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from services.passkeys import PasskeyService, Verify, encode, decode
from services.task_store import TaskError
from services.user_store import UserStore


@pytest.fixture
def keys(tmp_path):
    users = UserStore(tmp_path / 'users.json')
    user = users.create_user(username='alice', password='secret123', role='admin')
    service = PasskeyService(tmp_path / 'passkeys.json', 'example.com', 'https://example.com', enabled=True)
    key = ec.generate_private_key(ec.SECP256R1())
    identity = secrets.token_bytes(32)
    return service, users, user, key, identity


def client_data(kind, options, origin='https://example.com'):
    return json.dumps({'type': 'webauthn.' + kind, 'challenge': options['options']['challenge'], 'origin': origin}).encode()


def register(keys):
    service, users, user, key, identity = keys
    options = service.options('register', user, 'browser')
    numbers = key.public_key().public_numbers()
    cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})
    auth = hashlib.sha256(b'example.com').digest() + b'\x45' + struct.pack('>I', 0) + bytes(16) + struct.pack('>H', len(identity)) + identity + cose
    credential = {'id': encode(identity), 'rawId': encode(identity), 'type': 'public-key', 'response': {
        'clientDataJSON': encode(client_data('create', options)),
        'attestationObject': encode(cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth}))}}
    response = Verify(challenge_id=options['challenge_id'], credential=credential)
    assert service.verify('register', response, 'browser', users, user)['id'] == user['id']
    return response


def assertion(keys, *, origin='https://example.com', rp='example.com', counter=1, flags=b'\x05'):
    service, users, user, key, identity = keys
    options = service.options('login', user, 'browser')
    client = client_data('get', options, origin)
    auth = hashlib.sha256(rp.encode()).digest() + flags + struct.pack('>I', counter)
    signature = key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return Verify(challenge_id=options['challenge_id'], credential={'id': encode(identity), 'rawId': encode(identity), 'type': 'public-key',
        'response': {'clientDataJSON': encode(client), 'authenticatorData': encode(auth), 'signature': encode(signature),
                     'userHandle': encode(user['id'].encode())}})


def test_real_registration_login_replay_and_counter(keys):
    service, users, user, *_ = keys
    response = register(keys)
    with pytest.raises(TaskError, match='invalid_passkey_challenge'):
        service.verify('register', response, 'browser', users, user)
    response = assertion(keys)
    assert service.verify('login', response, 'browser', users)['id'] == user['id']
    with pytest.raises(TaskError, match='invalid_passkey_challenge'):
        service.verify('login', response, 'browser', users)
    with pytest.raises(TaskError, match='invalid_passkey_response'):
        service.verify('login', assertion(keys, counter=1), 'browser', users)
    assert service.verify('login', assertion(keys, counter=2), 'browser', users)


@pytest.mark.parametrize('kwargs', [{'origin': 'https://evil.invalid'}, {'rp': 'evil.invalid'}, {'flags': b'\x01'}])
def test_reject_origin_rp_and_missing_verification(keys, kwargs):
    service, users, *_ = keys
    register(keys)
    with pytest.raises(TaskError, match='invalid_passkey_response'):
        service.verify('login', assertion(keys, **kwargs), 'browser', users)


def test_binding_expiry_disabled_user_and_recovery(keys):
    service, users, user, *_ = keys
    register(keys)
    with pytest.raises(TaskError, match='invalid_passkey_challenge'):
        service.verify('login', assertion(keys), 'other-browser', users)
    response = assertion(keys)
    service.clock = lambda: 10**12
    with pytest.raises(TaskError, match='invalid_passkey_challenge'):
        service.verify('login', response, 'browser', users)
    service.revoke_user(user['id'])
    assert not service.store.snapshot()['credentials']
    assert users.verify_password('alice', 'secret123')  # Password fallback survives device loss.
    service.enabled = False
    with pytest.raises(TaskError, match='passkeys_disabled'):
        service.options('login', user, 'browser')


def test_reject_untrusted_configuration(tmp_path):
    with pytest.raises(ValueError):
        PasskeyService(tmp_path / 'p.json', 'example.com', 'http://example.com', enabled=True)
