/**
 * 模块: 前端 - 通用组件
 * 功能: 一键复制文本到剪贴板的按钮组件
 */
import { useState } from 'react'

interface CopyButtonProps {
  text: string
  label?: string
}

export default function CopyButton({ text, label }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // 旧浏览器或非安全上下文下 clipboard API 不可用，回退到 execCommand
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`text-xs px-2 py-0.5 rounded border transition-colors ${
        copied
          ? 'bg-green-100 text-green-700 border-green-300'
          : 'bg-white text-slate-500 border-slate-300 hover:border-blue-400 hover:text-blue-600'
      }`}
    >
      {copied ? '已复制' : label || '复制'}
    </button>
  )
}