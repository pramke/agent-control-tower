/**
 * 模块: 前端 - 通用组件
 * 功能: 错误边界组件，某个页面崩溃时显示友好提示，不影响其他页面
 */
import { Component, type ReactNode } from 'react'

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { hasError: boolean; error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  // React 16+ 错误边界生命周期：捕获子组件渲染/生命周期中的 js 错误，避免整个页面崩溃
  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div className="flex items-center justify-center min-h-[200px] p-8">
          <div className="text-center">
            <p className="text-red-500 text-lg font-medium mb-2">页面加载失败</p>
            <p className="text-slate-500 text-sm mb-4">{this.state.error?.message}</p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-4 py-1.5 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
