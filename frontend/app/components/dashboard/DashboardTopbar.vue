<script setup lang="ts">
import type { User } from '../../types/aether';

defineProps<{
  standalone?: boolean;
  agentVisualLabel: string;
  agentVisualStatus: 'idle' | 'thinking' | 'executing' | 'approval' | 'error';
  backendStatus: 'checking' | 'connected' | 'unavailable';
  backendHealthError: string;
  localAuthMode: boolean;
  user: User | null;
  workspaceContext?: string;
}>();

const emit = defineEmits<{ (event: 'sign-out'): void }>();
</script>

<template>
  <header v-if="standalone" class="topbar standalone-topbar">
    <a class="brand" href="/" aria-label="Aether — beranda" :title="agentVisualLabel">
      <span class="brand-mark" :class="agentVisualStatus" aria-hidden="true">
        <img src="/aether-monogram.png" alt="" />
        <span v-if="agentVisualStatus === 'approval'" class="brand-approval-dot" />
      </span>
      <span class="brand-name">Aether</span>
    </a>
    <div class="topbar-right">
      <span class="backend-indicator" :class="backendStatus">
        <span class="indicator-dot" />
        {{ backendStatus === 'connected' ? 'Backend tersambung' : backendStatus === 'checking' ? 'Memeriksa backend' : 'Backend tidak tersedia' }}
      </span>
      <span v-if="backendHealthError" class="backend-error" :title="backendHealthError">{{ backendHealthError }}</span>
      <span v-if="user" class="user-label">{{ localAuthMode ? 'Mode lokal' : user.name }}</span>
      <button v-if="user && !localAuthMode" class="sign-out" type="button" @click="emit('sign-out')">Keluar</button>
    </div>
  </header>

  <header v-else class="workspace-topbar">
    <div class="workspace-context">
      <span>Aether</span>
      <span class="context-divider" aria-hidden="true">/</span>
      <strong>{{ workspaceContext }}</strong>
    </div>
    <div class="topbar-right">
      <span class="backend-indicator" :class="backendStatus">
        <span class="indicator-dot" />
        {{ backendStatus === 'connected' ? 'Backend tersambung' : backendStatus === 'checking' ? 'Memeriksa backend' : 'Backend tidak tersedia' }}
      </span>
      <span v-if="backendHealthError" class="backend-error" :title="backendHealthError">{{ backendHealthError }}</span>
      <span v-if="user" class="user-label">{{ localAuthMode ? 'Mode lokal' : user.name }}</span>
      <button v-if="user && !localAuthMode" class="sign-out" type="button" @click="emit('sign-out')">Keluar</button>
    </div>
  </header>
</template>
