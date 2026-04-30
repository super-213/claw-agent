export const els = {
  sessionList: document.getElementById('sessionList'),
  messageList: document.getElementById('messageList'),
  chatWindow: document.getElementById('chatWindow'),
  messageInput: document.getElementById('messageInput'),
  sendBtn: document.getElementById('sendBtn'),
  newSessionBtn: document.getElementById('newSessionBtn'),
  statusText: document.getElementById('statusText'),
  statusBadge: document.getElementById('statusBadge'),
  tokenSummary: document.getElementById('tokenSummary'),
  topbarTitle: document.getElementById('topbarTitle'),
  emptyState: document.getElementById('emptyState'),
  sidebar: document.getElementById('sidebar'),
  mobileMenuBtn: document.getElementById('mobileMenuBtn'),
  mobileSidebarClose: document.getElementById('mobileSidebarClose'),
  sidebarBackdrop: document.getElementById('sidebarBackdrop'),
  skillList: document.getElementById('skillList'),
  addSkillBtn: document.getElementById('addSkillBtn'),
  reloadSkillsBtn: document.getElementById('reloadSkillsBtn'),
  configBtn: document.getElementById('configBtn'),
  configModal: document.getElementById('configModal'),
  configModalClose: document.getElementById('configModalClose'),
  configCancelBtn: document.getElementById('configCancelBtn'),
  configForm: document.getElementById('configForm'),
  configBaseUrlInput: document.getElementById('configBaseUrlInput'),
  configApiKeyInput: document.getElementById('configApiKeyInput'),
  configModelInput: document.getElementById('configModelInput'),
  configSummary: document.getElementById('configSummary'),
  configFormError: document.getElementById('configFormError'),
  configSaveBtn: document.getElementById('configSaveBtn'),
  skillModal: document.getElementById('skillModal'),
  skillModalClose: document.getElementById('skillModalClose'),
  skillCancelBtn: document.getElementById('skillCancelBtn'),
  skillForm: document.getElementById('skillForm'),
  skillNameInput: document.getElementById('skillNameInput'),
  skillContentInput: document.getElementById('skillContentInput'),
  skillFormError: document.getElementById('skillFormError'),
  skillSaveBtn: document.getElementById('skillSaveBtn'),
};

export const isMobileLayout = () => window.matchMedia('(max-width: 860px)').matches;

export const setMobileSidebar = (open) => {
  els.sidebar.classList.toggle('open', open);
  els.sidebarBackdrop.classList.toggle('visible', open);
  els.mobileMenuBtn.setAttribute('aria-expanded', String(open));
};

export const fitMessageInput = () => {
  els.messageInput.style.height = 'auto';
  els.messageInput.style.height = Math.min(els.messageInput.scrollHeight, 160) + 'px';
};
