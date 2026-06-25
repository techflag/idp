// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
import { createApp } from 'vue'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { i18n, t } from './i18n'
import { pinia } from './stores/pinia'

document.title = (import.meta.env.VITE_APP_TITLE as string | undefined) || t('app.title')

const app = createApp(App)

app.use(pinia)
app.use(router)
app.use(i18n)
app.use(ArcoVue)
app.mount('#app')
