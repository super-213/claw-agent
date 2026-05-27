import { create } from 'zustand';
import type {
  ChatRunStatus,
  Message,
  ModelConfig,
  SessionSummary,
  Skill,
  User,
} from '../api/types';

export interface StreamState {
  busy: boolean;
  status: ChatRunStatus;
  pendingUserMessage: string;
  abortController?: AbortController;
}

interface AppState {
  currentUser: User | null;
  sessions: SessionSummary[];
  skills: Skill[];
  config: ModelConfig | null;
  currentSessionId: string | null;
  messages: Message[];
  streams: Record<string, StreamState>;
  statusText: string;
  setCurrentUser: (user: User | null) => void;
  setSessions: (sessions: SessionSummary[]) => void;
  setSkills: (skills: Skill[]) => void;
  setConfig: (config: ModelConfig | null) => void;
  setCurrentSessionId: (sessionId: string | null) => void;
  setMessages: (messages: Message[]) => void;
  beginStream: (sessionId: string, pendingUserMessage: string, abortController?: AbortController) => void;
  updateStream: (sessionId: string, patch: Partial<StreamState>) => void;
  endStream: (sessionId: string) => void;
  setStatusText: (text: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentUser: null,
  sessions: [],
  skills: [],
  config: null,
  currentSessionId: null,
  messages: [],
  streams: {},
  statusText: '就绪',
  setCurrentUser: (currentUser) => set({ currentUser }),
  setSessions: (sessions) => set({ sessions }),
  setSkills: (skills) => set({ skills }),
  setConfig: (config) => set({ config }),
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setMessages: (messages) => set({ messages }),
  beginStream: (sessionId, pendingUserMessage, abortController) =>
    set((state) => ({
      streams: {
        ...state.streams,
        [sessionId]: {
          busy: true,
          status: 'preparing',
          pendingUserMessage,
          abortController,
        },
      },
    })),
  updateStream: (sessionId, patch) =>
    set((state) => ({
      streams: {
        ...state.streams,
        [sessionId]: {
          ...(state.streams[sessionId] || { busy: true, status: 'idle', pendingUserMessage: '' }),
          ...patch,
        },
      },
    })),
  endStream: (sessionId) =>
    set((state) => {
      const next = { ...state.streams };
      delete next[sessionId];
      return { streams: next };
    }),
  setStatusText: (statusText) => set({ statusText }),
}));

export const selectCurrentSession = (state: AppState) =>
  state.sessions.find((session) => session.id === state.currentSessionId) || null;

export const isAdmin = (user: User | null | undefined): boolean => user?.role === 'admin';
