/**
 * Skeleton loading placeholders — animated pulse shapes for cards, text, tables.
 */
import type { ReactNode } from 'react'

function Bar({ className = '' }: { className?: string }) {
  return <div className={`bg-slate-200 rounded animate-pulse ${className}`} />
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-lg shadow p-5 space-y-3">
      <div className="flex items-center gap-3">
        <Bar className="w-10 h-10 rounded-full" />
        <div className="flex-1 space-y-2">
          <Bar className="h-4 w-3/5" />
          <Bar className="h-3 w-2/5" />
        </div>
      </div>
      <Bar className="h-3 w-full" />
      <Bar className="h-3 w-4/5" />
      <div className="flex gap-2 pt-2">
        <Bar className="h-6 w-16 rounded-full" />
        <Bar className="h-6 w-20 rounded-full" />
      </div>
    </div>
  )
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-100 flex gap-6">
        <Bar className="h-4 w-24" />
        <Bar className="h-4 w-32" />
        <Bar className="h-4 w-20" />
        <Bar className="h-4 w-16" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-5 py-3 border-b border-slate-50 flex gap-6">
          <Bar className="h-4 w-24" />
          <Bar className="h-4 w-40" />
          <Bar className="h-4 w-16" />
          <Bar className="h-4 w-12" />
        </div>
      ))}
    </div>
  )
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2">
      {/* 最后一行较短，模拟真实文本段落的视觉节奏 */}
      {Array.from({ length: lines }).map((_, i) => (
        <Bar key={i} className={`h-3 ${i === lines - 1 ? 'w-3/5' : 'w-full'}`} />
      ))}
    </div>
  )
}

export function SkeletonPage({ children }: { children?: ReactNode }) {
  return (
    <div className="animate-pulse space-y-4">
      <Bar className="h-6 w-48" />
      {children ?? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}
    </div>
  )
}
