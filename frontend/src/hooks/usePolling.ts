/** 通用轮询 Hook — active 时以固定间隔执行回调，组件卸载时自动清理。 */
import { useEffect, useRef } from 'react'

/** Generic polling hook — calls `fn` every `intervalMs` while `active` is true. */
export function usePolling(fn: () => void, intervalMs: number, active: boolean) {
  // 用 ref 保存最新回调引用，避免 setInterval 捕获过期闭包
  const savedFn = useRef(fn)
  savedFn.current = fn

  useEffect(() => {
    if (!active) return
    const id = setInterval(() => savedFn.current(), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs, active])
}
