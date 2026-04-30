import { skillsApi } from './api.js';
import { els, isMobileLayout, setMobileSidebar } from './dom.js';
import { setStatus } from './messages.js';
import { state } from './state.js';

export const openSkillModal = () => {
  els.skillForm.reset();
  els.skillFormError.textContent = '';
  els.skillModal.classList.add('open');
  els.skillModal.setAttribute('aria-hidden', 'false');
  setTimeout(() => els.skillNameInput.focus(), 0);
};

export const closeSkillModal = () => {
  els.skillModal.classList.remove('open');
  els.skillModal.setAttribute('aria-hidden', 'true');
  els.skillFormError.textContent = '';
};

export const renderSkills = () => {
  els.skillList.innerHTML = '';
  if (!state.skills.length) {
    const empty = document.createElement('div');
    empty.className = 'skill-empty';
    empty.textContent = '暂无技能';
    els.skillList.appendChild(empty);
    return;
  }

  state.skills.forEach((skill) => {
    const button = document.createElement('button');
    button.className = 'skill-item';
    button.type = 'button';
    button.title = `插入调用 ${skill.name} skill`;
    button.textContent = skill.name;
    button.addEventListener('click', () => {
      const prefix = `调用 ${skill.name} skill `;
      const current = els.messageInput.value.trimStart();
      els.messageInput.value = current ? prefix + current : prefix;
      els.messageInput.focus();
      els.messageInput.dispatchEvent(new Event('input'));
      if (isMobileLayout()) setMobileSidebar(false);
    });
    els.skillList.appendChild(button);
  });
};

export const loadSkills = async () => {
  try {
    const data = await skillsApi.list();
    state.skills = data.skills || [];
    renderSkills();
  } catch (error) {
    console.warn('loadSkills:', error);
  }
};

export const reloadSkills = async () => {
  try {
    const data = await skillsApi.reload();
    state.skills = data.skills || [];
    renderSkills();
    setStatus(`技能 ${state.skills.length}`, false);
    setTimeout(() => setStatus('就绪', false), 1200);
  } catch (error) {
    console.warn('reloadSkills:', error);
  }
};

export const submitSkill = async (event) => {
  event.preventDefault();

  const name = els.skillNameInput.value.trim();
  const content = els.skillContentInput.value.trim();
  els.skillFormError.textContent = '';
  els.skillSaveBtn.disabled = true;

  try {
    const data = await skillsApi.create({ name, content });
    closeSkillModal();
    await loadSkills();
    setStatus(`已添加 ${data.skill?.name || name}`, false);
    setTimeout(() => setStatus('就绪', false), 1200);
  } catch (error) {
    els.skillFormError.textContent = error.data?.message || '网络错误';
    console.warn('submitSkill:', error);
  } finally {
    els.skillSaveBtn.disabled = false;
  }
};
