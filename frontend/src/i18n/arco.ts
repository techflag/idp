import { computed } from 'vue'
import enUS from '@arco-design/web-vue/es/locale/lang/en-us'
import zhCN from '@arco-design/web-vue/es/locale/lang/zh-cn'
import { currentLocale } from './index'

export const arcoLocale = computed(() => (currentLocale.value === 'en-US' ? enUS : zhCN))
