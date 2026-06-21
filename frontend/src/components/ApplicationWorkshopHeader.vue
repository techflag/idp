<script setup lang="ts">
import { ref } from 'vue'
import { t } from '../i18n'

defineProps<{
  documentTitle: string
  documentMeta: string
  applicationName: string
  saveLoading: boolean
  canSaveApplication: boolean
  saved: boolean
  uploadCustomerOptions: Array<{ id: string; name: string }>
  uploadCustomerId: string
  uploadingSample: boolean
  taskLoading: boolean
  storeLoading: boolean
  canUploadSample: boolean
  isEditingApplication: boolean
}>()

const emit = defineEmits<{
  'update:applicationName': [value: string]
  'update:uploadCustomerId': [value: string]
  saveDraft: []
  publish: []
  uploadSample: []
  backToMarket: []
  backToDetail: []
}>()

const moreOpen = ref(false)

function closeAndEmit(eventName: 'uploadSample' | 'backToMarket' | 'backToDetail') {
  moreOpen.value = false
  if (eventName === 'uploadSample') {
    emit('uploadSample')
    return
  }
  if (eventName === 'backToMarket') {
    emit('backToMarket')
    return
  }
  emit('backToDetail')
}
</script>

<template>
  <section class="application-workshop-header">
    <div class="application-workshop-header__path">
      <span>{{ t('workshop.adminConsole') }}</span>
      <span>/</span>
      <span>{{ t('nav.documentApplications') }}</span>
      <span>/</span>
      <strong>{{ documentTitle }}</strong>
      <em>{{ documentMeta }}</em>
    </div>

    <div class="application-workshop-header__actions">
      <a-input
        class="application-workshop-header__application-name"
        size="small"
        :model-value="applicationName"
        :placeholder="t('workshop.applicationName')"
        @update:model-value="(value) => emit('update:applicationName', String(value))"
      />
      <div v-if="uploadCustomerOptions.length" class="application-workshop-header__customer">
        <span>{{ t('workshop.uploadCustomer') }}</span>
        <a-select
          size="small"
          class="application-workshop-header__customer-select"
          :placeholder="t('workshop.selectCustomer')"
          :model-value="uploadCustomerId || uploadCustomerOptions[0]?.id"
          :disabled="uploadingSample || storeLoading"
          @update:model-value="(value) => emit('update:uploadCustomerId', String(value))"
        >
          <a-option
            v-for="customer in uploadCustomerOptions"
            :key="customer.id"
            :value="customer.id"
          >
            {{ customer.name }}
          </a-option>
        </a-select>
      </div>
      <a-button size="small" :loading="saveLoading" :disabled="!canSaveApplication" @click="emit('saveDraft')">
        {{ t('workshop.saveDraft') }}
      </a-button>
      <a-button size="small" type="primary" :loading="saveLoading" :disabled="!canSaveApplication" @click="emit('publish')">
        {{ t('workshop.publishApplication') }}
      </a-button>

      <div class="application-workshop-header__more">
        <a-button size="small" @click="moreOpen = !moreOpen">{{ t('workshop.more') }}</a-button>
        <div v-if="moreOpen" class="application-workshop-header__more-panel">
          <div class="application-workshop-header__more-status">
            <span>{{ t('workshop.publishStatus') }}</span>
            <a-tag size="small" :color="saved ? 'green' : 'blue'">
              {{ saved ? t('workshop.published') : t('workshop.unpublished') }}
            </a-tag>
          </div>

          <a-button
            size="small"
            type="primary"
            long
            :loading="uploadingSample"
            :disabled="!canUploadSample || taskLoading"
            @click="closeAndEmit('uploadSample')"
          >
            {{ t('workshop.uploadSampleAndOcr') }}
          </a-button>
          <a-button size="small" long @click="closeAndEmit('backToMarket')">
            {{ t('workshop.backToApplicationCenter') }}
          </a-button>
          <a-button v-if="isEditingApplication" size="small" long @click="closeAndEmit('backToDetail')">
            {{ t('workshop.backToApplicationDetail') }}
          </a-button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.application-workshop-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 42px;
  padding: 4px 8px 8px;
  border-bottom: 1px solid #d7dee8;
  background: #f8fafc;
}

.application-workshop-header__path,
.application-workshop-header__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 0;
  flex-wrap: nowrap;
}

.application-workshop-header__application-name {
  width: 220px;
  flex: 0 1 220px;
}

.application-workshop-header__customer {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  min-width: 0;
}

.application-workshop-header__customer span {
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.application-workshop-header__customer-select {
  width: 156px;
}

.application-workshop-header__more {
  position: relative;
  flex: 0 0 auto;
}

.application-workshop-header__more-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 30;
  display: grid;
  width: 240px;
  gap: 10px;
  padding: 12px;
  border: 1px solid #d7dee8;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.14);
}

.application-workshop-header__more-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.application-workshop-header__path {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}

.application-workshop-header__path strong {
  max-width: 460px;
  overflow: hidden;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-workshop-header__path em {
  color: #64748b;
  font-style: normal;
  font-weight: 500;
}

@media (max-width: 1180px) {
  .application-workshop-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .application-workshop-header__actions {
    justify-content: flex-start;
    flex-wrap: wrap;
    width: 100%;
  }
}

@media (max-width: 720px) {
  .application-workshop-header__application-name,
  .application-workshop-header__customer,
  .application-workshop-header__customer-select {
    width: 100%;
    flex: 1 1 100%;
  }
}
</style>
