<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import type { FieldRule, FormInstance } from '@arco-design/web-vue'
import { Message } from '@arco-design/web-vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import PanelCard from '../components/PanelCard.vue'
import { loadCustomers } from '../services/workbenchApi'
import { useWorkbenchStore } from '../stores/workbench'
import type { CustomerSummary } from '../types/workbench'
import { buildTablePagination } from '../utils/tablePagination'

const router = useRouter()
const store = useWorkbenchStore()
const uploadInputRef = ref<HTMLInputElement | null>(null)
const uploadTargetCustomerId = ref('')
const uploadingCustomerId = ref('')
const uploadingFileName = ref('')
const uploadSubmitting = ref(false)
const createModalVisible = ref(false)
const createSubmitting = ref(false)
const createFormRef = ref<FormInstance>()
const createFormError = ref('')
const loadError = ref('')
const customersLoading = ref(false)
const customerList = ref<CustomerSummary[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const totalCustomers = ref(0)
const createFieldErrors = reactive({
  username: '',
})
const createForm = reactive({
  name: '',
  projectCode: '',
  owner: '',
  description: '',
  accountEnabled: true,
  username: '',
  password: '',
  displayName: '',
})
const createFormRules: Record<string, FieldRule[]> = {
  name: [{ required: true, message: '请输入客户名称' }],
  projectCode: [{ required: true, message: '请输入项目编号' }],
  owner: [{ required: true, message: '请输入负责人' }],
  username: [{ required: true, message: '请输入登录账号' }],
  password: [
    { required: true, message: '请输入初始密码' },
    { minLength: 6, message: '初始密码至少 6 位' },
  ],
  displayName: [{ required: true, message: '请输入客户显示名' }],
}

watch(
  () => createForm.username,
  () => {
    createFieldErrors.username = ''
    createFormError.value = ''
  },
)

watch(
  () => [createForm.name, createForm.projectCode, createForm.owner, createForm.password, createForm.displayName, createForm.accountEnabled],
  () => {
    createFormError.value = ''
  },
)

onMounted(async () => {
  store.setRole('admin')
  try {
    await refreshCustomers()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '客户数据加载失败。'
  }
})

const customerRows = computed(() => customerList.value)
const totalDocuments = computed(() => customerRows.value.reduce((sum, item) => sum + item.documentCount, 0))
const totalTasks = computed(() => customerRows.value.reduce((sum, item) => sum + item.taskCount, 0))
const uploadingCustomer = computed(() =>
  customerRows.value.find((item) => item.id === uploadingCustomerId.value) || null,
)
const uploadNoticeTitle = computed(() => {
  if (!uploadSubmitting.value) return ''
  return uploadingCustomer.value ? `正在上传到 ${uploadingCustomer.value.name}` : '正在上传验证文档'
})
const uploadNoticeDescription = computed(() => {
  if (!uploadSubmitting.value) return ''
  return uploadingFileName.value
    ? `${uploadingFileName.value} 上传后会自动创建识别任务，并进入工作台。`
    : '上传后会自动创建识别任务，并进入工作台。'
})
const customerTablePagination = computed(() =>
  buildTablePagination({
    total: totalCustomers.value,
    current: currentPage.value,
    pageSize: pageSize.value,
  }),
)
const uniqueOwnerCount = computed(() => new Set(customerRows.value.map((item) => item.owner)).size)

const customerColumns = computed(() => [
  { title: '客户', dataIndex: 'name', width: 180 },
  { title: '项目编号', dataIndex: 'projectCode', width: 170 },
  { title: '负责人', dataIndex: 'owner', width: 120 },
  { title: '文档数', dataIndex: 'documentCount', width: 90 },
  { title: '任务数', dataIndex: 'taskCount', width: 90 },
  { title: '说明', dataIndex: 'description' },
  { title: '操作', slotName: 'actions', width: 180 },
])

function openCustomer(customerId: string) {
  router.push({ name: 'admin-customer', params: { customerId } })
}

function openUploadPicker(customerId: string) {
  if (uploadSubmitting.value) {
    Message.info('已有验证文档正在上传，请稍候。')
    return
  }
  uploadTargetCustomerId.value = customerId
  if (uploadInputRef.value) {
    uploadInputRef.value.value = ''
  }
  uploadInputRef.value?.click()
}

async function refreshCustomers(page = currentPage.value, size = pageSize.value) {
  customersLoading.value = true
  loadError.value = ''
  try {
    const response = await loadCustomers(page, size)
    customerList.value = response.items
    totalCustomers.value = response.total
    currentPage.value = response.page
    pageSize.value = response.pageSize
  } finally {
    customersLoading.value = false
  }
}

async function handlePageChange(page: number) {
  await refreshCustomers(page, pageSize.value)
}

async function handlePageSizeChange(size: number) {
  await refreshCustomers(1, size)
}

async function handleUploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const customerId = uploadTargetCustomerId.value

  if (!file || !customerId) {
    input.value = ''
    return
  }

  uploadSubmitting.value = true
  uploadingCustomerId.value = customerId
  uploadingFileName.value = file.name
  Message.info(`已选择 ${file.name}，正在上传验证。`)

  try {
    const result = await store.uploadAndParseDocument(customerId, file)
    await refreshCustomers()
    Message.success(result.parseStatus?.state === 'completed' ? '新 POC 验证已上传并完成识别。' : '新 POC 验证已上传，识别已启动。')
    await router.push({ name: 'task-detail', params: { taskId: result.response.createdTask.id } })
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '上传新的 POC 验证失败。')
  } finally {
    input.value = ''
    uploadTargetCustomerId.value = ''
    uploadingCustomerId.value = ''
    uploadingFileName.value = ''
    uploadSubmitting.value = false
  }
}

