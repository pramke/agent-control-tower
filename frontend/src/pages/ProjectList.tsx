/**
 * 模块: 前端 - 项目列表页面
 * 功能: 展示、创建、批量管理项目，支持代理监测和SDK可观测两种项目类型
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import CopyButton from '../components/CopyButton'
import EmptyState from '../components/EmptyState'
import { SkeletonCard } from '../components/Skeleton'

interface Project {
  id: number
  name: string
  api_key: string
  base_url: string
  project_type: string
  created_at: string
}

interface CreatedProject {
  name: string
  api_key: string
  base_url: string
  project_type: string
}

interface Props {
  userRole: string
  onSelectProject: (project: Project, initialTab?: string) => void
}

export default function ProjectList({ userRole, onSelectProject }: Props) {
  const canWrite = !!userRole  // 所有登录用户都可写

  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('https://api.deepseek.com/anthropic')
  const [newApiKey, setNewApiKey] = useState('')
  const [newType, setNewType] = useState<'monitor' | 'agent'>('monitor')
  const [newTargetModel, setNewTargetModel] = useState('')
  const [newProviderType, setNewProviderType] = useState<'anthropic' | 'openai'>('anthropic')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [createdProject, setCreatedProject] = useState<CreatedProject | null>(null)
  const [proxyUrl, setProxyUrl] = useState('http://127.0.0.1:8001/proxy')

  const [batchMode, setBatchMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [confirmTarget, setConfirmTarget] = useState<{ ids: number[]; label: string } | null>(null)

  const fetchProjects = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await apiRequest<Project[]>('GET', '/projects')
      setProjects(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载项目失败')
    } finally {
      setLoading(false)
    }
  }

  // 页面首次加载时并行获取项目列表和公开代理地址
  useEffect(() => { fetchProjects(); fetchProxyUrl() }, [])

  const fetchProxyUrl = async () => {
    try {
      const data = await apiRequest<{ proxy_url: string }>('GET', '/config/public')
      setProxyUrl(data.proxy_url)
    } catch { /* use default */ }
  }

  // 重置创建向导所有字段到默认值，避免上次输入残留
  const resetWizard = () => {
    setNewName(''); setNewBaseUrl('https://api.deepseek.com/anthropic')
    setNewApiKey(''); setNewType('monitor')
    setNewTargetModel('')
    setNewProviderType('anthropic')
    setCreateError('')
  }

  // 每次打开创建弹窗前强制重置，保证表单状态干净
  const openCreate = () => { resetWizard(); setShowCreate(true) }

  // 根据项目类型构建不同请求参数：agent 模式对上游地址/Key 要求宽松，可使用占位值
  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) { setCreateError('请输入项目名称'); return }
    setCreateError('')
    setCreating(true)
    try {
      const resp = await apiRequest<CreatedProject>('POST', '/projects', {
        name: newName,
        base_url: newType === 'agent' ? (newBaseUrl || 'http://127.0.0.1:8001') : newBaseUrl,
        api_key_upstream: newType === 'agent' ? (newApiKey || 'sk-placeholder') : newApiKey,
        project_type: newType,
        target_model: newTargetModel || null,
        provider_type: newType === 'agent' ? 'anthropic' : newProviderType,
      })
      setShowCreate(false)
      resetWizard()
      setCreatedProject(resp)
      fetchProjects()
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  // 逐个删除项目，部分失败不中断后续删除，最后汇总失败数量
  const handleDelete = async (ids: number[]) => {
    setDeleting(true)
    let failed = 0
    for (const id of ids) {
      try { await apiRequest('DELETE', `/projects/${id}`) } catch { failed++ }
    }
    setConfirmTarget(null)
    setSelectedIds(new Set())
    setDeleting(false)
    await fetchProjects()
    if (failed > 0) setError(`${failed} 个项目删除失败`)
  }

  // 批量模式下切换单个项目选中状态
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === projects.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(projects.map((p) => p.id)))
  }

  // 退出批量管理模式并清空所有选中
  const exitBatchMode = () => { setBatchMode(false); setSelectedIds(new Set()) }

  return (
    <div className="h-full overflow-y-auto bg-slate-50">
      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-semibold text-slate-700">项目列表</h2>
            <p className="text-xs text-slate-400 mt-1">选择一个项目以进入工作空间</p>
          </div>
          <div className="flex gap-2 flex-wrap items-center">
            {batchMode && (
              <>
                <button onClick={toggleSelectAll} className="px-3 py-1.5 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200">
                  {selectedIds.size === projects.length ? '取消全选' : '全选'}
                </button>
                <button
                  onClick={() => {
                    if (selectedIds.size === 0) return
                    const selected = projects.filter((p) => selectedIds.has(p.id))
                    setConfirmTarget({ ids: Array.from(selectedIds), label: selected.length === 1 ? `「${selected[0].name}」` : `${selectedIds.size} 个项目` })
                  }}
                  disabled={selectedIds.size === 0}
                  className="px-3 py-1.5 text-sm bg-red-500 text-white rounded-md hover:bg-red-600 disabled:opacity-50"
                >
                  删除选中 ({selectedIds.size})
                </button>
                <button onClick={exitBatchMode} className="px-3 py-1.5 text-sm text-slate-500 bg-white border border-slate-300 rounded-md hover:bg-slate-100">
                  退出管理
                </button>
              </>
            )}
            {!batchMode && (
              <>
                {canWrite && (
                  <>
                    <button onClick={openCreate} className="px-3 py-1.5 text-sm bg-green-500 text-white rounded-md hover:bg-green-600">
                      创建项目
                    </button>
                    <button onClick={() => setBatchMode(true)} className="px-3 py-1.5 text-sm bg-slate-100 text-slate-600 rounded-md hover:bg-slate-200 border border-slate-300">
                      批量管理
                    </button>
                  </>
                )}
                <button onClick={fetchProjects} className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600">
                  刷新
                </button>
              </>
            )}
          </div>
        </div>

        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <SkeletonCard /><SkeletonCard /><SkeletonCard />
          </div>
        )}
        {error && <div className="text-red-600 bg-red-50 p-3 rounded mb-4">{error}</div>}

        {!loading && !error && projects.length === 0 && (
          <EmptyState
            title="暂无项目"
            description="创建项目以开始使用。"
            action={canWrite ? { label: '创建项目', onClick: openCreate } : undefined}
          />
        )}

        {!loading && projects.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((p) => (
              <div
                key={p.id}
                onClick={() => { if (!batchMode) onSelectProject(p) }}
                className={`bg-white rounded-lg shadow p-5 cursor-pointer hover:shadow-md transition-all border-2 ${
                  batchMode && selectedIds.has(p.id) ? 'border-blue-400 bg-blue-50/50' : 'border-transparent hover:border-blue-200'
                }`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {batchMode && (
                      <input
                        type="checkbox"
                        checked={selectedIds.has(p.id)}
                        onChange={() => toggleSelect(p.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-4 h-4 text-blue-500 rounded border-slate-300"
                      />
                    )}
                    <span className="text-2xl">{p.project_type === 'agent' ? '🤖' : '📡'}</span>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    p.project_type === 'agent' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                  }`}>
                    {p.project_type === 'agent' ? 'SDK 可观测' : '代理监测'}
                  </span>
                </div>
                <h3 className="font-medium text-slate-800 mb-1">{p.name}</h3>
                <p className="text-xs text-slate-400">创建于 {new Date(p.created_at).toLocaleDateString()}</p>
                <div className="flex items-center gap-2 mt-3 pt-3 border-t border-slate-100">
                  <span className="text-xs font-mono text-slate-400 bg-slate-100 px-2 py-1 rounded flex-1 select-none">
                    {p.api_key.slice(0, 12)}****
                  </span>
                  <CopyButton text={p.api_key} />
                  {!batchMode && canWrite && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmTarget({ ids: [p.id], label: `「${p.name}」` }) }}
                      className="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50"
                    >
                      删除
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create wizard — simple type-switch + form */}
        {showCreate && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
            <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-slate-800 mb-4">创建项目</h3>

              {/* Type selector tabs */}
              <div className="flex gap-1 bg-slate-100 rounded-lg p-1 mb-5">
                <button
                  onClick={() => setNewType('monitor')}
                  className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                    newType === 'monitor' ? 'bg-white shadow text-blue-700' : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  📡 代理监测
                </button>
                <button
                  onClick={() => setNewType('agent')}
                  className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                    newType === 'agent' ? 'bg-white shadow text-purple-700' : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  🔌 SDK 可观测
                </button>
              </div>

              {newType === 'monitor' && (
                <div className="mb-5">
                  <label className="block text-sm font-medium text-slate-700 mb-2">上游 API 格式</label>
                  <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
                    <button type="button"
                      onClick={() => { setNewProviderType('anthropic'); setNewBaseUrl('https://api.deepseek.com/anthropic') }}
                      className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                        newProviderType === 'anthropic' ? 'bg-white shadow text-blue-700' : 'text-slate-500 hover:text-slate-700'
                      }`}>
                      Anthropic 兼容
                    </button>
                    <button type="button"
                      onClick={() => { setNewProviderType('openai'); setNewBaseUrl('https://api.openai.com/v1') }}
                      className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                        newProviderType === 'openai' ? 'bg-white shadow text-green-700' : 'text-slate-500 hover:text-slate-700'
                      }`}>
                      OpenAI 兼容
                    </button>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    {newProviderType === 'anthropic'
                      ? '上游需支持 Anthropic Messages 格式（如 DeepSeek /anthropic 端点）'
                      : '上游需支持 OpenAI Chat Completions 格式（如 GLM、Kimi、DeepSeek /v1 等）'}
                  </p>
                </div>
              )}

              <form onSubmit={handleCreateSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">项目名称</label>
                  <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" required placeholder="例如：我的 AI 项目" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    上游 API 地址 {newType === 'agent' && <span className="text-slate-400 font-normal">（可选）</span>}
                  </label>
                  <input type="text" value={newBaseUrl} onChange={(e) => setNewBaseUrl(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm font-mono" required={newType === 'monitor'} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    上游 API Key {newType === 'agent' && <span className="text-slate-400 font-normal">（可选）</span>}
                  </label>
                  <input type="password" value={newApiKey} onChange={(e) => setNewApiKey(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm font-mono" required={newType === 'monitor'} placeholder={newType === 'agent' ? '留空自动使用占位值' : 'sk-...'} />
                </div>

                {newType === 'monitor' && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">
                      目标模型 <span className="text-slate-400 font-normal">（可选，覆盖默认映射）</span>
                    </label>
                    <input type="text" value={newTargetModel} onChange={(e) => setNewTargetModel(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm font-mono" placeholder="例如 deepseek-v4-pro，留空则自动映射" />
                    <p className="text-xs text-slate-400 mt-1">所有请求的模型名将被替换为此值。留空则根据 Claude 模型名自动映射。</p>
                  </div>
                )}

                {newType === 'agent' && (
                  <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-xs text-purple-700">
                    创建后可获取 API Key 和 SDK 接入指引，使用 <code className="bg-purple-100 px-1 rounded">@observe()</code> 装饰器上报 Trace 数据。
                  </div>
                )}

                {createError && <div className="text-red-600 bg-red-50 p-2 rounded text-sm">{createError}</div>}

                <div className="flex gap-2">
                  <button type="button" onClick={() => setShowCreate(false)} className="flex-1 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200">取消</button>
                  <button type="submit" disabled={creating} className="flex-1 py-2 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600 disabled:opacity-50">
                    {creating ? '创建中…' : '创建项目'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Created success dialog */}
        {createdProject && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
              <h3 className="text-lg font-semibold text-green-700 mb-2">项目创建成功</h3>
              <p className="text-sm text-slate-600 mb-1">项目名称：<strong>{createdProject.name}</strong></p>
              <p className="text-sm text-slate-500 mb-4">请保存以下 API Key，它将用于客户端接入代理。</p>
              <div className="flex items-center gap-2 bg-slate-100 rounded p-3 mb-4">
                <code className="text-xs text-slate-700 break-all flex-1 font-mono">{createdProject.api_key.slice(0, 8)}***</code>
                <CopyButton text={createdProject.api_key} />
              </div>
              <div className="text-xs text-slate-400 mb-4">
                代理地址：<code className="text-slate-600">{proxyUrl}</code>
              </div>
              <button onClick={() => setCreatedProject(null)} className="w-full px-4 py-2 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600">
                我已保存，关闭
              </button>
            </div>
          </div>
        )}

        {/* Delete confirm */}
        {confirmTarget && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm">
              <h3 className="text-lg font-semibold text-slate-800 mb-2">确认删除</h3>
              <p className="text-sm text-slate-600 mb-4">确定要删除 {confirmTarget.label} 吗？此操作不可撤销。</p>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setConfirmTarget(null)} className="px-4 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200">取消</button>
                <button onClick={() => handleDelete(confirmTarget.ids)} disabled={deleting} className="px-4 py-2 text-sm text-white bg-red-500 rounded-md hover:bg-red-600 disabled:opacity-50">
                  {deleting ? '删除中…' : '确认删除'}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
