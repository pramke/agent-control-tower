/**
 * 评估管理页面：管理评估集、评测用例及评估运行，支持创建/删除和运行任务。
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

// 项目基础信息
interface Project {
  id: number
  name: string
}

// 评估集数据结构
interface EvalSet {
  id: number
  project_id: number | null
  name: string
  description: string | null
  scoring_method: string
  pass_threshold: number
  created_at: string
}

// 评测用例数据结构
interface EvalCase {
  id: number
  eval_set_id: number
  input_text: string
  expected_output: string | null
  expected_tools: string[] | null
  max_tokens: number
  weight: number
  tags: string[] | null
  created_at: string
}

// 评估运行记录数据结构
interface EvalRun {
  id: number
  eval_set_id: number
  project_id: number | null
  model: string
  mode: string
  tools: string[] | null
  status: string
  total_cases: number
  passed_cases: number
  average_score: number
  total_tokens: number
  total_cost: number
  duration_ms: number
  regression_detected: boolean
  started_at: string
  finished_at: string | null
}

// 评分方式中文映射
function scoringLabel(m: string) {
  if (m === 'exact_match') return '精确匹配'
  if (m === 'semantic') return '语义相似'
  if (m === 'llm_judge') return 'LLM 评判'
  return m
}

export default function EvalSetManagement() {
  // 项目与评估集数据
  const [projects, setProjects] = useState<Project[]>([])
  const [sets, setSets] = useState<EvalSet[]>([])
  const [selectedSetId, setSelectedSetId] = useState<number | null>(null)
  const [cases, setCases] = useState<EvalCase[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 创建评估集弹窗表单
  const [showCreateSet, setShowCreateSet] = useState(false)
  const [newSetName, setNewSetName] = useState('')
  const [newSetDesc, setNewSetDesc] = useState('')
  const [newSetScoring, setNewSetScoring] = useState('exact_match')
  const [newSetThreshold, setNewSetThreshold] = useState(0.8)
  const [newSetProjectId, setNewSetProjectId] = useState<number | null>(null)
  const [creatingSet, setCreatingSet] = useState(false)

  // 添加用例弹窗表单
  const [showAddCase, setShowAddCase] = useState(false)
  const [newCaseInput, setNewCaseInput] = useState('')
  const [newCaseExpected, setNewCaseExpected] = useState('')
  const [newCaseTools, setNewCaseTools] = useState('')
  const [newCaseWeight, setNewCaseWeight] = useState(1.0)
  const [addingCase, setAddingCase] = useState(false)

  // 运行评估弹窗表单
  const [showRunEval, setShowRunEval] = useState(false)
  const [runModel, setRunModel] = useState('deepseek-chat')
  const [runMode, setRunMode] = useState('react')
  const [runTools, setRunTools] = useState('')
  const [runProjectId, setRunProjectId] = useState<number | null>(null)
  const [running, setRunning] = useState(false)

  // 展开查看用例详情
  const [expandedCase, setExpandedCase] = useState<number | null>(null)

  // 页面加载时获取项目列表和评估集列表
  useEffect(() => {
    apiRequest<Project[]>('GET', '/projects')
      .then(setProjects)
      .catch(() => {})
    fetchSets()
  }, [])

  // 获取所有评估集
  const fetchSets = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await apiRequest<EvalSet[]>('GET', '/eval/sets?limit=100')
      setSets(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载评估集失败')
    } finally {
      setLoading(false)
    }
  }

  // 获取指定评估集下的所有用例
  const fetchCases = async (setId: number) => {
    try {
      const data = await apiRequest<EvalCase[]>('GET', `/eval/sets/${setId}/cases`)
      setCases(data)
    } catch {
      setCases([])
    }
  }

  // 获取指定评估集的运行记录
  const fetchRuns = async (setId: number) => {
    try {
      const data = await apiRequest<EvalRun[]>('GET', `/eval/runs?eval_set_id=${setId}&limit=50`)
      setRuns(data)
    } catch {
      setRuns([])
    }
  }

  // 选择评估集，加载其用例和运行记录；切换时收起已展开的用例详情
  const selectSet = (setId: number) => {
    setSelectedSetId(setId)
    setExpandedCase(null) // 切换评估集时避免展示上一个评估集的详情
    fetchCases(setId)
    fetchRuns(setId)
  }

  // 创建新评估集
  const handleCreateSet = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreatingSet(true)
    try {
      await apiRequest('POST', '/eval/sets', {
        name: newSetName,
        description: newSetDesc || null,
        scoring_method: newSetScoring,
        pass_threshold: newSetThreshold,
        project_id: newSetProjectId,
      })
      setShowCreateSet(false)
      setNewSetName('')
      setNewSetDesc('')
      fetchSets()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setCreatingSet(false)
    }
  }

  // 删除评估集
  const handleDeleteSet = async (id: number) => {
    try {
      await apiRequest('DELETE', `/eval/sets/${id}`)
      if (selectedSetId === id) {
        setSelectedSetId(null)
        setCases([])
        setRuns([])
      }
      fetchSets()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  // 向当前评估集中添加评测用例
  const handleAddCase = async (e: React.FormEvent) => {
    e.preventDefault()
    if (selectedSetId === null) return
    setAddingCase(true)
    try {
      await apiRequest('POST', '/eval/cases', {
        eval_set_id: selectedSetId,
        input_text: newCaseInput,
        expected_output: newCaseExpected || null,
        expected_tools: newCaseTools ? newCaseTools.split(',').map((t) => t.trim()) : null,
        weight: newCaseWeight,
      })
      setShowAddCase(false)
      setNewCaseInput('')
      setNewCaseExpected('')
      setNewCaseTools('')
      fetchCases(selectedSetId)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '添加失败')
    } finally {
      setAddingCase(false)
    }
  }

  // 删除指定用例
  const handleDeleteCase = async (caseId: number) => {
    try {
      await apiRequest('DELETE', `/eval/cases/${caseId}`)
      if (selectedSetId !== null) fetchCases(selectedSetId)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  // 启动评估运行
  const handleRunEval = async () => {
    if (selectedSetId === null) return
    setRunning(true)
    try {
      await apiRequest('POST', '/eval/runs', {
        eval_set_id: selectedSetId,
        model: runModel,
        mode: runMode,
        tools: runTools ? runTools.split(',').map((t) => t.trim()) : [],
        project_id: runProjectId,
      })
      setShowRunEval(false)
      fetchRuns(selectedSetId)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '启动评估失败')
    } finally {
      setRunning(false)
    }
  }

  // 删除评估运行记录
  const handleDeleteRun = async (runId: number) => {
    try {
      await apiRequest('DELETE', `/eval/runs/${runId}`)
      if (selectedSetId !== null) fetchRuns(selectedSetId)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      {/* 页面标题与操作按钮 */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-700">评估管理</h2>
        <div className="flex gap-2">
          <button
            onClick={() => setShowCreateSet(true)}
            className="px-3 py-1.5 text-sm bg-green-500 text-white rounded-md hover:bg-green-600 transition-colors"
          >
            创建评估集
          </button>
          <button onClick={fetchSets} className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors">
            刷新
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && <div className="text-red-600 bg-red-50 p-3 rounded mb-4 text-sm">{error}</div>}

      {/* 三栏布局：评估集列表 / 评测用例 / 评估运行记录 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：评估集列表 */}
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-slate-700 mb-3">评估集 ({sets.length})</h3>
          {loading && <p className="text-slate-400 text-sm">加载中...</p>}
          {!loading && sets.length === 0 && (
            <p className="text-slate-400 text-sm text-center py-4">暂无评估集</p>
          )}
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {sets.map((s) => (
              <div
                key={s.id}
                onClick={() => selectSet(s.id)}
                className={`p-3 rounded border cursor-pointer transition-colors ${
                  selectedSetId === s.id
                    ? 'border-blue-400 bg-blue-50'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-700 truncate">{s.name}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDeleteSet(s.id) }}
                    className="text-xs text-slate-400 hover:text-red-600 shrink-0 ml-2"
                  >
                    删除
                  </button>
                </div>
                <div className="flex gap-2 text-xs text-slate-400 mt-1">
                  <span>{scoringLabel(s.scoring_method)}</span>
                  <span>阈值: {s.pass_threshold}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 中间：评测用例 */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-slate-700">
              评测用例 {selectedSetId !== null ? `(${cases.length})` : ''}
            </h3>
            {selectedSetId !== null && (
              <button
                onClick={() => setShowAddCase(true)}
                className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
              >
                添加用例
              </button>
            )}
          </div>
          {selectedSetId === null && (
            <p className="text-slate-400 text-sm text-center py-8">请先选择一个评估集</p>
          )}
          {selectedSetId !== null && cases.length === 0 && (
            <p className="text-slate-400 text-sm text-center py-4">暂无用例</p>
          )}
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {cases.map((c) => (
              <div key={c.id} className="border border-slate-200 rounded p-3">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    {/* 点击展开/收起用例详情 */}
                    <p
                      className="text-sm text-slate-700 cursor-pointer hover:text-blue-600 line-clamp-2"
                      onClick={() => setExpandedCase(expandedCase === c.id ? null : c.id)}
                    >
                      {c.input_text}
                    </p>
                    {/* 展开详情：期望输出、期望工具、权重、Token、标签 */}
                    {expandedCase === c.id && (
                      <div className="mt-2 text-xs">
                        {c.expected_output && (
                          <p className="text-slate-500">期望输出: {c.expected_output}</p>
                        )}
                        {c.expected_tools && c.expected_tools.length > 0 && (
                          <p className="text-slate-500">期望工具: {c.expected_tools.join(', ')}</p>
                        )}
                        <div className="flex gap-2 mt-1 text-slate-400">
                          <span>权重: {c.weight}</span>
                          <span>Token: {c.max_tokens}</span>
                          {c.tags && c.tags.length > 0 && <span>标签: {c.tags.join(', ')}</span>}
                        </div>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => handleDeleteCase(c.id)}
                    className="text-xs text-slate-400 hover:text-red-600 shrink-0 ml-2"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 右侧：评估运行记录 */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-slate-700">评估运行记录</h3>
            {selectedSetId !== null && (
              <button
                onClick={() => {
                  setShowRunEval(true)
                  if (selectedSetId) {
                    const set = sets.find((s) => s.id === selectedSetId)
                    if (set?.project_id) setRunProjectId(set.project_id)
                  }
                }}
                className="px-2 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600 transition-colors"
              >
                运行评估
              </button>
            )}
          </div>
          {selectedSetId === null && (
            <p className="text-slate-400 text-sm text-center py-8">请先选择一个评估集</p>
          )}
          {selectedSetId !== null && runs.length === 0 && (
            <p className="text-slate-400 text-sm text-center py-4">暂无运行记录</p>
          )}
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {runs.map((r) => (
              <div key={r.id} className="border border-slate-200 rounded p-3">
                <div className="flex items-center justify-between">
                  {/* 运行状态标签 */}
                  <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                    r.status === 'completed'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-blue-100 text-blue-700'
                  }`}>
                    {r.status === 'completed' ? '已完成' : '运行中'}
                  </span>
                  <button
                    onClick={() => handleDeleteRun(r.id)}
                    className="text-xs text-slate-400 hover:text-red-600"
                  >
                    删除
                  </button>
                </div>
                {/* 运行结果详情 */}
                <div className="text-xs text-slate-500 mt-1 space-y-0.5">
                  <p>模型: {r.model} · 模式: {r.mode}</p>
                  <p>通过: {r.passed_cases}/{r.total_cases} · 均分: {(r.average_score * 100).toFixed(1)}%</p>
                  <p>Token: {r.total_tokens} · 费用: ${r.total_cost.toFixed(6)}</p>
                  <p>耗时: {(r.duration_ms / 1000).toFixed(1)}s</p>
                  {r.regression_detected && (
                    <p className="text-red-600 font-medium">检测到回退</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 创建评估集弹窗 */}
      {showCreateSet && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-slate-800 mb-4">创建评估集</h3>
            <form onSubmit={handleCreateSet} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">名称</label>
                <input
                  type="text"
                  value={newSetName}
                  onChange={(e) => setNewSetName(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">描述</label>
                <input
                  type="text"
                  value={newSetDesc}
                  onChange={(e) => setNewSetDesc(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-sm text-slate-600">评分方式</span>
                  <select
                    value={newSetScoring}
                    onChange={(e) => setNewSetScoring(e.target.value)}
                    className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
                  >
                    <option value="exact_match">精确匹配</option>
                    <option value="semantic">语义相似</option>
                    <option value="llm_judge">LLM 评判</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">通过阈值</span>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={newSetThreshold}
                    onChange={(e) => setNewSetThreshold(Number(e.target.value))}
                    className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm"
                  />
                </label>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">关联项目</label>
                <select
                  value={newSetProjectId ?? ''}
                  onChange={(e) => setNewSetProjectId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
                >
                  <option value="">不关联</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => setShowCreateSet(false)}
                  className="px-4 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creatingSet}
                  className="px-4 py-2 text-sm text-white bg-green-500 rounded-md hover:bg-green-600 disabled:opacity-50"
                >
                  {creatingSet ? '创建中…' : '创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 添加评测用例弹窗 */}
      {showAddCase && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg">
            <h3 className="text-lg font-semibold text-slate-800 mb-4">添加评测用例</h3>
            <form onSubmit={handleAddCase} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">输入文本</label>
                <textarea
                  value={newCaseInput}
                  onChange={(e) => setNewCaseInput(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">期望输出（可选）</label>
                <textarea
                  value={newCaseExpected}
                  onChange={(e) => setNewCaseExpected(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-sm text-slate-600">期望工具（逗号分隔）</span>
                  <input
                    type="text"
                    value={newCaseTools}
                    onChange={(e) => setNewCaseTools(e.target.value)}
                    className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm"
                    placeholder="calculator, http_get"
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">权重</span>
                  <input
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    value={newCaseWeight}
                    onChange={(e) => setNewCaseWeight(Number(e.target.value))}
                    className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm"
                  />
                </label>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => setShowAddCase(false)}
                  className="px-4 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={addingCase}
                  className="px-4 py-2 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600 disabled:opacity-50"
                >
                  {addingCase ? '添加中…' : '添加'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 运行评估弹窗 */}
      {showRunEval && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-slate-800 mb-4">运行评估</h3>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-sm text-slate-600">模型</span>
                  <input
                    type="text"
                    value={runModel}
                    onChange={(e) => setRunModel(e.target.value)}
                    className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm"
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">模式</span>
                  <select
                    value={runMode}
                    onChange={(e) => setRunMode(e.target.value)}
                    className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
                  >
                    <option value="react">ReAct</option>
                    <option value="plan_execute">Plan+Execute</option>
                    <option value="supervisor">Supervisor</option>
                  </select>
                </label>
              </div>
              <label className="block">
                <span className="text-sm text-slate-600">工具（逗号分隔）</span>
                <input
                  type="text"
                  value={runTools}
                  onChange={(e) => setRunTools(e.target.value)}
                  className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm"
                  placeholder="calculator, http_get"
                />
              </label>
              <label className="block">
                <span className="text-sm text-slate-600">项目</span>
                <select
                  value={runProjectId ?? ''}
                  onChange={(e) => setRunProjectId(e.target.value ? Number(e.target.value) : null)}
                  className="mt-1 w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
                >
                  <option value="">不关联</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowRunEval(false)}
                  className="px-4 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200"
                >
                  取消
                </button>
                <button
                  onClick={handleRunEval}
                  disabled={running}
                  className="px-4 py-2 text-sm text-white bg-green-500 rounded-md hover:bg-green-600 disabled:opacity-50"
                >
                  {running ? '启动中…' : '启动评估'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
