"""Регистрация мелких core-модулей дашборда + точка для будущих прототипов.

Импортируется из bot_start ПОСЛЕ setup(...) всех больших модулей, поэтому
зарегистрированное здесь оказывается в конце меню. Новый прототип =
register(Module(key=..., title_key=..., on_open=...)) (см. core/registry.py).
"""
from core.dashboard import language_screen
from core.registry import Module, register

# Переключатель языка (ru/en/de) — последним пунктом меню.
register(Module(key="language", title_key="module.language", on_open=language_screen))
