<script setup lang="ts">
import { reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { currentLocale, setLocale, t, type SupportedLocale } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useWorkbenchStore } from '../stores/workbench'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const workbenchStore = useWorkbenchStore()
const form = reactive({
  account: '',
  password: '',
})
const localeOptions: Array<{ locale: SupportedLocale; label: string }> = [
  { locale: 'zh-CN', label: t('locale.zhCN') },
  { locale: 'en-US', label: t('locale.enUS') },
]
async function submitLogin() {
  if (!form.account.trim()) {
    Message.warning(t('auth.usernamePlaceholder'))
    return
  }
  if (!form.password.trim()) {
    Message.warning(t('auth.passwordPlaceholder'))
    return
  }

  try {
    const user = await auth.login(form.account.trim(), form.password)
    workbenchStore.reset()
    workbenchStore.setRole(user.role === 'user' ? 'customer' : user.role)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    const target = redirect || (user.role === 'admin' ? '/admin' : '/tasks')
    await router.push(target)
    Message.success(t('auth.loginSuccess'))
  } catch (error) {
    Message.error(error instanceof Error ? error.message : t('auth.loginFailure'))
  }
}
</script>

<template>
  <div class="entry-page">
    <section class="entry-page__frame">
      <div class="entry-page__intro">
        <div class="entry-page__intro-main">
          <p class="entry-page__kicker">文档接入与智能理解</p>
          <h2>旗讯OCR智能文档处理平台</h2>
          <p class="entry-page__summary">
            支持 PPT、Excel、Word、PDF、图片等文档统一进入处理链路，完成识别、理解与结构化输出后，继续服务知识库、大模型与业务流程。
          </p>
        </div>
        <div class="entry-page__hero-visual">
          <div class="entry-page__process">
            <div class="entry-page__process-track" />

            <article class="entry-page__process-step entry-page__process-step--upload">
              <div class="entry-page__process-head">
                <span class="entry-page__process-index">01</span>
                <div>
                  <h3>多格式接入</h3>
                  <p>PPT、Excel、Word、PDF 与图片统一进入处理链路。</p>
                </div>
              </div>
              <div class="entry-page__upload-scene">
                <div class="entry-page__upload-stage">
                  <div class="entry-page__upload-dropzone">
                    <div class="entry-page__upload-queue">
                      <div class="entry-page__upload-file entry-page__upload-file--active">
                        <span class="entry-page__upload-file-icon" />
                        <div class="entry-page__upload-file-lines">
                          <span />
                          <span />
                        </div>
                      </div>
                      <div class="entry-page__upload-file entry-page__upload-file--queued">
                        <span class="entry-page__upload-file-icon" />
                        <div class="entry-page__upload-file-lines">
                          <span />
                          <span />
                        </div>
                      </div>
                      <div class="entry-page__upload-file entry-page__upload-file--queued entry-page__upload-file--queued-2">
                        <span class="entry-page__upload-file-icon" />
                        <div class="entry-page__upload-file-lines">
                          <span />
                          <span />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="entry-page__upload-types">
                    <span>PPT</span>
                    <span>Excel</span>
                    <span>Word</span>
                    <span>PDF</span>
                    <span>图片</span>
                  </div>
                </div>
                <div class="entry-page__upload-progress-list">
                  <div class="entry-page__upload-progress entry-page__upload-progress--1">
                    <label>合同 / PDF</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                  <div class="entry-page__upload-progress entry-page__upload-progress--2">
                    <label>发票 / 图片</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                  <div class="entry-page__upload-progress entry-page__upload-progress--3">
                    <label>表格 / Excel</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                  <div class="entry-page__upload-progress entry-page__upload-progress--4">
                    <label>报告 / Word</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                  <div class="entry-page__upload-progress entry-page__upload-progress--5">
                    <label>演示稿 / PPT</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                  <div class="entry-page__upload-progress entry-page__upload-progress--6">
                    <label>扫描件 / 图片</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                  <div class="entry-page__upload-progress entry-page__upload-progress--7">
                    <label>附件 / 压缩包</label>
                    <div class="entry-page__upload-progress-bar"><span /></div>
                  </div>
                </div>
              </div>
            </article>

            <article class="entry-page__process-step entry-page__process-step--recognize">
              <div class="entry-page__process-head">
                <span class="entry-page__process-index">02</span>
                <div>
                  <h3>智能解析</h3>
                  <p>完成 OCR、版面理解、表格识别与结构化抽取。</p>
                </div>
              </div>
              <div class="entry-page__recognition-scene">
                <div class="entry-page__recognition-preview">
                  <div class="entry-page__recognition-scanline" />
                  <div class="entry-page__recognition-tabs">
                    <span class="entry-page__recognition-tab entry-page__recognition-tab--active">表格</span>
                    <span class="entry-page__recognition-tab">KV</span>
                    <span class="entry-page__recognition-tab">文本</span>
                  </div>
                  <div class="entry-page__recognition-table">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
                <div class="entry-page__recognition-results">
                  <div class="entry-page__recognition-field">
                    <span />
                    <strong />
                  </div>
                  <div class="entry-page__recognition-field">
                    <span />
                    <strong />
                  </div>
                  <div class="entry-page__recognition-field">
                    <span />
                    <strong />
                  </div>
                  <div class="entry-page__recognition-field">
                    <span />
                    <strong />
                  </div>
                  <div class="entry-page__recognition-field">
                    <span />
                    <strong />
                  </div>
                  <div class="entry-page__recognition-text">
                    <span />
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
                <div class="entry-page__recognition-support">
                  <div class="entry-page__recognition-support-item">
                    <label>字段映射</label>
                    <span />
                  </div>
                  <div class="entry-page__recognition-support-item">
                    <label>表格切片</label>
                    <span />
                  </div>
                  <div class="entry-page__recognition-support-item">
                    <label>版面定位</label>
                    <span />
                  </div>
                  <div class="entry-page__recognition-support-item">
                    <label>结果校验</label>
                    <span />
                  </div>
                </div>
              </div>
            </article>

            <article class="entry-page__process-step entry-page__process-step--business">
              <div class="entry-page__process-head">
                <span class="entry-page__process-index">03</span>
                <div>
                  <h3>场景应用</h3>
                  <p>识别结果继续服务知识库、大模型与二次业务应用。</p>
                </div>
              </div>
              <div class="entry-page__business-scene">
                <div class="entry-page__business-flow">
                  <div class="entry-page__business-core">
                    <span class="entry-page__business-core-node" />
                    <strong>结构结果</strong>
                    <small>统一输出</small>
                  </div>
                  <div class="entry-page__business-branch">
                    <span class="entry-page__business-line entry-page__business-line--top" />
                    <span class="entry-page__business-line entry-page__business-line--middle" />
                    <span class="entry-page__business-line entry-page__business-line--bottom" />
                  </div>
                  <div class="entry-page__business-targets">
                    <div class="entry-page__business-target">
                      <strong>知识库</strong>
                      <span />
                    </div>
                    <div class="entry-page__business-target">
                      <strong>大模型</strong>
                      <span />
                    </div>
                    <div class="entry-page__business-target">
                      <strong>业务系统</strong>
                      <span />
                    </div>
                    <div class="entry-page__business-target">
                      <strong>检索问答</strong>
                      <span />
                    </div>
                    <div class="entry-page__business-target">
                      <strong>流程自动化</strong>
                      <span />
                    </div>
                  </div>
                </div>
                <div class="entry-page__business-cards">
                  <div class="entry-page__business-card entry-page__business-card--kb" />
                  <div class="entry-page__business-card entry-page__business-card--llm" />
                  <div class="entry-page__business-card entry-page__business-card--app" />
                  <div class="entry-page__business-card entry-page__business-card--search" />
                  <div class="entry-page__business-card entry-page__business-card--flow" />
                </div>
                <div class="entry-page__business-support">
                  <div class="entry-page__business-support-item">
                    <label>知识入库</label>
                    <span />
                  </div>
                  <div class="entry-page__business-support-item">
                    <label>智能问答</label>
                    <span />
                  </div>
                  <div class="entry-page__business-support-item">
                    <label>流程触发</label>
                    <span />
                  </div>
                  <div class="entry-page__business-support-item">
                    <label>系统回填</label>
                    <span />
                  </div>
                </div>
              </div>
            </article>
          </div>
        </div>
      </div>

      <div class="entry-page__auth">
        <div class="entry-page__locale" :aria-label="t('locale.switchLabel')">
          <button
            v-for="item in localeOptions"
            :key="item.locale"
            type="button"
            :class="{ 'is-active': currentLocale === item.locale }"
            @click="setLocale(item.locale)"
          >
            {{ item.label }}
          </button>
        </div>
        <div class="entry-page__auth-head">
          <div>
            <span class="entry-page__auth-label">{{ t('auth.systemLogin') }}</span>
            <h3>{{ t('auth.accountLogin') }}</h3>
            <p class="entry-page__auth-summary">{{ t('auth.loginSummary') }}</p>
          </div>
        </div>

        <div class="entry-page__auth-panel">
          <div class="entry-page__fields">
            <label class="entry-page__field">
              <span>{{ t('auth.username') }}</span>
              <input
                v-model="form.account"
                type="text"
                :placeholder="t('auth.usernamePlaceholder')"
                autocomplete="username"
              />
            </label>

            <label class="entry-page__field">
              <span>{{ t('auth.password') }}</span>
              <input
                v-model="form.password"
                type="password"
                :placeholder="t('auth.passwordPlaceholder')"
                autocomplete="current-password"
                @keydown.enter="submitLogin"
              />
            </label>
          </div>

          <div class="entry-page__submit">
            <a-button type="primary" size="large" long :loading="auth.loginLoading" @click="submitLogin">
              {{ t('auth.submitLogin') }}
            </a-button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.entry-page {
  min-height: 100vh;
}

