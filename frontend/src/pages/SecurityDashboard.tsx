/**
 * 模块：安全仪表盘 (SecurityDashboard)
 * 功能：监控和展示项目安全状态，包括防护层状态概览和检测告警列表，
 *       支持按项目切换、告警刷新、告警确认等操作。
 */

import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

// 项目基础信息
interface Project {
  id: number
  name: string
}

// 检测告警数据结构
interface DetectionAlert {
  id: number
  alert_type: string
  severity: string
  title: string
  description: string
  evidence: Record<string, unknown>
  model: string | null
  acknowledged: boolean
  detected_at: string
}

// 告警列表响应
interface AlertListResponse {
  total: number
  page: number
  page_size: number
  items: DetectionAlert[]
}

// 防护层检查项数据结构
interface SecurityCheck {
  category: string
  status: 'ok' | 'warning' | 'critical'
  count: number
  description: string
}

// 根据状态返回圆点颜色样式
function statusDot(status: string) {
  switch (status) {
    case 'ok': return 'bg-green-500'
    case 'warning': return 'bg-yellow-500'
    case 'critical': return 'bg-red-500'
    default: return 'bg-slate-400'
  }
}

// 状态中文标签
function statusLabel(status: string) {
  switch (status) {
    case 'ok': return '正常'
    case 'warning': return '注意'
    case 'critical': return '危险'
    default: return status
  }
}

// 状态颜色组合样式
function statusColor(status: string) {
  switch (status) {
    case 'ok': return 'text-green-700 bg-green-50 border-green-200'
    case 'warning': return 'text-yellow-700 bg-yellow-50 border-yellow-200'
    case 'critical': return 'text-red-700 bg-red-50 border-red-200'
    default: return 'text-slate-600 bg-slate-50 border-slate-200'
  }
}

// 严重程度标签样式
function severityBadge(s: string) {
  if (s === 'critical' || s === 'high') return 'bg-red-100 text-red-700'
  if (s === 'warning' || s === 'medium') return 'bg-amber-100 text-amber-700'
  return 'bg-blue-100 text-blue-700'
}

// 告警类型中文映射
function alertTypeLabel(t: string) {
  const map: Record<string, string> = {
    injection: '注入攻击',
    bait_key: '蜜钥泄露',
    fingerprint: '模型指纹',
    content_filter: '内容过滤',
    data_leak: '数据泄露',
  }
  return map[t] || t
}

