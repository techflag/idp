<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <section class="panel-card">
    <header class="panel-card__header">
      <div>
        <h3>{{ title }}</h3>
        <p v-if="description">{{ description }}</p>
      </div>
      <div class="panel-card__extra">
        <slot name="extra" />
      </div>
    </header>
    <div class="panel-card__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.panel-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  border: 1px solid #d7dde5;
  border-radius: 0;
  background: #ffffff;
  overflow: hidden;
}

.panel-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e5e7eb;
}

.panel-card__header h3 {
  margin: 0;
  font-size: 14px;
  line-height: 1.2;
  color: #111827;
  font-weight: 700;
}

.panel-card__header p {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: #64748b;
}

.panel-card__extra {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-card__body {
  min-height: 0;
}

@media (max-width: 960px) {
  .panel-card {
    padding: 12px;
  }

  .panel-card__header {
    flex-direction: column;
  }
}
</style>