.entry-page__frame {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(420px, 0.9fr);
  min-height: 100vh;
  background:
    linear-gradient(90deg, rgba(15, 23, 42, 0.02) 0, rgba(15, 23, 42, 0.02) 1px, transparent 1px, transparent 96px),
    linear-gradient(180deg, rgba(15, 23, 42, 0.02) 0, rgba(15, 23, 42, 0.02) 1px, transparent 1px, transparent 96px),
    linear-gradient(180deg, #f3f6fa 0%, #edf2f7 100%);
}

.entry-page__intro,
.entry-page__auth {
  position: relative;
  padding: 30px 28px;
  box-sizing: border-box;
}

.entry-page__intro {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 14px;
  border-right: 1px solid #d8dee8;
}

.entry-page__kicker {
  margin: 0 0 10px;
  color: #b45309;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.entry-page__intro-main h2 {
  max-width: 580px;
  margin: 0;
  color: #111827;
  font-size: 32px;
  line-height: 1.16;
  letter-spacing: -0.025em;
}

.entry-page__summary {
  max-width: 600px;
  margin: 10px 0 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.7;
}

.entry-page__hero-visual {
  display: flex;
  align-items: stretch;
  height: 100%;
  min-height: clamp(420px, 56vh, 640px);
  border: 1px solid #d8dee8;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.12), transparent 30%),
    linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%);
  overflow: hidden;
}

