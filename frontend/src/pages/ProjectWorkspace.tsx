/**
 * 模块: 前端 - 项目工作空间页面
 * 功能: 根据项目类型（监控/Agent）展示不同侧边栏和 Tab 面板，统一管理子视图路由
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import CopyButton from '../components/CopyButton'
import Sidebar from '../components/Sidebar'
import Dashboard from './Dashboard'
import Calls from './Calls'
import Stats from './Stats'
import SecurityDashboard from './SecurityDashboard'
import TraceViewer from './TraceViewer'
import EvalSetManagement from './EvalSetManagement'
import PromptManager from './PromptManager'

interface Project {
  id: number
  name: string
  api_key: string
  base_url: string
  project_type: string
  created_at: string
}

interface Props {
  project: Project
  userRole: string
  initialTab?: string
  onSwitchProject: (project: Project) => void
}

type MonitorTab = 'overview' | 'calls' | 'stats' | 'security' | 'settings'
type AgentTab = 'sdk' | 'traces' | 'prompts' | 'eval'

const MONITOR_TABS: { key: MonitorTab; label: string; icon: string }[] = [
  { key: 'overview', label: '概览', icon: '📊' },
  { key: 'calls', label: '调用记录', icon: '📋' },
  { key: 'stats', label: '费用分析', icon: '💰' },
  { key: 'security', label: '安全', icon: '🛡️' },
  { key: 'settings', label: '设置', icon: '⚙️' },
]

const AGENT_TABS: { key: AgentTab; label: string; icon: string }[] = [
  { key: 'sdk', label: 'SDK 接入', icon: '📦' },
  { key: 'traces', label: '追踪记录', icon: '🔍' },
  { key: 'prompts', label: 'Prompt 管理', icon: '💬' },
  { key: 'eval', label: '评估', icon: '📝' },
]

export default function ProjectWorkspace({ project }: Props) {
  const isMonitor = project.project_type === 'monitor'
  const [monitorTab, setMonitorTab] = useState<MonitorTab>('overview')
  const [agentTab, setAgentTab] = useState<AgentTab>('sdk')

  // 根据项目类型选择对应的 Tab 列表和当前激活 Tab
  const activeTab = isMonitor ? monitorTab : agentTab
  const tabs = isMonitor ? MONITOR_TABS : AGENT_TABS
  const handleTabChange = (key: string) => {
    if (isMonitor) setMonitorTab(key as MonitorTab)
    else setAgentTab(key as AgentTab)
  }

  return (
    <div className="h-full flex bg-slate-50">
      <Sidebar
        projectName={project.name}
        projectType={project.project_type as 'monitor' | 'agent' | 'production'}
        activeTab={activeTab}
        tabs={tabs}
        onTabChange={handleTabChange}
      />

      <div className="flex-1 min-w-0 overflow-y-auto">
        {isMonitor && (
          <>
            {monitorTab === 'overview' && <Dashboard projectId={project.id} />}
            {monitorTab === 'calls' && <Calls projectId={project.id} />}
            {monitorTab === 'stats' && <Stats projectId={project.id} />}
            {monitorTab === 'security' && <SecurityDashboard />}
            {monitorTab === 'settings' && <MonitorSettings project={project} />}
          </>
        )}
        {!isMonitor && (
          <>
            {agentTab === 'sdk' && <SdkGuide project={project} />}
            {agentTab === 'traces' && <TraceViewer projectId={project.id} />}
            {agentTab === 'prompts' && <PromptManager projectId={project.id} />}
            {agentTab === 'eval' && <EvalSetManagement />}
          </>
        )}
      </div>
    </div>
  )
}

// 隐藏 API Key 中间部分，界面上仅展示前8位
function maskApiKey(key: string): string {
  return key.length > 12 ? key.slice(0, 8) + '***' : key
}

/** ─── Agent模式: SDK接入指引（pip安装 + 代码示例 + API Key展示） ─── */

