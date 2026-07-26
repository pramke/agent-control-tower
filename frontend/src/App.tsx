/**
 * 模块: 前端 - 应用根组件
 * 功能: 管理全局认证状态、视图路由和顶层导航，根据用户角色切换页面
 */
import { useState, useEffect } from 'react'
import ErrorBoundary from './components/ErrorBoundary'
import Login, { UserInfo } from './pages/Login'
import ProjectList from './pages/ProjectList'
import ProjectWorkspace from './pages/ProjectWorkspace'
import AdminUsers from './pages/AdminUsers'
import NotificationCenter from './pages/NotificationCenter'
import { loadTokens, getAccessToken, clearTokens, fetchMe } from './api/client'

interface Project {
  id: number
  name: string
  api_key: string
  base_url: string
  project_type: string
  created_at: string
}

type View = 'projects' | 'workspace' | 'admin_users'

const ROLE_CONFIG: Record<string, { label: string; color: string }> = {
  admin: { label: '管理员', color: 'bg-red-500' },
  user: { label: '用户', color: 'bg-slate-500' },
}

export default function App() {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [view, setView] = useState<View>('projects')
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [initialTab, setInitialTab] = useState<string | undefined>(undefined)

  // 页面加载时恢复本地存储的 Token，尝试获取用户信息；Token 无效时自动清除
  useEffect(() => {
    loadTokens()
    if (getAccessToken()) {
      fetchMe()
        .then((u) => setUser(u))
        .catch(() => { clearTokens() })
    }
  }, [])

  const handleLogin = (u: UserInfo) => { setUser(u) }

  const handleLogout = () => {
    clearTokens()
    setUser(null)
    setView('projects')
    setSelectedProject(null)
  }

  const handleSelectProject = (project: Project, initialTab?: string) => {
    setSelectedProject(project)
    setInitialTab(initialTab)
    setView('workspace')
  }

  const handleBack = () => {
    setView('projects')
    setSelectedProject(null)
  }

  if (!user) {
    return <Login onLogin={handleLogin} />
  }

  const roleCfg = ROLE_CONFIG[user.role] || ROLE_CONFIG.user
  // 仅管理员可访问用户管理页面
  const canAdmin = user.role === 'admin'

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-slate-50">
      {/* Top navigation bar */}
      <nav className="bg-slate-800 flex-shrink-0">
        <div className="max-w-7xl mx-auto px-4 flex items-center h-12">
          <div className="flex items-center gap-3 flex-1">
            <button
              onClick={handleBack}
              className="text-sm text-slate-300 hover:text-white transition-colors font-medium"
            >
              智能体控制塔
            </button>
            {view !== 'projects' && (
              <span className="text-slate-500 text-sm">/ {selectedProject?.name}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {canAdmin && (
              <button
                onClick={() => { setView('admin_users'); setSelectedProject(null) }}
                className={`px-3 py-1.5 text-xs rounded transition-colors ${
                  view === 'admin_users'
                    ? 'bg-slate-600 text-white'
                    : 'text-slate-300 hover:text-white border border-slate-600'
                }`}
              >
                用户管理
              </button>
            )}
            {view === 'admin_users' && (
              <button
                onClick={handleBack}
                className="px-3 py-1.5 text-xs text-slate-300 hover:text-white border border-slate-600 rounded transition-colors"
              >
                项目列表
              </button>
            )}
            <span className={`px-2 py-0.5 rounded text-xs text-white ${roleCfg.color}`}>
              {roleCfg.label}
            </span>
            <span className="text-slate-300 text-xs hidden sm:inline">{user.username}</span>
            <NotificationCenter />
            <button
              onClick={handleLogout}
              className="px-3 py-1.5 text-xs text-slate-300 hover:text-white border border-slate-600 rounded"
            >
              退出
            </button>
          </div>
        </div>
      </nav>

      <div className="flex-1 min-h-0">
      {/* 使用 ErrorBoundary 包裹子视图，子组件崩溃不影响导航栏 */}
      <ErrorBoundary>
        {view === 'projects' && (
          <ProjectList userRole={user.role} onSelectProject={handleSelectProject} />
        )}
        {view === 'workspace' && selectedProject && (
          <ProjectWorkspace
            project={selectedProject}
            userRole={user.role}
            initialTab={initialTab}
            onSwitchProject={(p) => handleSelectProject(p)}
          />
        )}
        {view === 'admin_users' && <AdminUsers />}
      </ErrorBoundary>
      </div>
    </div>
  )
}
