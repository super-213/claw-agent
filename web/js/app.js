import {
  closeConfigModal,
  loadConfig,
  openConfigModal,
  submitConfig,
} from './config.js';
import { els, fitMessageInput, isMobileLayout, setMobileSidebar } from './dom.js';
import {
  createSession,
  loadSessions,
  renderSessions,
  sendMessage,
} from './sessions.js';
import {
  closeSkillModal,
  loadSkills,
  openSkillModal,
  reloadSkills,
  submitSkill,
} from './skills.js';
import { state } from './state.js';

els.messageInput.addEventListener('input', fitMessageInput);
els.messageInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

els.sendBtn.addEventListener('click', sendMessage);
els.newSessionBtn.addEventListener('click', createSession);

els.configBtn.addEventListener('click', openConfigModal);
els.configForm.addEventListener('submit', submitConfig);
els.configModalClose.addEventListener('click', closeConfigModal);
els.configCancelBtn.addEventListener('click', closeConfigModal);
els.configModal.addEventListener('click', (event) => {
  if (event.target === els.configModal) closeConfigModal();
});

els.addSkillBtn.addEventListener('click', openSkillModal);
els.reloadSkillsBtn.addEventListener('click', reloadSkills);
els.skillForm.addEventListener('submit', submitSkill);
els.skillModalClose.addEventListener('click', closeSkillModal);
els.skillCancelBtn.addEventListener('click', closeSkillModal);
els.skillModal.addEventListener('click', (event) => {
  if (event.target === els.skillModal) closeSkillModal();
});

els.mobileMenuBtn.addEventListener('click', () => {
  setMobileSidebar(!els.sidebar.classList.contains('open'));
});
els.mobileSidebarClose.addEventListener('click', () => setMobileSidebar(false));
els.sidebarBackdrop.addEventListener('click', () => setMobileSidebar(false));

document.addEventListener('click', () => {
  if (!state.openMenuSessionId) return;
  state.openMenuSessionId = null;
  renderSessions();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (els.configModal.classList.contains('open')) closeConfigModal();
  if (els.skillModal.classList.contains('open')) closeSkillModal();
  if (els.sidebar.classList.contains('open')) setMobileSidebar(false);
  if (state.openMenuSessionId) {
    state.openMenuSessionId = null;
    renderSessions();
  }
});

window.addEventListener('resize', () => {
  if (!isMobileLayout()) setMobileSidebar(false);
});

window.addEventListener('load', async () => {
  await loadConfig();
  await loadSkills();
  await loadSessions();
  if (!state.currentSessionId) await createSession();
});