function openCreateCustomerModal() {
  createForm.name = ''
  createForm.projectCode = ''
  createForm.owner = ''
  createForm.description = ''
  createForm.accountEnabled = true
  createForm.username = ''
  createForm.password = ''
  createForm.displayName = ''
  createFormError.value = ''
  createFieldErrors.username = ''
  createModalVisible.value = true
}

function resolveCreateCustomerError(message: string) {
  createFormError.value = message
  if (message.includes('登录账号')) {
    createFieldErrors.username = message
  }
}

async function submitCreateCustomer(): Promise<boolean> {
  createFormError.value = ''
  createFieldErrors.username = ''
  const errors = await createFormRef.value?.validate()
  if (errors) {
    return false
  }

  const customerPayload = {
    name: createForm.name.trim(),
    projectCode: createForm.projectCode.trim(),
    owner: createForm.owner.trim(),
    description: createForm.description.trim(),
  }
  const accountPayload = {
    username: createForm.username.trim(),
    password: createForm.password.trim(),
    displayName: createForm.displayName.trim(),
  }

  createSubmitting.value = true
  try {
    const result = createForm.accountEnabled
      ? await store.createCustomerWithAccount({
          customer: customerPayload,
          account: {
            ...accountPayload,
          },
        })
      : { customer: await store.createCustomer(customerPayload), account: null }
    Message.success(
      result.account
        ? `客户与登录账号已创建，可直接使用账号 ${result.account.username} 登录。`
        : '客户已创建。',
    )
    await refreshCustomers()
    createModalVisible.value = false
    await router.push({ name: 'admin-customer', params: { customerId: result.customer.id } })
    return true
  } catch (error) {
    const message = error instanceof Error ? error.message : '新建客户失败。'
    resolveCreateCustomerError(message)
    Message.error(message)
    return false
  } finally {
    createSubmitting.value = false
  }
}

async function handleCreateCustomerBeforeOk() {
  return submitCreateCustomer()
}
</script>

