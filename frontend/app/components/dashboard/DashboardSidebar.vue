<script setup lang="ts">
import type { Approval, Conversation, User } from '../../types/aether';

defineProps<{
  activeSidebarSection: 'home' | 'explore' | 'collection';
  activeConversationId: string | null;
  activeMemoryCount: number;
  agentVisualLabel: string;
  agentVisualStatus: 'idle' | 'thinking' | 'executing' | 'approval' | 'error';
  approvals: Approval[];
  busy: boolean;
  conversations: Conversation[];
  localAuthMode: boolean;
  user: User | null;
  visibleConversations: Conversation[];
  workspaceView: 'chat' | 'memory';
  conversationSearch: string;
}>();

const emit = defineEmits<{
  (event: 'update:conversationSearch', value: string): void;
  (event: 'start-new-task'): void;
  (event: 'open-home'): void;
  (event: 'open-explore'): void;
  (event: 'open-collection'): void;
  (event: 'open-conversation', conversationId: string): void;
  (event: 'decide-approval', approval: Approval, approve: boolean): void;
}>();
</script>

<template>
  <aside class="sidebar">
    <a class="brand sidebar-brand" href="/" aria-label="Aether — beranda" :title="agentVisualLabel">
      <span class="brand-mark" :class="agentVisualStatus" aria-hidden="true">
        <img src="/aether-monogram.png" alt="" />
        <span v-if="agentVisualStatus === 'approval'" class="brand-approval-dot" />
      </span>
      <span class="brand-name">ÆTHER</span>
    </a>

    <button class="new-chat" type="button" :disabled="busy" @click="emit('start-new-task')">
      <span aria-hidden="true">＋</span> Percakapan baru
    </button>

    <nav class="workspace-nav" aria-label="Workspace">
      <button type="button" :class="{ selected: activeSidebarSection === 'home' }" @click="emit('open-home')">
        <svg aria-hidden="true" viewBox="0 0 20 20">
          <path d="m3 9 7-6 7 6M5 8v9h10V8M8 17v-5h4v5" />
        </svg>
        Beranda
      </button>
      <button type="button" :class="{ selected: activeSidebarSection === 'explore' }" @click="emit('open-explore')">
        <svg aria-hidden="true" viewBox="0 0 20 20">
          <circle cx="8.5" cy="8.5" r="5.5" />
          <path d="m13 13 4 4" />
        </svg>
        Jelajahi
      </button>
      <button type="button" :class="{ selected: activeSidebarSection === 'collection' }" @click="emit('open-collection')">
        <svg aria-hidden="true" viewBox="0 0 20 20">
          <path d="M2.5 5.5h6l1.5 2h7.5v9h-15zM2.5 7.5v-2a1.5 1.5 0 0 1 1.5-1.5h3l1.5 1.5" />
        </svg>
        Koleksi
        <span class="nav-count">{{ activeMemoryCount }}</span>
      </button>
    </nav>

    <template v-if="workspaceView === 'chat'">
      <p class="sidebar-heading">TERBARU</p>
      <label v-if="activeSidebarSection === 'explore' || conversationSearch" class="conversation-search">
        <span class="visually-hidden">Cari percakapan</span>
        <input
          :value="conversationSearch"
          type="search"
          placeholder="Cari percakapan…"
          @input="emit('update:conversationSearch', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <button
        v-for="conversation in visibleConversations"
        :key="conversation.id"
        class="conversation-item"
        :class="{ selected: activeConversationId === conversation.id }"
        type="button"
        @click="emit('open-conversation', conversation.id)"
      >
        <span class="conversation-icon" aria-hidden="true" />
        <span>{{ conversation.title }}</span>
      </button>
      <p v-if="conversations.length === 0" class="empty-history">Belum ada percakapan.</p>
      <p v-else-if="visibleConversations.length === 0" class="empty-history">Tidak ada percakapan yang cocok.</p>

      <section v-if="approvals.length" class="sidebar-approvals" aria-label="Persetujuan">
        <div class="sidebar-section-heading approval-heading has-approvals">
          <p class="sidebar-heading">PERSETUJUAN</p>
          <span class="approval-count">{{ approvals.length }}</span>
        </div>
        <article v-for="approval in approvals" :key="approval.id" class="sidebar-card approval-card">
          <p>{{ approval.tool_name === 'create_task' ? 'Buat tugas' : approval.tool_name }}</p>
          <span>{{ approval.tool_arguments.title || 'Tindakan memerlukan persetujuanmu.' }}</span>
          <div class="approval-actions">
            <button type="button" :disabled="busy" @click="emit('decide-approval', approval, true)">Setujui</button>
            <button type="button" :disabled="busy" @click="emit('decide-approval', approval, false)">Tolak</button>
          </div>
        </article>
      </section>
    </template>

    <div class="sidebar-footer">
      <div class="sidebar-profile">
        <span class="sidebar-avatar" aria-hidden="true"><img src="/aether-monogram.png" alt="" /></span>
        <span class="sidebar-profile-copy">
          <strong>{{ user?.name || 'Aether' }}</strong>
          <small>{{ localAuthMode ? 'Workspace lokal' : user?.email || 'Personal workspace' }}</small>
        </span>
      </div>
    </div>
  </aside>
</template>
