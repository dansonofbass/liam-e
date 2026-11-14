import { useCallback, useEffect, useLayoutEffect, useRef, useState, type DependencyList, type RefObject } from 'react'

export function useFollowScroll(ref: RefObject<HTMLElement | null>, deps: DependencyList) {
  const following = useRef(true)
  const [showEnd, setShowEnd] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const onScroll = () => {
      following.current = element.scrollHeight - element.clientHeight - element.scrollTop <= 48
      setShowEnd(!following.current)
    }
    element.addEventListener('scroll', onScroll)
    const observer = new MutationObserver(() => {
      if (following.current) element.scrollTop = element.scrollHeight
    })
    observer.observe(element, { childList: true, subtree: true, characterData: true })
    return () => { element.removeEventListener('scroll', onScroll); observer.disconnect() }
  }, [ref])
  useLayoutEffect(() => {
    if (following.current && ref.current) ref.current.scrollTop = ref.current.scrollHeight
    // The caller supplies the content changes that should trigger following.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  const scrollToEnd = useCallback(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
    following.current = true
    setShowEnd(false)
  }, [ref])
  return { showEnd, scrollToEnd }
}
