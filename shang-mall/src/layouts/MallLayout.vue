<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useClientType } from '@/composables/useClientType'
import { useBrandStore } from '@/stores/brand'
import { useCartStore } from '@/stores/cart'
import { useAuthStore } from '@/stores/auth'
import { resolveMediaUrl } from '@/utils/media'
import { fetchHome } from '@/api/catalog'

const route = useRoute()
const router = useRouter()
const { isH5, isWeb } = useClientType()
const brand = useBrandStore()
const cart = useCartStore()
const auth = useAuthStore()

const hideTab = computed(() => !!route.meta.hideTab)
const activeTab = computed(() => (route.meta.tab as string) || '')
const searchQ = ref('')
const hotKeywords = ref<string[]>([])

/** 频道栏槽位（V2 口径：活动位/热门精选）。标题取后台运营位配置，运营可改；下方仅为接口不可用时的兜底文案。 */
const CHANNEL_SLOTS = [
  { code: 'home_hot_spus', fallback: '热门精选', color: '#ff8a5b' },
  { code: 'home_promo_subsidy', fallback: '活动位 · 热门精选', color: '#e07a1c' },
  { code: 'home_promo_flash', fallback: '活动位 · 新品上架', color: '#c8453c' },
  { code: 'home_promo_live', fallback: '活动位 · 品牌专区', color: '#febb4a' },
]
const channelTitles = ref<Record<string, string>>({})

const channels = computed(() => [
  ...CHANNEL_SLOTS.map((s) => ({
    label: channelTitles.value[s.code] || s.fallback,
    to: `/promo/${s.code}`,
    color: s.color,
  })),
  { label: '全部分类', to: '/category', color: '#47704C' },
])

const activeChannel = computed(() => {
  const path = route.path
  const code = String(route.params.code || '')
  if (path.startsWith('/promo/') && code) return `/promo/${code}`
  if (path.startsWith('/category')) return '/category'
  return ''
})

onMounted(async () => {
  try {
    const res = await fetchHome(8)
    const slots = res.data.slots || []
    const kws = (slots.find((s) => s.code === 'home_hot_keywords')?.items || [])
      .map((it) => it.title)
      .filter(Boolean) as string[]
    if (kws.length) hotKeywords.value = kws
    const titles: Record<string, string> = {}
    slots.forEach((s) => {
      if (s.title) titles[s.code] = s.title
    })
    channelTitles.value = titles
  } catch {
    /* keep fallback */
  }
})

function onTab(name: string) {
  // 购物车游客可浏览；「我的」由路由守卫拉起登录层（PRD §8.0 / §8.1）
  const map: Record<string, string> = {
    home: '/',
    category: '/category',
    cart: '/cart',
    me: '/me',
  }
  router.push(map[name] || '/')
}

function onSearch() {
  const q = searchQ.value.trim()
  router.push(q ? { path: '/search', query: { q } } : '/search')
}

function goChannel(to: string) {
  if (route.fullPath === to || (to === '/category' && route.path === '/category')) {
    return
  }
  void router.push(to)
}
</script>

<template>
  <div class="mall" :class="{ 'is-h5': isH5, 'is-web': isWeb }">
    <!-- ===== Web 门户壳 ===== -->
    <template v-if="isWeb">
      <div class="web-utility">
        <div class="web-utility-inner">
          <span>中国大陆 · 北京</span>
          <div class="web-utility-links">
            <RouterLink v-if="!auth.isLoggedIn" to="/login">亲，请登录</RouterLink>
            <RouterLink v-if="!auth.isLoggedIn" to="/login">免费注册</RouterLink>
            <span v-else>Hi，{{ auth.customer?.nickname || '会员' }}</span>
            <RouterLink to="/me">我的尚品汇</RouterLink>
            <RouterLink to="/cart">购物车{{ cart.count ? `(${cart.count})` : '' }}</RouterLink>
            <RouterLink to="/favorites">收藏夹</RouterLink>
            <RouterLink to="/orders">我的订单</RouterLink>
          </div>
        </div>
      </div>

      <header class="web-header-main">
        <div class="web-header-inner">
          <RouterLink class="web-logo-block" to="/">
            <img :src="resolveMediaUrl(brand.logoUrl)" :alt="brand.displayName" />
            <div>
              <div class="name">{{ brand.displayName }}</div>
              <div class="tag">{{ brand.slogan }}</div>
            </div>
          </RouterLink>
          <div class="web-search-block">
            <form class="web-search-tb" @submit.prevent="onSearch">
              <div class="cat-select">商品 ▾</div>
              <input v-model="searchQ" placeholder="搜索商品名称 / 副标题" />
              <button type="submit" class="btn-search">搜索</button>
            </form>
            <div class="web-hot-tags">
              <RouterLink
                v-for="(kw, i) in hotKeywords"
                :key="kw"
                :to="{ path: '/search', query: { q: kw } }"
                :class="{ hot: i === 0 }"
              >
                {{ kw }}
              </RouterLink>
            </div>
          </div>
        </div>
      </header>

      <!-- 后台运营位落地页 / 分类 -->
      <nav class="web-shortcuts">
        <a
          v-for="ch in channels"
          :key="ch.to"
          href="javascript:;"
          :class="{ active: activeChannel === ch.to }"
          @click.prevent="goChannel(ch.to)"
        >
          <span class="dot" :style="{ background: ch.color }" />
          {{ ch.label }}
        </a>
      </nav>
    </template>

    <main class="mall-main">
      <RouterView />
    </main>

    <aside v-if="isWeb" class="web-float-rail" aria-label="快捷入口">
      <RouterLink to="/cart">
        <svg class="rail-ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="9" cy="20" r="1.5" /><circle cx="18" cy="20" r="1.5" />
          <path d="M2 3h3l2.5 12h12L22 7H6" />
        </svg>
        <span>购物车</span>
      </RouterLink>
      <RouterLink to="/favorites">
        <svg class="rail-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 20s-7-4.5-7-9.5A4 4 0 0112 7a4 4 0 017 3.5C19 15.5 12 20 12 20z" />
        </svg>
        <span>收藏</span>
      </RouterLink>
      <RouterLink to="/orders">
        <svg class="rail-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4" />
        </svg>
        <span>订单</span>
      </RouterLink>
      <RouterLink to="/me">
        <svg class="rail-ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" />
        </svg>
        <span>我的</span>
      </RouterLink>
    </aside>

    <footer v-if="isWeb" class="web-footer">
      {{ brand.displayName }} · Web 门户 · {{ brand.slogan }}
    </footer>

    <van-tabbar
      v-if="isH5 && !hideTab"
      :model-value="activeTab"
      active-color="var(--ink)"
      inactive-color="var(--muted)"
      @change="onTab"
    >
      <van-tabbar-item name="home" icon="home-o">首页</van-tabbar-item>
      <van-tabbar-item name="category" icon="apps-o">分类</van-tabbar-item>
      <van-tabbar-item name="cart" icon="shopping-cart-o" :badge="cart.count || ''">
        购物车
      </van-tabbar-item>
      <van-tabbar-item name="me" icon="user-o">我的</van-tabbar-item>
    </van-tabbar>
  </div>
</template>
