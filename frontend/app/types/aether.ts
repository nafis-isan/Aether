export type User = {
  id: string;
  email: string;
  name: string;
};

export type Conversation = {
  id: string;
  title: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  pending?: boolean;
  metadata?: Record<string, unknown> | null;
};

export type AuthResponse = {
  access_token: string;
  user: User;
};

export type ChatResponse = {
  conversation_id: string;
  reply: string;
  model: string;
  pending_approval_id?: string | null;
  citations?: Array<{ title?: string; url: string; snippet?: string | null; provider?: string | null }>;
};

export type ActivityEvent = {
  event_id: string;
  sequence: number;
  type: string;
  run_id: string;
  created_at: string;
  data: Record<string, unknown>;
};

export type PlanProgress = {
  index: number;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'stopped' | 'paused';
};

export type UsageTotals = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost?: number;
};

export type AgentDefinition = {
  name: string;
  description: string;
};

export type AgentActivity = {
  id: string;
  name: string;
  description: string;
  status: 'idle' | 'thinking' | 'working' | 'approval' | 'completed' | 'error';
  isRouted?: boolean;
};

export type Approval = {
  id: string;
  tool_name: string;
  tool_arguments: Record<string, unknown>;
};

export type Memory = {
  id: string;
  memory_type: 'preference' | 'fact' | 'context';
  content: string;
  importance: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type Artifact = {
  id: string;
  conversation_id: string;
  agent_run_id?: string | null;
  title: string;
  kind: string;
  mime_type: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type WorkspaceView = 'chat' | 'memory';

export type AgentVisualStatus = 'idle' | 'thinking' | 'executing' | 'approval' | 'error';
