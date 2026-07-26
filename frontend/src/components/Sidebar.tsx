/**
 * 侧边导航栏：显示当前项目名称与类型、渲染功能标签页切换。
 */
interface Project {
  id: number; name: string; api_key: string; base_url: string
  project_type: string; created_at: string
}

interface Tab {
  key: string; label: string; icon: string; disabled?: boolean
}

interface Props {
  projectName: string
  projectType: 'monitor' | 'agent' | 'production'
  activeTab: string
  tabs: Tab[]
  onTabChange: (key: string) => void
  onSwitchProject?: (project: Project) => void
}

export default function Sidebar({ projectName, projectType, activeTab, tabs, onTabChange }: Props) {
  // 根据项目类型决定徽章样式和文案；非 agent 类型统一视为监测项目
  const isMonitor = projectType !== 'agent'

  const typeBadgeClass = isMonitor ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'
  const typeLabel = isMonitor ? '监测项目' : 'Agent 项目'

  return (
    <aside className="w-56 bg-white border-r border-slate-200 flex flex-col flex-shrink-0 h-[calc(100vh-3rem)]">
      {/* Project header — static display, no switcher for now */}
      <div className="px-3 py-3 border-b border-slate-100">
        <div className="px-2 py-1.5">
          <span className="text-sm font-semibold text-slate-800 truncate block">{projectName}</span>
          <span className={`inline-block mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${typeBadgeClass}`}>
            {typeLabel}
          </span>
        </div>
      </div>

      {/* Navigation items */}
      <nav className="flex-1 overflow-y-auto py-2">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            disabled={tab.disabled}
            onClick={() => { if (!tab.disabled) onTabChange(tab.key) }}
            className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors ${
              tab.disabled
                ? 'text-slate-300 cursor-not-allowed border-l-2 border-transparent'
                : activeTab === tab.key
                  ? 'bg-blue-50 text-blue-600 font-medium border-l-2 border-blue-500'
                  : 'text-slate-600 hover:bg-slate-50 border-l-2 border-transparent'
            }`}
          >
            <span className="w-5 text-center opacity-60">{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  )
}
