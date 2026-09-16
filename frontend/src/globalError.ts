/** A page that renders nothing and a page that crashed look identical to a
 * viewer — both are just blank. That ambiguity is exactly what made an iPad
 * report of "the dashboard shows nothing" undiagnosable from here: every
 * request the page needed was verified working, so if the browser really
 * ran the same code, there was nothing left to blame but the code — and yet
 * no error ever reached the console-less person holding the iPad.
 *
 * This turns that class of failure visible. Anything Vue's own error
 * handling would otherwise only log to a console nobody on a phone can open
 * — a thrown error in a lifecycle hook, a rejected promise nothing awaited —
 * lands here instead, and App.vue renders it as a plain on-page banner.
 * Confirmed 2026-09-12: server and API were fine end to end while an iPad
 * dashboard stayed blank, with no way to see why.
 */
import { ref } from 'vue'

export const globalError = ref<string | null>(null)

export function reportError(source: string, err: unknown): void {
  const message = err instanceof Error ? (err.stack || err.message) : String(err)
  // eslint-disable-next-line no-console
  console.error(`[${source}]`, err)
  globalError.value = `${source}: ${message}`.slice(0, 2000)
}

export function installGlobalErrorHandlers(app: { config: { errorHandler?: unknown } }): void {
  ;(app.config as { errorHandler?: (err: unknown, instance: unknown, info: string) => void }).errorHandler =
    (err, _instance, info) => reportError(`组件错误(${info})`, err)
  window.addEventListener('error', (e) => reportError('脚本错误', e.error ?? e.message))
  window.addEventListener('unhandledrejection', (e) => reportError('未处理的 Promise 拒绝', e.reason))
}
