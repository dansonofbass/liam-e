const DEFAULT_UPDATE_THROTTLE_MS = 60_000

export interface ServiceWorkerContainerLike {
  register(scriptURL: string, options?: RegistrationOptions): Promise<{ update(): Promise<unknown> }>
}

export interface VisibilityDocumentLike {
  visibilityState: DocumentVisibilityState
  addEventListener(type: 'visibilitychange', listener: () => void): void
  removeEventListener(type: 'visibilitychange', listener: () => void): void
}

export interface RegisterServiceWorkerOptions {
  container?: ServiceWorkerContainerLike
  doc?: VisibilityDocumentLike
  now?: () => number
  throttleMs?: number
}

/**
 * Registers the navigation-offline service worker and rechecks for updates when a standalone or
 * long-lived tab returns to the foreground.
 */
export function registerServiceWorker(
  scriptUrl: string,
  options: RegisterServiceWorkerOptions = {},
): () => void {
  const container = options.container ?? (typeof navigator !== 'undefined' ? navigator.serviceWorker : undefined)
  const doc = options.doc ?? (typeof document !== 'undefined' ? document : undefined)
  if (!container) return () => {}

  const now = options.now ?? (() => Date.now())
  const throttleMs = options.throttleMs ?? DEFAULT_UPDATE_THROTTLE_MS
  let disposed = false
  let registration: { update(): Promise<unknown> } | undefined
  let lastCheck = now()

  // Browsers that disable service workers can still use the online app.
  void container
    .register(scriptUrl, { updateViaCache: 'none' })
    .then((reg) => {
      if (!disposed) registration = reg
    })
    .catch(() => {})

  const onVisibilityChange = () => {
    if (!registration || doc?.visibilityState !== 'visible') return
    const current = now()
    if (current - lastCheck < throttleMs) return
    lastCheck = current
    void registration.update().catch(() => {})
  }

  doc?.addEventListener('visibilitychange', onVisibilityChange)
  return () => {
    disposed = true
    doc?.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
