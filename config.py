# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: config.py
# 模块作用: 配置管理模块，负责插件启动状态与分类信息的 JSON 持久化读写。
#           提供插件自启开关、分类归属的增删改查接口，并支持旧格式兼容迁移。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

"""配置管理：负责启动状态 & 分类信息的 JSON 持久化读写。

数据存储路径: Blender用户配置目录/scripts/pmp/startup_config.json
数据格式: {module_name: {"categories": [cat_id, ...], "startup": bool}}

主要功能:
  - load/save: 加载和保存配置到JSON文件
  - get_startup/set_startup: 获取/设置插件自启状态
  - get_categories/set_categories: 获取/设置插件分类列表
  - add_category/remove_category/toggle_category: 分类增删切换
  - get_all_addons/get_addons_by_category: 批量查询

输入: 各函数接收 module_name (str) 作为插件标识
输出: 各函数返回配置数据或操作结果
"""

import bpy
import json
import os
import addon_utils
from .data import CATEGORY_AUTO_MAP

# 配置文件路径（延迟计算，首次访问时确定）
_config_path = None
# 配置缓存字典，键为模块名，值为配置字典
_CACHE: dict = {}


def _get_config_path():
    """获取配置文件路径（延迟计算）。

    配置文件位于 Blender 用户资源目录下的 scripts/pmp/startup_config.json。
    首次调用时计算路径并缓存，后续调用直接返回缓存值。

    输入: 无（使用全局变量 _config_path）
    输出: str - 配置文件的绝对路径
    """
    global _config_path
    if _config_path is None:
        _config_path = os.path.join(
            bpy.utils.user_resource('CONFIG', path="scripts/pmp", create=True),
            "startup_config.json"
        )
    return _config_path


def _migrate_legacy_format():
    """向后兼容：将旧格式转换为新格式。

    支持两种旧格式的迁移：
    - 格式1: {name: bool} -> {name: {"categories": ["UNCATEGORIZED"], "startup": bool}}
    - 格式2: {name: {"category": str, "startup": bool}} -> {name: {"categories": [cat_id, ...], "startup": bool}}

    旧分类ID会通过映射表转换为新分类ID（如 "VIEW_3D" -> "3D_VIEWPORT"）。

    输入: 无（直接修改全局 _CACHE）
    输出: 无
    """
    for key in list(_CACHE.keys()):
        val = _CACHE[key]
        # 格式1: {name: bool}
        if isinstance(val, bool):
            _CACHE[key] = {
                "categories": ["UNCATEGORIZED"],
                "startup": val
            }
        # 格式2: {name: {category: str, startup: bool}} → 转为列表
        elif isinstance(val, dict) and "category" in val and "categories" not in val:
            old_cat = val["category"]
            # 旧分类ID映射到新分类ID
            old_to_new = {
                "VIEW_3D": ["3D_VIEWPORT"],
                "OBJECT_SCENE": ["3D_VIEWPORT"],
                "MESH_EDIT": ["MESH_EDIT"],
                "SCULPT": ["SCULPT"],
                "IMAGE_EDITOR": ["IMAGE_EDITOR"],
                "UV_EDIT": ["UV_TEXTURE"],
                "UV_EDITOR": ["UV_TEXTURE"],
                "TEXTURE_PAINT": ["UV_TEXTURE"],
                "NODE_EDITOR": ["GEOMETRY_NODES"],
                "DOPESHEET_EDITOR": ["3D_VIEWPORT"],
                "TEXT_EDITOR": ["SYSTEM"],
                "POSE_MODE": ["POSE_MODE"],
                "OTHER": ["UNCATEGORIZED"],
                "UNCATEGORIZED": ["UNCATEGORIZED"],
            }
            new_cats = old_to_new.get(old_cat, ["UNCATEGORIZED"])
            _CACHE[key] = {
                "categories": new_cats,
                "startup": val.get("startup", False)
            }


