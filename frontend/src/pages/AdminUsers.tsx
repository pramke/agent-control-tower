/**
 * 模块: 前端 - Admin 用户管理页面
 * 功能: 管理员查看所有用户、修改角色、删除用户
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

interface UserRow {
  id: number
  username: string
  role: string
  created_at: string
}

const ROLE_OPTIONS = ['user', 'admin'] as const

export default function AdminUsers() {
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [updatingId, setUpdatingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<UserRow | null>(null)
  const [successMsg, setSuccessMsg] = useState('')

  const fetchUsers = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await apiRequest<UserRow[]>('GET', '/admin/users')
      setUsers(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载用户列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchUsers() }, [])

  /** 切换用户角色 */
  const handleRoleChange = async (userId: number, newRole: string) => {
    setUpdatingId(userId)
    setError('')
    try {
      await apiRequest('PUT', `/admin/users/${userId}/role`, { role: newRole })
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u)))
      setSuccessMsg(`用户角色已更新`)
      setTimeout(() => setSuccessMsg(''), 2000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '角色更新失败')
    } finally {
      setUpdatingId(null)
    }
  }

  /** 删除用户 */
  const handleDelete = async () => {
    if (!confirmDelete) return
    setDeletingId(confirmDelete.id)
    setError('')
    try {
      await apiRequest('DELETE', `/admin/users/${confirmDelete.id}`)
      setUsers((prev) => prev.filter((u) => u.id !== confirmDelete.id))
      setConfirmDelete(null)
      setSuccessMsg(`用户 ${confirmDelete.username} 已删除`)
      setTimeout(() => setSuccessMsg(''), 2000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeletingId(null)
    }
  }

  const roleBadge = (role: string) => {
    const map: Record<string, string> = {
      admin: 'bg-red-100 text-red-700',
      user: 'bg-slate-100 text-slate-600',
    }
    const labels: Record<string, string> = { admin: '管理员', user: '用户' }
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${map[role] || ''}`}>
        {labels[role] || role}
      </span>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold text-slate-700">用户管理</h2>
        <button
          onClick={fetchUsers}
          className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600"
        >
          刷新
        </button>
      </div>

      {successMsg && (
        <div className="bg-green-50 text-green-700 p-2 rounded text-sm mb-4">{successMsg}</div>
      )}
      {error && (
        <div className="bg-red-50 text-red-600 p-2 rounded text-sm mb-4">{error}</div>
      )}

      {loading && <p className="text-slate-500 text-sm">加载中...</p>}

      {!loading && !error && users.length === 0 && (
        <p className="text-slate-400 text-sm">暂无用户数据</p>
      )}

      {!loading && users.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 text-slate-500 font-medium">用户名</th>
                <th className="text-left px-4 py-3 text-slate-500 font-medium">角色</th>
                <th className="text-left px-4 py-3 text-slate-500 font-medium hidden sm:table-cell">注册时间</th>
                <th className="text-right px-4 py-3 text-slate-500 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-800">{u.username}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {roleBadge(u.role)}
                      {updatingId === u.id ? (
                        <span className="text-xs text-slate-400">更新中...</span>
                      ) : (
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u.id, e.target.value)}
                          className="text-xs border border-slate-200 rounded px-1 py-0.5 bg-white text-slate-600"
                        >
                          {ROLE_OPTIONS.map((r) => (
                            <option key={r} value={r}>
                              {r === 'admin' ? '管理员' : '用户'}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-400 hidden sm:table-cell">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setConfirmDelete(u)}
                      className="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition-colors"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 删除确认弹窗 */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold text-slate-800 mb-2">确认删除用户</h3>
            <p className="text-sm text-slate-600 mb-4">
              确定要删除用户 <strong>{confirmDelete.username}</strong>（{confirmDelete.role}）吗？此操作不可撤销。
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmDelete(null)}
                className="px-4 py-2 text-sm text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={deletingId === confirmDelete.id}
                className="px-4 py-2 text-sm text-white bg-red-500 rounded-md hover:bg-red-600 disabled:opacity-50"
              >
                {deletingId === confirmDelete.id ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
