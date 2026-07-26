"""ACT SDK——Agent Control Tower 的 Python SDK，供下游项目接入使用"""
from setuptools import setup, find_packages

setup(
    name='act-sdk',
    version='0.1.0',
    packages=find_packages(),
    install_requires=['httpx>=0.28'],
    python_requires='>=3.10',
)
