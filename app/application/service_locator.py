"""
Service Locator & Dependency Injection Container
Provides thread-safe access to application services without global tight-coupling.
"""

from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar("T")


class ServiceLocator:
    _services: Dict[str, Any] = {}

    @classmethod
    def register(cls, interface_type: Type[T], instance: T) -> None:
        key = interface_type.__name__
        cls._services[key] = instance

    @classmethod
    def get(cls, interface_type: Type[T]) -> T:
        key = interface_type.__name__
        if key not in cls._services:
            raise KeyError(f"Service '{key}' is not registered in ServiceLocator.")
        return cls._services[key]

    @classmethod
    def try_get(cls, interface_type: Type[T]) -> Optional[T]:
        key = interface_type.__name__
        return cls._services.get(key)

    @classmethod
    def clear(cls) -> None:
        cls._services.clear()