.entry-page__process {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
  gap: 14px;
  width: 100%;
  min-height: 0;
  height: auto;
  padding: 16px;
}

.entry-page__process-track {
  position: absolute;
  top: 108px;
  left: 44px;
  right: 44px;
  height: 2px;
  background: linear-gradient(90deg, #cbd5e1 0%, #bfdbfe 30%, #cbd5e1 100%);
}

.entry-page__process-track::after {
  content: '';
  position: absolute;
  top: -2px;
  left: -10%;
  width: 18%;
  height: 6px;
  background: linear-gradient(90deg, transparent 0%, rgba(37, 99, 235, 0.95) 50%, transparent 100%);
  animation: processFlow 3.8s linear infinite;
}

.entry-page__process-step {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-rows: auto 1fr;
  align-self: stretch;
  gap: 12px;
  align-content: start;
  height: 100%;
  padding: 16px;
  border: 1px solid #d8e1ec;
  width: 100%;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.entry-page__process-step::before {
  content: '';
  position: absolute;
  top: 20px;
  left: 18px;
  width: 12px;
  height: 12px;
  background: #2563eb;
  box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.12);
}

.entry-page__process-head {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 12px;
  align-items: start;
}

.entry-page__process-index {
  min-width: 32px;
  padding-top: 18px;
  color: #94a3b8;
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
}

.entry-page__process-head h3 {
  margin: 0;
  color: #0f172a;
  font-size: 18px;
}

.entry-page__process-head p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.entry-page__upload-scene,
.entry-page__recognition-scene,
.entry-page__business-scene {
  display: grid;
  grid-template-rows: auto auto;
  align-content: start;
  gap: 10px;
  min-height: 0;
}

.entry-page__upload-stage {
  display: grid;
  gap: 8px;
}

.entry-page__upload-dropzone {
  display: grid;
  place-items: center;
  min-height: 72px;
  padding: 12px;
  border: 1px dashed #93c5fd;
  background: linear-gradient(180deg, #f8fbff 0%, #eef4ff 100%);
  overflow: hidden;
}

.entry-page__upload-queue {
  position: relative;
  width: 148px;
  height: 108px;
}

.entry-page__upload-file {
  position: absolute;
  left: 50%;
  top: 8px;
  display: grid;
  gap: 10px;
  width: 108px;
  padding: 16px 14px;
  border: 1px solid #bfdbfe;
  background: #ffffff;
  transform: translateX(-50%);
}

.entry-page__upload-file-icon {
  width: 30px;
  height: 38px;
  background: linear-gradient(180deg, #2563eb 0%, #60a5fa 100%);
}

.entry-page__upload-file-lines {
  display: grid;
  gap: 6px;
}

.entry-page__upload-file-lines span {
  display: block;
  height: 7px;
  background: #dbeafe;
}

.entry-page__upload-types {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.entry-page__upload-types span {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border: 1px solid #dbeafe;
  background: rgba(255, 255, 255, 0.84);
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.entry-page__upload-file--active {
  z-index: 3;
  animation: uploadLead 3.4s ease-in-out infinite;
}

.entry-page__upload-file--queued {
  z-index: 2;
  top: 18px;
  opacity: 0.84;
  transform: translateX(-42%) scale(0.94);
  animation: uploadQueue 3.4s ease-in-out infinite;
}

.entry-page__upload-file--queued-2 {
  z-index: 1;
  top: 28px;
  opacity: 0.7;
  transform: translateX(-34%) scale(0.88);
  animation-delay: 0.35s;
}

.entry-page__upload-progress-list {
  display: grid;
  gap: 8px;
}

.entry-page__upload-progress {
  display: grid;
  gap: 6px;
}

.entry-page__upload-progress label {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
}

.entry-page__upload-progress-bar {
  height: 8px;
  background: #e2e8f0;
  overflow: hidden;
}

.entry-page__upload-progress span {
  display: block;
  width: 28%;
  height: 100%;
  background: linear-gradient(90deg, #2563eb 0%, #60a5fa 100%);
  animation: uploadProgress 2.6s ease-in-out infinite;
}

.entry-page__upload-progress--2 span {
  animation-delay: 0.45s;
}

.entry-page__upload-progress--3 span {
  animation-delay: 0.9s;
}

.entry-page__upload-progress--4 span {
  animation-delay: 1.35s;
}

.entry-page__upload-progress--5 span {
  animation-delay: 1.7s;
}

.entry-page__upload-progress--6 span {
  animation-delay: 2.05s;
}

.entry-page__upload-progress--7 span {
  animation-delay: 2.4s;
}

.entry-page__recognition-preview {
  position: relative;
  display: grid;
  gap: 10px;
  align-content: start;
  padding: 16px;
  min-height: 72px;
  border: 1px solid #dbeafe;
  background: #ffffff;
  overflow: hidden;
}

.entry-page__recognition-scanline {
  position: absolute;
  left: 0;
  right: 0;
  height: 28px;
  background: linear-gradient(180deg, transparent 0%, rgba(37, 99, 235, 0.12) 50%, transparent 100%);
  animation: recognitionScan 2.8s ease-in-out infinite;
}

.entry-page__recognition-tabs {
  display: flex;
  gap: 8px;
}

.entry-page__recognition-tab {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  animation: tabSwap 4.2s ease-in-out infinite;
}

.entry-page__recognition-tab:nth-child(2) {
  animation-delay: 1.1s;
}

.entry-page__recognition-tab:nth-child(3) {
  animation-delay: 2.2s;
}

.entry-page__recognition-tab--active {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

.entry-page__recognition-table {
  display: grid;
  gap: 10px;
}

.entry-page__recognition-table span {
  display: block;
  height: 14px;
  background:
    linear-gradient(90deg, #2563eb 0 18%, #dbeafe 18% 46%, #bfdbfe 46% 70%, #e2e8f0 70% 100%);
  position: relative;
  overflow: hidden;
}

.entry-page__recognition-table span::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 -18%;
  width: 18%;
  background: linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.86) 50%, transparent 100%);
  animation: rowSweep 2.4s linear infinite;
}

.entry-page__recognition-table span:nth-child(2)::after {
  animation-delay: 0.35s;
}

.entry-page__recognition-table span:nth-child(3)::after {
  animation-delay: 0.7s;
}

.entry-page__recognition-results {
  display: grid;
  gap: 10px;
}

.entry-page__recognition-scene,
.entry-page__business-scene {
  grid-template-rows: auto auto 1fr;
  height: 100%;
}

.entry-page__recognition-field {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 10px;
  align-items: center;
}

.entry-page__recognition-field span,
.entry-page__recognition-field strong {
  display: block;
  height: 10px;
}

.entry-page__recognition-field span {
  background: #cbd5e1;
}

.entry-page__recognition-field strong {
  background: linear-gradient(90deg, #2563eb 0%, #60a5fa 60%, #bfdbfe 100%);
  animation: fieldFill 3s ease-in-out infinite;
}

.entry-page__recognition-field:nth-child(2) strong {
  animation-delay: 0.4s;
}

.entry-page__recognition-field:nth-child(3) strong {
  animation-delay: 0.8s;
}

.entry-page__recognition-field:nth-child(4) strong {
  animation-delay: 1.2s;
}

.entry-page__recognition-field:nth-child(5) strong {
  animation-delay: 1.6s;
}

.entry-page__recognition-text {
  display: grid;
  gap: 7px;
  padding-top: 2px;
}

.entry-page__recognition-text span {
  display: block;
  height: 8px;
  background: #e2e8f0;
  animation: textReveal 3.4s ease-in-out infinite;
}

.entry-page__recognition-text span:nth-child(1) {
  width: 86%;
}

.entry-page__recognition-text span:nth-child(2) {
  width: 72%;
  animation-delay: 0.45s;
}

.entry-page__recognition-text span:nth-child(3) {
  width: 78%;
  animation-delay: 0.9s;
}

.entry-page__recognition-text span:nth-child(4) {
  width: 64%;
  animation-delay: 1.35s;
}

.entry-page__recognition-support {
  display: grid;
  align-content: end;
  gap: 10px;
  min-height: 100%;
}

.entry-page__recognition-support-item {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 10px;
  align-items: center;
}

.entry-page__recognition-support-item label {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.entry-page__recognition-support-item span {
  display: block;
  height: 8px;
  background: linear-gradient(90deg, #e2e8f0 0%, #cbd5e1 36%, #e2e8f0 100%);
  animation: textReveal 3.2s ease-in-out infinite;
}

.entry-page__business-flow {
  display: grid;
  grid-template-columns: 88px 28px 1fr;
  align-items: center;
  gap: 10px;
  min-height: 0;
}

.entry-page__business-core {
  display: grid;
  justify-items: center;
  gap: 6px;
  padding: 12px 8px;
  border: 1px solid #dbeafe;
  background: #ffffff;
}

.entry-page__business-core-node {
  width: 18px;
  height: 18px;
  background: #2563eb;
  box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.12);
  animation: nodePulse 2.8s ease-in-out infinite;
}

.entry-page__business-core strong {
  color: #0f172a;
  font-size: 13px;
}

.entry-page__business-core small {
  color: #64748b;
  font-size: 11px;
}

.entry-page__business-branch {
  display: grid;
  gap: 16px;
}

.entry-page__business-line {
  position: relative;
  display: block;
  height: 6px;
  background: #e2e8f0;
  overflow: hidden;
}

.entry-page__business-line::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 -40%;
  width: 40%;
  background: linear-gradient(90deg, transparent 0%, #60a5fa 50%, transparent 100%);
  animation: lineTravel 2.4s linear infinite;
}

.entry-page__business-line--middle::after {
  animation-delay: 0.4s;
}

.entry-page__business-line--bottom::after {
  animation-delay: 0.8s;
}

.entry-page__business-targets {
  display: grid;
  gap: 10px;
}

.entry-page__business-target {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 10px;
  align-items: center;
}

.entry-page__business-target strong {
  color: #0f172a;
  font-size: 12px;
}

.entry-page__business-target span {
  display: block;
  height: 10px;
  background: linear-gradient(90deg, #2563eb 0%, #60a5fa 62%, #dbeafe 100%);
  animation: targetFill 3s ease-in-out infinite;
}

.entry-page__business-target:nth-child(2) span {
  animation-delay: 0.35s;
}

.entry-page__business-target:nth-child(3) span {
  animation-delay: 0.7s;
}

.entry-page__business-target:nth-child(4) span {
  animation-delay: 1.05s;
}

.entry-page__business-target:nth-child(5) span {
  animation-delay: 1.4s;
}

.entry-page__business-cards {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.entry-page__business-card {
  height: 48px;
  border: 1px solid #dbeafe;
  background: linear-gradient(90deg, #eff6ff 0%, #ffffff 100%);
  animation: resultReveal 3.2s ease-in-out infinite;
}

.entry-page__business-card--kb::before,
.entry-page__business-card--llm::before,
.entry-page__business-card--app::before {
  content: '';
  display: block;
  height: 100%;
  width: 100%;
}

.entry-page__business-card--kb::before {
  background:
    linear-gradient(90deg, #2563eb 0 18%, #60a5fa 18% 42%, transparent 42% 100%);
}

.entry-page__business-card--llm::before {
  background:
    linear-gradient(90deg, #7c3aed 0 18%, #a78bfa 18% 42%, transparent 42% 100%);
}

.entry-page__business-card--app::before {
  background:
    linear-gradient(90deg, #f59e0b 0 18%, #fdba74 18% 42%, transparent 42% 100%);
}

.entry-page__business-card--search::before,
.entry-page__business-card--flow::before {
  content: '';
  display: block;
  height: 100%;
  width: 100%;
}

.entry-page__business-card--search::before {
  background:
    linear-gradient(90deg, #0ea5e9 0 18%, #7dd3fc 18% 42%, transparent 42% 100%);
}

.entry-page__business-card--flow::before {
  background:
    linear-gradient(90deg, #10b981 0 18%, #6ee7b7 18% 42%, transparent 42% 100%);
}

.entry-page__business-card:nth-child(2) {
  animation-delay: 0.55s;
}

.entry-page__business-card:nth-child(3) {
  animation-delay: 1.1s;
}

.entry-page__business-card:nth-child(4) {
  animation-delay: 1.65s;
}

.entry-page__business-card:nth-child(5) {
  animation-delay: 2.2s;
}

.entry-page__business-support {
  display: grid;
  align-content: end;
  gap: 10px;
  min-height: 100%;
}

.entry-page__business-support-item {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 10px;
  align-items: center;
}

.entry-page__business-support-item label {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.entry-page__business-support-item span {
  display: block;
  height: 8px;
  background: linear-gradient(90deg, #e2e8f0 0%, #cbd5e1 36%, #e2e8f0 100%);
  animation: textReveal 3.2s ease-in-out infinite;
}

/* 登录区保持紧凑块状，避免面板被剩余高度拉出大面积空白。 */
.entry-page__auth {
  display: grid;
  grid-template-rows: auto auto;
  align-content: center;
  justify-content: center;
  gap: 12px;
  min-height: 100%;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.88) 0%, rgba(255, 255, 255, 0.94) 100%),
    linear-gradient(135deg, rgba(249, 115, 22, 0.06), rgba(15, 23, 42, 0.03));
}

.entry-page__locale {
  position: absolute;
  top: 22px;
  right: 24px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid #d8dee8;
  background: rgba(255, 255, 255, 0.9);
}

.entry-page__locale button {
  min-width: 48px;
  height: 28px;
  border: 0;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.18s ease,
    color 0.18s ease;
}

.entry-page__locale button:hover,
.entry-page__locale button.is-active {
  background: #111827;
  color: #ffffff;
}

.entry-page__auth-head {
  display: grid;
  gap: 6px;
  max-width: 500px;
}

.entry-page__auth-head,
.entry-page__auth-panel {
  width: 100%;
  max-width: 500px;
}

.entry-page__auth-label {
  display: inline-block;
  margin-bottom: 10px;
  color: #64748b;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.entry-page__auth-head h3 {
  margin: 0;
  color: #111827;
  font-size: 30px;
  line-height: 1.1;
}

.entry-page__auth-summary {
  margin: 6px 0 0;
  max-width: 500px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.entry-page__auth-panel {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 18px;
  min-height: 0;
  padding: 22px;
  border: 1px solid #d8dee8;
  background: rgba(255, 255, 255, 0.82);
}

.entry-page__fields {
  display: grid;
  gap: 14px;
}

.entry-page__field {
  display: grid;
  gap: 8px;
}

.entry-page__field span {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.entry-page__field input {
  width: 100%;
  height: 48px;
  padding: 0 14px;
  border: 1px solid #cbd5e1;
  outline: none;
  background: #fff;
  color: #111827;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.entry-page__field input:focus {
  border-color: #f59e0b;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.18);
}

.entry-page__submit :deep(.arco-btn) {
  height: 48px;
  border-radius: 0;
  font-weight: 600;
}

.entry-page__submit :deep(.arco-btn-primary) {
  background: linear-gradient(90deg, #111827 0%, #1f2937 100%);
}

@keyframes processFlow {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(680%);
  }
}

@keyframes uploadLead {
  0%,
  100% {
    transform: translateX(-50%) translateY(10px);
  }
  50% {
    transform: translateX(-50%) translateY(-2px);
  }
}

@keyframes uploadQueue {
  0%,
  100% {
    transform: translateX(-42%) scale(0.94);
  }
  50% {
    transform: translateX(-48%) translateY(-3px) scale(0.97);
  }
}

@keyframes uploadProgress {
  0%,
  100% {
    width: 22%;
  }
  50% {
    width: 88%;
  }
}

@keyframes recognitionScan {
  0% {
    transform: translateY(0);
  }
  100% {
    transform: translateY(96px);
  }
}

@keyframes rowSweep {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(620%);
  }
}

@keyframes fieldFill {
  0%,
  100% {
    width: 32%;
    opacity: 0.7;
  }
  50% {
    width: 100%;
    opacity: 1;
  }
}

@keyframes tabSwap {
  0%,
  100% {
    opacity: 0.6;
    transform: translateY(0);
  }
  18% {
    opacity: 1;
    transform: translateY(-1px);
  }
  32% {
    opacity: 1;
  }
}

@keyframes textReveal {
  0%,
  100% {
    opacity: 0.45;
    transform: scaleX(0.84);
    transform-origin: left center;
  }
  50% {
    opacity: 1;
    transform: scaleX(1);
  }
}

@keyframes nodePulse {
  0%,
  100% {
    transform: scale(1);
    box-shadow: none;
  }
  50% {
    transform: scale(1.1);
    box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.12);
  }
}

@keyframes lineTravel {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(460%);
  }
}

@keyframes targetFill {
  0%,
  100% {
    opacity: 0.5;
    transform: scaleX(0.72);
    transform-origin: left center;
  }
  50% {
    opacity: 1;
    transform: scaleX(1);
  }
}

@keyframes resultReveal {
  0%,
  100% {
    opacity: 0.7;
    transform: translateX(0);
  }
  50% {
    opacity: 1;
    transform: translateX(4px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .entry-page__process-track::after,
  .entry-page__upload-file,
  .entry-page__upload-progress span,
  .entry-page__recognition-scanline,
  .entry-page__recognition-field strong,
  .entry-page__business-node,
  .entry-page__business-line::after,
  .entry-page__business-card {
    animation: none !important;
  }
}

@media (max-width: 1120px) {
  .entry-page__frame {
    grid-template-columns: 1fr;
  }

  .entry-page__intro {
    border-right: none;
    border-bottom: 1px solid #d8dee8;
  }
}

@media (max-width: 960px) {
  .entry-page {
    min-height: auto;
  }

  .entry-page__frame {
    min-height: auto;
  }

  .entry-page__intro,
  .entry-page__auth {
    padding: 22px 20px;
  }

  .entry-page__locale {
    top: 16px;
    right: 18px;
  }

  .entry-page__intro {
    grid-template-rows: auto auto;
  }

  .entry-page__auth-head {
    gap: 8px;
  }

  .entry-page__intro-main h2 {
    font-size: 28px;
  }

  .entry-page__hero-visual {
    height: auto;
    min-height: 0;
  }

  .entry-page__process {
    grid-template-columns: 1fr;
  }

  .entry-page__process-step {
    padding: 14px;
  }

  .entry-page__upload-dropzone,
  .entry-page__recognition-preview {
    min-height: 0;
  }

  .entry-page__auth {
    grid-template-rows: auto auto;
    padding-top: 62px;
  }

  .entry-page__auth-panel {
    padding: 20px 16px;
  }

  .entry-page__business-flow,
  .entry-page__business-cards {
    grid-template-columns: 1fr;
  }
}
</style>