<template>
  <div class="admin-customers-page">
    <PanelCard
      v-if="loadError"
      title="客户数据加载失败"
      :description="loadError"
    >
      <a-empty description="后端客户数据暂不可用，请先恢复 8002 服务后再刷新。" />
    </PanelCard>

    <template v-else>
      <AdminPageHeader
        breadcrumb="管理后台 / 客户管理"
        title="客户管理"
        subtitle="这里按客户空间看负责人、规模与说明，并从客户入口直接上传新的 POC 验证。"
        meta-label="客户总数"
        :meta-value="totalCustomers"
      >
        <template #actions>
          <a-button type="primary" @click="openCreateCustomerModal">新建客户</a-button>
        </template>
      </AdminPageHeader>

      <section class="admin-customers-page__metric-grid">
        <article class="admin-customers-page__metric-card">
          <span>客户</span>
          <strong>{{ totalCustomers }}</strong>
          <p>当前纳入管理的客户空间总量</p>
        </article>
        <article class="admin-customers-page__metric-card">
          <span>当前页文档</span>
          <strong>{{ totalDocuments }}</strong>
          <p>当前页客户累计文档规模</p>
        </article>
        <article class="admin-customers-page__metric-card admin-customers-page__metric-card--accent">
          <span>当前页负责人</span>
          <strong>{{ uniqueOwnerCount }}</strong>
          <p>当前页客户空间对应的负责人数量</p>
        </article>
        <article class="admin-customers-page__metric-card">
          <span>当前页任务</span>
          <strong>{{ totalTasks }}</strong>
          <p>当前页客户空间下累计任务总数</p>
        </article>
      </section>

      <PanelCard
        title="客户清单"
        description="按客户查看负责人、项目编号、规模与空间说明，并从这里直接上传新的 POC 验证或进入客户空间。"
      >
        <div v-if="uploadSubmitting" class="admin-customers-page__upload-status">
          <div class="admin-customers-page__upload-spinner" aria-hidden="true" />
          <div>
            <strong>{{ uploadNoticeTitle }}</strong>
            <span>{{ uploadNoticeDescription }}</span>
          </div>
        </div>
        <a-table
          :columns="customerColumns"
          :data="customerRows"
          row-key="id"
          :pagination="customerTablePagination"
          :loading="customersLoading"
          @page-change="handlePageChange"
          @page-size-change="handlePageSizeChange"
        >
          <template #actions="{ record }">
            <a-space>
              <a-button
                type="text"
                :loading="uploadSubmitting && uploadingCustomerId === record.id"
                :disabled="uploadSubmitting && uploadingCustomerId !== record.id"
                @click="openUploadPicker(record.id)"
              >
                {{ uploadSubmitting && uploadingCustomerId === record.id ? '上传中' : '上传验证' }}
              </a-button>
              <a-button type="text" @click="openCustomer(record.id)">进入空间</a-button>
            </a-space>
          </template>
        </a-table>
        <input
          ref="uploadInputRef"
          class="admin-customers-page__file-input"
          type="file"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
          @change="handleUploadChange"
        />
      </PanelCard>

      <a-modal
        v-model:visible="createModalVisible"
        title="新建客户"
        :width="720"
        :body-style="{ maxHeight: '72vh', overflow: 'auto', padding: '16px 20px 12px' }"
        :ok-loading="createSubmitting"
        :ok-text="createForm.accountEnabled ? '创建客户和账号' : '创建客户'"
        cancel-text="取消"
        :on-before-ok="handleCreateCustomerBeforeOk"
      >
        <a-form ref="createFormRef" :model="createForm" :rules="createFormRules" layout="vertical">
          <div v-if="createFormError" class="admin-customers-page__form-error">
            {{ createFormError }}
          </div>
          <div class="admin-customers-page__form-grid">
            <a-form-item field="name" label="客户名称" required>
              <a-input v-model="createForm.name" placeholder="例如：华东药业 PoC" />
            </a-form-item>
            <a-form-item field="projectCode" label="项目编号" required>
              <a-input v-model="createForm.projectCode" placeholder="例如：EAST-PHARM-2026" />
            </a-form-item>
            <a-form-item field="owner" label="负责人" required>
              <a-input v-model="createForm.owner" placeholder="例如：张顾问" />
            </a-form-item>
            <div />
            <a-form-item field="description" label="空间说明" class="admin-customers-page__form-item--full">
              <a-textarea
                v-model="createForm.description"
                :auto-size="{ minRows: 2, maxRows: 4 }"
                placeholder="说明该客户空间的业务背景或验证目标"
              />
            </a-form-item>
          </div>
          <div class="admin-customers-page__form-section">
            <div class="admin-customers-page__form-section-head">
              <div>
                <div class="admin-customers-page__form-section-title">客户登录账号</div>
                <p class="admin-customers-page__form-section-tip">默认同步创建客户账号，创建后即可用该账号直接登录客户工作区。</p>
              </div>
              <label class="admin-customers-page__switch-field">
                <span>同步创建</span>
                <a-switch v-model="createForm.accountEnabled" />
              </label>
            </div>
          </div>
          <template v-if="createForm.accountEnabled">
            <div class="admin-customers-page__form-grid">
              <a-form-item
                field="username"
                label="登录账号"
                required
                :help="createFieldErrors.username || undefined"
                :validate-status="createFieldErrors.username ? 'error' : undefined"
              >
                <a-input v-model="createForm.username" placeholder="例如：east-pharm-demo" />
              </a-form-item>
              <a-form-item field="password" label="初始密码" required>
                <a-input-password v-model="createForm.password" placeholder="至少 6 位" />
              </a-form-item>
              <a-form-item field="displayName" label="客户显示名" required class="admin-customers-page__form-item--full">
                <a-input v-model="createForm.displayName" placeholder="例如：华东药业项目组" />
              </a-form-item>
            </div>
          </template>
        </a-form>
      </a-modal>
    </template>
  </div>
