"""
模块: 项目启动入口
功能: 开发环境启动脚本，清理 PYTHONPATH 后启动 FastAPI 服务器
"""
import os, sys, subprocess, socket

# 安全检查：PYTHONPATH 必须为空，防止导入环境中的旧版本依赖
assert 'PYTHONPATH' not in os.environ or not os.environ['PYTHONPATH'], \
    "PYTHONPATH is set! Run with: PYTHONPATH=\"\" python start.py"

PROJECT = r'E:\python.py4\agent-control-tower'  # 项目根目录
VENV = os.path.join(PROJECT, '.venv')            # 虚拟环境目录

python = os.path.join(VENV, 'Scripts', 'python.exe')  # Windows 下的 Python 解释器路径

os.chdir(PROJECT)
sys.path.insert(0, os.path.join(VENV, 'Lib', 'site-packages'))  # 优先使用 venv 的包
sys.path.insert(0, PROJECT)                                      # 项目模块可直接 import


def _check_port(host: str, port: int) -> int | None:
    """检查端口是否已被占用。返回占用进程 PID，若空闲返回 None。"""
    if sys.platform != 'win32':
        return None
    try:
        out = subprocess.check_output(
            ['netstat', '-ano'], text=True, timeout=5
        )
        for line in out.splitlines():
            if f'{host}:{port}' in line and 'LISTENING' in line:
                parts = line.strip().split()
                return int(parts[-1])
    except Exception:
        pass
    return None


def _kill_process(pid: int) -> bool:
    try:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                       capture_output=True, timeout=10)
        return True
    except Exception:
        return False


import uvicorn

if __name__ == '__main__':
    os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///./act2.db')

    host, port = '127.0.0.1', 8001
    pid = _check_port(host, port)
    if pid is not None:
        import signal
        print(f'[!] Port {port} already in use by PID {pid}')
        if _kill_process(pid):
            import time; time.sleep(0.5)
            print(f'    Killed PID {pid}, restarting...')
        else:
            print(f'    Cannot kill PID {pid}. Run: taskkill /F /PID {pid}')
            sys.exit(1)

    uvicorn.run('backend.main:app', host=host, port=port, reload=False)
