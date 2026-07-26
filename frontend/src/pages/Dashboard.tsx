/**
 * 模块: 前端 - 仪表盘页面
 * 功能: 展示项目近7天调用概览、费用趋势柱状图和模型分布饼状条，同时展示项目接入信息
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import CopyButton from '../components/CopyButton'

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

export default function Dashboard({ projectId }: Props) {
  const [summary, setSummary] = useState<StatsRow | null>(null)
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [byModel, setByModel] = useState<ByModelRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [projectInfo, setProjectInfo] = useState<{ api_key: string; base_url: string; proxy_url: string; name: string; target_model: string } | null>(null)

  // 并行请求概览、每日数据、模型分布和项目信息，减少加载等待时间
  const fetchData = async () => {
    setLoading(true)
    setError('')
    try {
      const [s, d, m, info] = await Promise.all([
        apiRequest<StatsRow>('GET', `/stats/${projectId}/summary?days=7`),
        apiRequest<DailyRow[]>('GET', `/stats/${projectId}/daily?days=7`),
        apiRequest<ByModelRow[]>('GET', `/stats/${projectId}/by_model?days=7`),
        apiRequest<{ api_key: string; base_url: string; proxy_url: string; name: string; target_model: string }>('GET', `/projects/${projectId}/full`),
      ])
      setSummary(s)
      setDaily(d)
      setByModel(m)
      setProjectInfo(info)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [projectId])

  // 计算每日费用最大值用于柱状图高度缩放，最小值 0.001 避免除零
  const maxCost = daily.reduce((m, d) => Math.max(m, d.cost), 0.001)
  // 计算模型总费用，用于各模型占比计算
  const totalByModel = byModel.reduce((sum, m) => sum + m.total_cost, 0.001)

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6 animate-pulse">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-white rounded-lg shadow p-4 space-y-2">
              <div className="h-7 w-16 bg-slate-200 rounded mx-auto" />
              <div className="h-3 w-24 bg-slate-200 rounded mx-auto" />
            </div>
          ))}
        </div>
        <div className="bg-white rounded-lg shadow p-5 space-y-3">
          <div className="h-4 w-36 bg-slate-200 rounded" />
          <div className="h-32 bg-slate-100 rounded" />
        </div>
        <div className="bg-white rounded-lg shadow p-5 space-y-3">
          <div className="h-4 w-32 bg-slate-200 rounded" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="space-y-1">
              <div className="h-3 w-48 bg-slate-200 rounded" />
              <div className="h-2 bg-slate-200 rounded-full" />
            </div>
          ))}
        </div>
      </div>
    )
  }
  if (error) return <div className="max-w-7xl mx-auto px-4 py-6"><div className="text-red-600 bg-red-50 p-3 rounded text-sm">{error}</div></div>

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      {/* Quick stats cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-xl font-bold text-slate-700">{summary.total_calls.toLocaleString()}</p>
            <p className="text-xs text-slate-500 mt-1">近7天调用次数</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-xl font-bold text-slate-700">
              {((summary.total_input_tokens + summary.total_output_tokens) / 1000).toFixed(0)}K
            </p>
            <p className="text-xs text-slate-500 mt-1">近7天总 Token</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-xl font-bold text-slate-700">${summary.total_cost.toFixed(4)}</p>
            <p className="text-xs text-slate-500 mt-1">近7天总费用</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-xl font-bold text-slate-700">{summary.avg_latency_ms.toFixed(0)}ms</p>
            <p className="text-xs text-slate-500 mt-1">平均延迟</p>
          </div>
        </div>
      )}

      {/* Daily cost chart */}
      <div className="bg-white rounded-lg shadow p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">近7天费用趋势 (USD)</h3>
        {daily.length > 0 ? (
          <div className="flex items-end gap-1 h-32">
            {daily.map((d) => {
              // 每根柱子高度按 maxCost 等比例计算，hover 显示精确金额
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
                    style={{ height: `${Math.max(h, 1)}%` }}
                  />
                  <span className="text-[9px] text-slate-400 mt-1">{d.date.slice(5)}</span>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-sm text-slate-400 text-center py-4">暂无每日数据</p>
        )}
      </div>

      {/* Model distribution */}
      <div className="bg-white rounded-lg shadow p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">按模型分布 (近7天)</h3>
        {byModel.length > 0 ? (
          <div className="space-y-3">
            {byModel.map((m) => {
              // 计算各模型费用占比，宽度按百分比渲染进度条
              const pct = totalByModel > 0 ? (m.total_cost / totalByModel) * 100 : 0
              return (
                <div key={m.model}>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="font-mono text-slate-600">{m.model}</span>
                    <span className="text-slate-500 text-xs">
                      {m.calls} 次 · ${m.total_cost.toFixed(4)}
                    </span>
                  </div>
                  <div className="w-full bg-slate-200 rounded-full h-2">
                    <div className="h-2 rounded-full bg-indigo-400 transition-all" style={{ width: `${Math.max(pct, 1)}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-sm text-slate-400 text-center py-4">暂无模型分布数据</p>
        )}
      </div>

      {/* Connection info */}
      {projectInfo && (
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">接入信息</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">代理地址（客户端接入用）</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-slate-100 rounded px-3 py-2 text-sm font-mono text-slate-700">{projectInfo.proxy_url}</code>
                <CopyButton text={projectInfo.proxy_url} />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">API Key</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-slate-100 rounded px-3 py-2 text-sm font-mono text-slate-700">{projectInfo.api_key.slice(0, 8)}***</code>
                <CopyButton text={projectInfo.api_key} />
              </div>
            </div>
          </div>
          {projectInfo.target_model && (
            <div className="flex items-center gap-2 text-xs mt-3 pt-3 border-t border-slate-100">
              <span className="text-slate-500">当前目标模型：</span>
              <code className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded font-mono text-xs">{projectInfo.target_model}</code>
              <span className="text-slate-400">可在「设置」中修改</span>
            </div>
          )}
          <div className="flex items-center gap-2 mt-3 text-xs">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-slate-500">代理服务运行中 — 将客户端配置为以上地址和 Key 即可接入监控</span>
          </div>
        </div>
      )}
    </div>
  )
}