def _infer_categories_from_bl_info(module_name: str) -> list:
    """根据插件的 bl_info category 自动推断 PMP 分类列表。

    读取插件的 bl_info 中的 category 字段，通过 CATEGORY_AUTO_MAP 映射表
    将 Blender 标准分类名转换为 PMP 内部分类ID列表。
    如果无法推断，默认归入 "UNCATEGORIZED" 分类。

    输入:
      module_name (str): 插件的模块名，如 "io_scene_fbx"
    输出:
      list - 分类ID列表，如 ["SYSTEM"] 或 ["UNCATEGORIZED"]
    """
    try:
        addon_utils.modules_refresh()
        for mod in addon_utils.modules():
            if mod.__name__ == module_name:
                info = addon_utils.module_bl_info(mod)
                bl_category = info.get("category", "").lower().strip()
                if bl_category in CATEGORY_AUTO_MAP:
                    # 过滤掉已隐藏/已删除的分类
                    from .data import is_category_hidden
                    valid_cats = [c for c in CATEGORY_AUTO_MAP[bl_category] if not is_category_hidden(c)]
                    if valid_cats:
                        return valid_cats
                    break
                break
    except Exception:
        pass
    return ["UNCATEGORIZED"]


def load():
    """从JSON文件加载配置到内存缓存。

    如果配置文件存在则读取并解析，同时执行旧格式迁移；
    如果文件不存在或解析失败，则初始化为空字典。

    输入: 无
    输出: 无（修改全局 _CACHE）
    """
    global _CACHE
    path = _get_config_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _CACHE = json.load(f)
                _migrate_legacy_format()
        except Exception:
            _CACHE = {}
    else:
        _CACHE = {}


def save():
    """将内存缓存中的配置写入JSON文件。

    自动创建配置目录（如不存在），以UTF-8编码、缩进2格写入。
    写入失败时静默忽略（不抛出异常）。

    输入: 无（读取全局 _CACHE）
    输出: 无
    """
    try:
        path = _get_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _ensure_addon_entry(module_name: str):
    """确保插件在配置中有条目，若不存在则自动创建并推断分类。

    当访问一个尚未配置的插件时，自动根据其 bl_info 推断分类，
    并初始化自启状态为 False。也初始化兼容性状态字段（"compatibility","last_error").

    输入:
      module_name (str): 插件模块名
    输出: 无（修改全局 _CACHE）
    """
    if module_name not in _CACHE:
        categories = _infer_categories_from_bl_info(module_name)
        _CACHE[module_name] = {
            "categories": categories,
            "startup": False,
            "compatibility": "unknown",
            "last_error": None,
        }
    else:
        # 兼容旧格式：如果存在但为布尔或缺少兼容字段，进行补足
        val = _CACHE[module_name]
        if isinstance(val, dict):
            if "compatibility" not in val:
                val.setdefault("compatibility", "unknown")
            if "last_error" not in val:
                val.setdefault("last_error", None)
        elif isinstance(val, bool):
            _CACHE[module_name] = {
                "categories": ["UNCATEGORIZED"],
                "startup": val,
                "compatibility": "unknown",
                "last_error": None,
            }


def get_compatibility(module_name: str) -> str:
    """获取插件兼容性状态：unknown/compatible/incompatible/requires_native

    保证返回字符串，若未配置则返回 'unknown' 并确保条目存在。
    """
    _ensure_addon_entry(module_name)
    info = _CACHE.get(module_name, {})
    return info.get("compatibility", "unknown")


def set_compatibility(module_name: str, status: str, last_error: str = None):
    """设置插件兼容性状态并保存。

    status 建议使用: 'unknown', 'compatible', 'incompatible', 'requires_native'
    last_error 可选，用于记录检测到的异常信息。
    """
    _ensure_addon_entry(module_name)
    _CACHE[module_name]["compatibility"] = status
    _CACHE[module_name]["last_error"] = last_error
    save()


def get_startup(module_name: str) -> bool:
    """获取插件是否设置为随 Blender 自启。

    兼容旧格式：如果缓存值为布尔类型（格式1），直接返回该值。

    输入:
      module_name (str): 插件模块名
    输出:
      bool - True 表示自启开启，False 表示关闭
    """
    _ensure_addon_entry(module_name)
    value = _CACHE[module_name]
    if isinstance(value, bool):
        return value
    return value.get("startup", False)


def set_startup(module_name: str, value: bool):
    """设置插件是否随 Blender 自启，并立即持久化保存。

    输入:
      module_name (str): 插件模块名
      value (bool): True 开启自启，False 关闭自启
    输出: 无
    """
    _ensure_addon_entry(module_name)
    _CACHE[module_name]["startup"] = value
    save()


