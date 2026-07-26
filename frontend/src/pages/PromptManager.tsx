/**
 * Prompt 管理页面：创建、查看和管理当前项目的系统提示词模板。
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

interface Prompt {
  id: number
  name: string
  content: string
  version: number
  created_at: string
}

export default function PromptManager({ projectId }: { projectId: number }) {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newContent, setNewContent] = useState('')
  const [creating, setCreating] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const fetchPrompts = async () => {
    setLoading(true)
    try {
      const data = await apiRequest<Prompt[]>('GET', `/prompts?project_id=${projectId}`)
      setPrompts(data)
    } catch {
      setError('加载 Prompt 失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchPrompts() }, [projectId])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    // 防止提交空名称或空内容的 Prompt
    if (!newName.trim() || !newContent.trim()) return
    setCreating(true)
    try {
      await apiRequest('POST', '/prompts', { name: newName, content: newContent, project_id: projectId })
      setShowCreate(false)
      setNewName('')
      setNewContent('')
      fetchPrompts()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  if (loading) return <div className="p-6 text-slate-400 text-sm">加载中…</div>
  if (error) return <div className="p-6 text-red-600 text-sm">{error}</div>

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-slate-700">Prompt 管理</h3>
        <button onClick={() => setShowCreate(true)} className="px-3 py-1.5 text-sm bg-green-500 text-white rounded-md hover:bg-green-600">
          新建 Prompt
        </button>
      </div>

      {prompts.length === 0 && (
        <div className="text-center py-12 text-slate-400">
          暂无 Prompt，点击「新建 Prompt」创建第一个
        </div>
      )}

      <div className="space-y-3">
        {prompts.map((p) => (
          <div key={p.id} className="bg-white rounded-lg shadow p-4">
            <div
              className="flex items-center justify-between cursor-pointer"
              onClick={() => setExpandedId(expandedId === p.id ? null : p.id) /* 切换展开/收起 */}
            >
              <div>
                <span className="font-medium text-slate-800">{p.name}</span>
                <span className="ml-2 text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">v{p.version}</span>
              </div>
              <span className="text-xs text-slate-400">{new Date(p.created_at).toLocaleDateString()}</span>
            </div>
            <p className="text-sm text-slate-600 mt-1 line-clamp-2">{p.content}</p>
            {expandedId === p.id && (
              <pre className="mt-3 bg-slate-50 rounded p-3 text-xs text-slate-700 whitespace-pre-wrap border border-slate-200">
                {p.content}
              </pre>
            )}
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-slate-800 mb-4">新建 Prompt</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">名称</label>
                <input type="text" value={newName} onChange={e => setNewName(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" required placeholder="例如：customer_service" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">内容</label>
                <textarea value={newContent} onChange={e => setNewContent(e.target.value)} rows={5}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm font-mono" required placeholder="系统提示词内容…" />
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setShowCreate(false)} className="flex-1 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200">取消</button>
                <button type="submit" disabled={creating} className="flex-1 py-2 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600 disabled:opacity-50">
                  {creating ? '创建中…' : '创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
