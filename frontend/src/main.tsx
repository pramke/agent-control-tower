/**
 * 模块: 前端 - 项目入口
 * 功能: React 应用启动入口，渲染 App 组件到页面
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
