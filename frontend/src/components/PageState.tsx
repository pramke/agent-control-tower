/**
 * Unified page state wrapper — loading (skeleton), error, or empty.
 * Falls back to children when data is ready.
 */
import type { ReactNode } from 'react'
import { SkeletonPage } from './Skeleton'
import EmptyState from './EmptyState'

interface Props {
  loading: boolean
  error: string | null
  empty: boolean
  emptyTitle?: string
  emptyMessage?: string
  emptyAction?: { label: string; onClick: () => void }
  children: ReactNode
}

export default function PageState({
  loading,
  error,
  empty,
  emptyTitle,
  emptyMessage,
  emptyAction,
  children,
}: Props) {
  // 优先级：loading > error > empty > children
  if (loading) return <SkeletonPage />

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center max-w-md">
          <p className="text-red-500 text-lg font-medium mb-2">加载失败</p>
          <p className="text-slate-500 text-sm">{error}</p>
        </div>
      </div>
    )
  }

  if (empty) {
    return <EmptyState title={emptyTitle ?? '暂无数据'} description={emptyMessage} action={emptyAction} />
  }

  return <>{children}</>
}
