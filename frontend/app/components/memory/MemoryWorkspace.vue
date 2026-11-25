<script setup lang="ts">
import type { Memory } from '../../types/aether';

const props = defineProps<{
  activeMemoryCount: number;
  archivedMemoryCount: number;
  busy: boolean;
  errorMessage: string;
  memories: Memory[];
  memoryContent: string;
  memoryType: Memory['memory_type'];
  memoryImportance: number;
  memorySearch: string;
  memoryCategoryFilter: Memory['memory_type'] | 'all';
  showArchivedMemories: boolean;
  visibleMemories: Memory[];
}>();

const emit = defineEmits<{
  (event: 'update:memoryContent', value: string): void;
  (event: 'update:memoryType', value: Memory['memory_type']): void;
  (event: 'update:memoryImportance', value: number): void;
  (event: 'update:memorySearch', value: string): void;
  (event: 'update:memoryCategoryFilter', value: Memory['memory_type'] | 'all'): void;
  (event: 'update:showArchivedMemories', value: boolean): void;
  (event: 'save-memory'): void;
  (event: 'set-memory-active', memory: Memory, active: boolean): void;
  (event: 'delete-memory', memory: Memory): void;
}>();

const memoryLabels: Record<Memory['memory_type'], string> = {
  preference: 'Preferensi',
  fact: 'Fakta',
  context: 'Konteks'
};

function formatMemoryDate(value: string): string {
  return new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(new Date(value));
}
</script>

<template>
  <section class="memory-workspace" aria-labelledby="memory-title">
    <header class="memory-header">
      <div>
        <p class="eyebrow">PERSONAL CONTEXT</p>
        <h1 id="memory-title">Memory</h1>
        <p>Hal yang kamu simpan dapat membantu Aether memberi jawaban yang lebih relevan.</p>
      </div>
      <div class="memory-counts" aria-label="Ringkasan memory">
        <span><strong>{{ activeMemoryCount }}</strong> aktif</span>
        <span><strong>{{ archivedMemoryCount }}</strong> diarsipkan</span>
      </div>
    </header>

    <div class="memory-layout">
      <form class="memory-editor" @submit.prevent="emit('save-memory')">
        <div>
          <p class="eyebrow">TAMBAHKAN MEMORY</p>
          <h2>Simpan konteks penting</h2>
          <p>Memory hanya disimpan atas tindakanmu dan dapat dinonaktifkan kapan saja.</p>
        </div>
        <label class="memory-field">
          Kategori
          <select :value="memoryType" @change="emit('update:memoryType', ($event.target as HTMLSelectElement).value as Memory['memory_type'])">
            <option value="preference">Preferensi</option>
            <option value="fact">Fakta</option>
            <option value="context">Konteks</option>
          </select>
        </label>
        <label class="memory-field">
          Isi
          <textarea
            :value="memoryContent"
            maxlength="2000"
            rows="5"
            required
            placeholder="Contoh: Saya lebih suka penjelasan ringkas dengan contoh praktis."
            @input="emit('update:memoryContent', ($event.target as HTMLTextAreaElement).value)"
          />
        </label>
        <label class="memory-field">
          Kepentingan
          <select :value="memoryImportance" @change="emit('update:memoryImportance', Number(($event.target as HTMLSelectElement).value))">
            <option :value="1">Rendah</option>
            <option :value="2">Agak rendah</option>
            <option :value="3">Normal</option>
            <option :value="4">Penting</option>
            <option :value="5">Sangat penting</option>
          </select>
        </label>
        <button class="primary-button memory-save" type="submit" :disabled="busy || !memoryContent.trim()">
          {{ busy ? 'Menyimpan…' : 'Simpan memory' }}
        </button>
      </form>

      <div class="memory-library">
        <div class="memory-library-heading">
          <div>
            <p class="eyebrow">MEMORY TERSIMPAN</p>
            <h2>{{ showArchivedMemories ? 'Semua status' : 'Memory aktif' }}</h2>
          </div>
          <label class="archive-toggle">
            <input
              :checked="showArchivedMemories"
              type="checkbox"
              @change="emit('update:showArchivedMemories', ($event.target as HTMLInputElement).checked)"
            />
            Tampilkan arsip
          </label>
        </div>
        <div class="memory-filters">
          <label class="memory-search">
            <span class="visually-hidden">Cari memory</span>
            <input
              :value="memorySearch"
              type="search"
              placeholder="Cari isi memory…"
              @input="emit('update:memorySearch', ($event.target as HTMLInputElement).value)"
            />
          </label>
          <label class="memory-category-filter">
            <span class="visually-hidden">Filter kategori memory</span>
            <select
              :value="memoryCategoryFilter"
              @change="emit('update:memoryCategoryFilter', ($event.target as HTMLSelectElement).value as Memory['memory_type'] | 'all')"
            >
              <option value="all">Semua kategori</option>
              <option value="preference">Preferensi</option>
              <option value="fact">Fakta</option>
              <option value="context">Konteks</option>
            </select>
          </label>
        </div>
        <p v-if="errorMessage" class="error-message memory-error" role="alert">{{ errorMessage }}</p>
        <p v-if="memories.length === 0" class="memory-empty">Belum ada memory. Simpan konteks pertama yang ingin Aether ingat.</p>
        <p v-else-if="visibleMemories.length === 0" class="memory-empty">Tidak ada memory yang cocok dengan filter ini.</p>
        <ul v-else class="memory-list">
          <li v-for="memory in visibleMemories" :key="memory.id" class="memory-card">
            <div class="memory-card-meta">
              <span class="memory-category">{{ memoryLabels[memory.memory_type] }}</span>
              <span class="memory-status" :class="{ archived: !memory.is_active }">{{ memory.is_active ? 'Aktif' : 'Diarsipkan' }}</span>
            </div>
            <p>{{ memory.content }}</p>
            <div class="memory-card-footer">
              <span>Kepentingan {{ memory.importance }}/5</span>
              <time v-if="memory.updated_at" :datetime="memory.updated_at">Diperbarui {{ formatMemoryDate(memory.updated_at) }}</time>
              <div>
                <button type="button" :disabled="busy" @click="emit('set-memory-active', memory, !memory.is_active)">
                  {{ memory.is_active ? 'Arsipkan' : 'Aktifkan' }}
                </button>
                <button type="button" class="delete-memory" :disabled="busy" @click="emit('delete-memory', memory)">Hapus</button>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
