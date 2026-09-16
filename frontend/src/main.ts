import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { installGlobalErrorHandlers } from './globalError'
import './style.css'

const app = createApp(App)
installGlobalErrorHandlers(app)
app.use(router)
app.mount('#app')

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* SW is an enhancement; app works without it */
    })
  })
}