</template>

<style scoped>
.admin-customers-page {
  display: grid;
  gap: 12px;
}

.admin-customers-page__metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.admin-customers-page__metric-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #ffffff;
}

.admin-customers-page__metric-card--accent {
  border-left: 2px solid #2563eb;
}

.admin-customers-page__metric-card span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.admin-customers-page__metric-card strong {
  color: #111827;
  font-size: 22px;
  line-height: 1.15;
  letter-spacing: -0.02em;
}

.admin-customers-page__metric-card p {
  margin: 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.admin-customers-page__file-input {
  display: none;
}

.admin-customers-page__upload-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1e3a8a;
}

.admin-customers-page__upload-status strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  line-height: 1.4;
}

.admin-customers-page__upload-status span {
  display: block;
  margin-top: 2px;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}

.admin-customers-page__upload-spinner {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  border: 2px solid rgba(37, 99, 235, 0.18);
  border-top-color: #2563eb;
  border-radius: 999px;
  animation: admin-customers-spin 0.8s linear infinite;
}

@keyframes admin-customers-spin {
  to {
    transform: rotate(360deg);
  }
}

.admin-customers-page__form-error {
  margin-bottom: 12px;
  padding: 8px 10px;
  border: 1px solid #f3c7c3;
  background: #fff3f2;
  color: #c0392b;
  font-size: 12px;
  line-height: 1.5;
}

.admin-customers-page__form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 12px;
}

.admin-customers-page__form-item--full {
  grid-column: 1 / -1;
}

.admin-customers-page__form-section {
  margin: 4px 0 8px;
  padding-top: 8px;
  border-top: 1px solid #e5e7eb;
}

.admin-customers-page__form-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.admin-customers-page__form-section-title {
  color: #111827;
  font-size: 13px;
  font-weight: 600;
}

.admin-customers-page__form-section-tip {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.admin-customers-page__switch-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #475569;
  font-size: 12px;
  white-space: nowrap;
}

.admin-customers-page :deep(.arco-table-th),
.admin-customers-page :deep(.arco-table-td) {
  white-space: nowrap;
}

.admin-customers-page :deep(.arco-form-item) {
  margin-bottom: 12px;
}

.admin-customers-page :deep(.arco-table) {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 0;
  overflow: hidden;
}

.admin-customers-page :deep(.arco-table-th) {
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
}

.admin-customers-page :deep(.arco-table-tr:hover .arco-table-td) {
  background: rgba(37, 99, 235, 0.04);
}

@media (max-width: 960px) {
  .admin-customers-page__metric-grid {
    grid-template-columns: 1fr;
  }

  .admin-customers-page__form-grid {
    grid-template-columns: 1fr;
  }

  .admin-customers-page__form-item--full {
    grid-column: auto;
  }

  .admin-customers-page__form-section-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
