/**
 * 费用分析页面：展示项目 Token 用量、费用趋势与模型分布。
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

interface StatsRow {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost: number
  avg_latency_ms: number
}

interface DailyRow {
  date: string
  calls: number
  cost: number
}

interface ByModelRow {
  model: string
  calls: number
  total_tokens: number
  total_cost: number
}

interface Props {
  projectId: number
}

export default function Stats({ projectId }: Props) {
  const [summary, setSummary] = useState<StatsRow | null>(null)
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [byModel, setByModel] = useState<ByModelRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [days, setDays] = useState(14)

  const fetchStats = async () => {
    setLoading(true)
    setError('')
    try {
      const [s, d, m] = await Promise.all([
        apiRequest<StatsRow>('GET', `/stats/${projectId}/summary?days=${days}`),
        apiRequest<DailyRow[]>('GET', `/stats/${projectId}/daily?days=${days}`),
        apiRequest<ByModelRow[]>('GET', `/stats/${projectId}/by_model?days=${days}`),
      ])
      setSummary(s)
      setDaily(d)
      setByModel(m)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载统计数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchStats() }, [projectId, days])

  // 使用 0.001 防止除零（分母为 0 时 bar 高度仍为 0）
  const maxCost = daily.reduce((m, d) => Math.max(m, d.cost), 0.001)
  const totalByModel = byModel.reduce((sum, m) => sum + m.total_cost, 0.001)

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-700">费用分析</h2>
        <div className="flex gap-2 items-center">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
          >
            <option value={7}>近7天</option>
            <option value={14}>近14天</option>
            <option value={30}>近30天</option>
          </select>
          <button onClick={fetchStats} className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600">
            刷新
          </button>
        </div>
      </div>

      {error && <div className="text-red-600 bg-red-50 p-3 rounded text-sm">{error}</div>}

      {loading && <p className="text-slate-500 text-sm text-center py-8">加载中...</p>}

      {!loading && summary && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-xl font-bold text-slate-700">{summary.total_calls.toLocaleString()}</p>
              <p className="text-xs text-slate-500 mt-1">总调用次数</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-xl font-bold text-slate-700">
                {((summary.total_input_tokens + summary.total_output_tokens) / 1000).toFixed(0)}K
              </p>
              <p className="text-xs text-slate-500 mt-1">总 Token</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-xl font-bold text-slate-700">${summary.total_cost.toFixed(4)}</p>
              <p className="text-xs text-slate-500 mt-1">总费用</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-xl font-bold text-slate-700">{summary.avg_latency_ms.toFixed(0)}ms</p>
              <p className="text-xs text-slate-500 mt-1">平均延迟</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-xl font-bold text-slate-700">
                {summary.total_calls > 0 ? ((summary.total_input_tokens + summary.total_output_tokens) / summary.total_calls).toFixed(0) : '—'}
              </p>
              <p className="text-xs text-slate-500 mt-1">平均Token/次</p>
            </div>
          </div>

          {/* Daily chart */}
          <div className="bg-white rounded-lg shadow p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">近{days}天费用趋势 (USD)</h3>
            {daily.length > 0 ? (
              <div className="flex items-end gap-1 h-32">
                {daily.map((d) => {
                  const h = maxCost > 0 ? (d.cost / maxCost) * 100 : 0
                  return (
                    <div
                      key={d.date}
                      className="flex-1 flex flex-col items-center group relative"
                      title={`${d.date}: ${d.calls} 次, $${d.cost.toFixed(6)}`}
                    >
                      <span className="text-[9px] text-slate-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        ${d.cost.toFixed(4)}
                      </span>
                      <div
                        className="w-full bg-blue-400 hover:bg-blue-500 rounded-t transition-colors min-h-[2px]"
                        style={{ height: `${Math.max(h, 1)}%` /* 最小 1% 确保零费用的柱也能看到 */ }}
                      />
                      <span className="text-[9px] text-slate-400 mt-1">{d.date.slice(5)}</span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="text-sm text-slate-400 text-center py-4">暂无每日数据。</p>
            )}
          </div>

          {/* By model breakdown */}
          <div className="bg-white rounded-lg shadow p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">按模型分布</h3>
            {byModel.length > 0 ? (
              <div className="space-y-3">
                {byModel.map((m) => {
                  const pct = totalByModel > 0 ? (m.total_cost / totalByModel) * 100 : 0
                  return (
                    <div key={m.model}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="font-mono text-slate-600">{m.model}</span>
                        <span className="text-slate-500 text-xs">
                          {m.calls} 次 · ${m.total_cost.toFixed(4)} · {((m.total_tokens || 0) / 1000).toFixed(0)}K tokens
                        </span>
                      </div>
                      <div className="w-full bg-slate-200 rounded-full h-2">
                        <div
                          className="h-2 rounded-full bg-indigo-400 transition-all"
                          style={{ width: `${Math.max(pct, 1)}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="text-sm text-slate-400 text-center py-4">暂无模型分布数据。</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
