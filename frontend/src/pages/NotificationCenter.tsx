/**
 * 模块: 前端 - 页面
 * 功能: 通知中心面板，显示系统告警和通知消息
 */
import { useEffect, useState, useRef, useCallback } from 'react'
import { apiRequest, getAccessToken } from '../api/client'

/** 告警/通知项数据结构 */
interface AlertItem {
  id: number
  project_id: number | null
  trace_id: string | null
  level: string          // 级别：critical / warning / info
  category: string       // 分类：error_rate / cost_anomaly / dead_agent 等
  message: string        // 告警消息正文
  suggestion: string | null  // 处理建议
  acknowledged: boolean  // 是否已确认
  created_at: string     // 创建时间
}

/** 根据告警级别返回对应的 CSS 徽章样式 */
function levelBadge(level: string): string {
  switch (level) {
    case 'critical': return 'bg-red-100 text-red-700 border-red-300'
    case 'warning': return 'bg-amber-100 text-amber-700 border-amber-300'
    default: return 'bg-blue-100 text-blue-700 border-blue-300'
  }
}

/** 告警级别中文显示 */
function levelLabel(level: string): string {
  switch (level) {
    case 'critical': return '严重'
    case 'warning': return '警告'
    default: return '信息'
  }
}

/** 告警分类中文映射 */
function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    error_rate: '错误率',
    cost_anomaly: '成本异常',
    dead_agent: 'Agent挂死',
    budget_exceeded: '预算超限',
    approval_required: '待审批',
    tool_unhealthy: '工具异常',
    eval_regression: '评估倒退',
  }
  return map[cat] || cat
}

/** 将 ISO 时间戳转换为相对时间描述 */
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins}分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}小时前`
  return `${Math.floor(hours / 24)}天前`
}

/**
 * NotificationCenter 通知中心组件
 * - 顶部工具栏中的铃铛图标按钮，显示未读数量角标
 * - 点击展开下拉通知面板
 * - 通过 REST API + WebSocket 实时接收新告警
 */
export default function NotificationCenter() {
  const [alerts, setAlerts] = useState<AlertItem[]>([])         // 告警列表（最新30条）
  const [open, setOpen] = useState(false)                       // 面板展开/收起
  const [unackedCount, setUnackedCount] = useState(0)           // 未读告警数
  const wsRef = useRef<WebSocket | null>(null)                  // WebSocket 连接
  const containerRef = useRef<HTMLDivElement>(null)             // 面板容器引用（用于点击外部关闭）

  /** 从后端加载最新告警列表 */
  const fetchAlerts = useCallback(async () => {
    try {
      const data = await apiRequest<AlertItem[]>('GET', '/alerts?limit=30')
      setAlerts(data)
      setUnackedCount(data.filter((a) => !a.acknowledged).length)
    } catch {
      // silently fail for notifications
    }
  }, [])

  /** 首次挂载时加载告警列表 */
  useEffect(() => {
    fetchAlerts()
  }, [fetchAlerts])

  /**
   * 建立 WebSocket 连接以实时接收新告警
   * - 从登录用户获取 token 后连接 /ws/alerts
   * - 收到 alert 类型消息时插入列表头部并递增未读计数
   * - 连接断开后自动重试（10秒间隔）
   */
  useEffect(() => {
    let stopped = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (stopped) return
      const token = getAccessToken()
      if (!token) return

      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/alerts?token=${token}`)
      wsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data)
          if (payload.type === 'alert') {
            setAlerts((prev) => [payload, ...prev].slice(0, 30))
            setUnackedCount((c) => c + 1)
          }
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        if (!stopped) {
          retryTimer = setTimeout(connect, 10000)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      stopped = true
      if (retryTimer) clearTimeout(retryTimer)
      wsRef.current?.close()
    }
  }, [])

  /** 面板展开时注册点击外部自动关闭；使用 mousedown 而非 click 以避免冒泡延迟 */
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  /** 标记单条告警为已读 */
  const ack = async (id: number) => {
    try {
      await apiRequest<{ ok: boolean }>('POST', `/alerts/${id}/ack`)
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)))
      setUnackedCount((c) => Math.max(0, c - 1))
    } catch {
      // ignore
    }
  }

  /** 一键全部已读 */
  const ackAll = async () => {
    const unacked = alerts.filter((a) => !a.acknowledged)
    for (const a of unacked) {
      await ack(a.id)
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => { setOpen(!open); if (!open) fetchAlerts() }}
        className="relative px-2 py-2 text-slate-300 hover:text-white transition-colors"
        title="通知中心"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unackedCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none">
            {unackedCount > 9 ? '9+' : unackedCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-96 bg-white rounded-lg shadow-xl border border-slate-200 z-50 max-h-[32rem] flex flex-col">
          <div className="flex items-center justify-between px-4 py-2 border-b border-slate-100">
            <h3 className="text-sm font-semibold text-slate-700">
              通知中心
              {unackedCount > 0 && (
                <span className="ml-2 text-xs text-slate-400">({unackedCount} 未读)</span>
              )}
            </h3>
            {unackedCount > 0 && (
              <button onClick={ackAll} className="text-xs text-blue-500 hover:text-blue-700">
                全部已读
              </button>
            )}
          </div>

          <div className="overflow-y-auto flex-1">
            {alerts.length === 0 && (
              <p className="text-sm text-slate-400 text-center py-8">暂无通知。</p>
            )}
            {alerts.map((a) => (
              <div
                key={a.id}
                className={`px-4 py-2.5 border-b border-slate-50 hover:bg-slate-50 cursor-pointer transition-colors ${
                  !a.acknowledged ? 'bg-blue-50/50' : ''
                }`}
                onClick={() => !a.acknowledged && ack(a.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${levelBadge(a.level)}`}>
                      {levelLabel(a.level)}
                    </span>
                    <span className="text-[10px] text-slate-400 bg-slate-100 px-1 py-0.5 rounded">
                      {categoryLabel(a.category)}
                    </span>
                    {!a.acknowledged && (
                      <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                    )}
                  </div>
                  <span className="text-[10px] text-slate-400 shrink-0">{timeAgo(a.created_at)}</span>
                </div>
                <p className="text-sm text-slate-700 mt-1 line-clamp-2">{a.message}</p>
                {a.suggestion && (
                  <p className="text-xs text-amber-700 mt-0.5 line-clamp-1">{a.suggestion}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
