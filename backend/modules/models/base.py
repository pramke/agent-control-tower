"""
模块: 后端 - 数据库基类
功能: SQLAlchemy 声明式基类，所有模型继承自此
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类 — 所有数据库模型继承此类以自动获取 MetaData 和表注册能力。
    类体为空，由 SQLAlchemy 通过 has_inherited_table / _sa_registry 自动发现子类映射。"""
    pass
