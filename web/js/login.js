import { authApi } from './api.js';

const els = {
  form: document.getElementById('authForm'),
  subtitle: document.getElementById('authSubtitle'),
  username: document.getElementById('usernameInput'),
  password: document.getElementById('passwordInput'),
  displayName: document.getElementById('displayNameInput'),
  displayNameField: document.getElementById('displayNameField'),
  confirmPassword: document.getElementById('confirmPasswordInput'),
  confirmPasswordField: document.getElementById('confirmPasswordField'),
  options: document.getElementById('usernameOptions'),
  error: document.getElementById('authError'),
  submit: document.getElementById('authSubmitBtn'),
};

let bootstrapMode = false;

const setError = (message = '') => {
  els.error.textContent = message;
};

const fillUsernames = async () => {
  try {
    const data = await authApi.usernames();
    els.options.innerHTML = '';
    (data.usernames || []).forEach((username) => {
      const option = document.createElement('option');
      option.value = username;
      els.options.appendChild(option);
    });
  } catch {
    els.options.innerHTML = '';
  }
};

const configureMode = async () => {
  const status = await authApi.bootstrapStatus();
  bootstrapMode = !status.admin_exists;
  if (bootstrapMode) {
    els.subtitle.textContent = '首次使用需要初始化管理员账号';
    els.submit.textContent = '创建管理员';
    els.displayNameField.hidden = false;
    els.confirmPasswordField.hidden = false;
    els.password.setAttribute('autocomplete', 'new-password');
    return;
  }
  els.subtitle.textContent = '登录后继续使用工作台';
  els.submit.textContent = '登录';
  els.displayNameField.hidden = true;
  els.confirmPasswordField.hidden = true;
  await fillUsernames();
};

els.form.addEventListener('submit', async (event) => {
  event.preventDefault();
  setError();
  const username = els.username.value.trim();
  const password = els.password.value;
  if (!username || !password) {
    setError('请输入用户名和密码');
    return;
  }
  if (bootstrapMode && password !== els.confirmPassword.value) {
    setError('两次输入的密码不一致');
    return;
  }
  els.submit.disabled = true;
  try {
    if (bootstrapMode) {
      await authApi.bootstrapAdmin({
        username,
        password,
        display_name: els.displayName.value.trim() || username,
      });
    } else {
      await authApi.login({ username, password });
    }
    window.location.href = '/';
  } catch (error) {
    const code = error.data?.error || '';
    setError({
      invalid_credentials: '用户名或密码错误',
      weak_password: '密码至少需要 6 位',
      invalid_username: '用户名需要 2-40 位且不能包含空格',
      username_exists: '用户名已存在',
      admin_already_exists: '管理员已存在，请直接登录',
    }[code] || error.message || '请求失败');
  } finally {
    els.submit.disabled = false;
  }
});

configureMode().catch(() => {
  setError('无法读取登录状态');
});
