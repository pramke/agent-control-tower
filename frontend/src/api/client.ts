/**
 * 模块: 前端 - API通信层
 * 功能: 封装所有与后端通信的请求方法，管理访问令牌和用户角色
 */

const API_BASE = '/api'

let accessToken: string | null = null
let _refreshToken: string | null = null

export function setTokens(access: string, refresh: string): void {
  accessToken = access
  _refreshToken = refresh
  localStorage.setItem('access_token', access)
  localStorage.setItem('refresh_token', refresh)
}

export function loadTokens(): void {
  accessToken = localStorage.getItem('access_token')
  _refreshToken = localStorage.getItem('refresh_token')
  // refreshToken 仅存 localStorage 备用，当前无主动刷新逻辑，消除 unused 警告
  void _refreshToken
}

export function clearTokens(): void {
  accessToken = null
  _refreshToken = null
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}

export function getAccessToken(): string | null {
  return accessToken
}

export class ApiError extends Error {
  code: string
  details: Record<string, unknown>

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.code = code
    this.details = details
  }
}

/**
 * 通用 API 请求方法
 * 自动附加 Token 到请求头，统一处理错误并抛出 ApiError
 */
export async function apiRequest<T>(method: string, path: string, body?: unknown, isFormData?: boolean): Promise<T> {
  const headers: Record<string, string> = {}
  if (!isFormData) headers['Content-Type'] = 'application/json'
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`

  const fetchBody: BodyInit | undefined = isFormData ? (body as FormData) : (body ? JSON.stringify(body) : undefined)
  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: fetchBody })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ code: 'UNKNOWN', message: res.statusText }))
    throw new ApiError(err.code || 'UNKNOWN', err.message || '请求失败', err.details || {})
  }
  return res.json()
}

/** 登录：用用户名/密码换取 JWT Token 并持久化 */
export async function login(username: string, password: string): Promise<{ id: number; username: string; role: string }> {
  const data = await apiRequest<{ access_token: string; refresh_token: string }>('POST', '/auth/login', { username, password })
  setTokens(data.access_token, data.refresh_token)
  return fetchMe()
}

/** 注册 */
export async function register(username: string, password: string): Promise<{ id: number; username: string; role: string }> {
  const data = await apiRequest<{ access_token: string; refresh_token: string }>('POST', '/auth/register', { username, password })
  setTokens(data.access_token, data.refresh_token)
  return fetchMe()
}

/** 获取当前用户信息 */
export async function fetchMe(): Promise<{ id: number; username: string; role: string }> {
  return apiRequest('GET', '/me')
}