def get_categories(module_name: str) -> list:
    """获取插件所属的分类ID列表。

    自动过滤掉已隐藏/已删除的分类，确保返回的分类都是有效的。
    如果过滤后分类列表为空，则自动归入 UNCATEGORIZED。

    输入:
      module_name (str): 插件模块名
    输出:
      list - 分类ID列表，如 ["3D_VIEWPORT", "MESH_EDIT"]，至少包含一个分类
    """
    _ensure_addon_entry(module_name)
    cats = _CACHE[module_name].get("categories", ["UNCATEGORIZED"])
    # 过滤掉已隐藏/已删除的分类
    from .data import is_category_hidden
    valid_cats = [c for c in cats if not is_category_hidden(c)]
    if not valid_cats:
        valid_cats = ["UNCATEGORIZED"]
    # 如果过滤后有变化，同步更新缓存
    if valid_cats != cats:
        _CACHE[module_name]["categories"] = valid_cats
        save()
    return valid_cats


def set_categories(module_name: str, categories: list):
    """设置插件所属的分类ID列表，并立即持久化保存。

    输入:
      module_name (str): 插件模块名
      categories (list): 分类ID列表，如 ["3D_VIEWPORT", "SYSTEM"]
    输出: 无
    """
    _ensure_addon_entry(module_name)
    _CACHE[module_name]["categories"] = categories
    save()


def add_category(module_name: str, category: str):
    """为插件添加一个分类（如果该分类尚未存在则追加），并持久化保存。

    输入:
      module_name (str): 插件模块名
      category (str): 要添加的分类ID
    输出: 无
    """
    _ensure_addon_entry(module_name)
    cats = _CACHE[module_name].get("categories", [])
    if category not in cats:
        cats.append(category)
        _CACHE[module_name]["categories"] = cats
        save()


def remove_category(module_name: str, category: str):
    """从插件的分类列表中移除一个分类，并持久化保存。

    如果移除后分类列表为空，则自动归入 "UNCATEGORIZED" 分类（至少保留一个）。

    输入:
      module_name (str): 插件模块名
      category (str): 要移除的分类ID
    输出: 无
    """
    _ensure_addon_entry(module_name)
    cats = _CACHE[module_name].get("categories", [])
    if category in cats:
        cats.remove(category)
        if not cats:  # 至少保留一个分类
            cats = ["UNCATEGORIZED"]
        _CACHE[module_name]["categories"] = cats
        save()


def toggle_category(module_name: str, category: str):
    """切换插件是否属于某分类（存在则移除，不存在则添加），并持久化保存。

    至少保留一个分类：如果只剩一个分类，则不允许移除。

    输入:
      module_name (str): 插件模块名
      category (str): 要切换的分类ID
    输出: 无
    """
    _ensure_addon_entry(module_name)
    cats = _CACHE[module_name].get("categories", [])
    if category in cats:
        if len(cats) > 1:  # 至少保留一个分类
            cats.remove(category)
    else:
        cats.append(category)
    _CACHE[module_name]["categories"] = cats
    save()


def has_user_config() -> bool:
    """检查是否存在用户配置（配置缓存非空且至少有一个插件条目）。

    用于判断是否为首次使用：
    - 首次使用时，配置缓存为空或没有任何插件条目
    - 非首次使用时，配置缓存中至少有一个插件的配置

    输入: 无
    输出:
      bool - 存在用户配置返回 True，否则返回 False
    """
    # 配置缓存中有至少一个插件条目视为已有用户配置
    return len(_CACHE) > 0


def get_all_addons() -> dict:
    """获取所有已配置插件的配置字典副本。

    输入: 无
    输出:
      dict - 键为模块名，值为配置字典的浅拷贝
    """
    return _CACHE.copy()


def get_addons_by_category(category: str) -> list:
    """获取指定分类下的所有插件模块名列表（插件可属于多个分类）。

    输入:
      category (str): 分类ID，如 "3D_VIEWPORT"
    输出:
      list - 属于该分类的插件模块名列表
    """
    result = []
    for module_name, info in _CACHE.items():
        if isinstance(info, dict) and category in info.get("categories", []):
            result.append(module_name)
    return result