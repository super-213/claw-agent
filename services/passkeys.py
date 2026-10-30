"""Opt-in WebAuthn ceremonies backed by one-use, browser-bound challenges."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from services.task_store import TaskStore, TaskError


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


class Ceremony(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = ''
    password: str = ''


class Verify(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge_id: str = Field(max_length=200)
    credential: dict
    name: str = Field(default='我的通行密钥', max_length=80)


class PasskeyService:
    def __init__(self, path, rp_id='', origin='', *, enabled=False, clock=time.time):
        self.store = TaskStore(path)
        self.rp_id, self.origin, self.enabled, self.clock = rp_id, origin, enabled, clock
        if enabled:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {'https', 'http'} or parsed.path or parsed.query or parsed.fragment
                    or parsed.username or not rp_id or not parsed.hostname
                    or not (parsed.hostname == rp_id or parsed.hostname.endswith('.' + rp_id))
                    or (parsed.scheme == 'http' and parsed.hostname != 'localhost')):
                raise ValueError('invalid_passkey_origin_or_rp_id')

    def available(self):
        if not self.enabled:
            raise TaskError('passkeys_disabled', status=404)

    def options(self, kind, user, binding):
        self.available()
        from webauthn import generate_registration_options, generate_authentication_options
        from webauthn.helpers import options_to_json
        from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                               UserVerificationRequirement, PublicKeyCredentialDescriptor)
        with self.store.transaction() as doc:
            challenges = doc.setdefault('challenges', {})
            for key in list(challenges):
                if challenges[key]['expires'] <= self.clock():
                    challenges.pop(key)
            if len(challenges) >= 200 or sum(c['binding'] == binding for c in challenges.values()) >= 10:
                raise TaskError('passkey_rate_limited', status=429)
            credentials = [PublicKeyCredentialDescriptor(id=decode(row['id']))
                for row in doc.setdefault('credentials', {}).values() if row['user_id'] == user['id']]
            if kind == 'register':
                if len(credentials) >= 10:
                    raise TaskError('passkey_limit', status=409)
                options = generate_registration_options(rp_id=self.rp_id, rp_name='Home Agent',
                    user_id=user['id'].encode(), user_name=user['username'], exclude_credentials=credentials,
                    authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                        user_verification=UserVerificationRequirement.REQUIRED))
            else:
                if not credentials:
                    raise TaskError('invalid_credentials', status=401)
                options = generate_authentication_options(rp_id=self.rp_id, allow_credentials=credentials,
                    user_verification=UserVerificationRequirement.REQUIRED)
            identity = secrets.token_urlsafe(32)
            challenges[identity] = {'kind': kind, 'user_id': user['id'], 'binding': binding,
                'challenge': encode(options.challenge), 'expires': self.clock() + 300}
        return {'challenge_id': identity, 'options': json.loads(options_to_json(options))}

    def verify(self, kind, payload, binding, users, user=None):
        self.available()
        from webauthn import verify_registration_response, verify_authentication_response
        # Consume BEFORE cryptographic verification. Failed attempts also cannot replay.
        with self.store.transaction() as doc:
            challenge = doc.setdefault('challenges', {}).pop(payload.challenge_id, None)
        if (not challenge or challenge['expires'] <= self.clock() or challenge['kind'] != kind
                or not secrets.compare_digest(challenge['binding'], binding)
                or (kind == 'register' and (not user or challenge['user_id'] != user['id']))):
            raise TaskError('invalid_passkey_challenge', status=401)
        actor = users.get_user(challenge['user_id'])
        if not actor or actor['status'] != 'active':
            raise TaskError('invalid_credentials', status=401)
        kwargs = dict(credential=payload.credential, expected_challenge=decode(challenge['challenge']),
                      expected_rp_id=self.rp_id, expected_origin=self.origin, require_user_verification=True)
        try:
            with self.store.transaction() as doc:
                credentials = doc.setdefault('credentials', {})
                if kind == 'register':
                    if sum(row['user_id'] == actor['id'] for row in credentials.values()) >= 10:
                        raise TaskError('passkey_limit', status=409)
                    verified = verify_registration_response(**kwargs)
                    identity = encode(verified.credential_id)
                    if identity in credentials:
                        raise TaskError('passkey_already_registered', status=409)
                    credentials[identity] = {'id': identity, 'user_id': actor['id'], 'name': payload.name,
                        'public_key': encode(verified.credential_public_key), 'sign_count': verified.sign_count,
                        'created_at': self.clock()}
                else:
                    row = credentials.get(payload.credential.get('id'))
                    if not row or row['user_id'] != actor['id']:
                        raise TaskError('invalid_credentials', status=401)
                    handle = payload.credential.get('response', {}).get('userHandle')
                    if handle and decode(handle) != actor['id'].encode():
                        raise TaskError('invalid_credentials', status=401)
                    verified = verify_authentication_response(**kwargs,
                        credential_public_key=decode(row['public_key']), credential_current_sign_count=row['sign_count'])
                    row['sign_count'] = verified.new_sign_count
        except TaskError:
            raise
        except Exception as exc:
            raise TaskError('invalid_passkey_response', '通行密钥验证失败，请重试或使用密码登录。', status=401) from exc
        return actor

    def revoke_user(self, user_id):
        with self.store.transaction() as doc:
            doc['credentials'] = {key: row for key, row in doc.get('credentials', {}).items() if row['user_id'] != user_id}
            doc['challenges'] = {key: row for key, row in doc.get('challenges', {}).items() if row['user_id'] != user_id}


def passkey_router(service, require_user, get_users, login, cookie_name):
    router = APIRouter(prefix='/api/auth/passkeys', tags=['passkeys'])
    browser_cookie = 'claw_passkey_browser'

    def binding(request, response=None):
        value = request.cookies.get(browser_cookie)
        if not value and response is not None:
            value = secrets.token_urlsafe(32)
            response.set_cookie(browser_cookie, value, httponly=True, samesite='strict', max_age=300,
                                secure=service.origin.startswith('https://'))
        if not value:
            raise TaskError('invalid_passkey_challenge', status=401)
        return hashlib.sha256((value + ':' + (request.cookies.get(cookie_name) or '')).encode()).hexdigest()

    def password_check(user, password):
        if not get_users().verify_password(user['username'], password):
            raise TaskError('invalid_credentials', status=401)

    @router.get('/status')
    def status():
        return {'enabled': service.enabled}

    @router.get('')
    def listing(user=Depends(require_user)):
        service.available()
        rows = service.store.snapshot().get('credentials', {}).values()
        return {'credentials': [{k: row[k] for k in ('id', 'name', 'created_at')}
                                for row in rows if row['user_id'] == user['id']]}

    @router.post('/register/options')
    def register_options(payload: Ceremony, request: Request, response: Response, user=Depends(require_user)):
        service.available()
        password_check(user, payload.password)
        return service.options('register', user, binding(request, response))

    @router.post('/register/verify')
    def register_verify(payload: Verify, request: Request, user=Depends(require_user)):
        service.verify('register', payload, binding(request), get_users(), user)
        return {'ok': True}

    @router.post('/login/options')
    def login_options(payload: Ceremony, request: Request, response: Response):
        service.available()
        user = get_users().get_user_by_username(payload.username)
        if not user or user['status'] != 'active':
            raise TaskError('invalid_credentials', status=401)
        return service.options('login', user, binding(request, response))

    @router.post('/login/verify')
    def login_verify(payload: Verify, request: Request):
        user = service.verify('login', payload, binding(request), get_users())
        get_users().mark_login(user['id'])
        response = login(user, previous_token=request.cookies.get(cookie_name))
        response.delete_cookie(browser_cookie)
        return response

    @router.post('/{identity}/delete')
    def delete(identity: str, payload: Ceremony, user=Depends(require_user)):
        service.available()
        password_check(user, payload.password)
        with service.store.transaction() as doc:
            row = doc.setdefault('credentials', {}).get(identity)
            if not row or row['user_id'] != user['id']:
                raise TaskError('passkey_not_found', status=404)
            del doc['credentials'][identity]
        return {'ok': True}
    return router
