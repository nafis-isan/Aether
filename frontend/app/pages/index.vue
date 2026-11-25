<script setup lang="ts">
import MarkdownIt from 'markdown-it';
import taskLists from 'markdown-it-task-lists';
import type {
  ActivityEvent,
  AgentActivity,
  AgentDefinition,
  AgentVisualStatus,
  Approval,
  Artifact,
  AuthResponse,
  ChatMessage,
  ChatResponse,
  Conversation,
  Memory,
  PlanProgress,
  UsageTotals,
  User,
  WorkspaceView
} from '../types/aether';

type SpeechRecognitionResultLike = {
  isFinal: boolean;
  0: { transcript: string };
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

const runtimeConfig = useRuntimeConfig();
const markdown = new MarkdownIt({ html: false, breaks: true, linkify: false })
  .use(taskLists, { label: true });
const apiBase = runtimeConfig.public.apiBase;
const wsBase = runtimeConfig.public.wsBase;
const token = useState<string | null>('aether-access-token', () => null);
const user = ref<User | null>(null);
const workspaceView = ref<WorkspaceView>('chat');
const activeSidebarSection = ref<'home' | 'explore' | 'collection'>('home');
const conversationSearch = ref('');
const sidebarWidth = ref(280);
const sidebarResizing = ref(false);
const localAuthMode = ref(false);
const authModeLoaded = ref(false);
const authMode = ref<'login' | 'register'>('login');
const email = ref('');
const password = ref('');
const name = ref('');
const conversations = ref<Conversation[]>([]);
const messages = ref<ChatMessage[]>([]);
const activeConversationId = ref<string | null>(null);
const draft = ref('');
const attachmentInput = ref<HTMLInputElement | null>(null);
const selectedAttachment = ref<File | null>(null);
const attachmentText = ref('');
const isReadingAttachment = ref(false);
const modelRole = ref<'general' | 'coding'>('general');
const busy = ref(false);
const isStoppingRun = ref(false);
const isPausingRun = ref(false);
const isResumingRun = ref(false);
const isRedirectingRun = ref(false);
const streamedReply = ref('');
const errorMessage = ref('');
const backendStatus = ref<'checking' | 'connected' | 'unavailable'>('checking');
const backendHealthError = ref('');
const activityEvents = ref<ActivityEvent[]>([]);
const agentDefinitions = ref<AgentDefinition[]>([]);
const activityStatus = ref<'disconnected' | 'connecting' | 'connected'>('disconnected');
const eventCursors = ref<Record<string, number>>({});
const approvals = ref<Approval[]>([]);
const approvalModalId = ref<string | null>(null);
const memories = ref<Memory[]>([]);
const artifacts = ref<Artifact[]>([]);
const memoryContent = ref('');
const memoryType = ref<Memory['memory_type']>('preference');
const memoryImportance = ref(3);
const memorySearch = ref('');
const memoryCategoryFilter = ref<Memory['memory_type'] | 'all'>('all');
const showArchivedMemories = ref(false);
const pendingMessage = ref('');
const composerInput = ref<HTMLTextAreaElement | null>(null);
const speechRecognitionAvailable = ref(false);
const speechSynthesisAvailable = ref(false);
const isListening = ref(false);
const speakReplies = ref(true);
const voiceStatus = ref('');
let speechRecognition: SpeechRecognitionLike | null = null;
let voiceTranscript = '';
let voiceDraftPrefix = '';
let activitySocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let activityGeneration = 0;
let reconnectAttempt = 0;

const capabilities = [
  {
    name: 'Browser lokal',
    icon: '↗',
    detail: 'Perlu diaktifkan; navigasi dibatasi ke host allowlist.',
    prompt: 'Buka halaman yang diizinkan dan rangkum informasi yang relevan.'
  },
  {
    name: 'Tugas',
    icon: '▦',
    detail: 'Tinjau tugas; pembuatan tugas meminta persetujuan.',
    prompt: 'Buat tugas untuk menyiapkan rencana kerja minggu ini.'
  },
  {
    name: 'Kalkulator',
    icon: 'ƒx',
    detail: 'Hitung ekspresi aritmetika dengan batas aman.',
    prompt: 'Hitung dan jelaskan hasil dari '
  },
  {
    name: 'Perencanaan',
    icon: '⌘',
    detail: 'Uraikan tujuan menjadi langkah berurutan.',
    prompt: 'Buat rencana langkah demi langkah untuk '
  }
];

const visibleMemories = computed(() => memories.value.filter((memory) => {
  const matchesStatus = showArchivedMemories.value || memory.is_active;
  const matchesQuery = memory.content.toLocaleLowerCase().includes(memorySearch.value.trim().toLocaleLowerCase());
  const matchesCategory = memoryCategoryFilter.value === 'all' || memory.memory_type === memoryCategoryFilter.value;
  return matchesStatus && matchesQuery && matchesCategory;
}));

const visibleConversations = computed(() => {
  const query = conversationSearch.value.trim().toLocaleLowerCase();
  return conversations.value.filter((conversation) => conversation.title.toLocaleLowerCase().includes(query));
});
const activeMemoryCount = computed(() => memories.value.filter((memory) => memory.is_active).length);
const archivedMemoryCount = computed(() => memories.value.length - activeMemoryCount.value);
const modelDetails = computed(() => modelRole.value === 'general'
  ? {
      name: 'Nemotron 3 Ultra',
      provider: 'NVIDIA · OpenRouter',
      purpose: 'Percakapan umum dan penalaran'
    }
  : {
      name: 'North Mini Code',
      provider: 'Cohere · OpenRouter',
      purpose: 'Pemrograman dan desain software'
    });
const hasStartedTask = computed(() => Boolean(activeConversationId.value || pendingMessage.value || messages.value.length));
const latestAssistantOutput = computed(() => {
  if (busy.value && pendingMessage.value) return streamedReply.value;
  return [...messages.value].reverse().find((message) => message.role === 'assistant')?.content || streamedReply.value;
});
const latestAssistantCitations = computed(() => {
  const latest = [...messages.value].reverse().find((message) => message.role === 'assistant');
  const metadata = latest?.metadata as Record<string, unknown> | undefined;
  return Array.isArray(metadata?.citations)
    ? metadata.citations as Array<{ title?: string; url: string; snippet?: string | null; provider?: string | null }>
    : [];
});
const conversationHistory = computed(() => {
  const latestAssistant = !busy.value
    ? [...messages.value].reverse().find((message) => message.role === 'assistant')
    : undefined;
  return latestAssistant
    ? messages.value.filter((message) => message.id !== latestAssistant.id)
    : messages.value;
});
const currentActivityEvents = computed(() => currentRunEvents.value.filter((event) =>
  event.type !== 'assistant.delta' && event.type !== 'usage.updated'
));
const latestToolEvent = computed(() => currentToolEvents.value.at(-1));
const isToolRunning = computed(() => latestToolEvent.value?.type === 'tool.started');
const rollbackTaskId = computed(() => {
  const event = currentToolEvents.value.find((item) =>
    item.type === 'tool.completed'
    && item.data.tool === 'create_task'
  );
  const output = event?.data.output as { task?: { id?: string } } | undefined;
  return output?.task?.id || null;
});
const currentApprovalModal = computed(() => approvals.value.find((approval) => approval.id === approvalModalId.value) || null);

function renderMessageMarkdown(content: string): string {
  return markdown.render(content);
}

function formatRunValue(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function stepSummary(index: number): string {
  const summary = currentRunEvents.value
    .filter((event) => event.type === 'plan.step.completed' && event.data.index === index)
    .at(-1)?.data.summary;
  return typeof summary === 'string' ? summary : '';
}

function formatUsageCount(value: number | undefined): string {
  return typeof value === 'number' ? new Intl.NumberFormat('id-ID').format(value) : '—';
}

function formatReportedCost(value: number | undefined): string {
  return typeof value === 'number'
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value)
    : 'Tidak dilaporkan';
}

const currentRunEvents = computed(() => {
  const latestEvent = activityEvents.value.at(-1);
  if (!latestEvent) return [];
  return activityEvents.value
    .filter((event) => event.run_id === latestEvent.run_id)
    .sort((left, right) => left.sequence - right.sequence);
});

const currentDag = computed(() => {
  const event = currentRunEvents.value.find((item) => item.type === 'dag.created');
  return event?.data as {
    execution_mode?: string;
    parallel_supported?: boolean;
    nodes?: Array<{ id: string; label: string; status: string; agent: string }>;
    edges?: Array<{ from: string; to: string }>;
  } | undefined;
});

const currentPlanProgress = computed<PlanProgress[]>(() => {
  const planEvent = currentRunEvents.value.find((event) => event.type === 'plan.created');
  const rawSteps = planEvent?.data.steps;
  if (!Array.isArray(rawSteps)) return [];
  return rawSteps.flatMap((rawStep): PlanProgress[] => {
    if (typeof rawStep !== 'object' || rawStep === null || !('index' in rawStep) || !('description' in rawStep)) {
      return [];
    }
    const index = rawStep.index;
    const description = rawStep.description;
    if (typeof index !== 'number' || typeof description !== 'string') return [];
    const stepEvents = currentRunEvents.value.filter(
      (event) => event.data.index === index
        && (event.type === 'plan.step.started' || event.type === 'plan.step.completed')
    );
    const latestStepEvent = stepEvents.at(-1);
    const runStopped = ['workflow.failed', 'workflow.cancelled', 'workflow.limited']
      .includes(currentRunEvents.value.at(-1)?.type || '');
    const runPaused = currentRunEvents.value.at(-1)?.type === 'workflow.paused';
    return [{
      index,
      description,
      status: latestStepEvent?.type === 'plan.step.completed'
        ? 'completed'
        : latestStepEvent?.type === 'plan.step.started'
          ? runPaused ? 'paused' : runStopped ? 'stopped' : 'in_progress'
          : 'pending'
    }];
  });
});

const currentUsage = computed(() => {
  const usageEvent = currentRunEvents.value.filter((event) => event.type === 'usage.updated').at(-1);
  const rawUsage = usageEvent?.data.usage;
  const usage = typeof rawUsage === 'object' && rawUsage !== null ? rawUsage as UsageTotals : {};
  const modelCalls = usageEvent?.data.model_calls;
  const costLimit = usageEvent?.data.reported_cost_limit_usd;
  return {
    promptTokens: usage.prompt_tokens,
    completionTokens: usage.completion_tokens,
    totalTokens: usage.total_tokens,
    reportedCost: usage.cost,
    modelCalls: typeof modelCalls === 'number' ? modelCalls : undefined,
    costLimit: typeof costLimit === 'number' ? costLimit : undefined
  };
});

const currentToolEvents = computed(() => currentRunEvents.value.filter((event) =>
  ['tool.started', 'tool.completed', 'tool.failed'].includes(event.type)
));

const currentRouteExplanation = computed(() => {
  const basis = currentRunEvents.value
    .filter((event) => event.type === 'agent.status' && event.data.status === 'routed')
    .at(-1)?.data.route_basis;
  return typeof basis === 'string' ? basis : '';
});

const isWorkflowActive = computed(() => {
  const latestEvent = currentRunEvents.value.at(-1);
  if (!latestEvent) return false;
  return ![
    'workflow.completed',
    'workflow.failed',
    'workflow.cancelled',
    'workflow.limited',
    'workflow.paused'
  ].includes(latestEvent.type)
    && latestEvent.data.status !== 'waiting_approval';
});

const isWorkflowPaused = computed(() => currentRunEvents.value.at(-1)?.type === 'workflow.paused');

const currentRouteEvent = computed(() => currentRunEvents.value
  .filter((event) => event.type === 'agent.status' && event.data.status === 'routed')
  .at(-1));

const routedAgentId = computed(() => {
  const agentId = currentRouteEvent.value?.data.agent;
  return typeof agentId === 'string' ? agentId : null;
});

const currentRunStatus = computed(() => {
  const latestEvent = currentRunEvents.value.at(-1);
  if (!latestEvent) return 'Belum ada aktivitas';
  if (latestEvent.type === 'workflow.failed' || latestEvent.data.status === 'failed') return 'Gagal';
  if (latestEvent.type === 'workflow.cancelled') return 'Dihentikan';
  if (latestEvent.type === 'workflow.limited') return 'Batas eksekusi tercapai';
  if (latestEvent.type === 'workflow.stop_requested') return 'Menghentikan run…';
  if (latestEvent.type === 'workflow.pause_requested') return 'Menunggu checkpoint untuk jeda';
  if (latestEvent.type === 'workflow.paused') return 'Dijeda';
  if (latestEvent.data.status === 'resuming') return 'Melanjutkan run';
  if (latestEvent.data.status === 'waiting_approval') return 'Menunggu persetujuan';
  if (latestEvent.type === 'workflow.completed') return 'Selesai';
  if (latestEvent.type === 'agent.started' && latestEvent.data.agent === 'aether_core') return 'Core memproses';
  if (latestEvent.type === 'agent.started') return 'Agent bekerja';
  if (latestEvent.data.status === 'routed') return 'Agent dipilih';
  return latestEvent.type.replaceAll('.', ' ');
});

const agentVisualStatus = computed<AgentVisualStatus>(() => {
  const latestEvent = currentRunEvents.value.at(-1);
  if (
    approvals.value.length > 0
    || latestEvent?.data.status === 'waiting_approval'
    || latestEvent?.type === 'approval.required'
  ) {
    return 'approval';
  }
  if (
    latestEvent?.type === 'workflow.failed'
    || latestEvent?.type === 'workflow.limited'
    || latestEvent?.type === 'tool.failed'
    || latestEvent?.data.status === 'failed'
  ) {
    return 'error';
  }
  if (isToolRunning.value) return 'executing';
  if (isWorkflowActive.value) return 'thinking';
  return 'idle';
});

const agentVisualLabel = computed(() => ({
  idle: 'Aether siap menerima tujuan baru',
  thinking: 'Aether sedang merencanakan',
  executing: 'Aether sedang menjalankan tool',
  approval: 'Aether menunggu persetujuan',
  error: 'Run terakhir mengalami error'
})[agentVisualStatus.value]);

const workspaceContext = computed(() => {
  if (workspaceView.value === 'memory') return 'Memory';
  if (!hasStartedTask.value) return 'Workspace';
  return conversations.value.find((conversation) => conversation.id === activeConversationId.value)?.title || 'Task';
});

const agentActivities = computed<AgentActivity[]>(() => {
  const displayNames: Record<string, string> = {
    assistant: 'Assistant',
    researcher: 'Researcher',
    developer: 'Developer',
    productivity: 'Productivity Agent',
    document: 'Document Agent'
  };
  const coreEvents = currentRunEvents.value.filter((event) =>
    (event.type === 'agent.started' && event.data.agent === 'aether_core')
    || event.type === 'workflow.completed'
    || event.type === 'workflow.failed'
    || (event.type === 'agent.status' && event.data.status === 'routed')
  );
  const lastCoreEvent = coreEvents.at(-1);
  let coreStatus: AgentActivity['status'] = 'idle';
  if (lastCoreEvent?.type === 'agent.started') coreStatus = 'thinking';
  if (lastCoreEvent?.type === 'agent.status') coreStatus = 'completed';
  if (lastCoreEvent?.type === 'workflow.completed') coreStatus = 'completed';
  if (lastCoreEvent?.type === 'workflow.failed') coreStatus = 'error';

  const activities: AgentActivity[] = [{
    id: 'aether_core',
    name: 'Aether Core',
    description: 'Mengatur alur kerja dan memilih agent.',
    status: coreStatus,
    isRouted: false
  }];
  for (const agent of agentDefinitions.value) {
    const lastEvent = currentRunEvents.value
      .filter((event) => event.data.agent === agent.name)
      .at(-1);
    let agentStatus: AgentActivity['status'] = 'idle';
    if (lastEvent?.type === 'agent.started') agentStatus = 'working';
    if (lastEvent?.type === 'agent.completed') agentStatus = 'completed';
    if (lastEvent?.type === 'agent.status' && lastEvent.data.status === 'waiting_approval') agentStatus = 'approval';
    if (lastEvent?.type === 'workflow.failed' || lastEvent?.data.status === 'failed') agentStatus = 'error';
    activities.push({
      id: agent.name,
      name: displayNames[agent.name] || agent.name,
      description: agent.description,
      status: agentStatus,
      isRouted: routedAgentId.value === agent.name
    });
  }
  return activities;
});

function agentDisplayName(agentId: unknown): string {
  if (typeof agentId !== 'string') return 'Agent';
  if (agentId === 'aether_core') return 'Aether Core';
  return agentActivities.value.find((agent) => agent.id === agentId)?.name || agentId;
}

function activityActor(event: ActivityEvent): string {
  if (event.type.startsWith('workflow.') || event.data.status === 'routed') return 'Aether Core';
  return agentDisplayName(event.data.agent);
}

function activityDescription(event: ActivityEvent): string {
  if (event.type === 'agent.started' && event.data.agent === 'aether_core') return 'Mulai menganalisis permintaan';
  if (event.data.status === 'routed') return `Memilih ${agentDisplayName(event.data.agent)}`;
  if (event.type === 'plan.created') return 'Membuat rencana langkah';
  if (event.type === 'plan.step.started') return `Mulai langkah ${String(event.data.index || '')}`;
  if (event.type === 'plan.step.completed') return `Menyelesaikan langkah ${String(event.data.index || '')}`;
  if (event.type === 'dag.created') return 'Menyusun DAG eksekusi';
  if (event.type === 'subagent.started') return `Sub-agent mulai: ${String(event.data.node || 'worker')}`;
  if (event.type === 'subagent.completed') return `Sub-agent selesai: ${String(event.data.node || 'worker')}`;
  if (event.type === 'provider.retry') return `Retry provider ke-${String(event.data.attempt || 1)} (${String(event.data.reason || 'error')})`;
  if (event.type === 'provider.recovered') return `Pemulihan berhasil setelah ${String(event.data.attempt || 1)} retry`;
  if (event.type === 'artifact.created') return `Artifact dibuat: ${String(event.data.title || 'Dokumen')}`;
  if (event.type === 'workflow.stop_requested') return 'Permintaan berhenti diterima';
  if (event.type === 'workflow.pause_requested') return 'Menunggu checkpoint aman untuk jeda';
  if (event.type === 'workflow.paused') return 'Run dijeda pada checkpoint aman';
  if (event.type === 'workflow.redirected') return 'Memulai run baru dari instruksi yang dialihkan';
  if (event.data.status === 'resuming') return 'Melanjutkan dari checkpoint';
  if (event.type === 'workflow.cancelled') return 'Run dihentikan';
  if (event.type === 'workflow.limited') return 'Run berhenti pada batas eksekusi';
  if (event.type === 'agent.started') return 'Mulai bekerja';
  if (event.type === 'agent.completed') return 'Menyelesaikan tugas';
  if (event.type === 'tool.started') return `Menjalankan ${String(event.data.tool || 'tool')}`;
  if (event.type === 'tool.completed') return `Selesai ${String(event.data.tool || 'tool')}`;
  if (event.type === 'tool.failed') return `Gagal ${String(event.data.tool || 'tool')}`;
  if (event.type === 'usage.updated') return 'Memperbarui penggunaan token/biaya';
  if (event.type === 'agent.status' && event.data.status === 'waiting_approval') return 'Menunggu persetujuan';
  if (event.type === 'approval.required') return 'Persetujuan tindakan diperlukan';
  if (event.type === 'workflow.completed') return 'Alur kerja selesai';
  if (event.type === 'workflow.failed') return 'Alur kerja gagal';
  return event.type.replaceAll('.', ' ');
}

function activityTone(event: ActivityEvent): 'success' | 'running' | 'approval' | 'error' | 'neutral' {
  if (['workflow.failed', 'workflow.limited', 'tool.failed'].includes(event.type) || event.data.status === 'failed') {
    return 'error';
  }
  if (
    event.type.startsWith('approval.')
    || event.data.status === 'waiting_approval'
    || event.type === 'workflow.paused'
  ) {
    return 'approval';
  }
  if (
    ['workflow.completed', 'plan.step.completed', 'tool.completed', 'agent.completed', 'provider.recovered', 'subagent.completed', 'artifact.created'].includes(event.type)
    || event.type === 'approval.approved'
  ) {
    return 'success';
  }
  if (
    ['agent.started', 'plan.step.started', 'tool.started', 'provider.retry', 'subagent.started', 'dag.created', 'workflow.stop_requested', 'workflow.pause_requested']
      .includes(event.type)
  ) {
    return 'running';
  }
  return 'neutral';
}

function formatActivityTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('id-ID', { hour: '2-digit', minute: '2-digit' }).format(date);
}

function formatMemoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function getErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = error.data;
    if (typeof data === 'object' && data !== null && 'detail' in data && typeof data.detail === 'string') {
      return data.detail;
    }
  }
  return error instanceof Error ? error.message : 'Terjadi kesalahan yang tidak diketahui.';
}

async function checkBackend(): Promise<void> {
  try {
    await $fetch(`${apiBase}/health`);
    backendStatus.value = 'connected';
    backendHealthError.value = '';
  } catch (error) {
    backendStatus.value = 'unavailable';
    backendHealthError.value = getErrorMessage(error);
  }
}

async function initializeApplication(): Promise<void> {
  await checkBackend();
  if (backendStatus.value !== 'connected') {
    authModeLoaded.value = true;
    return;
  }
  try {
    const mode = await $fetch<{ local_auth: boolean }>(`${apiBase}/auth/mode`);
    localAuthMode.value = mode.local_auth;
    await loadAgents();
    if (mode.local_auth) {
      busy.value = true;
      user.value = await $fetch<User>(`${apiBase}/auth/me`);
      await Promise.all([loadConversations(), loadApprovals(), loadMemories(), loadArtifacts()]);
    }
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
    authModeLoaded.value = true;
  }
}

async function authenticate(): Promise<void> {
  errorMessage.value = '';
  busy.value = true;
  try {
    if (authMode.value === 'register') {
      await $fetch<User>(`${apiBase}/auth/register`, {
        method: 'POST',
        body: { email: email.value, password: password.value, name: name.value }
      });
    }
    const result = await $fetch<AuthResponse>(`${apiBase}/auth/login`, {
      method: 'POST',
      body: { email: email.value, password: password.value }
    });
    token.value = result.access_token;
    user.value = result.user;
    password.value = '';
    await Promise.all([loadAgents(), loadConversations(), loadApprovals(), loadMemories(), loadArtifacts()]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function loadAgents(): Promise<void> {
  agentDefinitions.value = await $fetch<AgentDefinition[]>(`${apiBase}/agents`);
}

function authHeaders(): Record<string, string> {
  if (localAuthMode.value) {
    return {};
  }
  if (!token.value) {
    throw new Error('Silakan login kembali untuk melanjutkan.');
  }
  return { Authorization: `Bearer ${token.value}` };
}

async function loadConversations(): Promise<void> {
  conversations.value = await $fetch<Conversation[]>(`${apiBase}/conversations`, {
    headers: authHeaders()
  });
  if (activeConversationId.value) {
    const selected = conversations.value.find((conversation) => conversation.id === activeConversationId.value);
    if (!selected) {
      activeConversationId.value = null;
      messages.value = [];
    }
  }
}

async function loadApprovals(): Promise<void> {
  if (!token.value && !localAuthMode.value) {
    approvals.value = [];
    approvalModalId.value = null;
    return;
  }
  const knownIds = new Set(approvals.value.map((approval) => approval.id));
  const updatedApprovals = await $fetch<Approval[]>(`${apiBase}/approvals`, {
    headers: authHeaders()
  });
  approvals.value = updatedApprovals;
  const newApproval = updatedApprovals.find((approval) => !knownIds.has(approval.id));
  if (newApproval) {
    approvalModalId.value = newApproval.id;
  } else if (!updatedApprovals.some((approval) => approval.id === approvalModalId.value)) {
    approvalModalId.value = null;
  }
}

async function loadMemories(): Promise<void> {
  if (!token.value && !localAuthMode.value) {
    memories.value = [];
    return;
  }
  memories.value = await $fetch<Memory[]>(`${apiBase}/memory?active_only=false`, {
    headers: authHeaders()
  });
}

async function loadArtifacts(conversationId?: string | null): Promise<void> {
  if (!token.value && !localAuthMode.value) {
    artifacts.value = [];
    return;
  }
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
  artifacts.value = await $fetch<Artifact[]>(`${apiBase}/artifacts${query}`, {
    headers: authHeaders()
  });
}

function openActivitySocket(generation: number): void {
  if ((!token.value && !localAuthMode.value) || !activeConversationId.value || generation !== activityGeneration) {
    return;
  }
  activityStatus.value = 'connecting';
  const cursor = encodeURIComponent(JSON.stringify(eventCursors.value));
  const url = `${wsBase.replace(/\/$/, '')}/ws/chat/${activeConversationId.value}?after=${cursor}`;
  const protocols = localAuthMode.value
    ? ['aether', 'aether.local']
    : ['aether', `aether.bearer.${token.value}`];
  const socket = new WebSocket(url, protocols);
  activitySocket = socket;

  socket.onopen = () => {
    if (generation !== activityGeneration) {
      socket.close();
      return;
    }
    activityStatus.value = 'connected';
    reconnectAttempt = 0;
  };
  socket.onmessage = (message) => {
    if (generation !== activityGeneration) {
      return;
    }
    try {
      const event = JSON.parse(message.data) as ActivityEvent;
      eventCursors.value = {
        ...eventCursors.value,
        [event.run_id]: Math.max(eventCursors.value[event.run_id] || 0, event.sequence)
      };
      activityEvents.value = [...activityEvents.value, event]
        .sort((left, right) => left.created_at.localeCompare(right.created_at)
          || (left.run_id === right.run_id ? left.sequence - right.sequence : 0))
        .slice(-200);
      if (event.type === 'assistant.delta' && typeof event.data.text === 'string') {
        streamedReply.value += event.data.text;
      }
      if (event.type === 'approval.required') {
        void loadApprovals().catch((error: unknown) => {
          errorMessage.value = getErrorMessage(error);
        });
      }
    } catch (error) {
      errorMessage.value = getErrorMessage(error);
    }
  };
  socket.onclose = (event: CloseEvent) => {
    if (generation !== activityGeneration) {
      return;
    }
    activitySocket = null;
    activityStatus.value = 'disconnected';
    if (event.code === 4401) {
      errorMessage.value = 'Sesi aktivitas berakhir. Silakan login kembali.';
      return;
    }
    if (event.code === 4404) {
      errorMessage.value = 'Percakapan tidak ditemukan atau tidak dapat diakses.';
      return;
    }
    const delay = Math.min(1000 * 2 ** reconnectAttempt, 15000);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => openActivitySocket(generation), delay);
  };
}

function disconnectActivity(resetCursor = true): void {
  activityGeneration += 1;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (activitySocket) {
    const socket = activitySocket;
    activitySocket = null;
    socket.close();
  }
  activityStatus.value = 'disconnected';
  if (resetCursor) {
    eventCursors.value = {};
    activityEvents.value = [];
  }
}

function connectActivity(): void {
  disconnectActivity();
  reconnectAttempt = 0;
  if ((token.value || localAuthMode.value) && activeConversationId.value) {
    openActivitySocket(activityGeneration);
  }
}

async function decideApproval(approval: Approval, approve: boolean): Promise<void> {
  errorMessage.value = '';
  busy.value = true;
  try {
    const result = await $fetch<ChatResponse>(`${apiBase}/approvals/${approval.id}/decision`, {
      method: 'POST',
      headers: authHeaders(),
      body: { approve }
    });
    approvalModalId.value = null;
    await Promise.all([loadApprovals(), loadConversations()]);
    activeConversationId.value = result.conversation_id;
    await openConversation(result.conversation_id);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function saveMemory(): Promise<void> {
  const content = memoryContent.value.trim();
  if (!content || busy.value) {
    return;
  }
  errorMessage.value = '';
  busy.value = true;
  try {
    await $fetch(`${apiBase}/memory`, {
      method: 'POST',
      headers: authHeaders(),
      body: { memory_type: memoryType.value, content, importance: memoryImportance.value }
    });
    memoryContent.value = '';
    workspaceView.value = 'memory';
    await loadMemories();
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function setMemoryActive(memory: Memory, isActive: boolean): Promise<void> {
  errorMessage.value = '';
  try {
    const updated = await $fetch<Memory>(`${apiBase}/memory/${memory.id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: { is_active: isActive }
    });
    memories.value = memories.value.map((item) => item.id === updated.id ? updated : item);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  }
}

async function deleteMemory(memory: Memory): Promise<void> {
  errorMessage.value = '';
  try {
    await $fetch(`${apiBase}/memory/${memory.id}`, {
      method: 'DELETE',
      headers: authHeaders()
    });
    memories.value = memories.value.filter((item) => item.id !== memory.id);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  }
}

async function openConversation(conversationId: string): Promise<void> {
  errorMessage.value = '';
  busy.value = true;
  try {
    messages.value = await $fetch<ChatMessage[]>(
      `${apiBase}/conversations/${conversationId}/messages`,
      { headers: authHeaders() }
    );
    activeConversationId.value = conversationId;
    activeSidebarSection.value = 'home';
    await loadArtifacts(conversationId);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

function openHome(): void {
  activeSidebarSection.value = 'home';
  workspaceView.value = 'chat';
}

async function openExplore(): Promise<void> {
  activeSidebarSection.value = 'explore';
  workspaceView.value = 'chat';
  await nextTick();
  document.querySelector<HTMLInputElement>('.conversation-search input')?.focus();
}

function openCollection(): void {
  activeSidebarSection.value = 'collection';
  workspaceView.value = 'memory';
}

function beginSidebarResize(event: PointerEvent): void {
  if (window.innerWidth <= 760) return;
  sidebarResizing.value = true;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  window.addEventListener('pointermove', resizeSidebar);
  window.addEventListener('pointerup', endSidebarResize, { once: true });
}

function resizeSidebar(event: PointerEvent): void {
  if (!sidebarResizing.value) return;
  sidebarWidth.value = Math.min(420, Math.max(220, event.clientX));
}

function endSidebarResize(): void {
  sidebarResizing.value = false;
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  window.removeEventListener('pointermove', resizeSidebar);
  localStorage.setItem('aether-sidebar-width', String(sidebarWidth.value));
}

function openAttachmentPicker(): void {
  attachmentInput.value?.click();
}

async function extractAttachmentText(file: File): Promise<string> {
  const extension = file.name.split('.').pop()?.toLocaleLowerCase() || '';
  const textExtensions = new Set(['txt', 'md', 'markdown', 'csv', 'tsv', 'json', 'xml', 'html', 'htm', 'js', 'ts', 'vue', 'css', 'scss', 'py', 'sql', 'log']);

  if (textExtensions.has(extension) || file.type.startsWith('text/')) {
    return file.text();
  }

  if (extension === 'pdf' || file.type === 'application/pdf') {
    const pdfjs = await import('pdfjs-dist');
    pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
    const document = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;
    const pages: string[] = [];
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const textContent = await page.getTextContent();
      pages.push(textContent.items.map((item) => ('str' in item ? item.str : '')).join(' ').trim());
    }
    return pages.filter(Boolean).join('\n\n');
  }

  if (extension === 'docx' || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
    const mammoth = await import('mammoth');
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
    return result.value;
  }

  throw new Error(`Format .${extension || 'file'} belum didukung. Gunakan PDF, DOCX, TXT, atau dokumen teks.`);
}

async function handleAttachmentChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    errorMessage.value = 'Dokumen maksimal berukuran 10 MB.';
    input.value = '';
    return;
  }

  selectedAttachment.value = file;
  attachmentText.value = '';
  errorMessage.value = '';
  isReadingAttachment.value = true;
  try {
    attachmentText.value = await extractAttachmentText(file);
  } catch (error) {
    selectedAttachment.value = null;
    errorMessage.value = getErrorMessage(error);
  } finally {
    isReadingAttachment.value = false;
  }
}

function removeAttachment(): void {
  selectedAttachment.value = null;
  attachmentText.value = '';
  if (attachmentInput.value) attachmentInput.value.value = '';
}

async function sendMessage(): Promise<void> {
  const draftMessage = draft.value.trim();
  if (!draftMessage && !selectedAttachment.value) return;
  if (isReadingAttachment.value) return;
  const message = selectedAttachment.value
    ? [
        draftMessage || `Tinjau dokumen ${selectedAttachment.value.name}.`,
        '',
        `[Lampiran: ${selectedAttachment.value.name}]`,
        attachmentText.value.trim()
          ? `--- Isi dokumen ---\n${attachmentText.value.slice(0, 100_000)}`
          : 'Dokumen tidak dapat dibaca sebagai teks.'
      ].join('\n')
    : draftMessage;
  if (isWorkflowPaused.value || (busy.value && isWorkflowActive.value)) {
    await redirectCurrentRun(message);
    return;
  }
  if (busy.value) return;
  errorMessage.value = '';
  pendingMessage.value = message;
  busy.value = true;
  try {
    if (!activeConversationId.value) {
      const conversation = await $fetch<Conversation>(`${apiBase}/conversations`, {
        method: 'POST',
        headers: authHeaders(),
        body: { title: message.split('\n')[0].slice(0, 80) || 'New conversation' }
      });
      activeConversationId.value = conversation.id;
    }
    if (selectedAttachment.value) {
      await $fetch(`${apiBase}/artifacts`, {
        method: 'POST',
        headers: authHeaders(),
        body: {
          conversation_id: activeConversationId.value,
          title: selectedAttachment.value.name,
          kind: 'document',
          mime_type: selectedAttachment.value.type || 'application/octet-stream',
          content: attachmentText.value,
          metadata: {
            size: selectedAttachment.value.size,
            source: 'chat_attachment'
          }
        }
      });
    }
    streamedReply.value = '';
    const response = await $fetch<ChatResponse>(`${apiBase}/chat`, {
      method: 'POST',
      headers: authHeaders(),
      body: {
        message,
        conversation_id: activeConversationId.value,
        model_role: modelRole.value
      }
    });
    if (speakReplies.value) {
      speakReply(response.reply);
    }
    pendingMessage.value = '';
    activeConversationId.value = response.conversation_id;
    draft.value = '';
    removeAttachment();
    await Promise.all([
      loadConversations(),
      openConversation(response.conversation_id),
      loadArtifacts(response.conversation_id),
      response.pending_approval_id ? loadApprovals() : Promise.resolve()
    ]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    if (!isRedirectingRun.value) {
      busy.value = false;
      pendingMessage.value = '';
    }
    if (!isListening.value && !window.speechSynthesis?.speaking) {
      voiceStatus.value = '';
    }
  }
}

async function pauseCurrentRun(): Promise<void> {
  const runId = currentRunEvents.value[0]?.run_id;
  if (!runId || isPausingRun.value) return;
  errorMessage.value = '';
  isPausingRun.value = true;
  try {
    await $fetch(`${apiBase}/agents/runs/${runId}/pause`, {
      method: 'POST',
      headers: authHeaders()
    });
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    isPausingRun.value = false;
  }
}

async function resumeCurrentRun(): Promise<void> {
  const runId = currentRunEvents.value[0]?.run_id;
  if (!runId || isResumingRun.value) return;
  errorMessage.value = '';
  isResumingRun.value = true;
  busy.value = true;
  streamedReply.value = '';
  try {
    const response = await $fetch<ChatResponse>(`${apiBase}/agents/runs/${runId}/resume`, {
      method: 'POST',
      headers: authHeaders()
    });
    activeConversationId.value = response.conversation_id;
    await Promise.all([loadConversations(), openConversation(response.conversation_id)]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    isResumingRun.value = false;
    busy.value = false;
  }
}

async function redirectCurrentRun(message: string): Promise<void> {
  const runId = currentRunEvents.value[0]?.run_id;
  if (!runId || isRedirectingRun.value) return;
  errorMessage.value = '';
  isRedirectingRun.value = true;
  busy.value = true;
  pendingMessage.value = message;
  streamedReply.value = '';
  try {
    const response = await $fetch<ChatResponse>(`${apiBase}/agents/runs/${runId}/redirect`, {
      method: 'POST',
      headers: authHeaders(),
      body: { message }
    });
    draft.value = '';
    removeAttachment();
    pendingMessage.value = '';
    activeConversationId.value = response.conversation_id;
    await Promise.all([
      loadConversations(),
      openConversation(response.conversation_id),
      response.pending_approval_id ? loadApprovals() : Promise.resolve()
    ]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    isRedirectingRun.value = false;
    busy.value = false;
    pendingMessage.value = '';
  }
}

async function stopCurrentRun(): Promise<void> {
  const runId = currentRunEvents.value[0]?.run_id;
  if (!runId || isStoppingRun.value) return;
  errorMessage.value = '';
  isStoppingRun.value = true;
  try {
    await $fetch(`${apiBase}/agents/runs/${runId}/stop`, {
      method: 'POST',
      headers: authHeaders()
    });
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    isStoppingRun.value = false;
  }
}

function startVoiceInput(): void {
  if (isListening.value) {
    speechRecognition?.stop();
    voiceStatus.value = 'Menyiapkan transkripsi…';
    return;
  }
  const Recognition = (window as Window & { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition
    || (window as Window & { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition;
  if (!Recognition) {
    errorMessage.value = 'Browser ini belum mendukung input suara. Coba Chrome atau Edge versi terbaru.';
    return;
  }
  if (!window.isSecureContext) {
    errorMessage.value = 'Input suara memerlukan koneksi aman (HTTPS) atau localhost.';
    return;
  }

  errorMessage.value = '';
  voiceTranscript = '';
  voiceDraftPrefix = draft.value.trim();
  speechRecognition = new Recognition();
  speechRecognition.lang = 'id-ID';
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;
  speechRecognition.onstart = () => {
    isListening.value = true;
    voiceStatus.value = 'Mendengarkan… pilih tombol Selesai saat sudah selesai bicara.';
  };
  speechRecognition.onresult = (event) => {
    let finalText = '';
    let interimText = '';
    for (let index = 0; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result.isFinal) {
        finalText += result[0].transcript;
      } else {
        interimText += result[0].transcript;
      }
    }
    voiceTranscript = finalText.trim();
    const recognizedText = `${finalText}${interimText}`.trim();
    draft.value = [voiceDraftPrefix, recognizedText].filter(Boolean).join(' ');
  };
  speechRecognition.onerror = (event) => {
    const messages: Record<string, string> = {
      'not-allowed': 'Izin mikrofon ditolak. Izinkan akses mikrofon di pengaturan browser.',
      'service-not-allowed': 'Layanan pengenalan suara browser tidak diizinkan.',
      'audio-capture': 'Mikrofon tidak ditemukan atau sedang digunakan aplikasi lain.',
      'no-speech': 'Tidak ada ucapan yang terdeteksi. Tekan mikrofon dan coba lagi.',
      network: 'Layanan pengenalan suara tidak dapat dijangkau. Periksa koneksi internet.',
      aborted: 'Perekaman suara dihentikan.'
    };
    errorMessage.value = messages[event.error] || `Pengenalan suara gagal (${event.error}).`;
  };
  speechRecognition.onend = () => {
    isListening.value = false;
    speechRecognition = null;
    if (voiceTranscript) {
      draft.value = [voiceDraftPrefix, voiceTranscript].filter(Boolean).join(' ');
      voiceStatus.value = 'Mengirim transkripsi…';
      void sendMessage();
      return;
    }
    voiceStatus.value = '';
  };
  try {
    speechRecognition.start();
  } catch (error) {
    speechRecognition = null;
    errorMessage.value = error instanceof Error ? error.message : 'Tidak dapat memulai mikrofon.';
  }
}

function speakReply(text: string): void {
  if (!('speechSynthesis' in window)) {
    voiceStatus.value = 'Pembacaan suara tidak didukung browser ini.';
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'id-ID';
  utterance.onstart = () => {
    voiceStatus.value = 'Aether sedang berbicara…';
  };
  utterance.onend = () => {
    voiceStatus.value = '';
  };
  utterance.onerror = () => {
    voiceStatus.value = 'Balasan suara gagal diputar.';
  };
  window.speechSynthesis.speak(utterance);
}

function toggleSpokenReplies(): void {
  speakReplies.value = !speakReplies.value;
  if (!speakReplies.value && 'speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    voiceStatus.value = '';
  }
}

function initializeVoiceSupport(): void {
  const browserWindow = window as Window & { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor };
  speechRecognitionAvailable.value = Boolean(browserWindow.SpeechRecognition || browserWindow.webkitSpeechRecognition);
  speechSynthesisAvailable.value = 'speechSynthesis' in window;
}

function useSuggestedPrompt(prompt: string): void {
  draft.value = prompt;
  void nextTick(() => composerInput.value?.focus());
}

function startNewTask(): void {
  disconnectActivity();
  activeSidebarSection.value = 'home';
  workspaceView.value = 'chat';
  activeConversationId.value = null;
  messages.value = [];
  pendingMessage.value = '';
  streamedReply.value = '';
  draft.value = '';
  errorMessage.value = '';
  void nextTick(() => composerInput.value?.focus());
}

function dismissApprovalModal(): void {
  approvalModalId.value = null;
}

async function rollbackCreatedTask(): Promise<void> {
  if (!rollbackTaskId.value) return;
  try {
    await $fetch(`${apiBase}/tasks/${rollbackTaskId.value}`, {
      method: 'DELETE',
      headers: authHeaders()
    });
    await loadConversations();
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  }
}

function signOut(): void {
  if (localAuthMode.value) {
    return;
  }
  disconnectActivity();
  token.value = null;
  user.value = null;
  conversations.value = [];
  messages.value = [];
  activeConversationId.value = null;
  draft.value = '';
  password.value = '';
  memoryContent.value = '';
  errorMessage.value = '';
  approvals.value = [];
  approvalModalId.value = null;
  memories.value = [];
}

watch(activeConversationId, () => {
  activityEvents.value = [];
  eventCursors.value = {};
  streamedReply.value = '';
});
watch([token, activeConversationId, localAuthMode], connectActivity);
onMounted(() => {
  const savedSidebarWidth = Number(localStorage.getItem('aether-sidebar-width'));
  if (savedSidebarWidth >= 220 && savedSidebarWidth <= 420) {
    sidebarWidth.value = savedSidebarWidth;
  }
  initializeVoiceSupport();
  void initializeApplication();
});
onBeforeUnmount(() => {
  disconnectActivity();
  window.removeEventListener('pointermove', resizeSidebar);
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  speechRecognition?.stop();
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
});
</script>

<template>
  <main class="app-shell">
    <DashboardTopbar
      v-if="!authModeLoaded || (!localAuthMode && !token)"
      standalone
      :agent-visual-label="agentVisualLabel"
      :agent-visual-status="agentVisualStatus"
      :backend-status="backendStatus"
      :backend-health-error="backendHealthError"
      :local-auth-mode="localAuthMode"
      :user="user"
      @sign-out="signOut"
    />

    <section v-if="!authModeLoaded" class="startup-state">
      <span class="spark">✳</span>
      <p>{{ backendStatus === 'unavailable' ? 'Backend Aether belum tersambung.' : 'Menghubungkan ke Aether...' }}</p>
      <p v-if="backendHealthError" class="error-message" role="alert">{{ backendHealthError }}</p>
    </section>

    <section v-else-if="!localAuthMode && !token" class="auth-layout">
      <div class="intro">
        <p class="eyebrow">PERSONAL AI WORKSPACE</p>
        <h1>Ide besar,<br /><span>mulai dari sini.</span></h1>
        <p class="intro-copy">Masuk untuk bercakap dengan Aether. Percakapan disimpan di akunmu dan diproses lewat model OpenRouter di backend.</p>
        <div class="model-chips"><span>Nemotron · General</span><span>North Mini Code · Coding</span></div>
      </div>

      <form class="auth-card" @submit.prevent="authenticate">
        <div class="auth-tabs">
          <button type="button" :class="{ active: authMode === 'login' }" @click="authMode = 'login'; errorMessage = ''">Masuk</button>
          <button type="button" :class="{ active: authMode === 'register' }" @click="authMode = 'register'; errorMessage = ''">Buat akun</button>
        </div>
        <h2>{{ authMode === 'login' ? 'Selamat datang kembali' : 'Mulai bersama Aether' }}</h2>
        <p class="card-copy">{{ authMode === 'login' ? 'Masuk untuk melanjutkan percakapanmu.' : 'Buat akun untuk memulai workspace pribadimu.' }}</p>
        <label v-if="authMode === 'register'" class="field-label">
          Nama
          <input v-model="name" autocomplete="name" maxlength="120" required placeholder="Nama kamu" />
        </label>
        <label class="field-label">
          Email
          <input v-model="email" autocomplete="email" type="email" required placeholder="kamu@email.com" />
        </label>
        <label class="field-label">
          Kata sandi
          <input v-model="password" :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'" type="password" :minlength="authMode === 'register' ? 12 : 1" maxlength="128" required placeholder="Minimal 12 karakter" />
        </label>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <button class="primary-button" type="submit" :disabled="busy">
          {{ busy ? 'Memproses...' : authMode === 'login' ? 'Masuk ke Aether' : 'Buat akun' }}
        </button>
        <p class="privacy-note">Token akses hanya disimpan sementara di memori tab ini.</p>
      </form>
    </section>

    <section v-else class="workspace" :style="{ '--sidebar-width': `${sidebarWidth}px` }" :class="{ 'sidebar-resizing': sidebarResizing }">
      <DashboardSidebar
        v-model:conversation-search="conversationSearch"
        :active-sidebar-section="activeSidebarSection"
        :active-conversation-id="activeConversationId"
        :active-memory-count="activeMemoryCount"
        :agent-visual-label="agentVisualLabel"
        :agent-visual-status="agentVisualStatus"
        :approvals="approvals"
        :busy="busy"
        :conversations="conversations"
        :local-auth-mode="localAuthMode"
        :user="user"
        :visible-conversations="visibleConversations"
        :workspace-view="workspaceView"
        @start-new-task="startNewTask"
        @open-home="openHome"
        @open-explore="openExplore"
        @open-collection="openCollection"
        @open-conversation="openConversation"
        @decide-approval="decideApproval"
      />
      <button
        class="sidebar-resizer"
        type="button"
        aria-label="Sesuaikan lebar sidebar"
        title="Geser untuk mengubah lebar sidebar"
        @pointerdown.prevent="beginSidebarResize"
      ><span /></button>

      <div class="workspace-main">
        <DashboardTopbar
          :agent-visual-label="agentVisualLabel"
          :agent-visual-status="agentVisualStatus"
          :backend-status="backendStatus"
          :backend-health-error="backendHealthError"
          :local-auth-mode="localAuthMode"
          :user="user"
          :workspace-context="workspaceContext"
          @sign-out="signOut"
        />

      <section v-if="workspaceView === 'chat'" class="chat-area">
        <div class="task-workspace" :class="{ 'is-empty': !hasStartedTask }">
          <section class="task-main" aria-label="Task workspace">
            <div v-if="!hasStartedTask" class="task-landing-intro">
              <span class="landing-logo" aria-label="Aether">
                <img src="/aether-monogram-mint.png" alt="" />
              </span>
              <p class="eyebrow">PERSONAL AI WORKSPACE</p>
              <h2>Selamat datang,<br /><span>apa yang ingin kamu buat?</span></h2>
              <p>Berpikir, merencanakan, dan berkarya lebih jernih bersama ruang kerja yang memahami caramu bekerja.</p>
            </div>

            <section v-else class="task-timeline-pane" aria-labelledby="timeline-title" aria-live="polite" :aria-busy="busy">
              <header class="task-pane-heading">
                <div>
                  <p class="eyebrow">RUN / {{ currentRunEvents[0]?.run_id.slice(0, 8) || 'PENDING' }}</p>
                  <h2 id="timeline-title">
                    <span class="timeline-brain" :class="agentVisualStatus" aria-hidden="true">
                      <img src="/aether-monogram.png" alt="" />
                    </span>
                    Task timeline
                  </h2>
                </div>
                <span class="run-state" :class="isWorkflowActive ? 'running' : isWorkflowPaused ? 'approval' : currentRunEvents.at(-1)?.type === 'workflow.failed' ? 'error' : 'success'">
                  <span class="status-dot" />
                  {{ currentRunStatus }}
                </span>
              </header>

              <div class="run-summary">
                <div class="run-summary-copy">
                  <span class="run-kicker">GOAL</span>
                  <strong>{{ pendingMessage || conversations.find((item) => item.id === activeConversationId)?.title || 'Task berjalan' }}</strong>
                </div>
                <div v-if="currentRunEvents.length" class="run-usage-inline">
                  <span>{{ formatUsageCount(currentUsage.totalTokens ?? 0) }} tokens</span>
                  <span>{{ formatUsageCount(currentUsage.modelCalls ?? 0) }} calls</span>
                </div>
              </div>

              <div v-if="latestToolEvent" class="tool-activity" :class="{ running: isToolRunning, failed: latestToolEvent.type === 'tool.failed' }" role="status">
                <span aria-hidden="true">⌁</span>
                <strong>{{ isToolRunning ? 'Using Tool' : latestToolEvent.type === 'tool.failed' ? 'Tool failed' : 'Tool used' }}: {{ String(latestToolEvent.data.tool || 'tool') }}</strong>
                <span>{{ isToolRunning ? 'Sedang berjalan' : latestToolEvent.type === 'tool.failed' ? 'Perlu diperiksa' : 'Selesai' }}</span>
              </div>

              <div v-if="currentPlanProgress.length" class="plan-progress" aria-label="Rencana eksekusi">
                <p class="agent-list-label">EXECUTION PLAN</p>
                <ol>
                  <li v-for="step in currentPlanProgress" :key="step.index" :class="step.status">
                    <span class="plan-step-index">{{ step.status === 'completed' ? '✓' : String(step.index).padStart(2, '0') }}</span>
                    <span class="plan-step-description">{{ step.description }}</span>
                    <span class="plan-step-status">
                      {{ step.status === 'completed' ? 'Selesai' : step.status === 'in_progress' ? 'Berjalan' : step.status === 'stopped' ? 'Terhenti' : step.status === 'paused' ? 'Dijeda' : 'Menunggu' }}
                    </span>
                  </li>
                </ol>
              </div>

              <div v-if="currentDag?.nodes?.length" class="dag-view" aria-label="Task dependency graph">
                <p class="agent-list-label">TASK DAG <span>{{ currentDag.parallel_supported ? 'PARALLEL READY' : 'SEQUENTIAL' }}</span></p>
                <ol>
                  <li v-for="(node, index) in currentDag.nodes" :key="node.id" :class="{ active: node.status === 'in_progress' }">
                    <span class="dag-node-index">{{ String(index + 1).padStart(2, '0') }}</span>
                    <span class="dag-node-copy">
                      <strong>{{ node.label }}</strong>
                      <small>{{ node.agent }}</small>
                    </span>
                    <span v-if="index < (currentDag.nodes?.length || 0) - 1" class="dag-edge" aria-hidden="true">→</span>
                  </li>
                </ol>
              </div>

              <div v-if="currentActivityEvents.length" class="task-event-log" aria-label="Log aktivitas run">
                <p class="agent-list-label">ACTIVITY LOG</p>
                <ol>
                  <li v-for="event in currentActivityEvents" :key="event.event_id" :class="activityTone(event)">
                    <span class="timeline-marker" aria-hidden="true">
                      {{ activityTone(event) === 'success' ? '✓' : activityTone(event) === 'error' || activityTone(event) === 'approval' ? '!' : activityTone(event) === 'running' ? '·' : '—' }}
                    </span>
                    <time :datetime="event.created_at">{{ formatActivityTime(event.created_at) }}</time>
                    <div class="timeline-entry">
                      <strong>{{ activityDescription(event) }}</strong>
                      <span>{{ activityActor(event) }}</span>
                    </div>
                  </li>
                </ol>
              </div>
              <p v-else class="timeline-empty">Menghubungkan ke log run…</p>

              <div class="timeline-workers">
                <p class="agent-list-label">WORKERS</p>
                <ul class="agent-list">
                  <li
                    v-for="agent in agentActivities"
                    :key="agent.id"
                    class="agent-row"
                    :class="{ 'selected-agent': agent.isRouted }"
                    :title="agent.description"
                  >
                    <span class="agent-indicator" :class="agent.status" aria-hidden="true" />
                    <span class="agent-name">{{ agent.name }}</span>
                    <span class="agent-state" :class="agent.status">
                      {{ { idle: 'Idle', thinking: 'Thinking', working: 'Working', approval: 'Approval', completed: 'Done', error: 'Error' }[agent.status] }}
                    </span>
                  </li>
                </ul>
              </div>

              <details v-if="currentRouteExplanation || currentPlanProgress.length" class="process-summary">
                <summary>Ringkasan proses yang dapat diaudit</summary>
                <p v-if="currentRouteExplanation"><strong>Alasan routing:</strong> {{ currentRouteExplanation }}</p>
                <ol v-if="currentPlanProgress.length">
                  <li v-for="step in currentPlanProgress" :key="step.index">
                    <strong>{{ step.description }}</strong>
                    <span v-if="stepSummary(step.index)">{{ stepSummary(step.index) }}</span>
                  </li>
                </ol>
                <small>Ringkasan ini memakai routing dan hasil langkah yang tercatat, bukan chain-of-thought internal.</small>
              </details>

              <div v-if="isWorkflowPaused" class="run-controls">
                <p>Run dijeda pada checkpoint aman.</p>
                <button type="button" :disabled="isResumingRun" @click="resumeCurrentRun">
                  {{ isResumingRun ? 'Melanjutkan…' : 'Lanjutkan run' }}
                </button>
              </div>
            </section>

            <div class="composer-wrap" :class="{ 'goal-composer-wrap': !hasStartedTask }">
              <p v-if="errorMessage" class="error-message chat-error" role="alert">{{ errorMessage }}</p>
              <form class="composer task-composer" @submit.prevent="sendMessage">
                <input
                  ref="attachmentInput"
                  class="visually-hidden"
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.markdown,.csv,.tsv,.json,.xml,.html,.js,.ts,.vue,.css,.py,.sql,.log,text/plain,text/csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  @change="handleAttachmentChange"
                />
                <label class="visually-hidden" for="task-goal">Tujuan task untuk Aether</label>
                <textarea
                  id="task-goal"
                  ref="composerInput"
                  v-model="draft"
                  maxlength="12000"
                  rows="1"
                  aria-label="Tujuan task untuk Aether"
                  :placeholder="isWorkflowActive || isWorkflowPaused ? '> Tulis perubahan tujuan untuk mengalihkan run…' : '> Apa yang ingin Aether selesaikan?'"
                  @keydown.enter.exact.prevent="sendMessage"
                />
                <div v-if="selectedAttachment" class="attachment-chip" :class="{ reading: isReadingAttachment }">
                  <span class="attachment-chip-icon" aria-hidden="true">◆</span>
                  <span>
                    <strong>{{ selectedAttachment.name }}</strong>
                    <small>{{ isReadingAttachment ? 'Membaca dokumen…' : `${(selectedAttachment.size / 1024).toFixed(selectedAttachment.size < 1024 * 1024 ? 0 : 1)} KB` }}</small>
                  </span>
                  <button type="button" aria-label="Hapus lampiran" @click="removeAttachment">×</button>
                </div>
                <div class="composer-footer">
                  <div class="composer-left-tools">
                    <button
                      class="attachment-button"
                      type="button"
                      aria-label="Lampirkan berkas"
                      title="Lampirkan dokumen"
                      :disabled="busy || isReadingAttachment"
                      @click="openAttachmentPicker"
                    >
                      <svg aria-hidden="true" viewBox="0 0 20 20">
                        <path d="M7.2 11.8 13 6a2.6 2.6 0 0 1 3.7 3.7l-7.1 7.1a4.2 4.2 0 0 1-6-6l7.6-7.6" />
                      </svg>
                    </button>
                    <button
                      class="voice-button"
                      :class="{ listening: isListening }"
                      type="button"
                      :disabled="busy || !speechRecognitionAvailable"
                      :aria-label="isListening ? 'Selesai merekam suara' : 'Mulai input suara'"
                      :title="speechRecognitionAvailable ? (isListening ? 'Selesai bicara' : 'Bicara ke Aether') : 'Input suara tidak didukung browser ini'"
                      @click="startVoiceInput"
                    >
                      <svg aria-hidden="true" viewBox="0 0 20 20">
                        <rect x="7" y="2.5" width="6" height="10" rx="3" />
                        <path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5M7.5 17.5h5" />
                      </svg>
                    </button>
                  </div>
                  <div class="composer-actions">
                    <label class="inline-model-select">
                      <span class="visually-hidden">Pilih model · {{ modelDetails.provider }}</span>
                      <select v-model="modelRole" :aria-label="`Model ${modelDetails.name}, ${modelDetails.purpose}`">
                        <option value="general">Nemotron · General</option>
                        <option value="coding">North Mini Code · Coding</option>
                      </select>
                    </label>
                    <button
                      class="voice-toggle"
                      type="button"
                      :disabled="!speechSynthesisAvailable"
                      :aria-pressed="speakReplies"
                      :title="speechSynthesisAvailable ? (speakReplies ? 'Matikan balasan suara' : 'Aktifkan balasan suara') : 'Balasan suara tidak didukung browser ini'"
                      @click="toggleSpokenReplies"
                    >{{ speakReplies ? 'Suara aktif' : 'Suara mati' }}</button>
                    <button v-if="busy && isWorkflowActive" class="pause-button" type="button" :disabled="isPausingRun" @click="pauseCurrentRun">
                      {{ isPausingRun ? 'Menjeda…' : 'Jeda' }}
                    </button>
                    <button v-if="busy && isWorkflowActive" class="stop-button" type="button" :disabled="isStoppingRun" @click="stopCurrentRun">
                      {{ isStoppingRun ? 'Menghentikan…' : 'Hentikan' }}
                    </button>
                    <button class="send-button" type="submit" :disabled="(!draft.trim() && !selectedAttachment) || isReadingAttachment || (busy && !isWorkflowActive)" :aria-label="hasStartedTask ? 'Jalankan instruksi' : 'Jalankan task'">
                      {{ isRedirectingRun ? 'Mengalihkan…' : isWorkflowActive || isWorkflowPaused ? 'Alihkan tujuan' : busy ? 'Menjalankan…' : 'Jalankan ↗' }}
                    </button>
                  </div>
                </div>
              </form>
              <p v-if="voiceStatus" class="voice-status" role="status" aria-live="polite">{{ voiceStatus }}</p>
              <p class="voice-privacy">
                {{ speechRecognitionAvailable ? 'Mikrofon hanya aktif saat tombol ditekan. Pengenalan ucapan menggunakan layanan browser.' : 'Input suara tidak didukung browser ini. Coba Chrome atau Edge terbaru.' }}
              </p>
            </div>

            <section v-if="!hasStartedTask" class="capabilities-panel" aria-labelledby="capabilities-title">
              <div class="capabilities-heading">
                <div>
                  <p class="eyebrow">AVAILABLE CAPABILITIES</p>
                  <h2 id="capabilities-title">Apa yang bisa Aether lakukan</h2>
                </div>
                <span>AKSI TERBATAS</span>
              </div>
              <div class="capability-grid">
                <button v-for="capability in capabilities" :key="capability.name" type="button" class="capability-card" @click="useSuggestedPrompt(capability.prompt)">
                  <span class="capability-icon" aria-hidden="true">{{ capability.icon }}</span>
                  <span class="capability-copy">
                    <strong>{{ capability.name }}</strong>
                    <small>{{ capability.detail }}</small>
                  </span>
                  <span class="capability-action" aria-hidden="true">＋</span>
                </button>
              </div>
            </section>
          </section>

          <aside v-if="hasStartedTask" class="artifact-pane" aria-labelledby="artifact-title">
            <header class="task-pane-heading">
              <div>
                <p class="eyebrow">OUTPUT / ARTIFACTS</p>
                <h2 id="artifact-title">Hasil task</h2>
              </div>
              <span class="output-state" :class="{ ready: latestAssistantOutput && !busy, running: busy }">
                <span class="status-dot" />
                {{ busy ? 'Updating' : latestAssistantOutput ? 'Ready' : 'Waiting' }}
              </span>
            </header>

            <section class="artifact-card primary-artifact">
              <div class="artifact-card-heading">
                <span>AGENT RESPONSE</span>
                <span class="artifact-kind">REPORT</span>
              </div>
              <div v-if="latestAssistantOutput" class="task-output message-markdown" v-html="renderMessageMarkdown(latestAssistantOutput)" />
              <p v-else-if="busy" class="artifact-placeholder"><span class="status-dot running" />Menunggu hasil pertama dari Aether…</p>
              <p v-else class="artifact-placeholder">Hasil, ringkasan, dan jawaban akhir akan muncul di sini.</p>
            </section>

            <details v-if="conversationHistory.length" class="artifact-section conversation-history">
              <summary>Riwayat percakapan <span>{{ conversationHistory.length }}</span></summary>
              <article
                v-for="message in conversationHistory"
                :key="message.id"
                class="history-message"
                :class="message.role"
              >
                <header>
                  <strong>{{ message.role === 'assistant' ? 'Aether' : 'Kamu' }}</strong>
                  <time :datetime="message.created_at">{{ formatActivityTime(message.created_at) }}</time>
                </header>
                <div class="message-markdown" v-html="renderMessageMarkdown(message.content)" />
              </article>
            </details>

            <section v-if="currentPlanProgress.some((step) => step.status === 'completed' && stepSummary(step.index))" class="artifact-section">
              <div class="artifact-section-heading">
                <h3>Catatan langkah</h3>
                <span>{{ currentPlanProgress.filter((step) => step.status === 'completed' && stepSummary(step.index)).length }}</span>
              </div>
              <article v-for="step in currentPlanProgress" :key="step.index">
                <template v-if="step.status === 'completed' && stepSummary(step.index)">
                  <p>{{ step.description }}</p>
                  <span>{{ stepSummary(step.index) }}</span>
                </template>
              </article>
            </section>

            <section v-if="currentToolEvents.some((event) => event.type === 'tool.completed' && event.data.output !== undefined)" class="artifact-section tool-artifacts">
              <div class="artifact-section-heading">
                <h3>Tool outputs</h3>
                <span>{{ currentToolEvents.filter((event) => event.type === 'tool.completed' && event.data.output !== undefined).length }}</span>
              </div>
              <details v-for="event in currentToolEvents.filter((item) => item.type === 'tool.completed' && item.data.output !== undefined)" :key="event.event_id">
                <summary><span class="tool-output-icon">✓</span>{{ String(event.data.tool || 'Tool') }}</summary>
                <pre>{{ formatRunValue(event.data.output) }}</pre>
              </details>
            </section>

            <section v-if="artifacts.length" class="artifact-section saved-artifacts">
              <div class="artifact-section-heading">
                <h3>Saved artifacts</h3>
                <span>{{ artifacts.length }}</span>
              </div>
              <details v-for="artifact in artifacts" :key="artifact.id">
                <summary><span class="tool-output-icon">◆</span>{{ artifact.title }}</summary>
                <div class="artifact-preview">
                  <span>{{ artifact.kind }} · {{ artifact.mime_type }}</span>
                  <div v-if="artifact.mime_type.includes('markdown') || artifact.mime_type.includes('text')" class="message-markdown" v-html="renderMessageMarkdown(artifact.content)" />
                  <pre v-else>{{ artifact.content }}</pre>
                </div>
              </details>
            </section>

            <section v-if="latestAssistantCitations.length" class="artifact-section citation-artifacts">
              <div class="artifact-section-heading">
                <h3>Sources</h3>
                <span>{{ latestAssistantCitations.length }}</span>
              </div>
              <a v-for="citation in latestAssistantCitations" :key="citation.url" :href="citation.url" target="_blank" rel="noopener noreferrer">
                <strong>{{ citation.title || citation.url }}</strong>
                <span>{{ citation.url }}</span>
                <small v-if="citation.snippet">{{ citation.snippet }}</small>
              </a>
            </section>

            <section v-if="rollbackTaskId" class="artifact-section rollback-artifacts">
              <button type="button" @click="rollbackCreatedTask">
                Undo · hapus tugas yang baru dibuat
              </button>
            </section>

            <div v-if="currentRunEvents.length" class="usage-meter artifact-usage" aria-label="Penggunaan model">
              <p class="agent-list-label">RUN USAGE</p>
              <div><span>Token</span><strong>{{ formatUsageCount(currentUsage.totalTokens ?? 0) }}</strong></div>
              <div><span>Input / output</span><strong>{{ formatUsageCount(currentUsage.promptTokens ?? 0) }} / {{ formatUsageCount(currentUsage.completionTokens ?? 0) }}</strong></div>
              <div><span>Panggilan model</span><strong>{{ formatUsageCount(currentUsage.modelCalls ?? 0) }}</strong></div>
              <div><span>Biaya dilaporkan</span><strong>{{ formatReportedCost(currentUsage.reportedCost) }}</strong></div>
              <small v-if="currentUsage.costLimit !== undefined">Batas biaya: {{ formatReportedCost(currentUsage.costLimit) }} · berdasarkan laporan provider</small>
            </div>
          </aside>
        </div>
      </section>

      <MemoryWorkspace
        v-if="workspaceView === 'memory'"
        v-model:memory-content="memoryContent"
        v-model:memory-type="memoryType"
        v-model:memory-importance="memoryImportance"
        v-model:memory-search="memorySearch"
        v-model:memory-category-filter="memoryCategoryFilter"
        v-model:show-archived-memories="showArchivedMemories"
        :active-memory-count="activeMemoryCount"
        :archived-memory-count="archivedMemoryCount"
        :busy="busy"
        :error-message="errorMessage"
        :memories="memories"
        :visible-memories="visibleMemories"
        @save-memory="saveMemory"
        @set-memory-active="setMemoryActive"
        @delete-memory="deleteMemory"
      />

      <div v-if="currentApprovalModal" class="approval-overlay" role="presentation" @click.self="dismissApprovalModal">
        <section class="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-dialog-title">
          <button class="approval-close" type="button" aria-label="Tutup detail persetujuan" @click="dismissApprovalModal">×</button>
          <p class="eyebrow approval-eyebrow">ACTION NEEDS APPROVAL</p>
          <h2 id="approval-dialog-title">Aether meminta persetujuan</h2>
          <p class="approval-description">
            {{ currentApprovalModal.tool_name === 'create_task' ? 'Aether ingin membuat tugas berikut. Tugas belum dibuat sampai kamu menyetujuinya.' : 'Tinjau detail tindakan ini sebelum memutuskan.' }}
          </p>
          <div class="approval-action-name">
            <span>TOOL</span>
            <strong>{{ currentApprovalModal.tool_name }}</strong>
          </div>
          <pre class="approval-arguments">{{ formatRunValue(currentApprovalModal.tool_arguments) }}</pre>
          <div class="approval-dialog-actions">
            <button type="button" class="approval-deny" :disabled="busy" @click="decideApproval(currentApprovalModal, false)">Tolak</button>
            <button type="button" class="approval-allow" :disabled="busy" @click="decideApproval(currentApprovalModal, true)">
              {{ busy ? 'Memproses…' : 'Setujui tindakan' }}
            </button>
          </div>
        </section>
      </div>
      </div>
    </section>
  </main>
</template>

<style>
:root {
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #080b10;
  color: #e7eaf0;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; min-height: 100vh; }
button, input, textarea, select { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.62; }
:focus-visible { outline: 2px solid #72dfbf; outline-offset: 2px; }

.app-shell { min-height: 100vh; background: #080b10; }
.topbar { height: 72px; display: flex; align-items: center; justify-content: space-between; padding: 0 5vw; border-bottom: 1px solid #ffffff0f; }
.brand { display: inline-flex; align-items: center; width: 108px; height: 30px; text-decoration: none; }
.brand img { display: block; width: 100%; height: 100%; object-fit: contain; }
.topbar-right { display: flex; align-items: center; gap: 20px; color: #9aa5b5; font-size: 12px; }
.backend-indicator { display: inline-flex; align-items: center; gap: 8px; }
.indicator-dot { width: 7px; height: 7px; border-radius: 50%; background: #d3a64e; }
.backend-indicator.connected .indicator-dot { background: #5bd6a4; }
.backend-indicator.unavailable .indicator-dot { background: #ec6c72; }
.backend-error { max-width: 260px; overflow: hidden; color: #ff9a9f; text-overflow: ellipsis; white-space: nowrap; }
.user-label { color: #dce3ed; }
.sign-out { padding: 7px 12px; border: 1px solid #ffffff20; border-radius: 8px; background: transparent; color: #dce3ed; }
.auth-layout { width: min(1120px, 90vw); min-height: calc(100vh - 72px); margin: auto; display: grid; grid-template-columns: 1.1fr 0.8fr; align-items: center; gap: 12%; padding: 55px 0; }
.eyebrow { color: #71dabe; font-size: 10px; font-weight: 700; letter-spacing: 0.19em; }
.intro h1 { margin: 22px 0; font-size: clamp(42px, 5.5vw, 72px); line-height: 1.06; letter-spacing: -0.055em; }
.intro h1 span { color: #87a2bd; }
.intro-copy, .card-copy { color: #9aa5b5; font-size: 14px; line-height: 1.8; }
.intro-copy { max-width: 440px; }
.model-chips { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 30px; }
.model-chips span { padding: 9px 12px; border: 1px solid #ffffff14; border-radius: 999px; color: #bac6d3; font-size: 11px; }
.auth-card { padding: 30px; border: 1px solid #ffffff18; border-radius: 18px; background: #111722d9; box-shadow: 0 25px 80px #0005; }
.auth-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 4px; border-radius: 10px; background: #090d13; }
.auth-tabs button { padding: 10px; border: 0; border-radius: 7px; background: transparent; color: #8d99a9; font-size: 12px; }
.auth-tabs button.active { background: #1c2633; color: #eef4fa; }
.auth-card h2 { margin: 26px 0 4px; font-size: 20px; letter-spacing: -0.03em; }
.card-copy { margin: 0 0 23px; font-size: 12px; }
.field-label { display: grid; gap: 8px; margin-top: 15px; color: #b6c0cd; font-size: 11px; }
.field-label input { width: 100%; padding: 12px 13px; border: 1px solid #ffffff18; border-radius: 9px; outline: none; background: #090d13; color: #f2f5f8; font-size: 13px; }
.field-label input:focus, .composer:focus-within { border-color: #65cfb0aa; }
.primary-button { width: 100%; margin-top: 23px; padding: 13px; border: 0; border-radius: 9px; background: #72dfbf; color: #07110e; font-weight: 700; font-size: 12px; }
.privacy-note { margin: 14px 0 0; color: #687485; text-align: center; font-size: 10px; }
.error-message { color: #ff9a9f; font-size: 12px; line-height: 1.5; }
.startup-state { min-height: calc(100vh - 72px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #9aa5b5; font-size: 12px; text-align: center; }
.startup-state p { margin: 0; }
.startup-state .error-message { max-width: min(520px, 85vw); }

.workspace { min-height: calc(100vh - 72px); display: grid; grid-template-columns: 238px minmax(0, 1fr); }
.sidebar { max-height: calc(100vh - 72px); overflow-y: auto; padding: 24px 14px; border-right: 1px solid #ffffff10; background: #0b0f16a8; }
.new-chat { width: 100%; padding: 11px 12px; border: 1px solid #ffffff20; border-radius: 8px; background: #121923; color: #e9eff5; text-align: left; font-size: 12px; transition: background 140ms ease, border-color 140ms ease; }
.new-chat:hover { border-color: #72dfbf66; background: #17212b; }
.new-chat span { margin-right: 8px; color: #72dfbf; font-size: 17px; vertical-align: -1px; }
.workspace-nav { display: grid; gap: 4px; margin: 18px 0 24px; padding-bottom: 15px; border-bottom: 1px solid #ffffff10; }
.workspace-nav button { display: flex; align-items: center; gap: 10px; padding: 10px; border: 0; border-radius: 7px; background: transparent; color: #9da9b7; text-align: left; font-size: 11px; }
.workspace-nav button:hover, .workspace-nav button.selected { background: #17212d; color: #e5ecf2; }
.workspace-nav button > span:first-child { width: 16px; color: #72dfbf; text-align: center; font-size: 15px; }
.nav-count { margin-left: auto; color: #72dfbf; font-size: 10px; font-variant-numeric: tabular-nums; }
.sidebar-section-heading { display: flex; align-items: center; justify-content: space-between; }
.sidebar-heading { margin: 20px 9px 10px; color: #687586; font-size: 9px; font-weight: 700; letter-spacing: 0.18em; }
.conversation-search { display: block; margin: 0 0 8px; }
.conversation-search input { width: 100%; padding: 8px 9px; border: 1px solid #ffffff14; border-radius: 6px; outline: none; background: #090d13; color: #dce4ec; font-size: 10px; }
.conversation-search input:focus { border-color: #72dfbf88; }
.conversation-item { width: 100%; display: flex; align-items: center; gap: 9px; overflow: hidden; margin: 3px 0; padding: 10px 9px; border: 0; border-radius: 8px; background: transparent; color: #9da9b7; text-align: left; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.conversation-item.selected, .conversation-item:hover { background: #17212d; color: #e5ecf2; }
.conversation-icon { color: #6bd9b9; }
.empty-history { padding: 0 9px; color: #687586; font-size: 11px; }
.sidebar-empty { margin: 0; padding: 0 9px; color: #687586; font-size: 10px; line-height: 1.5; }
.sidebar-card { margin: 8px 0; padding: 10px; border: 1px solid #ffffff14; border-radius: 9px; background: #111722; }
.sidebar-card p { margin: 0 0 5px; color: #e2e8ef; font-size: 11px; font-weight: 600; }
.sidebar-card > span { display: block; color: #929eac; font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.approval-actions { display: flex; gap: 7px; margin-top: 9px; }
.approval-actions button { padding: 7px 9px; border: 1px solid #ffffff1c; border-radius: 6px; background: #18222e; color: #dce5ec; font-size: 9px; }
.approval-actions button:first-child { border-color: #72dfbf55; color: #72dfbf; }
.chat-area { min-width: 0; height: calc(100vh - 72px); display: flex; flex-direction: column; padding: 27px clamp(20px, 4vw, 58px) 20px; }
.chat-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.chat-heading .eyebrow { margin: 0 0 9px; }
.chat-heading h1 { margin: 0; font-size: clamp(20px, 2.4vw, 29px); letter-spacing: -0.04em; }
.model-select-label { display: grid; gap: 6px; color: #6f7b8b; font-size: 8px; letter-spacing: 0.14em; }
.model-select-label select { min-width: 185px; padding: 9px 10px; border: 1px solid #ffffff20; border-radius: 8px; background: #111722; color: #dfe7ef; font-size: 10px; letter-spacing: normal; }
.model-purpose { max-width: 230px; color: #8a96a4; font-size: 9px; letter-spacing: normal; line-height: 1.4; }
.agent-workspace { width: min(980px, 100%); margin: 20px auto 0; padding: 15px 17px 13px; border: 1px solid #ffffff12; border-radius: 10px; background: #0d131c; }
.activity-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.activity-heading .eyebrow { margin: 0 0 5px; font-size: 8px; }
.activity-heading h2 { margin: 0; color: #e3e9ef; font-size: 13px; font-weight: 600; letter-spacing: -0.01em; }
.activity-status { display: inline-flex; align-items: center; gap: 7px; color: #84909e; font-size: 9px; }
.activity-status.connected { color: #72dfbf; }
.activity-status.connecting { color: #d3a64e; }
.connection-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.run-overview { display: grid; grid-template-columns: minmax(140px, 0.7fr) minmax(0, 1.6fr); align-items: stretch; gap: 12px; margin-top: 13px; padding: 11px; border: 1px solid #ffffff0d; border-radius: 7px; background: #0a0f16; }
.run-overview-copy { display: grid; align-content: center; justify-items: start; gap: 5px; min-width: 0; }
.run-kicker, .route-node-label { color: #738090; font-size: 8px; font-weight: 700; letter-spacing: 0.13em; }
.run-overview-copy strong { color: #e2e8ef; font-size: 12px; font-weight: 600; }
.run-overview-copy > span:last-child { overflow: hidden; max-width: 100%; color: #778393; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.route-track { display: grid; grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr); align-items: center; gap: 7px; }
.route-node { min-width: 0; display: grid; gap: 4px; padding: 9px 10px; border: 1px solid #ffffff10; border-radius: 6px; background: #101721; }
.route-node strong { overflow: hidden; color: #dce4ec; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.route-node > span:last-child { overflow: hidden; color: #788493; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.route-node-selected { border-color: #72dfbf4d; background: #102019; }
.route-node-selected .route-node-label { color: #72dfbf; }
.route-arrow { color: #657384; text-align: center; font-size: 14px; }
.agent-list-label { margin: 13px 0 0; color: #657282; font-size: 8px; font-weight: 700; letter-spacing: 0.12em; }
.agent-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 7px; margin: 13px 0 0; padding: 0; list-style: none; }
.agent-row { min-width: 0; display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 9px 10px; border: 1px solid #ffffff0d; border-radius: 7px; background: #111822; }
.agent-row.core-agent { grid-column: 1 / -1; }
.agent-row.selected-agent { border-color: #72dfbf4d; background: #101b19; }
.agent-indicator { width: 7px; height: 7px; border-radius: 50%; background: #596573; }
.agent-indicator.thinking, .agent-indicator.approval { background: #d3a64e; }
.agent-indicator.working { background: #72dfbf; }
.agent-indicator.completed { background: #6a9c8b; }
.agent-indicator.error { background: #ec6c72; }
.agent-copy { min-width: 0; display: grid; gap: 3px; }
.agent-name { overflow: hidden; color: #dce4ec; font-size: 10px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.agent-description { overflow: hidden; color: #778393; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.agent-state { color: #808d9b; font-size: 8px; white-space: nowrap; }
.agent-state.thinking, .agent-state.approval { color: #d3a64e; }
.agent-state.working { color: #72dfbf; }
.agent-state.completed { color: #8ab9a8; }
.agent-state.error { color: #ec6c72; }
.event-trail { display: grid; grid-template-columns: 125px minmax(0, 1fr); align-items: start; gap: 10px; margin-top: 11px; padding-top: 10px; border-top: 1px solid #ffffff0d; }
.event-trail > p { margin: 2px 0 0; color: #657282; font-size: 8px; font-weight: 700; letter-spacing: 0.12em; }
.event-trail ul { display: grid; gap: 5px; margin: 0; padding: 0; list-style: none; }
.event-trail li { display: grid; grid-template-columns: 44px minmax(88px, 0.45fr) minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; color: #a9b5c1; font-size: 8px; }
.event-trail time { color: #687586; font-variant-numeric: tabular-nums; }
.event-actor { overflow: hidden; color: #b7c2ce; text-overflow: ellipsis; white-space: nowrap; }
.event-trail li span:last-child { color: #7e8b99; }
.welcome-state { flex: 1; width: min(980px, 100%); display: flex; flex-direction: column; justify-content: center; gap: 22px; margin: 0 auto; padding: 24px 0; }
.welcome-intro .eyebrow { margin: 0 0 11px; }
.welcome-intro h2 { margin: 0; color: #edf2f6; font-size: clamp(25px, 3.2vw, 37px); font-weight: 550; line-height: 1.16; letter-spacing: -0.045em; }
.welcome-intro h2 span { color: #88a99f; }
.welcome-intro > p:last-child { margin: 11px 0 0; color: #8e9aa8; font-size: 12px; }
.prompt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.prompt-card { position: relative; min-height: 83px; display: grid; align-content: start; gap: 8px; padding: 13px 38px 13px 14px; border: 1px solid #ffffff13; border-radius: 8px; background: #101721; color: #dfe6ec; text-align: left; }
.prompt-card:hover { border-color: #72dfbf66; background: #141d27; }
.prompt-card > span:first-child { color: #72dfbf; font-size: 8px; font-weight: 700; letter-spacing: 0.11em; text-transform: uppercase; }
.prompt-card strong { max-width: 440px; color: #c3ccd5; font-size: 10px; font-weight: 450; line-height: 1.5; }
.prompt-card .prompt-arrow { position: absolute; top: 12px; right: 13px; color: #748291; font-size: 13px; }
.messages { flex: 1; overflow-y: auto; width: min(850px, 100%); margin: 25px auto 18px; padding: 0 7px; }
.message { display: flex; gap: 13px; margin: 0 0 24px; }
.message-avatar { flex: 0 0 28px; height: 28px; display: grid; place-items: center; border: 1px solid #ffffff20; border-radius: 9px; background: #151e29; color: #c6d2de; font-size: 10px; }
.message.assistant .message-avatar { border-color: #4cd7ae55; background: #10251f; color: #72dfbf; }
.message-content { min-width: 0; }
.message-author { display: flex; align-items: center; gap: 9px; margin: 0 0 7px; color: #9aa6b5; font-size: 10px; }
.message-markdown { min-width: 0; color: #e2e8ef; font-size: 13px; line-height: 1.75; overflow-wrap: anywhere; }
.message.pending .message-markdown { color: #cbd4dd; }
.message-markdown > :first-child { margin-top: 0; }
.message-markdown > :last-child { margin-bottom: 0; }
.message-markdown p { margin: 0 0 0.8em; }
.message-markdown h1, .message-markdown h2, .message-markdown h3, .message-markdown h4 { margin: 1.15em 0 0.55em; color: #edf2f6; font-weight: 580; line-height: 1.35; letter-spacing: -0.02em; }
.message-markdown h1 { font-size: 1.35em; }
.message-markdown h2 { font-size: 1.2em; }
.message-markdown h3, .message-markdown h4 { font-size: 1.05em; }
.message-markdown ul, .message-markdown ol { display: grid; gap: 0.38em; margin: 0.55em 0 0.9em; padding-left: 1.5em; }
.message-markdown li { padding-left: 0.15em; }
.message-markdown li::marker { color: #72dfbf; }
.message-markdown .task-list-item { list-style: none; margin-left: -1.5em; }
.message-markdown .task-list-item-checkbox { width: 0.95em; height: 0.95em; margin: 0 0.55em 0 0; accent-color: #72dfbf; vertical-align: -0.08em; }
.message-markdown blockquote { margin: 0.9em 0; padding: 0.15em 0 0.15em 1em; border-left: 2px solid #72dfbf66; color: #aab6c2; }
.message-markdown pre { max-width: 100%; overflow-x: auto; margin: 0.8em 0; padding: 12px 14px; border: 1px solid #ffffff12; border-radius: 4px; background: #090d12; color: #d7e3e1; line-height: 1.6; }
.message-markdown pre code { padding: 0; border: 0; background: transparent; color: inherit; }
.message-markdown code { padding: 0.12em 0.38em; border: 1px solid #ffffff12; border-radius: 3px; background: #111820; color: #b7e9d8; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.9em; }
.message-markdown a { color: #83d9bf; text-decoration: underline; text-decoration-color: #83d9bf66; text-underline-offset: 3px; }
.message-markdown hr { margin: 1.1em 0; border: 0; border-top: 1px solid #ffffff18; }
.message-markdown table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.message-markdown th, .message-markdown td { padding: 7px 10px; border: 1px solid #ffffff18; text-align: left; }
.message-markdown th { color: #edf2f6; background: #111820; }
.thinking-label { color: #7f8e9b; font-size: 9px; }
.thinking-placeholder { display: inline-flex; align-items: center; gap: 8px; margin: 0; color: #9ca9b5; font-size: 11px; }
.thinking-placeholder span { width: 7px; height: 7px; border: 1px solid #72dfbf; border-radius: 50%; background: #72dfbf55; }
.composer-wrap { width: min(850px, 100%); margin: auto auto 0; }
.composer { padding: 12px 13px 9px; border: 1px solid #ffffff20; border-radius: 9px; background: #111722; transition: border-color 140ms ease; }
.composer textarea { width: 100%; resize: vertical; min-height: 48px; max-height: 180px; border: 0; outline: none; background: transparent; color: #e9eff5; font-size: 12px; line-height: 1.6; }
.composer textarea::placeholder { color: #667383; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #7c8997; font-size: 9px; }
.composer-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.voice-toggle, .voice-button { padding: 8px 9px; border: 1px solid #ffffff20; border-radius: 4px; background: transparent; color: #aab5c0; font-size: 9px; white-space: nowrap; }
.voice-toggle[aria-pressed="true"] { border-color: #72dfbf55; color: #72dfbf; }
.voice-button:hover:not(:disabled), .voice-toggle:hover:not(:disabled) { border-color: #72dfbf88; color: #dce5ec; }
.voice-button.listening { border-color: #72dfbf88; background: #10251f; color: #72dfbf; }
.voice-privacy, .voice-status { margin: 7px 2px 0; color: #687586; font-size: 8px; line-height: 1.5; }
.voice-status { color: #9aa5b2; }
.send-button { padding: 8px 12px; border: 0; border-radius: 6px; background: #72dfbf; color: #07110e; font-size: 10px; font-weight: 700; }
.chat-error { margin: 0 0 10px; }
.memory-workspace { width: min(1200px, 100%); min-width: 0; height: calc(100vh - 72px); overflow-y: auto; margin: 0 auto; padding: 38px clamp(20px, 5vw, 64px); }
.memory-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 25px; padding-bottom: 24px; border-bottom: 1px solid #ffffff12; }
.memory-header .eyebrow { margin: 0 0 8px; }
.memory-header h1 { margin: 0; color: #edf2f6; font-size: 28px; letter-spacing: -0.04em; }
.memory-header > div:first-child > p:last-child { max-width: 470px; margin: 9px 0 0; color: #8e9aa8; font-size: 11px; line-height: 1.65; }
.memory-counts { display: flex; gap: 8px; }
.memory-counts span { padding: 8px 10px; border: 1px solid #ffffff12; border-radius: 6px; color: #909cab; font-size: 9px; white-space: nowrap; }
.memory-counts strong { color: #dce4ec; font-size: 11px; }
.memory-layout { display: grid; grid-template-columns: minmax(220px, 0.72fr) minmax(0, 1.5fr); align-items: start; gap: 22px; padding-top: 23px; }
.memory-editor { display: grid; gap: 14px; padding: 17px; border: 1px solid #ffffff12; border-radius: 9px; background: #0d131c; }
.memory-editor .eyebrow, .memory-library-heading .eyebrow { margin: 0 0 7px; font-size: 8px; }
.memory-editor h2, .memory-library-heading h2 { margin: 0; color: #e3e9ef; font-size: 14px; font-weight: 600; }
.memory-editor > div > p:last-child { margin: 7px 0 0; color: #85919e; font-size: 10px; line-height: 1.55; }
.memory-field { display: grid; gap: 7px; color: #aeb8c3; font-size: 10px; }
.memory-field select, .memory-field textarea, .memory-search input { width: 100%; padding: 10px 11px; border: 1px solid #ffffff18; border-radius: 6px; outline: none; background: #090d13; color: #e2e8ef; font: inherit; font-size: 10px; }
.memory-field textarea { resize: vertical; line-height: 1.6; }
.memory-field select:focus, .memory-field textarea:focus, .memory-search input:focus { border-color: #72dfbf88; }
.memory-save { margin: 0; cursor: pointer; }
.memory-library { min-width: 0; }
.memory-library-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.archive-toggle { display: inline-flex; align-items: center; gap: 7px; color: #9aa5b2; font-size: 9px; cursor: pointer; }
.archive-toggle input { accent-color: #72dfbf; }
.memory-filters { display: grid; grid-template-columns: minmax(0, 1fr) minmax(130px, 0.38fr); gap: 8px; margin: 13px 0; }
.memory-search { display: block; }
.memory-search input { background: #0d131c; }
.memory-category-filter select { width: 100%; height: 100%; padding: 10px 11px; border: 1px solid #ffffff18; border-radius: 6px; background: #0d131c; color: #e2e8ef; font: inherit; font-size: 10px; }
.memory-category-filter select:focus { outline: 2px solid #72dfbf88; outline-offset: 1px; }
.memory-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.memory-card { padding: 13px 14px 11px; border: 1px solid #ffffff12; border-radius: 8px; background: #0d131c; }
.memory-card-meta, .memory-card-footer, .memory-card-footer > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.memory-category { color: #72dfbf; font-size: 8px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
.memory-status { padding: 4px 7px; border-radius: 999px; background: #173027; color: #82d9b7; font-size: 8px; }
.memory-status.archived { background: #252b33; color: #a2acb7; }
.memory-card > p { margin: 11px 0 13px; color: #d5dde5; font-size: 11px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.memory-card-footer { padding-top: 9px; border-top: 1px solid #ffffff0d; color: #788594; font-size: 8px; }
.memory-card-footer button { padding: 5px 7px; border: 1px solid #ffffff18; border-radius: 5px; background: transparent; color: #aab5c0; font-size: 8px; }
.memory-card-footer button:hover { border-color: #72dfbf66; color: #72dfbf; }
.memory-card-footer .delete-memory:hover { border-color: #ec6c7288; color: #ff9a9f; }
.memory-empty { padding: 24px; border: 1px dashed #ffffff1d; border-radius: 8px; color: #8995a2; font-size: 10px; line-height: 1.6; text-align: center; }
.memory-error { margin: 8px 0; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; clip-path: inset(50%); }

@media (max-width: 760px) {
  .auth-layout { grid-template-columns: 1fr; gap: 30px; padding: 35px 0; }
  .intro h1 { font-size: 45px; }
  .intro-copy { font-size: 12px; }
  .workspace { grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; padding: 10px 14px; border-right: 0; border-bottom: 1px solid #ffffff10; }
  .sidebar-heading { margin: 14px 3px 8px; }
  .workspace-nav { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 8px 0 12px; padding-bottom: 9px; }
  .empty-history { display: none; }
  .new-chat { width: 100%; }
  .conversation-item { width: 100%; }
  .chat-area { height: calc(100vh - 36vh - 72px); min-height: 440px; padding: 18px 16px 16px; }
  .chat-heading { order: 0; align-items: flex-start; }
  .chat-heading h1 { max-width: 210px; font-size: 18px; }
  .model-select-label select { min-width: 125px; max-width: 145px; }
  .model-purpose { max-width: 145px; }
  .agent-workspace { order: 3; margin-top: 14px; padding: 12px; }
  .welcome-state, .messages { order: 1; }
  .composer-wrap { order: 2; }
  .run-overview { grid-template-columns: 1fr; }
  .run-overview-copy { grid-template-columns: auto 1fr; align-items: baseline; column-gap: 8px; }
  .run-overview-copy > span:last-child { grid-column: 1 / -1; }
  .agent-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-row.core-agent { grid-column: 1 / -1; }
  .agent-row { grid-template-columns: 7px minmax(0, 1fr); gap: 7px; padding: 8px; }
  .agent-state { grid-column: 2; }
  .agent-description { white-space: normal; }
  .event-trail { grid-template-columns: 1fr; gap: 7px; }
  .welcome-state { justify-content: flex-start; gap: 18px; padding: 24px 0; }
  .prompt-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .prompt-card { min-height: 65px; }
  .composer-footer { align-items: flex-end; }
  .composer-footer > span { max-width: 35%; line-height: 1.5; }
  .composer-actions { flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
  .voice-toggle, .voice-button, .send-button { padding: 7px 6px; font-size: 8px; }
  .memory-workspace { height: auto; min-height: calc(100vh - 36vh - 72px); overflow: visible; padding: 24px 16px; }
  .memory-header { align-items: flex-start; flex-direction: column; padding-bottom: 18px; }
  .memory-header h1 { font-size: 24px; }
  .memory-layout { grid-template-columns: 1fr; gap: 20px; padding-top: 18px; }
  .memory-filters { grid-template-columns: 1fr; }
}

@media (max-width: 420px) {
  .topbar { height: 62px; padding: 0 16px; }
  .topbar-right { gap: 9px; font-size: 10px; }
  .backend-error { display: none; }
  .workspace-nav button { padding: 9px 7px; }
  .chat-area { height: calc(100vh - 36vh - 62px); padding: 15px 12px 12px; }
  .chat-heading { gap: 8px; }
  .chat-heading h1 { max-width: 160px; font-size: 16px; }
  .model-select-label select { min-width: 115px; max-width: 125px; padding: 8px 6px; font-size: 9px; }
  .model-purpose { max-width: 125px; font-size: 8px; }
  .welcome-state { gap: 12px; padding: 14px 0; }
  .prompt-card { min-height: 60px; gap: 5px; padding: 10px 26px 10px 11px; }
  .prompt-card strong { font-size: 9px; line-height: 1.4; }
  .agent-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-row { grid-template-columns: 7px minmax(0, 1fr); }
  .agent-row.core-agent { grid-column: 1 / -1; }
  .agent-state { grid-column: 2; }
  .agent-description { display: none; }
  .agent-row { padding: 7px; }
  .agent-list { gap: 5px; margin-top: 9px; }
  .agent-workspace { padding: 10px; }
  .run-overview { gap: 8px; margin-top: 9px; padding: 8px; }
  .route-node { gap: 3px; padding: 7px; }
  .agent-list-label { margin-top: 10px; }
  .memory-counts { width: 100%; }
  .memory-counts span { flex: 1; text-align: center; }
  .route-track { grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr); gap: 4px; }
  .route-node { padding: 8px 7px; }
  .route-node strong { font-size: 9px; }
  .event-trail { grid-template-columns: 1fr; }
}

/* Operational workspace treatment: flat surfaces, explicit hierarchy, and compact labels. */
.app-shell { background: #08090d; }
.topbar { padding-right: clamp(16px, 3vw, 42px); padding-left: clamp(16px, 3vw, 42px); border-bottom-color: #ffffff12; }
.workspace { grid-template-columns: 224px minmax(0, 1fr); }
.sidebar { background: #0a0c11; }
.chat-area { padding: 24px clamp(20px, 3vw, 42px) 18px; }
.chat-heading { flex: 0 0 auto; padding-bottom: 17px; border-bottom: 1px solid #ffffff12; }
.chat-heading .eyebrow, .model-select-label, .run-kicker, .route-node-label, .agent-list-label, .event-trail > p {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.chat-heading .eyebrow { color: #788493; font-size: 9px; letter-spacing: 0.12em; }
.chat-heading h1 { font-size: clamp(18px, 2vw, 24px); font-weight: 560; letter-spacing: -0.035em; }
.model-select-label { gap: 5px; font-size: 8px; }
.model-select-label select { border-color: #ffffff1c; border-radius: 4px; background: #0d1117; }
.chat-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(255px, 300px); }
.conversation-workspace { min-width: 0; min-height: 0; display: flex; flex-direction: column; padding: 0 clamp(20px, 3vw, 42px) 0 0; }
.agent-workspace { width: auto; min-height: 0; overflow-y: auto; margin: 0; padding: 19px 0 8px 20px; border: 0; border-left: 1px solid #ffffff12; border-radius: 0; background: transparent; }
.activity-heading { padding-bottom: 14px; border-bottom: 1px solid #ffffff12; }
.activity-heading .eyebrow { color: #788493; font-size: 8px; }
.activity-heading h2 { color: #edf2f6; font-size: 16px; font-weight: 540; letter-spacing: -0.025em; }
.activity-status { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.run-overview { display: grid; gap: 5px; margin-top: 16px; padding: 0 0 14px; border: 0; border-bottom: 1px solid #ffffff12; border-radius: 0; background: transparent; }
.run-kicker, .route-node-label { font-size: 8px; letter-spacing: 0.11em; }
.run-overview > strong { color: #e8edf2; font-size: 13px; font-weight: 550; }
.run-overview > span:last-child, .orchestration-state { color: #788493; font-size: 9px; line-height: 1.5; }
.orchestration-path { display: grid; grid-template-columns: 1fr; gap: 0; margin-top: 16px; }
.orchestration-node { min-width: 0; display: grid; gap: 7px; padding: 0 0 12px; }
.orchestration-identity { display: flex; align-items: center; gap: 9px; min-height: 18px; }
.orchestration-identity strong { overflow: hidden; color: #e4e9ef; font-size: 12px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.orchestration-connector { width: 1px; height: 19px; margin: 0 0 12px 3px; background: #72dfbf55; }
.worker-node { padding: 0 0 15px; }
.worker-node.route-node-selected .route-node-label { color: #72dfbf; }
.worker-node.route-node-selected .orchestration-identity strong { color: #b7e9d8; }
.agent-indicator { flex: 0 0 7px; width: 7px; height: 7px; border-radius: 1px; }
.agent-directory { padding-top: 2px; border-top: 1px solid #ffffff12; }
.agent-list-label { margin: 14px 0 8px; color: #687586; font-size: 8px; letter-spacing: 0.1em; }
.agent-list { display: block; margin: 0; }
.agent-row { min-height: 34px; grid-template-columns: 7px minmax(0, 1fr) auto; gap: 9px; padding: 7px 4px; border: 0; border-bottom: 1px solid #ffffff0b; border-radius: 0; background: transparent; }
.agent-row.selected-agent { border-color: #ffffff0b; border-left: 2px solid #72dfbf; background: #0d1414; }
.agent-name { font-size: 10px; font-weight: 500; }
.agent-state { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.event-trail { display: block; margin-top: 16px; padding-top: 1px; border-top: 0; }
.event-trail ol { display: grid; gap: 0; margin: 0; padding: 0 0 0 9px; border-left: 1px solid #ffffff17; list-style: none; }
.event-trail li { display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 4px 7px; padding: 0 0 12px; color: #9aa5b2; font-size: 9px; line-height: 1.45; }
.event-trail time { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.event-actor { color: #c3ccd5; }
.event-trail li > span:last-child { grid-column: 2; overflow-wrap: anywhere; color: #798593; }
.welcome-state { width: 100%; max-width: 740px; gap: 27px; margin: auto; padding: 32px 0; }
.welcome-intro .eyebrow { margin-bottom: 15px; color: #788493; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; letter-spacing: 0.12em; }
.welcome-intro h2 { max-width: 650px; font-size: clamp(30px, 4vw, 46px); font-weight: 520; line-height: 1.12; letter-spacing: -0.05em; }
.welcome-intro h2 span { color: #a4b9b2; }
.welcome-intro > p:last-child { max-width: 480px; margin-top: 14px; color: #9aa5b2; font-size: 12px; line-height: 1.7; }
.prompt-grid { display: block; border-top: 1px solid #ffffff15; }
.prompt-card { width: 100%; min-height: 0; display: grid; grid-template-columns: 92px minmax(0, 1fr) 16px; align-items: center; gap: 12px; padding: 12px 4px 12px 0; border: 0; border-bottom: 1px solid #ffffff12; border-radius: 0; background: transparent; }
.prompt-card:hover { border-color: #ffffff28; background: transparent; }
.prompt-card > span:first-child { color: #72dfbf; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; letter-spacing: 0.08em; }
.prompt-card strong { max-width: none; color: #cbd3dc; font-size: 10px; font-weight: 450; line-height: 1.5; }
.prompt-card .prompt-arrow { position: static; color: #687586; text-align: right; }
.prompt-card:hover strong, .prompt-card:hover .prompt-arrow { color: #72dfbf; }
.messages { width: 100%; max-width: 780px; padding: 22px 4px 0; }
.message { gap: 12px; margin-bottom: 25px; }
.message-avatar { flex-basis: 24px; height: 24px; border-radius: 4px; background: #10141b; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.message.assistant .message-avatar { border-color: #ffffff1b; background: #101714; }
.message-author { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; }
.composer-wrap { width: 100%; max-width: 780px; padding: 12px 0 0; }
.composer { padding: 11px 12px 9px; border-radius: 5px; background: #0d1117; }
.composer textarea { font-size: 12px; }
.send-button { border-radius: 3px; }
.memory-editor, .memory-card { border-radius: 4px; background: #0b0f14; }
.memory-counts span { border-radius: 3px; }
.memory-status { border-radius: 2px; }
.memory-card-footer button { border-radius: 3px; }
.sidebar-card { border-radius: 4px; background: #0c1016; }
.new-chat, .conversation-item, .workspace-nav button { border-radius: 4px; }

@media (max-width: 900px) {
  .workspace { grid-template-columns: 205px minmax(0, 1fr); }
  .chat-body { grid-template-columns: minmax(0, 1fr) 250px; }
  .conversation-workspace { padding-right: 17px; }
  .agent-workspace { padding-left: 16px; }
}

@media (max-width: 760px) {
  .workspace { grid-template-columns: 1fr; }
  .chat-area { height: calc(100vh - 36vh - 72px); min-height: 480px; padding: 16px; }
  .chat-heading { align-items: center; padding-bottom: 12px; }
  .chat-body { display: flex; flex-direction: column; overflow-y: auto; }
  .conversation-workspace { flex: 1 0 auto; min-height: 0; padding: 0; }
  .welcome-state { flex: 1; gap: 12px; padding: 19px 0 14px; }
  .welcome-intro .eyebrow { margin-bottom: 9px; }
  .welcome-intro h2 { font-size: clamp(26px, 7vw, 34px); }
  .welcome-intro > p:last-child { margin-top: 9px; font-size: 11px; }
  .prompt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
  .prompt-card { grid-template-columns: minmax(0, 1fr) 14px; grid-template-rows: auto auto; gap: 4px; padding: 9px 2px 9px 0; }
  .prompt-card > span:first-child { grid-column: 1 / -1; }
  .prompt-card strong { grid-column: 1; font-size: 9px; }
  .prompt-card .prompt-arrow { grid-column: 2; grid-row: 2; }
  .messages { min-height: 220px; margin: 0 auto 10px; }
  .composer-wrap { margin-top: auto; padding-bottom: 14px; }
  .agent-workspace { flex: 0 0 auto; order: 1; max-height: 34vh; overflow-y: auto; margin-top: 0; padding: 15px 0 4px; border-top: 1px solid #ffffff12; border-left: 0; }
  .activity-heading { padding-bottom: 10px; }
  .run-overview { grid-template-columns: auto 1fr; align-items: baseline; column-gap: 8px; margin-top: 12px; padding-bottom: 10px; }
  .run-overview > span:last-child { grid-column: 1 / -1; }
  .orchestration-path { grid-template-columns: minmax(0, 1fr) 18px minmax(0, 1fr); align-items: center; gap: 7px; margin-top: 12px; }
  .orchestration-node { padding-bottom: 0; }
  .orchestration-connector { width: 100%; height: 1px; margin: 0; }
  .worker-node { padding-bottom: 0; }
  .agent-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
  .agent-row { grid-template-columns: 7px minmax(0, 1fr) auto; }
  .event-trail { display: block; }
  .event-trail ol { grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
  .memory-workspace { height: auto; min-height: calc(100vh - 36vh - 72px); overflow: visible; }
}

@media (max-width: 420px) {
  .chat-area { height: calc(100vh - 36vh - 62px); padding: 13px 12px; }
  .chat-heading { gap: 8px; }
  .chat-heading h1 { max-width: none; font-size: 16px; }
  .model-select-label select { min-width: 115px; max-width: 125px; padding: 8px 6px; font-size: 9px; }
  .model-purpose { max-width: 125px; font-size: 8px; }
  .conversation-workspace { flex-basis: 350px; min-height: 350px; }
  .welcome-state { gap: 13px; padding-top: 18px; }
  .welcome-intro h2 { font-size: 27px; }
  .welcome-intro > p:last-child { font-size: 11px; }
  .prompt-card { grid-template-columns: minmax(0, 1fr) 12px; grid-template-rows: auto auto; gap: 4px; padding: 9px 2px 9px 0; }
  .prompt-card strong { font-size: 9px; }
  .composer-footer > span { max-width: 68%; line-height: 1.5; }
  .agent-list { gap: 0 9px; }
  .agent-row { min-height: 32px; padding: 6px 2px; }
  .event-trail ol { grid-template-columns: 1fr; }
  .memory-counts { width: 100%; }
  .memory-counts span { flex: 1; text-align: center; }
}

/* Conversation landing page follows the supplied compact assistant-workspace reference. */
.topbar { height: 56px; padding: 0 24px; background: #191919; }
.workspace { min-height: calc(100vh - 56px); grid-template-columns: 252px minmax(0, 1fr); background: #191919; }
.sidebar { max-height: calc(100vh - 56px); padding: 17px 10px 22px; background: #1d1d1d; }
.new-chat { padding: 10px 12px; border: 0; border-radius: 7px; background: #373737; color: #f0f0f0; font-size: 12px; }
.new-chat:hover { background: #414141; }
.workspace-nav { gap: 3px; margin: 12px 0 20px; padding-bottom: 15px; }
.workspace-nav button { min-height: 34px; padding: 8px 10px; border-radius: 6px; color: #c3c3c3; }
.workspace-nav button:hover, .workspace-nav button.selected { background: #303030; color: #f4f4f4; }
.workspace-nav button > span:first-child { color: #c8c8c8; }
.sidebar-heading { margin: 18px 7px 9px; color: #c5c5c5; letter-spacing: 0.02em; }
.conversation-search input { padding: 9px 10px; border-color: #ffffff10; border-radius: 6px; background: #252525; }
.conversation-item { min-height: 34px; margin: 2px 0; border-radius: 5px; color: #c7c7c7; }
.conversation-item.selected, .conversation-item:hover { background: #2b2b2b; color: #fff; }
.empty-history, .sidebar-empty { color: #858585; }
.chat-area { height: calc(100vh - 56px); padding: 0 clamp(20px, 5vw, 72px) 28px; background: #191919; }
.chat-heading { min-height: 64px; align-items: center; padding-bottom: 12px; border-bottom-color: #ffffff0b; }
.chat-heading .eyebrow { margin-bottom: 4px; }
.chat-heading h1 { font-size: 18px; }
.chat-body.welcome-chat { grid-template-columns: minmax(0, 1fr); }
.chat-body.welcome-chat .agent-workspace { display: none; }
.chat-body.welcome-chat .conversation-workspace { display: grid; grid-template-rows: auto auto; align-content: center; gap: 25px; padding: 0; }
.welcome-state { width: min(660px, 100%); max-width: 660px; align-items: center; justify-content: center; gap: 25px; padding: 30px 0 20px; text-align: center; }
.welcome-intro { display: flex; flex-direction: column; align-items: center; }
.welcome-mark { width: 42px; height: 42px; margin-bottom: 8px; object-fit: contain; }
.welcome-intro h2 { font-family: Georgia, "Times New Roman", serif; font-size: clamp(32px, 4vw, 43px); font-weight: 400; line-height: 1.15; letter-spacing: -0.035em; }
.welcome-intro h2 span { color: #e2e2e2; }
.welcome-intro > p:last-child { margin-top: 9px; color: #9c9c9c; font-size: 12px; }
.prompt-grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; border: 0; }
.prompt-card { width: auto; min-height: 0; display: inline-flex; align-items: center; gap: 6px; padding: 8px 10px; border: 0; border-radius: 7px; background: #343434; color: #e2e2e2; font-size: 10px; }
.prompt-card:hover { border: 0; background: #414141; color: #fff; }
.prompt-icon { color: #cbd9d4; font-size: 12px; font-weight: 600; }
.chat-body.welcome-chat .composer-wrap { margin: 0 auto; padding: 0; }
.composer { padding: 14px 15px 11px; border: 1px solid #ffffff0c; border-radius: 14px; background: #303030; }
.composer:focus-within { border-color: #72dfbf66; }
.composer textarea { min-height: 55px; font-size: 13px; }
.composer textarea::placeholder { color: #999; }
.composer-footer { min-height: 32px; color: #999; }
.composer-actions { gap: 6px; }
.inline-model-select select { max-width: 164px; padding: 7px 8px; border: 0; border-radius: 6px; background: #3b3b3b; color: #e4e4e4; font-size: 9px; }
.voice-toggle, .voice-button { border-color: transparent; background: #3b3b3b; color: #d3d3d3; }
.voice-toggle[aria-pressed="true"] { border-color: transparent; color: #9ce5cd; }
.voice-button.listening { background: #183229; }
.stop-button { padding: 8px 10px; border: 1px solid #ec6c7266; border-radius: 6px; background: #3b2426; color: #ffb6ba; font-size: 9px; }
.stop-button:hover:not(:disabled) { background: #512d30; }
.send-button { padding: 8px 11px; }
.voice-privacy { margin-top: 6px; color: #747474; text-align: center; }
.voice-status { text-align: center; }
.plan-progress { margin-top: 15px; padding-top: 2px; border-top: 1px solid #ffffff0d; }
.plan-progress ol { display: grid; gap: 6px; margin: 8px 0 0; padding: 0; list-style: none; }
.plan-progress li { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: start; gap: 8px; color: #929eaa; font-size: 10px; line-height: 1.5; }
.plan-step-index { color: #6f7b88; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; }
.plan-step-description { overflow-wrap: anywhere; }
.plan-step-status { color: #687586; font-size: 8px; white-space: nowrap; }
.plan-progress li.in_progress .plan-step-status { color: #d3a64e; }
.plan-progress li.completed .plan-step-status { color: #72dfbf; }
.plan-progress li.stopped .plan-step-status { color: #ec9a82; }
.plan-progress li.paused .plan-step-status { color: #d3a64e; }
.pause-button { padding: 8px 10px; border: 1px solid #d3a64e66; border-radius: 6px; background: #30291c; color: #e8c77d; font-size: 9px; }
.pause-button:hover:not(:disabled) { background: #41371f; }
.usage-meter { display: grid; gap: 7px; margin-top: 14px; padding: 0 0 13px; border-bottom: 1px solid #ffffff12; }
.usage-meter .agent-list-label { margin: 0; }
.usage-meter > div { display: flex; justify-content: space-between; gap: 8px; color: #798593; font-size: 9px; }
.usage-meter strong { color: #c8d1da; font-size: 9px; font-weight: 500; text-align: right; }
.usage-meter small, .process-summary small { color: #687586; font-size: 8px; line-height: 1.5; }
.process-summary { margin-top: 14px; color: #8995a2; font-size: 9px; line-height: 1.55; }
.process-summary summary, .tool-event-details summary { color: #c1cbd4; cursor: pointer; }
.process-summary > p { margin: 9px 0; }
.process-summary ol { display: grid; gap: 9px; margin: 9px 0; padding-left: 17px; }
.process-summary li strong, .process-summary li span { display: block; }
.process-summary li strong { color: #b7c3ce; font-weight: 500; }
.process-summary li span { margin-top: 3px; color: #7f8b98; overflow-wrap: anywhere; }
.tool-event-details { display: grid; gap: 8px; margin-top: 14px; }
.tool-event-details .agent-list-label { margin: 0; }
.tool-event-details details { min-width: 0; padding: 8px; border: 1px solid #ffffff10; background: #0c1118; }
.tool-event-details summary { overflow-wrap: anywhere; font-size: 9px; }
.tool-event-details > details > span { display: block; margin-top: 9px; color: #788493; font-size: 8px; }
.tool-event-details pre { max-height: 160px; overflow: auto; margin: 5px 0 0; padding: 7px; background: #080b10; color: #b6c6d0; font-size: 8px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.tool-error { color: #ec9a82; font-size: 9px; }
.run-controls { display: grid; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #ffffff12; }
.run-controls p { margin: 0; color: #9aa5b2; font-size: 9px; line-height: 1.5; }
.run-controls button { justify-self: start; padding: 8px 10px; border: 1px solid #72dfbf66; border-radius: 4px; background: #10251f; color: #96e5cc; font-size: 9px; }
.run-controls button:hover:not(:disabled) { background: #18352b; }

@media (max-width: 760px) {
  .topbar { height: 56px; padding: 0 16px; }
  .workspace { min-height: calc(100vh - 56px); grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; padding: 10px 12px; }
  .chat-area { height: calc(100vh - 36vh - 56px); min-height: 440px; padding: 0 16px 16px; }
  .chat-body.welcome-chat { display: flex; flex: 1; min-height: 0; overflow: visible; }
  .chat-body.welcome-chat .conversation-workspace { display: grid; flex: 1; min-height: 0; align-content: center; gap: 18px; }
  .chat-body.welcome-chat .welcome-state { flex: 0 0 auto; justify-content: center; gap: 18px; padding: 12px 0; }
  .chat-body.welcome-chat .composer-wrap { flex: 0 0 auto; width: 100%; margin: 0; padding: 0 0 12px; }
  .chat-body.welcome-chat .composer-footer { align-items: flex-end; }
  .chat-body.welcome-chat .composer-footer > span { max-width: 32%; font-size: 8px; }
  .chat-body.welcome-chat .composer-actions { flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
  .chat-body.welcome-chat .inline-model-select select { max-width: 120px; padding: 7px 5px; font-size: 8px; }
  .chat-body.welcome-chat .voice-toggle,
  .chat-body.welcome-chat .voice-button,
  .chat-body.welcome-chat .stop-button,
  .chat-body.welcome-chat .pause-button,
  .chat-body.welcome-chat .send-button { padding: 7px 6px; font-size: 8px; }
}

@media (max-width: 420px) {
  .workspace { min-height: calc(100vh - 62px); grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; }
  .chat-area { height: calc(100vh - 36vh - 62px); min-height: 410px; padding: 0 12px 12px; }
  .chat-body.welcome-chat .welcome-state { gap: 14px; }
  .welcome-mark { width: 36px; height: 36px; }
  .welcome-intro h2 { font-size: 32px; }
  .prompt-grid { gap: 6px; }
  .prompt-card { padding: 7px 8px; }
  .chat-body.welcome-chat .composer { padding: 11px 10px 9px; }
  .chat-body.welcome-chat .composer textarea { min-height: 46px; }
}

@media (max-width: 360px) {
  body { min-width: 0; }
  .topbar { padding-right: 12px; padding-left: 12px; }
  .topbar-right { gap: 8px; font-size: 9px; }
  .user-label { display: none; }
  .chat-body.welcome-chat .composer-footer > span { display: none; }
  .chat-body.welcome-chat .composer-actions { width: 100%; justify-content: space-between; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; }
}

.app-shell { background: #0b0c0f; }
.topbar { background: #0b0c0f; border-bottom-color: #292a2e; }
.workspace { grid-template-columns: 252px minmax(0, 1fr); background: #0b0c0f; }
.sidebar { border-right: 1px solid #292a2e; background: #0d0e11; }
.new-chat { border: 1px solid #33353b; background: #111216; }
.new-chat:hover { border-color: #55575e; background: #15161a; }
.new-chat span, .workspace-nav button > span:first-child { color: #aeb3bb; }
.workspace-nav button:hover, .workspace-nav button.selected { background: #17181c; }
.sidebar-heading { color: #747982; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.conversation-search input { border-color: #2b2c31; background: #101115; }
.conversation-item.selected, .conversation-item:hover { background: #17181c; }
.chat-area { min-height: 0; padding: 0 24px 12px; background: #0b0c0f; }
.chat-heading { min-height: 64px; flex: 0 0 auto; border-bottom-color: #292a2e; }
.chat-heading .eyebrow, .task-pane-heading .eyebrow, .capabilities-heading .eyebrow {
  color: #747982;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9px;
  letter-spacing: 0.12em;
}
.chat-heading h1 { font-size: 17px; font-weight: 550; letter-spacing: -0.02em; }
.task-workspace { min-height: 0; flex: 1; display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(300px, 0.92fr); }
.task-workspace.is-empty { grid-template-columns: minmax(0, 1fr); }
.task-main { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.task-workspace.is-empty .task-main { display: grid; grid-template-rows: minmax(0, 1fr) auto auto minmax(0, 0.45fr); }
.task-landing-intro { width: min(760px, 100%); align-self: end; justify-self: center; padding: 0 8px 18px; }
.task-landing-intro .eyebrow { margin: 0 0 12px; color: #747982; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; letter-spacing: 0.12em; }
.task-landing-intro h2 { margin: 0; color: #edf0f3; font-size: clamp(26px, 3.2vw, 38px); font-weight: 520; line-height: 1.16; letter-spacing: -0.045em; }
.task-landing-intro h2 span { color: #aeb3bb; }
.task-landing-intro > p:last-child { max-width: 610px; margin: 12px 0 0; color: #888d96; font-size: 12px; line-height: 1.7; }
.task-timeline-pane { min-height: 0; flex: 1; overflow-y: auto; padding: 20px 22px 18px 4px; scrollbar-color: #33353b transparent; }
.task-pane-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 15px; border-bottom: 1px solid #292a2e; }
.task-pane-heading .eyebrow { margin: 0 0 5px; }
.task-pane-heading h2 { margin: 0; color: #e8ebef; font-size: 15px; font-weight: 560; letter-spacing: -0.025em; }
.run-state, .output-state { display: inline-flex; align-items: center; gap: 7px; color: #878c95; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; white-space: nowrap; }
.run-state.running, .output-state.running, .output-state.ready { color: #80cfae; }
.run-state.success { color: #80cfae; }
.run-state.approval { color: #d7b86f; }
.run-state.error { color: #d97b7e; }
.status-dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: currentColor; }
.run-summary { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 0; border-bottom: 1px solid #25262a; }
.run-summary-copy { min-width: 0; display: grid; gap: 6px; }
.run-kicker, .run-usage-inline, .artifact-card-heading, .artifact-kind, .capabilities-heading > span, .approval-action-name > span {
  color: #747982;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 8px;
  letter-spacing: 0.1em;
}
.run-summary-copy strong { overflow: hidden; color: #d8dce1; font-size: 11px; font-weight: 500; text-overflow: ellipsis; }
.run-usage-inline { display: flex; flex: 0 0 auto; gap: 10px; letter-spacing: 0; }
.tool-activity { display: flex; align-items: center; gap: 8px; margin-top: 14px; padding: 9px 10px; border: 1px solid #292a2e; color: #9297a0; font-size: 9px; }
.tool-activity > span:first-child { color: #aaaeb5; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
.tool-activity strong { color: #c9cdd2; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; font-weight: 500; }
.tool-activity > span:last-child { margin-left: auto; color: #7e838c; }
.tool-activity.running { border-color: #375142; }
.tool-activity.running > span:first-child, .tool-activity.running strong { color: #80cfae; }
.tool-activity.failed { border-color: #583638; }
.tool-activity.failed > span:first-child, .tool-activity.failed strong { color: #d97b7e; }
.plan-progress { margin-top: 18px; padding-top: 0; border: 0; }
.plan-progress .agent-list-label, .task-event-log > .agent-list-label, .timeline-workers > .agent-list-label { margin: 0 0 9px; }
.plan-progress ol { gap: 0; margin-top: 0; border-top: 1px solid #25262a; }
.plan-progress li { grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; gap: 9px; min-height: 38px; padding: 7px 0; border-bottom: 1px solid #25262a; color: #9da2aa; font-size: 10px; }
.plan-step-index { color: #777c85; font-size: 9px; }
.plan-progress li.completed .plan-step-index, .plan-progress li.completed .plan-step-status { color: #80cfae; }
.plan-progress li.in_progress .plan-step-status, .plan-progress li.paused .plan-step-status { color: #d7b86f; }
.plan-progress li.stopped .plan-step-status { color: #d97b7e; }
.task-event-log { margin-top: 19px; }
.task-event-log ol { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.task-event-log li { min-width: 0; display: grid; grid-template-columns: 16px 40px minmax(0, 1fr); align-items: start; gap: 8px; padding: 9px 0; border-bottom: 1px solid #222328; color: #989da5; }
.timeline-marker { width: 14px; height: 14px; display: grid; place-items: center; border: 1px solid #393b41; border-radius: 50%; color: #777c85; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; line-height: 1; }
.task-event-log li.success .timeline-marker { border-color: #375142; color: #80cfae; }
.task-event-log li.running .timeline-marker { border-color: #375142; color: #80cfae; }
.task-event-log li.approval .timeline-marker { border-color: #594d30; color: #d7b86f; }
.task-event-log li.error .timeline-marker { border-color: #583638; color: #d97b7e; }
.task-event-log time { padding-top: 2px; color: #717680; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.timeline-entry { min-width: 0; display: grid; gap: 3px; }
.timeline-entry strong { color: #c4c8ce; font-size: 10px; font-weight: 500; line-height: 1.45; }
.timeline-entry > span { color: #737882; font-size: 8px; }
.timeline-empty { color: #777c85; font-size: 10px; }
.timeline-workers { margin-top: 17px; padding-top: 14px; border-top: 1px solid #292a2e; }
.timeline-workers .agent-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 2px 12px; margin: 0; }
.timeline-workers .agent-row { min-height: 30px; grid-template-columns: 7px minmax(0, 1fr) auto; padding: 6px 2px; border: 0; border-bottom: 1px solid #222328; background: transparent; }
.timeline-workers .agent-name { color: #b7bcc4; font-size: 9px; }
.timeline-workers .agent-state { font-size: 8px; }
.agent-indicator.working, .agent-state.working, .agent-indicator.completed, .agent-state.completed { background-color: #80cfae; color: #80cfae; }
.agent-indicator.thinking, .agent-state.thinking, .agent-indicator.approval, .agent-state.approval { background-color: #d7b86f; color: #d7b86f; }
.agent-indicator.error, .agent-state.error { background-color: #d97b7e; color: #d97b7e; }
.process-summary { margin-top: 15px; padding-top: 11px; border-top: 1px solid #292a2e; color: #858a93; font-size: 9px; }
.process-summary summary { color: #b9bec5; font-size: 9px; }
.process-summary li strong { color: #b9bec5; }
.process-summary li span { color: #818690; }
.composer-wrap { position: sticky; z-index: 2; bottom: 0; width: auto; max-width: none; margin: 0; padding: 12px 22px 7px 4px; background: linear-gradient(180deg, #0b0c0f00 0%, #0b0c0f 18%); }
.task-composer { padding: 9px 10px 8px; border-color: #303238; border-radius: 7px; background: #101115; }
.task-composer:focus-within { border-color: #777b83; }
.task-composer textarea { min-height: 42px; max-height: 140px; resize: vertical; font-size: 12px; }
.task-composer textarea::placeholder { color: #747982; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.composer-footer { min-height: 29px; color: #747982; font-size: 8px; }
.composer-actions { flex-wrap: wrap; justify-content: flex-end; gap: 5px; }
.inline-model-select select, .voice-toggle, .voice-button { max-width: 152px; padding: 6px 7px; border: 1px solid #303238; border-radius: 4px; background: #111216; color: #aeb3bb; font-size: 8px; }
.voice-toggle[aria-pressed="true"] { border-color: #3a4b41; color: #aeb3bb; }
.voice-button.listening { border-color: #594d30; background: #171510; color: #d7b86f; }
.send-button { padding: 7px 10px; border: 1px solid #d5d7db; border-radius: 4px; background: #d5d7db; color: #111216; font-size: 9px; }
.send-button:hover:not(:disabled) { background: #f0f1f2; }
.pause-button { padding: 7px 9px; border: 1px solid #594d30; border-radius: 4px; background: #171510; color: #d7b86f; font-size: 8px; }
.stop-button { padding: 7px 9px; border: 1px solid #583638; border-radius: 4px; background: #171113; color: #d97b7e; font-size: 8px; }
.voice-privacy { text-align: left; }
.goal-composer-wrap { position: static; grid-row: 2; width: min(760px, 100%); justify-self: center; padding: 0 8px; background: transparent; }
.goal-composer { padding: 13px 14px 10px; border-color: #383a40; }
.goal-composer textarea { min-height: 52px; font-size: 14px; }
.goal-composer .composer-footer > span { color: #777c85; }
.capabilities-panel { grid-row: 3; width: min(760px, 100%); justify-self: center; align-self: start; padding: 22px 8px 0; }
.capabilities-heading { display: flex; align-items: end; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.capabilities-heading .eyebrow { margin: 0 0 5px; }
.capabilities-heading h2 { margin: 0; color: #d9dde2; font-size: 12px; font-weight: 550; }
.capabilities-heading > span { font-size: 7px; }
.capability-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid #292a2e; }
.capability-card { min-width: 0; display: grid; grid-template-columns: 26px minmax(0, 1fr) 12px; align-items: center; gap: 9px; padding: 12px 7px; border: 0; border-bottom: 1px solid #292a2e; background: transparent; color: #c5c9cf; text-align: left; }
.capability-card:nth-child(odd) { border-right: 1px solid #292a2e; }
.capability-card:hover { background: #101115; }
.capability-icon { width: 24px; height: 24px; display: grid; place-items: center; border: 1px solid #34363c; border-radius: 4px; color: #b7bbc2; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10px; }
.capability-copy { min-width: 0; display: grid; gap: 4px; }
.capability-copy strong { color: #d3d6db; font-size: 9px; font-weight: 550; }
.capability-copy small { color: #7f848d; font-size: 8px; line-height: 1.45; }
.capability-action { color: #777c85; font-size: 12px; }
.artifact-pane { min-width: 0; min-height: 0; overflow-y: auto; padding: 20px 4px 20px 20px; border-left: 1px solid #292a2e; scrollbar-color: #33353b transparent; }
.artifact-pane .task-pane-heading { padding-bottom: 15px; }
.artifact-card { margin-top: 16px; padding: 13px; border: 1px solid #292a2e; background: #0e0f12; }
.artifact-card-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 10px; border-bottom: 1px solid #25262a; }
.artifact-kind { color: #777c85; font-size: 7px; }
.task-output { padding-top: 12px; color: #cbd0d7; font-size: 11px; line-height: 1.7; }
.task-output pre, .artifact-section pre { max-width: 100%; overflow: auto; border-color: #292a2e; border-radius: 3px; background: #090a0d; color: #c4cad2; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; }
.task-output code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.artifact-placeholder { display: flex; align-items: center; gap: 8px; min-height: 58px; margin: 0; padding-top: 12px; color: #7d828b; font-size: 10px; line-height: 1.5; }
.artifact-placeholder .status-dot.running { color: #80cfae; }
.artifact-section { margin-top: 18px; }
.artifact-section-heading { display: flex; align-items: center; justify-content: space-between; padding-bottom: 8px; border-bottom: 1px solid #292a2e; }
.artifact-section-heading h3 { margin: 0; color: #c5c9cf; font-size: 10px; font-weight: 550; }
.artifact-section-heading > span { color: #777c85; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.artifact-section article { padding: 10px 0; border-bottom: 1px solid #222328; }
.artifact-section article p { margin: 0 0 5px; color: #bfc4cb; font-size: 9px; }
.artifact-section article > span { display: block; color: #818690; font-size: 9px; line-height: 1.55; overflow-wrap: anywhere; }
.tool-artifacts details { padding: 9px 0; border-bottom: 1px solid #222328; }
.tool-artifacts summary { color: #bec3ca; cursor: pointer; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; }
.tool-output-icon { margin-right: 8px; color: #80cfae; }
.tool-artifacts pre { max-height: 220px; margin: 9px 0 0; padding: 9px; white-space: pre-wrap; overflow-wrap: anywhere; }
.artifact-usage { margin-top: 18px; }
.approval-heading { margin-top: 20px; padding: 9px 8px; border: 1px solid #292a2e; }
.approval-heading .sidebar-heading { margin: 0; }
.approval-count { color: #777c85; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; }
.approval-heading.has-approvals { border-color: #594d30; background: #14120d; }
.approval-heading.has-approvals .sidebar-heading, .approval-heading.has-approvals .approval-count { color: #d7b86f; }
.approval-card { border-color: #594d30; background: #14120d; }
.approval-card p { color: #e0c782; }
.approval-actions button:first-child { border-color: #594d30; color: #d7b86f; background: #19160e; }
.approval-empty { margin-top: 9px; }
.approval-overlay { position: fixed; z-index: 20; inset: 0; display: grid; place-items: center; padding: 18px; background: #000a; backdrop-filter: blur(5px); }
.approval-dialog { position: relative; width: min(480px, 100%); padding: 26px; border: 1px solid #51472e; background: #101115; box-shadow: 0 24px 90px #0009; }
.approval-close { position: absolute; top: 13px; right: 13px; width: 28px; height: 28px; border: 1px solid #303238; background: transparent; color: #aeb3bb; font-size: 17px; }
.approval-eyebrow { margin: 0 0 12px; color: #d7b86f; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; letter-spacing: 0.12em; }
.approval-dialog h2 { margin: 0; color: #e5e8ec; font-size: 20px; font-weight: 550; }
.approval-description { margin: 10px 0 18px; color: #969ba4; font-size: 11px; line-height: 1.6; }
.approval-action-name { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-top: 1px solid #292a2e; border-bottom: 1px solid #292a2e; }
.approval-action-name strong { color: #d7b86f; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10px; font-weight: 500; }
.approval-arguments { max-height: 180px; overflow: auto; margin: 12px 0; padding: 11px; border: 1px solid #292a2e; background: #0b0c0f; color: #c1c6cd; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.approval-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.approval-dialog-actions button { padding: 9px 12px; border: 1px solid #393b41; background: transparent; color: #c5c9cf; font-size: 10px; }
.approval-dialog-actions .approval-allow { border-color: #d7b86f; background: #d7b86f; color: #17140c; font-weight: 600; }
.approval-dialog-actions .approval-deny:hover:not(:disabled) { border-color: #d97b7e; color: #d97b7e; }
.brand { width: auto; height: 32px; gap: 9px; }
.brand-mark { position: relative; width: 25px; height: 25px; display: grid; place-items: center; }
.brand-mark img { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 0 4px #54e4b422); transition: filter 180ms ease; }
.brand-mark.executing img { filter: drop-shadow(0 0 7px #54e4b466); }
.brand-mark.approval img { filter: sepia(1) saturate(1.2) brightness(1.1); }
.brand-mark.error img { filter: sepia(0.8) saturate(2) hue-rotate(300deg); }
.brand-mark.thinking img { animation: aether-thinking-pulse 1.8s ease-in-out infinite; }
.brand-approval-dot { position: absolute; top: -1px; right: -2px; width: 7px; height: 7px; border: 1px solid #0b0c0f; border-radius: 50%; background: #d7b86f; box-shadow: 0 0 7px #d7b86f88; }
.brand-name { color: #e5e8ec; font-size: 13px; font-weight: 650; letter-spacing: -0.035em; }
.task-pane-heading h2 { display: flex; align-items: center; gap: 8px; }
.timeline-brain { width: 15px; height: 15px; display: inline-flex; flex: 0 0 15px; }
.timeline-brain img { width: 100%; height: 100%; object-fit: contain; filter: grayscale(1) brightness(1.3) opacity(0.68); }
.timeline-brain.executing img { filter: drop-shadow(0 0 5px #54e4b466); }
.timeline-brain.approval img { filter: sepia(1) saturate(1.2) brightness(1.1); }
.timeline-brain.error img { filter: sepia(0.8) saturate(2) hue-rotate(300deg); }
.timeline-brain.thinking img { animation: aether-thinking-pulse 1.8s ease-in-out infinite; }
@keyframes aether-thinking-pulse {
  0%, 100% { opacity: 0.62; transform: scale(0.94); }
  50% { opacity: 1; transform: scale(1.04); }
}

@media (max-width: 900px) {
  .workspace { grid-template-columns: 210px minmax(0, 1fr); }
  .task-workspace { grid-template-columns: minmax(0, 1fr) minmax(270px, 0.85fr); }
  .artifact-pane { padding-left: 15px; }
  .task-timeline-pane, .composer-wrap { padding-right: 15px; }
}

@media (max-width: 1120px) {
  .composer-footer { align-items: flex-start; flex-direction: column; gap: 7px; }
  .composer-footer > span { max-width: 100%; }
  .composer-actions { max-width: 100%; width: 100%; justify-content: flex-start; }
}

@media (max-width: 760px) {
  .workspace { min-height: calc(100vh - 56px); grid-template-columns: 1fr; }
  .sidebar { max-height: 38vh; padding: 10px 12px; }
  .chat-area { height: auto; min-height: calc(100vh - 56px); padding: 0 16px 16px; }
  .chat-heading { min-height: 58px; }
  .task-workspace { min-height: 0; grid-template-columns: minmax(0, 1fr); }
  .task-workspace.is-empty .task-main { min-height: calc(100vh - 190px); grid-template-rows: minmax(24px, 1fr) auto auto minmax(12px, 0.35fr); }
  .task-landing-intro { padding-bottom: 14px; }
  .task-timeline-pane { min-height: 420px; padding: 15px 0; }
  .composer-wrap { position: sticky; padding: 10px 0 8px; }
  .goal-composer-wrap { position: static; padding: 0 4px; }
  .capabilities-panel { padding: 18px 4px 15px; }
  .artifact-pane { min-height: 300px; max-height: none; overflow: visible; padding: 16px 0 8px; border-top: 1px solid #292a2e; border-left: 0; }
  .composer-footer { align-items: flex-end; }
  .composer-footer > span { max-width: 30%; line-height: 1.4; }
  .composer-actions { max-width: 70%; }
}

@media (max-width: 420px) {
  .chat-area { padding-right: 12px; padding-left: 12px; }
  .task-landing-intro h2 { font-size: 27px; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability-card:nth-child(odd) { border-right: 0; }
  .task-event-log li { grid-template-columns: 16px 35px minmax(0, 1fr); gap: 6px; }
  .composer-footer > span { display: none; }
  .composer-actions { max-width: 100%; width: 100%; justify-content: space-between; }
  .inline-model-select select { max-width: 120px; }
  .approval-dialog { padding: 22px 17px; }
}

:root {
  color-scheme: light;
  --shell-paper: #f2f2ec;
  --shell-card: #fbfbf7;
  --shell-ink: #20231f;
  --shell-muted: #777e78;
  --shell-line: #d9dbd3;
  --shell-sidebar: #171a18;
  --shell-mint: #54e2b3;
  background: var(--shell-paper);
  color: var(--shell-ink);
}
body { background: var(--shell-paper); color: var(--shell-ink); }
.app-shell { min-height: 100vh; background: var(--shell-paper); color: var(--shell-ink); }
.standalone-topbar {
  height: 72px;
  padding: 0 clamp(20px, 4vw, 56px);
  border-bottom: 1px solid var(--shell-line);
  background: var(--shell-paper);
}
.standalone-topbar .brand-name { color: var(--shell-ink); }
.topbar-right { gap: 14px; color: var(--shell-muted); }
.backend-indicator.connected .indicator-dot { background: #35bd8e; }
.backend-indicator.checking .indicator-dot { background: #d4aa4f; }
.backend-indicator.unavailable .indicator-dot { background: #d56666; }
.backend-error { color: #b94d4d; }
.user-label { color: var(--shell-ink); }
.sign-out { border-color: var(--shell-line); border-radius: 9px; background: var(--shell-card); color: var(--shell-ink); }
.startup-state { min-height: calc(100vh - 72px); color: var(--shell-muted); }
.startup-state .error-message, .error-message { color: #b94d4d; }

.workspace {
  width: 100%;
  height: 100vh;
  min-height: 620px;
  position: relative;
  grid-template-columns: var(--sidebar-width, 280px) minmax(0, 1fr);
  overflow: hidden;
  background: var(--shell-paper);
}
.sidebar-resizer {
  position: absolute;
  z-index: 12;
  top: 0;
  bottom: 0;
  left: calc(var(--sidebar-width, 280px) - 3px);
  width: 7px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  touch-action: none;
}
.sidebar-resizer span {
  position: absolute;
  top: 50%;
  left: 2px;
  width: 3px;
  height: 44px;
  border-radius: 99px;
  background: transparent;
  transform: translateY(-50%);
  transition: background 140ms ease;
}
.sidebar-resizer:hover span,
.sidebar-resizing .sidebar-resizer span { background: #78bda3; }
.sidebar {
  position: relative;
  height: 100vh;
  max-height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow-y: auto;
  padding: 24px 14px 18px;
  border: 0;
  background: #181a18;
  scrollbar-color: #3a403c transparent;
}
.sidebar-brand { width: fit-content; height: 36px; margin: 0 12px 30px; gap: 8px; }
.sidebar-brand .brand-mark {
  order: 2;
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: #54ddb1;
  box-shadow: 0 0 8px #54ddb166;
}
.sidebar-brand .brand-mark img, .sidebar-brand .brand-approval-dot { display: none; }
.sidebar-brand .brand-mark.executing { box-shadow: 0 0 11px #54ddb199; }
.sidebar-brand .brand-mark.thinking { animation: aether-thinking-pulse 1.8s ease-in-out infinite; }
.sidebar-brand .brand-mark.approval { background: #edc86f; box-shadow: 0 0 8px #edc86f88; }
.sidebar-brand .brand-mark.error { background: #d56666; box-shadow: 0 0 8px #d5666688; }
.sidebar-brand .brand-name { order: 1; color: #58e3b5; font-size: 26px; font-weight: 750; letter-spacing: -0.085em; }
.brand-mark img { filter: drop-shadow(0 0 4px #54e4b422); }
.brand-mark.executing img { filter: drop-shadow(0 0 8px #54e4b488); }
.new-chat {
  min-height: 48px;
  padding: 10px 14px;
  border: 0;
  border-radius: 15px;
  background: var(--shell-mint);
  color: #14251e;
  font-size: 14px;
  font-weight: 600;
}
.new-chat:hover { border-color: transparent; background: #68e9be; }
.new-chat span { color: #173a2d; }
.workspace-nav { gap: 3px; margin: 18px 0 16px; padding-bottom: 0; border-bottom: 0; }
.workspace-nav button { min-height: 44px; padding: 8px 12px; border-radius: 10px; color: #a0a8a1; font-size: 13px; }
.workspace-nav button:hover, .workspace-nav button.selected { background: #292b29; color: #f5f6f2; }
.workspace-nav button svg { width: 20px; height: 20px; flex: 0 0 20px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.5; }
.nav-count { color: #75e6bd; }
.sidebar-heading { margin: 17px 14px 13px; color: #7f8981; font-size: 10px; letter-spacing: 0.15em; }
.conversation-search { margin: 0 0 9px; }
.conversation-search input {
  padding: 10px 11px;
  border-color: #333834;
  border-radius: 9px;
  background: #202421;
  color: #e6e9e4;
  font-size: 11px;
}
.conversation-search input::placeholder { color: #828b84; }
.conversation-search input:focus { border-color: #70d8b2; }
.conversation-item { min-height: 50px; margin: 2px 0; padding: 10px 16px; border-radius: 8px; color: #aab2ac; font-size: 13px; }
.conversation-item.selected, .conversation-item:hover { background: #242925; color: #f1f3ef; }
.conversation-icon { position: relative; width: 15px; height: 12px; flex: 0 0 15px; border: 1px solid #89968d; border-radius: 4px; color: #89968d; font-size: 0; }
.conversation-icon::after { position: absolute; bottom: -3px; left: 3px; width: 4px; height: 4px; border-bottom: 1px solid currentColor; border-left: 1px solid currentColor; background: #181a18; content: ""; transform: skewY(-38deg); }
.empty-history, .sidebar-empty { color: #838d85; }
.sidebar-section-heading.approval-heading { margin-top: 20px; padding: 10px 12px; border-color: #3b413c; }
.approval-heading .sidebar-heading { color: #9ba49d; }
.approval-count { color: #a9b0aa; }
.approval-heading.has-approvals { border-color: #a7823b; background: #292317; }
.approval-heading.has-approvals .sidebar-heading, .approval-heading.has-approvals .approval-count { color: #f0c66f; }
.sidebar-card { border-color: #3b413c; border-radius: 9px; background: #202421; }
.sidebar-card p { color: #f0c66f; }
.sidebar-card > span { color: #a8b0aa; }
.approval-actions button { border-color: #454c46; border-radius: 7px; background: #292e2a; color: #d6ddd6; }
.approval-actions button:first-child { border-color: #92733b; background: #302819; color: #f0c66f; }
.sidebar-approvals { margin-top: 14px; }
.sidebar-approvals .approval-heading { margin-top: 0; }
.sidebar-footer { margin-top: auto; padding-top: 18px; }
.sidebar-profile { display: flex; align-items: center; gap: 12px; min-height: 61px; margin: 14px 8px 0; }
.sidebar-avatar { width: 44px; height: 44px; display: grid; flex: 0 0 44px; place-items: center; border-radius: 13px; background: #303832; }
.sidebar-avatar img { width: 24px; height: 24px; object-fit: contain; }
.sidebar-profile-copy { min-width: 0; display: grid; gap: 4px; }
.sidebar-profile-copy strong { color: #eef0ec; font-size: 13px; font-weight: 600; }
.sidebar-profile-copy small { overflow: hidden; color: #89938b; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }

.workspace-main {
  min-width: 0;
  height: calc(100vh - 6px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  margin: 6px 6px 0 0;
  border-radius: 24px 24px 0 0;
  background: var(--shell-paper);
}
.workspace-topbar {
  z-index: 4;
  height: 82px;
  flex: 0 0 82px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 clamp(22px, 3.2vw, 48px);
  border-bottom: 1px solid #dedfd8;
  border-radius: 24px 24px 0 0;
  background: #f6f6f0;
}
.workspace-context { min-width: 0; display: flex; align-items: center; gap: 10px; color: #737973; font-size: 14px; }
.workspace-context strong { overflow: hidden; color: #30342f; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.context-divider { color: #b5b9b2; }
.workspace-topbar .topbar-right { justify-content: flex-end; flex-wrap: wrap; font-size: 11px; }
.workspace-topbar .backend-indicator { color: #6e766f; }
.workspace-topbar .user-label { color: #4a514b; }
.workspace-topbar .sign-out { padding: 7px 10px; }

.chat-area { height: auto; min-height: 0; flex: 1; overflow: hidden; padding: 0 clamp(20px, 3.2vw, 48px) 20px; background: var(--shell-paper); }
.task-workspace { grid-template-columns: minmax(0, 1.08fr) minmax(320px, 0.92fr); }
.task-main { color: var(--shell-ink); }
.task-workspace.is-empty .task-main { display: flex; flex-direction: column; overflow-y: auto; }
.task-main { align-items: center; }
.task-main > * { box-sizing: border-box; }
.task-landing-intro { width: min(1280px, 100%); flex: 1 0 auto; min-height: 280px; display: flex; flex-direction: column; align-items: center; justify-content: center; align-self: center; padding: 52px 0 28px; text-align: center; }
.landing-logo {
  position: relative;
  display: block;
  width: 108px;
  height: 108px;
  margin: 0 0 14px;
  overflow: visible;
  border-radius: 0;
}
.landing-logo img { width: 100%; height: 100%; display: block; border-radius: 0; }
.landing-logo::after {
  content: "";
  position: absolute;
  top: 2px;
  right: 2px;
  width: 12px;
  height: 12px;
  border: 2px solid #f5f7f4;
  border-radius: 50%;
  background: #69d3b8;
}
.task-landing-intro .eyebrow { margin-bottom: 18px; color: #69d3b8; font-family: inherit; font-size: 11px; letter-spacing: 0.18em; }
.task-landing-intro h2 {
  margin: 0;
  color: #1d211e;
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(42px, 4.2vw, 64px);
  font-weight: 700;
  line-height: 1.02;
  letter-spacing: -0.055em;
}
.task-landing-intro h2 span { color: #1d211e; }
.task-landing-intro > p:last-child { max-width: 620px; margin: 22px auto 0; color: #7c827d; font-size: 14px; line-height: 1.65; }
.task-timeline-pane { padding: 25px 24px 20px 2px; scrollbar-color: #c4c7bf transparent; }
.task-pane-heading { border-bottom-color: var(--shell-line); }
.task-pane-heading .eyebrow { color: #668879; font-family: inherit; }
.task-pane-heading h2 { color: #262a26; }
.run-state, .output-state { color: #777e78; }
.run-state.running, .run-state.success, .output-state.running, .output-state.ready { color: #328d6d; }
.run-state.approval { color: #a27725; }
.run-state.error { color: #b94d4d; }
.run-summary { border-bottom-color: var(--shell-line); }
.run-kicker, .run-usage-inline, .artifact-card-heading, .artifact-kind, .capabilities-heading > span { color: #777e78; }
.run-summary-copy strong { color: #343934; }
.tool-activity { border-color: #d7dad2; color: #737a73; background: #f8f8f3; }
.tool-activity > span:first-child, .tool-activity strong { color: #555d56; }
.tool-activity > span:last-child { color: #7c837d; }
.tool-activity.running { border-color: #a9d8c5; background: #f0faf5; }
.tool-activity.running > span:first-child, .tool-activity.running strong { color: #278361; }
.tool-activity.failed { border-color: #e2bcbc; background: #fff6f5; }
.tool-activity.failed > span:first-child, .tool-activity.failed strong { color: #b94d4d; }
.agent-list-label { color: #7c827d; font-family: inherit; letter-spacing: 0.12em; }
.plan-progress ol { border-top-color: var(--shell-line); }
.plan-progress li { border-bottom-color: var(--shell-line); color: #646b65; }
.plan-step-index { color: #858b85; }
.plan-progress li.completed .plan-step-index, .plan-progress li.completed .plan-step-status { color: #328d6d; }
.plan-progress li.in_progress .plan-step-status, .plan-progress li.paused .plan-step-status { color: #a27725; }
.plan-progress li.stopped .plan-step-status { color: #b94d4d; }
.task-event-log li { border-bottom-color: #e0e1db; color: #5e655f; }
.timeline-marker { border-color: #c7cbc3; color: #858b85; }
.task-event-log li.success .timeline-marker, .task-event-log li.running .timeline-marker { border-color: #8bc4aa; color: #328d6d; }
.task-event-log li.approval .timeline-marker { border-color: #d7bd81; color: #a27725; }
.task-event-log li.error .timeline-marker { border-color: #d8a2a2; color: #b94d4d; }
.task-event-log time, .timeline-entry > span { color: #848a84; }
.timeline-entry strong { color: #393e39; }
.timeline-empty { color: #747b75; }
.timeline-workers { border-top-color: var(--shell-line); }
.timeline-workers .agent-row { border-bottom-color: #e0e1db; }
.timeline-workers .agent-name { color: #464d47; }
.timeline-workers .agent-state { color: #777e78; }
.agent-indicator.working, .agent-state.working, .agent-indicator.completed, .agent-state.completed { background-color: #328d6d; color: #328d6d; }
.agent-indicator.thinking, .agent-state.thinking, .agent-indicator.approval, .agent-state.approval { background-color: #a27725; color: #a27725; }
.agent-indicator.error, .agent-state.error { background-color: #b94d4d; color: #b94d4d; }
.process-summary { border-top-color: var(--shell-line); color: #666d67; }
.process-summary summary, .process-summary li strong { color: #434a44; }
.process-summary li span { color: #727972; }
.process-summary small, .usage-meter small { color: #818781; }
.composer-wrap { background: linear-gradient(180deg, #f2f2ec00 0%, #f2f2ec 18%); }
.goal-composer-wrap { width: min(1280px, 100%) !important; justify-self: center; align-self: center; padding: 0 !important; }
.task-composer { box-sizing: border-box; }
.task-composer {
  min-height: 142px;
  border-color: #d7dad2;
  border-radius: 25px;
  background: #fbfbf7;
  box-shadow: 0 8px 26px #30352d0b;
  padding: 18px 18px 12px;
}
.task-composer:focus-within { border-color: #77c9a9; }
.task-composer textarea {
  min-height: 58px !important;
  color: #303630;
  font-size: 14px;
}
.task-composer textarea::placeholder { color: #a0a69f; font-size: 14px; }
.composer-footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  color: #868c86;
}
.composer-footer > span { display: none; }
.composer-left-tools { display: flex; align-items: center; gap: 6px; }
.attachment-button,
.composer-left-tools .voice-button {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #727972;
  transition: background-color 180ms ease, color 180ms ease, transform 180ms ease;
}
.attachment-button svg,
.composer-left-tools .voice-button svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.attachment-button:disabled { opacity: 0.75; cursor: not-allowed; }
.composer-left-tools .voice-button:not(:disabled):hover,
.composer-left-tools .voice-button.listening {
  background: #e7f5ef;
  color: #368b6e;
  transform: translateY(-1px);
}
.attachment-chip {
  max-width: 260px;
  min-height: 44px;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 24px;
  align-items: center;
  gap: 8px;
  margin: 4px 0 8px;
  padding: 7px 8px;
  border: 1px solid #b9d7c9;
  border-radius: 12px;
  background: #edf7f2;
}
.attachment-chip.reading { border-style: dashed; }
.attachment-chip-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #69d3b8;
  color: #fff;
  font-size: 10px;
}
.attachment-chip > span:nth-child(2) { min-width: 0; display: grid; gap: 2px; }
.attachment-chip strong { overflow: hidden; color: #3d4942; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.attachment-chip small { color: #7b887f; font-size: 8px; }
.attachment-chip button {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #718078;
  cursor: pointer;
}
.attachment-chip button:hover { background: #dcece4; color: #3d644f; }
.composer-actions { min-width: 0; justify-content: flex-end; }
.inline-model-select select, .voice-toggle, .voice-button { border-color: #d8dbd4; background: #f7f7f2; color: #555d56; }
.inline-model-select select {
  max-width: 178px;
  height: 34px;
  border-radius: 17px;
  cursor: pointer;
}
.voice-toggle[aria-pressed="true"] { border-color: #a8d7c3; color: #338567; }
.voice-button.listening { border-color: #d6bd80; background: #fcf8ed; color: #a27725; }
.send-button {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: #69d3b8;
  color: #17372b;
  font-size: 0;
  box-shadow: 0 5px 14px rgba(57, 156, 125, 0.12);
  transition: transform 180ms ease, background-color 180ms ease;
}
.send-button::after { content: "→"; font-size: 18px; line-height: 1; }
.send-button:hover:not(:disabled) { transform: translateY(-2px); background: #74ebc2; }
.pause-button { border-color: #d6bd80; background: #fcf8ed; color: #916c24; }
.stop-button { border-color: #d8a2a2; background: #fff6f5; color: #b94d4d; }
.voice-privacy, .voice-status { color: #858b85; }
.capabilities-panel { width: min(1280px, 100%); padding: 24px 0 0; box-sizing: border-box; }
.capabilities-heading { justify-content: flex-start; margin: 0 0 13px; }
.capabilities-heading h2 { margin: 0; }
.capabilities-heading .eyebrow { display: none; }
.capabilities-heading h2 { color: #777e78; font-size: 11px; font-weight: 500; }
.capabilities-heading > span { display: none; }
.capability-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; border-top: 0; }
.capability-card {
  min-height: 88px;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  padding: 13px;
  border: 1px solid #dedfd8;
  border-radius: 17px;
  background: #f8f8f4;
  cursor: pointer;
  box-shadow: 0 0 0 rgba(56, 139, 110, 0);
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    background-color 180ms ease,
    box-shadow 180ms ease;
}
.capability-card:nth-child(odd) { border-right: 1px solid #dedfd8; }
.capability-card:hover,
.capability-card:focus-visible {
  transform: translateY(-4px);
  border-color: #94c9b5;
  background: #fbfdf9;
  box-shadow: 0 10px 24px rgba(73, 126, 105, 0.11);
  outline: none;
}
.capability-icon {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 10px;
  background: #def5eb;
  color: #368b6e;
  font-size: 13px;
  transition:
    transform 180ms ease,
    background-color 180ms ease,
    color 180ms ease;
}
.capability-card:hover .capability-icon,
.capability-card:focus-visible .capability-icon {
  transform: scale(1.07) rotate(-2deg);
  background: #69d3b8;
  color: #ffffff;
}
.capability-copy { gap: 5px; }
.capability-copy strong { color: #343a35; font-size: 10px; transition: color 180ms ease; }
.capability-card:hover .capability-copy strong,
.capability-card:focus-visible .capability-copy strong { color: #25775c; }
.capability-copy small { color: #828982; font-size: 9px; }
.capability-action { display: none; }

.artifact-pane { padding: 25px 4px 20px 24px; border-left-color: var(--shell-line); scrollbar-color: #c4c7bf transparent; }
.artifact-pane .task-pane-heading { border-bottom-color: var(--shell-line); }
.artifact-card { border-color: #dedfd8; background: #fbfbf7; }
.artifact-card-heading { border-bottom-color: #e1e2dc; }
.task-output { color: #373d37; }
.task-output h1, .task-output h2, .task-output h3, .task-output h4 { color: #242924; }
.task-output pre, .artifact-section pre { border-color: #2b302c; background: #1b201d; color: #e4e9e4; }
.task-output code { color: #267c5f; }
.task-output pre code { color: inherit; }
.task-output blockquote { border-left-color: #83c8aa; color: #69716a; }
.task-output a { color: #287c5e; }
.task-output th { background: #eceee8; color: #303630; }
.task-output th, .task-output td { border-color: #d9dbd3; }
.artifact-placeholder { color: #818781; }
.artifact-section-heading { border-bottom-color: var(--shell-line); }
.artifact-section-heading h3 { color: #414841; }
.artifact-section-heading > span { color: #7c827d; }
.conversation-history { padding-top: 12px; border-top: 1px solid var(--shell-line); }
.conversation-history > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #414841; cursor: pointer; font-size: 10px; font-weight: 550; }
.conversation-history > summary span { color: #7c827d; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.artifact-section article, .tool-artifacts details { border-bottom-color: #e0e1db; }
.artifact-section article p { color: #454c46; }
.artifact-section article > span { color: #6d746e; }
.conversation-history .history-message { padding: 12px 0; }
.history-message header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.history-message header strong { color: #328d6d; font-size: 10px; font-weight: 600; }
.history-message.user header strong { color: #59615a; }
.history-message header time { color: #858b85; font-size: 9px; }
.conversation-history .message-markdown { color: #454c46; font-size: 11px; }
.conversation-history .message-markdown h1, .conversation-history .message-markdown h2,
.conversation-history .message-markdown h3, .conversation-history .message-markdown h4 { color: #282e29; }
.conversation-history .message-markdown blockquote { border-left-color: #83c8aa; color: #69716a; }
.conversation-history .message-markdown a { color: #287c5e; }
.tool-artifacts summary { color: #444b45; }
.tool-output-icon { color: #328d6d; }
.usage-meter { border-bottom-color: var(--shell-line); }
.usage-meter > div { color: #737a73; }
.usage-meter strong { color: #3e453f; }
.dag-view { margin-top: 18px; }
.dag-view > .agent-list-label { display: flex; justify-content: space-between; }
.dag-view > .agent-list-label span { color: #328d6d; }
.dag-view ol { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.dag-view li { display: grid; grid-template-columns: 26px minmax(0, 1fr) 18px; align-items: center; gap: 8px; min-height: 38px; }
.dag-node-index { width: 24px; height: 24px; display: grid; place-items: center; border: 1px solid #d5d8d0; border-radius: 50%; color: #737a73; font-size: 9px; }
.dag-node-copy { display: grid; gap: 3px; }
.dag-node-copy strong { color: #414841; font-size: 10px; }
.dag-node-copy small { color: #858c85; font-size: 8px; }
.dag-edge { color: #8e9690; text-align: center; }
.saved-artifacts details { padding: 9px 0; border-bottom: 1px solid #e0e1db; }
.saved-artifacts summary { display: flex; gap: 8px; color: #444b45; cursor: pointer; font-size: 10px; }
.artifact-preview { margin-top: 9px; }
.artifact-preview > span { display: block; margin-bottom: 7px; color: #858c85; font-size: 8px; }
.citation-artifacts a { display: grid; gap: 4px; padding: 9px 0; border-bottom: 1px solid #e0e1db; color: #287c5e; text-decoration: none; }
.citation-artifacts a strong { font-size: 10px; }
.citation-artifacts a span, .citation-artifacts a small { overflow-wrap: anywhere; color: #747b75; font-size: 8px; }
.rollback-artifacts button { width: 100%; padding: 9px 10px; border: 1px solid #d8b58b; border-radius: 8px; background: #fff8e9; color: #916c24; font-size: 9px; }
.run-controls { border-top-color: var(--shell-line); }
.run-controls p { color: #626a63; }
.run-controls button { border-color: #9bcdb5; background: #edf8f1; color: #287c5e; }

.memory-workspace { width: 100%; height: auto; min-height: 0; flex: 1; overflow-y: auto; margin: 0; padding: 34px clamp(22px, 4vw, 56px); color: var(--shell-ink); }
.memory-header { border-bottom-color: var(--shell-line); }
.memory-header .eyebrow, .memory-editor .eyebrow, .memory-library-heading .eyebrow { color: #668879; }
.memory-header h1, .memory-editor h2, .memory-library-heading h2 { color: #282d28; }
.memory-header > div:first-child > p:last-child, .memory-editor > div > p:last-child { color: #777e78; }
.memory-counts span { border-color: var(--shell-line); color: #6e756f; }
.memory-counts strong { color: #353b35; }
.memory-editor, .memory-card { border-color: #dedfd8; background: #fbfbf7; box-shadow: 0 8px 26px #30352d08; }
.memory-field { color: #515851; }
.memory-field select, .memory-field textarea, .memory-search input, .memory-category-filter select {
  border-color: #d8dbd4;
  border-radius: 8px;
  background: #fff;
  color: #303630;
}
.memory-field select:focus, .memory-field textarea:focus, .memory-search input:focus, .memory-category-filter select:focus { border-color: #77c9a9; outline-color: #77c9a9; }
.memory-card { border-radius: 10px; }
.memory-category { color: #328d6d; }
.memory-status { background: #e3f5eb; color: #328d6d; }
.memory-status.archived { background: #eeefeb; color: #747b75; }
.memory-card > p { color: #3e453f; }
.memory-card-footer { border-top-color: #e3e4de; color: #7c827d; }
.memory-card-footer button { border-color: #d8dbd4; color: #555d56; }
.memory-card-footer button:hover { border-color: #8fc9ad; color: #287c5e; }
.memory-card-footer .delete-memory:hover { border-color: #d68d8d; color: #b94d4d; }
.memory-empty { border-color: #c9cdc5; color: #737a73; }
.archive-toggle { color: #5d655e; }
.archive-toggle input { accent-color: #3da982; }
.primary-button { background: var(--shell-mint); color: #17372b; }

.auth-layout { min-height: calc(100vh - 72px); color: var(--shell-ink); }
.intro h1 { color: #1f241f; }
.intro h1 span { color: #5c7669; }
.intro-copy, .card-copy { color: #6f776f; }
.model-chips span { border-color: var(--shell-line); color: #555e56; }
.auth-card { border-color: #dedfd8; border-radius: 18px; background: #fbfbf7; box-shadow: 0 20px 60px #29322812; }
.auth-tabs { background: #eeefe9; }
.auth-tabs button { color: #747b75; }
.auth-tabs button.active { background: #fff; color: #282e29; box-shadow: 0 1px 3px #20282014; }
.auth-card h2 { color: #262b26; }
.card-copy { color: #777e78; }
.field-label { color: #4e564f; }
.field-label input { border-color: #d8dbd4; border-radius: 8px; background: #fff; color: #242924; }
.field-label input:focus { border-color: #77c9a9; }
.privacy-note { color: #7d847e; }
.approval-overlay { background: #20241faa; }
.approval-dialog { border-color: #dedfd8; border-radius: 16px; background: #fbfbf7; box-shadow: 0 24px 90px #20241f33; }
.approval-close { border-color: #d8dbd4; background: #fff; color: #59615a; }
.approval-eyebrow { color: #a27725; }
.approval-dialog h2 { color: #272d28; }
.approval-description { color: #687069; }
.approval-action-name { border-color: #dedfd8; }
.approval-action-name strong { color: #936c20; }
.approval-arguments { border-color: #dedfd8; border-radius: 8px; background: #f0f1eb; color: #404740; }
.approval-dialog-actions button { border-color: #d2d6cf; border-radius: 8px; color: #4e564f; }
.approval-dialog-actions .approval-allow { border-color: #edc86f; background: #edc86f; color: #33280f; }
.approval-dialog-actions .approval-deny:hover:not(:disabled) { border-color: #c46b6b; color: #b94d4d; }

@media (max-width: 1000px) {
  .workspace { grid-template-columns: var(--sidebar-width, 280px) minmax(0, 1fr); }
  .task-workspace { grid-template-columns: minmax(0, 1fr) minmax(280px, 0.88fr); }
  .capability-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .workspace { height: auto; min-height: 100vh; display: flex; flex-direction: column; overflow: visible; }
  .sidebar-resizer { display: none; }
  .sidebar { position: static; width: 100%; height: auto; max-height: 38vh; flex: 0 0 auto; padding: 14px 12px; }
  .sidebar-brand { margin: 0 8px 14px; }
  .new-chat { min-height: 46px; }
  .workspace-nav { grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 12px 0; padding-bottom: 12px; }
  .workspace-nav button { min-height: 38px; }
  .sidebar-heading { margin-top: 10px; }
  .workspace-main { height: auto; min-height: calc(100vh - 38vh); overflow: visible; margin: 0; border-radius: 19px 19px 0 0; }
  .workspace-topbar { position: sticky; top: 0; height: 66px; flex-basis: 66px; padding: 0 17px; border-radius: 19px 19px 0 0; }
  .workspace-topbar .topbar-right { gap: 8px; font-size: 9px; }
  .backend-error { display: none; }
  .chat-area { height: auto; min-height: calc(100vh - 38vh - 66px); overflow: visible; padding: 0 18px 18px; }
  .task-workspace { grid-template-columns: minmax(0, 1fr); }
  .task-workspace.is-empty .task-main { min-height: 660px; grid-template-rows: minmax(120px, 1fr) auto auto minmax(14px, 0.25fr); }
  .task-landing-intro { padding: 20px 4px 19px; }
  .task-landing-intro .eyebrow { margin-bottom: 14px; font-size: 9px; }
  .task-landing-intro h2 { font-size: clamp(36px, 10vw, 54px); }
  .task-landing-intro > p:last-child { margin-top: 14px; font-size: 12px; }
  .task-timeline-pane { min-height: 440px; overflow: visible; padding: 17px 0; }
  .composer-wrap { position: sticky; padding: 10px 0 8px; }
  .goal-composer-wrap { position: static; padding: 0 3px; }
  .capabilities-panel { padding: 18px 3px 20px; }
  .artifact-pane { min-height: 300px; max-height: none; overflow: visible; padding: 18px 0; border-top: 1px solid var(--shell-line); border-left: 0; }
  .memory-workspace { min-height: calc(100vh - 38vh - 66px); padding: 25px 18px; }
  .memory-layout, .memory-header { grid-template-columns: 1fr; }
  .memory-header { align-items: flex-start; flex-direction: column; }
  .memory-layout { display: grid; gap: 18px; }
  .auth-layout { width: min(560px, 92vw); min-height: calc(100vh - 72px); grid-template-columns: 1fr; gap: 26px; padding: 35px 0; }
  .intro h1 { font-size: clamp(40px, 10vw, 58px); }
  .auth-card { padding: 22px; }
}
@media (max-width: 480px) {
  .workspace-topbar { gap: 8px; }
  .workspace-context { gap: 6px; font-size: 11px; }
  .workspace-topbar .user-label { display: none; }
  .workspace-topbar .backend-indicator { gap: 5px; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability-card, .capability-card:nth-child(odd) { border-right: 1px solid #dedfd8; }
  .composer-footer { align-items: flex-start; flex-direction: column; }
  .composer-footer > span { max-width: 100%; }
  .composer-actions { max-width: 100%; width: 100%; justify-content: flex-start; }
  .memory-filters { grid-template-columns: 1fr; }
}
</style>