export default function SecurityDashboard() {
  // 状态管理
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [alerts, setAlerts] = useState<DetectionAlert[]>([])
  const [alertTotal, setAlertTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 防护层检查项初始状态
  const [checks, setChecks] = useState<SecurityCheck[]>([
    { category: 'Prompt注入防护', status: 'ok', count: 0, description: '实时检测系统提示词注入攻击' },
    { category: '数据脱敏', status: 'ok', count: 0, description: '自动掩码手机号/身份证/邮箱等敏感信息' },
    { category: '内容过滤', status: 'ok', count: 0, description: '检测并拦截色情/暴力/政治敏感内容' },
    { category: '工具审批流', status: 'ok', count: 0, description: '高风险工具执行前的强制审批' },
    { category: '蜜钥保护', status: 'ok', count: 0, description: '检测和告警蜜钥泄露' },
    { category: '模型纯度', status: 'ok', count: 0, description: '监控模型指纹防止降级' },
  ])

  // 页面加载时获取项目列表
  useEffect(() => {
    apiRequest<Project[]>('GET', '/projects')
      .then(setProjects)
      .catch(() => {})
  }, [])

  // 获取指定项目的告警数据，并更新防护层状态
  const fetchAlerts = async () => {
    if (selectedProjectId === null) return
    setLoading(true)
    setError('')
    try {
      const data = await apiRequest<AlertListResponse>(
        'GET',
        `/detection/${selectedProjectId}/alerts?limit=50&days=30`,
      )

      setAlerts(data.items)
      setAlertTotal(data.total)

      // 统计未处理告警按类型和严重程度分布，用于动态更新防护层状态
      const unackedCounts: Record<string, number> = {}
      const severityCounts: Record<string, number> = {}
      for (const a of data.items) {
        if (!a.acknowledged) {
          const type = a.alert_type || 'unknown'
          unackedCounts[type] = (unackedCounts[type] || 0) + 1
          severityCounts[a.severity] = (severityCounts[a.severity] || 0) + 1
        }
      }

      const injectionCount = unackedCounts['injection'] || 0
      const baitCount = unackedCounts['bait_key'] || 0

      // 根据告警数量自动更新各防护层状态
      setChecks((prev) =>
        prev.map((c) => {
          if (c.category === 'Prompt注入防护') {
            return { ...c, status: injectionCount > 5 ? 'critical' : injectionCount > 0 ? 'warning' : 'ok', count: injectionCount }
          }
          if (c.category === '数据脱敏') {
            const d = unackedCounts['data_leak'] || 0
            return { ...c, status: d > 0 ? 'warning' : 'ok', count: d }
          }
          if (c.category === '内容过滤') {
            const f = unackedCounts['content_filter'] || 0
            return { ...c, status: f > 0 ? 'warning' : 'ok', count: f }
          }
          if (c.category === '蜜钥保护') {
            return { ...c, status: baitCount > 0 ? 'critical' : 'ok', count: baitCount }
          }
          return c
        }),
      )
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  // 切换项目时自动获取告警数据
  useEffect(() => {
    if (selectedProjectId !== null) fetchAlerts()
  }, [selectedProjectId])

  // 确认告警（标记为已处理）
  const handleAcknowledge = async (alertId: number) => {
    if (selectedProjectId === null) return
    try {
      await apiRequest('POST', `/detection/${selectedProjectId}/alerts/${alertId}/acknowledge`)
      setAlerts((prev) => prev.map((a) => (a.id === alertId ? { ...a, acknowledged: true } : a)))
    } catch {
      // ignore
    }
  }

  // 未确认的告警才算"待处理"；严重事件需要同时满足 severity=critical 且未确认
  const blockedCount = alerts.filter((a) => !a.acknowledged).length
  const criticalCount = alerts.filter((a) => a.severity === 'critical' && !a.acknowledged).length

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      {/* 页面标题与项目选择器 */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-700">安全仪表盘</h2>
        <div className="flex gap-2 items-center">
          <select
            value={selectedProjectId ?? ''}
            onChange={(e) => setSelectedProjectId(e.target.value ? Number(e.target.value) : null)}
            className="border border-slate-300 rounded-md px-3 py-1.5 text-sm bg-white"
          >
            <option value="">选择项目</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button
            onClick={fetchAlerts}
            disabled={loading || selectedProjectId === null}
            className="px-3 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
          >
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && <div className="text-red-600 bg-red-50 p-3 rounded text-sm">{error}</div>}

      {/* 未选择项目时的提示 */}
      {selectedProjectId === null && (
        <div className="bg-white rounded-lg shadow p-8 text-center text-slate-400 text-sm">
          请选择一个项目以查看安全状态。
        </div>
      )}

      {selectedProjectId !== null && (
        <>
          {/* 统计卡片：未处理威胁、严重事件、已处理 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white rounded-lg shadow p-4 border-l-4 border-red-400">
              <p className="text-2xl font-bold text-red-600">{blockedCount}</p>
              <p className="text-sm text-slate-500 mt-0.5">未处理威胁 ({alertTotal} 总计)</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 border-l-4 border-yellow-400">
              <p className="text-2xl font-bold text-yellow-600">{criticalCount}</p>
              <p className="text-sm text-slate-500 mt-0.5">严重事件</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 border-l-4 border-blue-400">
              <p className="text-2xl font-bold text-blue-600">{alertTotal - blockedCount}</p>
              <p className="text-sm text-slate-500 mt-0.5">已处理</p>
            </div>
          </div>

          {/* 防护层状态列表 */}
          <div className="bg-white rounded-lg shadow p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">防护层状态</h3>
            <div className="space-y-3">
              {checks.map((check) => (
                <div
                  key={check.category}
                  className={`flex items-start gap-3 p-3 rounded-lg border ${statusColor(check.status)}`}
                >
                  <span className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${statusDot(check.status)}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{check.category}</span>
                      <div className="flex items-center gap-2">
                        {check.count > 0 && (
                          <span className="text-xs font-medium">{check.count} 个事件</span>
                        )}
                        <span className="text-xs font-medium">{statusLabel(check.status)}</span>
                      </div>
                    </div>
                    <p className="text-xs mt-0.5 opacity-75">{check.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 检测告警列表 */}
          <div className="bg-white rounded-lg shadow p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">检测告警 ({alerts.length})</h3>
            {alerts.length === 0 && (
              <p className="text-sm text-slate-400 text-center py-4">暂无告警记录。</p>
            )}
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {alerts.slice(0, 20).map((a) => (
                <div
                  key={a.id}
                  className={`flex items-start justify-between p-3 rounded border text-sm ${
                    a.acknowledged ? 'bg-slate-50 border-slate-100' : 'bg-red-50/50 border-red-100'
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${severityBadge(a.severity)}`}>
                        {a.severity}
                      </span>
                      <span className="text-xs text-slate-400 bg-slate-100 px-1 py-0.5 rounded">
                        {alertTypeLabel(a.alert_type)}
                      </span>
                      {!a.acknowledged && (
                        <span className="text-xs font-medium text-red-600">未处理</span>
                      )}
                    </div>
                    <p className="font-medium text-slate-700">{a.title}</p>
                    {a.description && (
                      <p className="text-xs text-slate-500 mt-0.5">{a.description}</p>
                    )}
                    <div className="flex gap-3 text-xs text-slate-400 mt-1">
                      {a.model && <span>模型: {a.model}</span>}
                      <span>{new Date(a.detected_at).toLocaleString()}</span>
                    </div>
                  </div>
                  {/* 未处理的告警显示「确认」按钮 */}
                  {!a.acknowledged && (
                    <button
                      onClick={() => handleAcknowledge(a.id)}
                      className="ml-3 px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 shrink-0"
                    >
                      确认
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
