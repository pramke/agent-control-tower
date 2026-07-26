/**
 * 空状态占位组件：无数据时展示图标、标题、描述和可选操作按钮。
 */
import type { ReactNode } from 'react'

interface Props {
  icon?: ReactNode
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
}

// 默认使用收件箱图标作为空状态视觉提示
const DefaultIcon = () => (
  <svg className="w-16 h-16 text-slate-300 mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
  </svg>
)

export default function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="text-center max-w-sm">
        {icon ?? <DefaultIcon />}
        <p className="text-slate-600 font-medium mb-1">{title}</p>
        {description && <p className="text-sm text-slate-400">{description}</p>}
        {action && (
          <button
            onClick={action.onClick}
            className="mt-4 px-4 py-2 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  )
}
