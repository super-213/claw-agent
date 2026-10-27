import { jsonRequest } from '../../api/client';
import type { User } from '../../api/types';

const decode = (value: string): ArrayBuffer => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4)), c => c.charCodeAt(0)).buffer;
const encode = (value: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
export const passkeysSupported = () => window.isSecureContext && 'PublicKeyCredential' in window && !!navigator.credentials;
function serialize(credential: PublicKeyCredential) {
  const response = credential.response;
  return { id: credential.id, rawId: encode(credential.rawId), type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: { clientDataJSON: encode(response.clientDataJSON),
      ...('attestationObject' in response ? { attestationObject: encode((response as AuthenticatorAttestationResponse).attestationObject) } : {}),
      ...('signature' in response ? {
        authenticatorData: encode((response as AuthenticatorAssertionResponse).authenticatorData),
        signature: encode((response as AuthenticatorAssertionResponse).signature),
        userHandle: (response as AuthenticatorAssertionResponse).userHandle ? encode((response as AuthenticatorAssertionResponse).userHandle!) : null,
      } : {}),
    } };
}
interface Ceremony { challenge_id: string; options: Record<string, any> }
export const passkeyApi = {
  status: () => jsonRequest<{ enabled: boolean }>('/api/auth/passkeys/status'),
  list: () => jsonRequest<{ credentials: { id: string; name: string; created_at: number }[] }>('/api/auth/passkeys'),
  remove: (id: string, password: string) => jsonRequest(`/api/auth/passkeys/${encodeURIComponent(id)}/delete`, { method: 'POST', body: JSON.stringify({ password }) }),
  register: async (password: string, name: string) => {
    const ceremony = await jsonRequest<Ceremony>('/api/auth/passkeys/register/options', { method: 'POST', body: JSON.stringify({ password }) });
    const options = ceremony.options;
    const credential = await navigator.credentials.create({ publicKey: { ...options, challenge: decode(options.challenge),
      user: { ...options.user, id: decode(options.user.id) },
      excludeCredentials: options.excludeCredentials?.map((row: any) => ({ ...row, id: decode(row.id) })),
    } as PublicKeyCredentialCreationOptions });
    if (!credential) throw new Error('通行密钥注册已取消');
    await jsonRequest('/api/auth/passkeys/register/verify', { method: 'POST', body: JSON.stringify({
      challenge_id: ceremony.challenge_id, credential: serialize(credential as PublicKeyCredential), name,
    }) });
  },
  login: async (username: string) => {
    const ceremony = await jsonRequest<Ceremony>('/api/auth/passkeys/login/options', { method: 'POST', body: JSON.stringify({ username }) });
    const options = ceremony.options;
    const credential = await navigator.credentials.get({ publicKey: { ...options, challenge: decode(options.challenge),
      allowCredentials: options.allowCredentials?.map((row: any) => ({ ...row, id: decode(row.id) })),
    } as PublicKeyCredentialRequestOptions });
    if (!credential) throw new Error('通行密钥登录已取消');
    return jsonRequest<{ user: User }>('/api/auth/passkeys/login/verify', { method: 'POST', body: JSON.stringify({
      challenge_id: ceremony.challenge_id, credential: serialize(credential as PublicKeyCredential),
    }) });
  },
};
