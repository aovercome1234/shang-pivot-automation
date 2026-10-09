<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { showToast } from 'vant'
import {
  CUSTOMER_FROZEN_CODE,
  LOGIN_FAILED_CODE,
  sendSms,
  type LoginResult,
} from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

/**
 * 登录表单（PRD §8.1）：手机号 11 位 / 1 开头，验证码 6 位；
 * 「获取验证码」发送后进入 60 秒倒计时不可重发；
 * 验证码错误内联红字在输入框下方，弹层不关闭。
 * 登录页与登录层共用，提交按钮由各自的容器渲染。
 */
withDefaults(defineProps<{ intro?: boolean }>(), { intro: false })

const emit = defineEmits<{ success: [LoginResult] }>()

const auth = useAuthStore()

const phone = ref('')
const code = ref('')
const phoneError = ref('')
const codeError = ref('')
const cooldown = ref(0)
const submitting = ref(false)
let timer: number | undefined

function stopTimer() {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
}

onUnmounted(stopTimer)

interface FailPayload {
  code?: number
  msg?: string
}

async function onSend() {
  phoneError.value = ''
  if (!/^1\d{10}$/.test(phone.value)) {
    phoneError.value = '请输入正确的手机号'
    return
  }
  if (cooldown.value > 0) return
  try {
    const res = await sendSms(phone.value)
    cooldown.value = res.data?.cooldownSec || 60
    showToast('验证码已发送（演示环境固定 123456）')
    stopTimer()
    timer = window.setInterval(() => {
      cooldown.value -= 1
      if (cooldown.value <= 0) stopTimer()
    }, 1000)
  } catch (err) {
    showToast((err as FailPayload)?.msg || '验证码发送失败，请稍后重试')
  }
}

async function submit() {
  if (submitting.value) return
  phoneError.value = ''
  codeError.value = ''
  if (!/^1\d{10}$/.test(phone.value)) {
    phoneError.value = '请输入正确的手机号'
    return
  }
  if (!/^\d{6}$/.test(code.value)) {
    codeError.value = '请输入 6 位验证码'
    return
  }
  submitting.value = true
  try {
    const res = await auth.login(phone.value, code.value)
    showToast('登录成功')
    emit('success', res)
  } catch (err) {
    const payload = err as FailPayload
    if (payload?.code === LOGIN_FAILED_CODE) {
      codeError.value = '验证码错误，请重新获取'
    } else if (payload?.code === CUSTOMER_FROZEN_CODE) {
      showToast('该账号不可用，请联系客服')
    } else {
      showToast(payload?.msg || '登录失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}

defineExpose({ submit, submitting })
</script>

<template>
  <div class="login-form">
    <p v-if="intro" class="muted intro">
      登录后才能加入购物车、下单与查看个人中心，登录成功后会回到刚才的页面。
    </p>

    <div class="field">
      <span class="field-label">手机号<span class="req">*</span></span>
      <input
        v-model="phone"
        class="input"
        :class="{ 'is-err': !!phoneError }"
        type="tel"
        inputmode="numeric"
        maxlength="11"
        placeholder="请输入 11 位手机号"
        @input="phoneError = ''"
      />
      <span v-if="phoneError" class="error-text">{{ phoneError }}</span>
      <span v-else class="hint">11 位数字，1 开头</span>
    </div>

    <div class="field">
      <span class="field-label">验证码<span class="req">*</span></span>
      <div class="code-row">
        <input
          v-model="code"
          class="input"
          :class="{ 'is-err': !!codeError }"
          type="tel"
          inputmode="numeric"
          maxlength="6"
          placeholder="请输入 6 位验证码"
          @input="codeError = ''"
        />
        <button
          type="button"
          class="btn btn-secondary code-btn"
          :disabled="cooldown > 0"
          @click="onSend"
        >
          {{ cooldown > 0 ? `${cooldown}s 后重发` : '获取验证码' }}
        </button>
      </div>
      <span v-if="codeError" class="error-text">{{ codeError }}</span>
      <span class="hint">演示环境验证码固定为 123456；发送后 60 秒内不可重发</span>
    </div>
  </div>
</template>

<style scoped>
.intro {
  margin: 0 0 16px;
  line-height: 1.6;
}

.code-row {
  display: flex;
  gap: 8px;
}

.code-row .input {
  flex: 1;
  min-width: 0;
}

.code-btn {
  white-space: nowrap;
  flex-shrink: 0;
}
</style>