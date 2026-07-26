/**
 * 模块: 前端 - 页面
 * 功能: Agent 运行追踪查看器，展示每次运行的详细步骤和节点日志
 *
 * 使用方式:
 *   - 左侧列表展示所有追踪记录（支持按状态筛选）
 *   - 点击某条追踪可查看其时间线详情（节点展开/折叠）
 *   - 每个节点显示：名称、类型、耗时、输入/输出、LLM 思考内容、Token 用量
 *
 * 数据结构:
 *   TraceSummary  - 追踪摘要列表项（用于左侧列表）
 *   TraceDetail   - 单次追踪完整详情（含节点列表 node[]）
 *   TraceNode     - 单个执行节点（LLM 调用 / 工具执行 / 人工审核）
 *
 * 辅助函数:
 *   nodeColors()    - 根据节点状态返回颜色主题
 *   typeBadge()     - 节点类型对应的 Tailwind 样式类
 *   typeLabel()     - 节点类型的中文标签
 *   runStatusBadge()- 运行状态对应的 Tailwind 样式类
 *   statusLabel()   - 运行状态的中文标签
 *
 * 组件:
 *   TraceViewer    - 默认导出，主页面组件
 *   JsonBlock      - 内部 JSON 展示组件（null/空对象折叠）
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

export interface TraceSummary {
  trace_id: string
  project_id: number | null
  agent_name: string
  status: string
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  total_tokens: number
  total_cost: number
}

export interface TraceNode {
  id: number
  node_name: string
  node_type: string
  sequence: number
  parent_node_id: number | null
  input: Record<string, unknown>
  output: Record<string, unknown>
  llm_thought: string | null
  error: string | null
  suggestion: string | null
  duration_ms: number
  token_usage: Record<string, number>
  status: string
}

interface TreeNode extends TraceNode {
  children: TreeNode[]
}

export interface TraceDetail {
  trace_id: string
  agent_name: string
  status: string
  start_time: string
  end_time: string | null
  total_duration_ms: number
  total_tokens: number
  total_cost: number
  input: Record<string, unknown>
  output: Record<string, unknown>
  nodes: TraceNode[]
}

export function nodeColors(node: TraceNode): { border: string; dot: string; label: string } {
  if (node.status === 'failed') return { border: 'border-red-400', dot: 'bg-red-500', label: '失败' }
  if (node.status === 'skipped') return { border: 'border-yellow-400', dot: 'bg-yellow-500', label: '跳过' }
  if (node.error) return { border: 'border-yellow-400', dot: 'bg-yellow-500', label: '重试' }
  return { border: 'border-green-400', dot: 'bg-green-500', label: '成功' }
}

export function typeBadge(nodeType: string): string {
  switch (nodeType) {
    case 'llm_call':
      return 'bg-indigo-100 text-indigo-700'
    case 'tool_execution':
      return 'bg-sky-100 text-sky-700'
    case 'human_review':
      return 'bg-amber-100 text-amber-700'
    default:
      return 'bg-slate-100 text-slate-600'
  }
}

export function typeLabel(nodeType: string): string {
  switch (nodeType) {
    case 'llm_call':
      return 'LLM调用'
    case 'tool_execution':
      return '工具执行'
    case 'human_review':
      return '人工审核'
    default:
      return nodeType
  }
}

export function runStatusBadge(status: string): string {
  if (status === 'failed') return 'bg-red-100 text-red-700'
  if (status === 'running' || status === 'awaiting_human') return 'bg-blue-100 text-blue-700'
  return 'bg-green-100 text-green-700'
}

export function statusLabel(status: string): string {
  switch (status) {
    case 'running':
      return '运行中'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'awaiting_human':
      return '等待决策'
    case 'starting':
      return '启动中'
    default:
      return status
  }
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  if (value == null || (typeof value === 'object' && Object.keys(value as object).length === 0)) {
    return null
  }
  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <pre className="text-xs bg-slate-100 rounded p-2 mt-0.5 overflow-x-auto max-h-48">
        {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

interface TraceViewerProps {
  projectId?: number
}

export default function TraceViewer({ projectId }: TraceViewerProps) {
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [selected, setSelected] = useState<TraceDetail | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadTraces = async (status = statusFilter) => {
    try {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      if (projectId) params.set('project_id', String(projectId))
      const qs = params.toString()
      setTraces(await apiRequest<TraceSummary[]>('GET', `/traces${qs ? `?${qs}` : ''}`))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载追踪列表失败')
    }
  }

  useEffect(() => {
    loadTraces()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, projectId])

  const openTrace = async (traceId: string) => {
    setLoading(true)
    setError('')
    setExpanded(null)
    try {
      setSelected(await apiRequest<TraceDetail>('GET', `/traces/${traceId}`))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载追踪失败')
    } finally {
      setLoading(false)
    }
  }

  // 将扁平节点列表构建为树结构：先建立 id→节点 映射，再将子节点挂到父节点下
  function buildTree(nodes: TraceNode[]): TreeNode[] {
    const map = new Map<number, TreeNode>()
    const roots: TreeNode[] = []
    for (const n of nodes) {
      map.set(n.id, { ...n, children: [] })
    }
    for (const n of nodes) {
      const node = map.get(n.id)!
      // 有父节点且父节点存在于列表中则挂载，否则视为根节点
      if (n.parent_node_id != null && map.has(n.parent_node_id)) {
        map.get(n.parent_node_id)!.children.push(node)
      } else {
        roots.push(node)
      }
    }
    return roots
  }

  const nodeTree = selected ? buildTree(selected.nodes) : []

  // 所有节点中的最大耗时，用于时间线进度条的等比例缩放
  const maxDuration = selected
    ? Math.max(1, ...selected.nodes.map((n) => n.duration_ms))
    : 1

  // 递归渲染节点行，depth 控制左侧缩进和连接线
  function NodeRow({ node, depth }: { node: TreeNode; depth: number }) {
    const colors = nodeColors(node)
    const isOpen = expanded === node.id
    return (
      <div key={node.id} className="relative" style={{ marginLeft: depth * 20 }}>
        {depth > 0 && (
          <div className="absolute left-[7px] -top-3 bottom-1/2 w-px bg-slate-200" />
        )}
        <span
          className={`absolute -left-5 top-3 w-3.5 h-3.5 rounded-full border-2 border-white shadow ${colors.dot}`}
        />
        <div
          className={`border-l-4 ${colors.border} bg-slate-50 rounded-md p-3 cursor-pointer hover:bg-slate-100 transition-colors`}
          onClick={() => setExpanded(isOpen ? null : node.id)}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs text-slate-400">#{node.sequence}</span>
              <span className="text-sm font-medium text-slate-700 truncate">{node.node_name}</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${typeBadge(node.node_type)}`}>
                {typeLabel(node.node_type)}
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-slate-400">{node.duration_ms}ms</span>
              <span className="text-[10px] text-slate-500">{colors.label}</span>
            </div>
          </div>
          <div className="mt-2 h-1 rounded bg-slate-200 overflow-hidden">
            <div
              className={`h-full ${colors.dot}`}
              style={{ width: `${Math.max(2, (node.duration_ms / maxDuration) * 100)}%` }}
            />
          </div>
          {isOpen && (
            <div className="mt-2 border-t border-slate-200 pt-2" onClick={(e) => e.stopPropagation()}>
              {node.llm_thought && (
                <div className="mt-1">
                  <p className="text-xs font-medium text-slate-500">LLM 思考</p>
                  <p className="text-xs text-slate-700 whitespace-pre-wrap mt-0.5">{node.llm_thought}</p>
                </div>
              )}
              <JsonBlock title="输入" value={node.input} />
              <JsonBlock title="输出" value={node.output} />
              <JsonBlock title="Token 用量" value={node.token_usage} />
              {node.error && (
                <p className="text-xs text-red-600 mt-2">错误：{node.error}</p>
              )}
              {node.suggestion && (
                <p className="text-xs text-amber-700 mt-1">建议: {node.suggestion}</p>
              )}
            </div>
          )}
        </div>
        {node.children.map((child) => (
          <NodeRow key={child.id} node={child} depth={depth + 1} />
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="bg-white rounded-lg shadow p-4 self-start">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-slate-700">追踪列表</h2>
          <div className="flex gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="border border-slate-300 rounded-md px-2 py-1 text-xs bg-white"
            >
              <option value="">全部</option>
              <option value="completed">成功</option>
              <option value="failed">失败</option>
              <option value="running">运行中</option>
            </select>
            <button
              onClick={() => loadTraces()}
              className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              刷新
            </button>
          </div>
        </div>
        <div className="space-y-2 max-h-[36rem] overflow-y-auto pr-1">
          {traces.length === 0 && <p className="text-sm text-slate-400">暂无追踪记录。</p>}
          {traces.map((t) => (
            <button
              key={t.trace_id}
              onClick={() => openTrace(t.trace_id)}
              className={`w-full text-left rounded-md border p-2.5 transition-colors ${
                selected?.trace_id === t.trace_id
                  ? 'border-blue-400 bg-blue-50'
                  : 'border-slate-200 hover:border-blue-300'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700 truncate">{t.agent_name}</span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${runStatusBadge(t.status)}`}>
                  {statusLabel(t.status)}
                </span>
              </div>
              <div className="flex items-center justify-between mt-1 text-[11px] text-slate-400">
                <span className="font-mono">{t.trace_id.slice(0, 8)}…</span>
                <span>{new Date(t.started_at).toLocaleString()}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="lg:col-span-2 bg-white rounded-lg shadow p-5">
        {error && <div className="text-red-600 bg-red-50 p-3 rounded text-sm mb-3">{error}</div>}
        {loading && <p className="text-slate-500 text-sm">加载追踪…</p>}
        {!selected && !loading && (
          <p className="text-slate-400 text-sm">选择一个追踪以查看执行时间线。</p>
        )}
        {selected && !loading && (
          <>
            <div className="flex items-center justify-between border-b border-slate-100 pb-3 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-700">{selected.agent_name}</h2>
                <p className="text-xs font-mono text-slate-400">{selected.trace_id}</p>
              </div>
              <div className="text-right text-xs text-slate-500 space-y-0.5">
                <span className={`inline-block px-2.5 py-1 rounded-full text-xs font-medium ${runStatusBadge(selected.status)}`}>
                  {statusLabel(selected.status)}
                </span>
                <p>
                  {selected.total_duration_ms}ms · {selected.total_tokens} Token · $
                  {selected.total_cost.toFixed(6)}
                </p>
              </div>
            </div>

            {/* 垂直连接线贯穿整个节点列表 */}
        <div className="relative pl-5">
              <div className="absolute left-[7px] top-1 bottom-1 w-px bg-slate-200" />
              <div className="space-y-3">
                {nodeTree.map((node) => (
                  <NodeRow key={node.id} node={node} depth={0} />
                ))}
                {nodeTree.length === 0 && (
                  <p className="text-sm text-slate-400">此追踪没有记录节点。</p>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
