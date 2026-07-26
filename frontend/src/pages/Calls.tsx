/**
 * 调用记录页面：按时间范围筛选并分页展示每次 API 调用的详细信息。
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

interface CallRecord {
  id: number
  model: string
  endpoint: string
  input_tokens: number
  output_tokens: number
  cache_tokens: number
  latency_ms: number
  cost: number
  request_hash: string
  prompt_preview: string | null
  status_code: number | null
  timestamp: string
}

interface Props {
  projectId: number
}

export default function Calls({ projectId }: Props) {
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [days, setDays] = useState(7)
  const [total, setTotal] = useState(0)
  const pageSize = 20

  const fetchCalls = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await apiRequest<{ items: CallRecord[]; total: number }>(
        'GET',
        `/calls?project_id=${projectId}&days=${days}&page=${page}&page_size=${pageSize}`
      )
      setCalls(data.items || [])
      setTotal(data.total || 0)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载调用记录失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchCalls() }, [projectId, page, days])

  // 确保至少 1 页，避免空数据时总页数为 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-700">调用记录</h2>
        <div className="flex gap-2 items-center">
          <select
            value={days}
            onChange={(e) => { setDays(Number(e.target.value)); setPage(1) /* 切换天数时重置到第一页 */ }}
            className="border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
          >
            <option value={1}>最近1天</option>
            <option value={3}>最近3天</option>
            <option value={7}>最近7天</option>
            <option value={30}>最近30天</option>
          </select>
          <button onClick={fetchCalls} className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600">
            刷新
          </button>
        </div>
      </div>

      {error && <div className="text-red-600 bg-red-50 p-3 rounded mb-4 text-sm">{error}</div>}

      {loading && <p className="text-slate-500 text-sm text-center py-8">加载中...</p>}

      {!loading && calls.length === 0 && (
        <div className="bg-white rounded-lg shadow p-8 text-center text-slate-400 text-sm">暂无调用记录。</div>
      )}

      {!loading && calls.length > 0 && (
        <>
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3 text-left">时间</th>
                    <th className="px-4 py-3 text-left">模型</th>
                    <th className="px-4 py-3 text-left">端点</th>
                    <th className="px-4 py-3 text-right">输入Token</th>
                    <th className="px-4 py-3 text-right">输出Token</th>
                    <th className="px-4 py-3 text-right">延迟</th>
                    <th className="px-4 py-3 text-right">费用</th>
                    <th className="px-4 py-3 text-right">状态码</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {calls.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-2.5 text-xs text-slate-500 whitespace-nowrap">
                        {new Date(c.timestamp).toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-xs font-mono text-slate-600">{c.model}</td>
                      <td className="px-4 py-2.5 text-xs font-mono text-slate-500 max-w-[200px] truncate">{c.endpoint}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-600 text-right">{c.input_tokens.toLocaleString()}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-600 text-right">{c.output_tokens.toLocaleString()}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-600 text-right">{c.latency_ms}ms</td>
                      <td className="px-4 py-2.5 text-xs text-slate-600 text-right">${c.cost.toFixed(6)}</td>
                      <td className="px-4 py-2.5 text-xs text-right">
                        <span className={`px-1.5 py-0.5 rounded text-xs ${c.status_code && c.status_code >= 400 ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
                          {c.status_code ?? '—'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 text-sm">
            <span className="text-slate-500">共 {total} 条记录</span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1 border border-slate-300 rounded text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                上一页
              </button>
              <span className="px-3 py-1 text-slate-500">{page} / {totalPages}</span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="px-3 py-1 border border-slate-300 rounded text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
