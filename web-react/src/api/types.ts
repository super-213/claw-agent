export type UserRole = 'admin' | 'user' | string;
export type UserStatus = 'active' | 'disabled' | 'deleted' | string;

export interface User {
  id: string;
  username: string;
  display_name?: string | null;
  role: UserRole;
  status: UserStatus;
  created_at?: string;
  updated_at?: string;
  last_login_at?: string | null;
}

export interface MessageUsage {
  total_tokens?: number;
  cumulative_tokens?: number;
  tool_tokens?: number;
  category?: string;
  [key: string]: unknown;
}

export interface MessageMedia {
  url?: string;
  src?: string;
  path?: string;
  type?: string;
  mime_type?: string;
  mimeType?: string;
  alt?: string;
  title?: string;
  name?: string;
  [key: string]: unknown;
}

export interface Message {
  role: string;
  content?: string;
  ts?: string;
  node_id?: string;
  parent_id?: string | null;
  usage?: MessageUsage | null;
  context_nodes?: string[];
  images?: Array<string | MessageMedia>;
  attachments?: Array<string | MessageMedia>;
  [key: string]: unknown;
}

export interface TokenUsage {
  total_tokens?: number;
  tool_tokens?: number;
  [key: string]: unknown;
}

export interface ShareConfig {
  scope: 'private' | 'all' | 'selected' | string;
  user_ids: string[];
  permission: 'read' | 'write' | string;
}

export interface SessionSummary {
  id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  token_usage?: TokenUsage;
  owner_user_id?: string;
  sharing?: ShareConfig;
  [key: string]: unknown;
}

export interface SessionDetail extends SessionSummary {
  messages: Message[];
  active_node_id?: string | null;
  summarized_nodes?: string[];
  summary?: string;
}

export interface Skill {
  name: string;
  path?: string;
  bytes?: number;
  updated_at?: string;
}

export interface ModelConfig {
  base_url?: string;
  model?: string;
  api_key_masked?: string;
  [key: string]: unknown;
}

export interface BranchApiNode {
  node_id: string;
  parent_id: string | null;
  role: string;
  summary?: string;
  child_count?: number;
}

export interface BranchTree {
  nodes: BranchApiNode[];
  active_node_id?: string | null;
}

export type ChatRunStatus =
  | 'idle'
  | 'preparing'
  | 'streaming'
  | 'running_tool'
  | 'saving'
  | 'done'
  | 'error';

export type ChatStreamEvent =
  | {
      type: 'step';
      stage?: string;
      message?: string;
      status?: ChatRunStatus;
      [key: string]: unknown;
    }
  | {
      type: 'model_start';
      iteration?: number;
      model?: string;
      message_count?: number;
      [key: string]: unknown;
    }
  | {
      type: 'model_delta';
      iteration?: number;
      delta?: string;
      [key: string]: unknown;
    }
  | {
      type: 'model_done';
      iteration?: number;
      content?: string;
      [key: string]: unknown;
    }
  | {
      type: 'command_start';
      iteration?: number;
      command?: string;
      [key: string]: unknown;
    }
  | {
      type: 'command_result';
      iteration?: number;
      output?: string;
      return_code?: number;
      success?: boolean;
      message?: string;
      [key: string]: unknown;
    }
  | {
      type: 'done';
      messages?: Message[];
      summarized_nodes?: string[];
      [key: string]: unknown;
    }
  | {
      type: 'error';
      message?: string;
      [key: string]: unknown;
    };

export interface DashboardSummary {
  generated_at?: string;
  kpis?: Record<string, number>;
  timeseries?: Array<Record<string, unknown>>;
  token_breakdown?: Array<Record<string, unknown>>;
  top_sessions?: Array<Record<string, unknown>>;
  role_tokens?: Array<Record<string, unknown>>;
  tool_summary?: Record<string, unknown>;
  recent_tool_calls?: Array<Record<string, unknown>>;
  alerts?: Array<Record<string, unknown>>;
  word_cloud?: Array<Record<string, unknown>>;
  heatmap?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface DashboardSessionsResponse {
  sessions: Array<Record<string, any>>;
}

export interface DashboardSessionDetail {
  session?: Record<string, any>;
  token_curve?: Array<Record<string, unknown>>;
  token_breakdown?: Array<Record<string, unknown>>;
  tool_calls?: Array<Record<string, unknown>>;
  recent_messages?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface HomeInventoryItem {
  id: string;
  name: string;
  normalized_name?: string;
  category?: string;
  location: string;
  zone?: string;
  quantity?: number | null;
  unit?: string;
  status?: string;
  expires_at?: string | null;
  updated_at?: string;
  source?: Record<string, unknown>;
}

export interface HomeInventoryDoc {
  version?: number;
  updated_at?: string;
  items: HomeInventoryItem[];
}

export interface HomeReminder {
  id: string;
  title: string;
  description?: string;
  trigger?: {
    type?: string;
    raw_text?: string;
    run_at?: string | null;
    rrule?: string | null;
  };
  recipients?: string[];
  channels?: string[];
  status?: string;
  priority?: string;
  next_run_at?: string | null;
  updated_at?: string;
}

export interface HomeNotification {
  id: string;
  title: string;
  body?: string;
  url?: string;
  status?: string;
  reason?: string | null;
  created_at?: string;
  read_at?: string | null;
}

export interface HomeTaskSummary {
  kpis?: Record<string, number>;
  status_distribution?: Array<Record<string, unknown>>;
  channel_distribution?: Array<Record<string, unknown>>;
  frequency_distribution?: Array<Record<string, unknown>>;
  alerts?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}