function SdkGuide({ project }: { project: Project }) {
  const [fullInfo, setFullInfo] = useState<{ proxy_url: string; api_key: string } | null>(null)
  const apiKey = fullInfo?.api_key || project.api_key
  const proxyUrl = fullInfo?.proxy_url || 'http://127.0.0.1:8001'

  // 获取项目完整信息以展示实际 proxy_url 和 api_key
  useEffect(() => {
    apiRequest<{ proxy_url: string; api_key: string }>('GET', `/projects/${project.id}/full`)
      .then((info) => setFullInfo(info))
      .catch(() => {})
  }, [project.id])

  const sdkCode = `from act_sdk import init, observe

init(project_id=${project.id}, api_key="${apiKey}", base_url="${proxyUrl}")
tracer = get_tracer()

@observe()
def my_agent(query: str):
    # Your agent logic here
    return {"result": "..."}`

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-slate-700 mb-4">SDK 接入</h3>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">1. 安装 SDK</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-slate-800 text-green-300 rounded px-3 py-2 text-sm font-mono">pip install -e act-sdk</code>
              <CopyButton text="pip install -e act-sdk" />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">2. 初始化并添加装饰器</label>
            <div className="relative">
              <pre className="bg-slate-800 text-green-300 rounded px-3 py-2 text-xs font-mono overflow-x-auto">{sdkCode}</pre>
              <div className="absolute top-2 right-2">
                <CopyButton text={sdkCode} />
              </div>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">3. API Key</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-slate-100 rounded px-3 py-2 text-sm font-mono text-slate-700">{maskApiKey(apiKey)}</code>
              <CopyButton text={apiKey} />
            </div>
          </div>

          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-sm text-green-700 font-medium mb-1">接入完成</p>
            <p className="text-xs text-green-600">
              使用 <code className="bg-green-100 px-1 rounded">@observe()</code> 装饰器包裹你的 Agent 函数，
              所有 LLM 调用和工具执行将自动上报到平台，可在「追踪记录」Tab 查看。
            </p>
          </div>
        </div>
      </div>

    </div>
  )
}

/** ─── 监控模式: 代理地址 + API Key 展示 + 目标模型/格式设置 ─── */

function MonitorSettings({ project }: { project: Project }) {
  const [fullInfo, setFullInfo] = useState<{ proxy_url: string; api_key: string; target_model: string; provider_type: string } | null>(null)
  const [modelInput, setModelInput] = useState('')
  const [providerType, setProviderType] = useState<string>('anthropic')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const apiKey = fullInfo?.api_key || project.api_key
  const proxyUrl = fullInfo?.proxy_url || project.base_url
  const targetModel = fullInfo?.target_model || ''

  // 获取项目完整配置以初始化表单字段（目标模型、上游格式等）
  useEffect(() => {
    apiRequest<{ proxy_url: string; api_key: string; target_model: string; provider_type: string }>('GET', `/projects/${project.id}/full`)
      .then((info) => { setFullInfo(info); setModelInput(info.target_model || ''); setProviderType(info.provider_type || 'anthropic') })
      .catch(() => {})
  }, [project.id])

  const handleSaveSettings = async () => {
    setSaving(true)
    setSaveMsg('')
    try {
      await apiRequest('PUT', `/projects/${project.id}/settings`, {
        target_model: modelInput || null,
        provider_type: providerType,
      })
      setSaveMsg('保存成功')
      setFullInfo((prev) => prev ? { ...prev, target_model: modelInput, provider_type: providerType } : null)
    } catch {
      setSaveMsg('保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-slate-700 mb-4">接入信息</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">代理地址（客户端接入用）</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-slate-100 rounded px-3 py-2 text-sm font-mono text-slate-700">{proxyUrl}</code>
              <CopyButton text={proxyUrl} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">API Key</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-slate-100 rounded px-3 py-2 text-sm font-mono text-slate-700">{maskApiKey(apiKey)}</code>
              <CopyButton text={apiKey} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">目标模型</label>
            <input type="text" value={modelInput} onChange={(e) => setModelInput(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="例如 deepseek-v4-pro，留空使用默认映射" />
            <p className="text-xs text-slate-400 mt-1">
              {targetModel
                ? `当前：所有请求模型名将被替换为「${targetModel}」`
                : '当前：根据 Claude 模型名自动映射（Haiku→Flash, Sonnet/Opus→Pro）'}
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-500 mb-1">上游 API 格式</label>
            <select value={providerType} onChange={(e) => setProviderType(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="anthropic">Anthropic 兼容（DeepSeek /anthropic 等）</option>
              <option value="openai">OpenAI 兼容（GLM、Kimi、DeepSeek /v1 等）</option>
            </select>
            <p className="text-xs text-slate-400 mt-1">
              切换后请确保 Base URL 和 API Key 对应正确的厂商。
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={handleSaveSettings} disabled={saving}
              className="px-4 py-2 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600 disabled:opacity-50">
              {saving ? '保存中…' : '保存设置'}
            </button>
            {saveMsg && <span className={`self-center text-xs ${saveMsg === '保存成功' ? 'text-green-600' : 'text-red-600'}`}>{saveMsg}</span>}
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-sm text-blue-700 font-medium mb-1">使用方式</p>
            <p className="text-xs text-blue-600">
              将客户端 API Base URL 设置为代理地址，API Key 设置为上述 Key，即可通过代理访问上游 LLM 服务。
              所有请求将被自动记录、监控和安全检测。
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
