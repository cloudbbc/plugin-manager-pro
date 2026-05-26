# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: menus.py
# 模块作用: 动态菜单生成系统，为每个分类生成菜单类，
#           支持插件的快速加载/停用操作及设置菜单。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

"""动态菜单生成系统：分类菜单 + 插件加载/停用。

主要功能:
  - _get_all_addons_by_category: 获取指定分类下的所有已安装插件
  - get_addon_display_info: 获取插件显示名称
  - draw_menu_items: 为指定分类动态生成菜单项
  - _create_category_menu_class: 动态创建分类菜单类
  - build_menu_classes: 构建所有菜单类（内置+自定义+设置）
  - _draw_settings_menu: 设置菜单绘制
  - menu_classes: 导出的菜单类列表
"""

import bpy
import addon_utils
from . import data, config


def _get_all_addons_by_category(category_id):
    """获取指定分类下的所有已安装插件模块名列表（无论是否加载，支持多分类）。

    遍历所有已安装插件，筛选属于指定分类的插件，
    自动跳过自身插件。

    输入:
      category_id (str): 分类ID，如 "3D_VIEWPORT"
    输出:
      list - 插件模块名列表
    """
    result = []
    addon_utils.modules_refresh()
    for mod in addon_utils.modules():
        module_name = mod.__name__
        if module_name == __package__ or module_name.startswith(__package__ + "."):
            continue
        cats = config.get_categories(module_name)
        if category_id in cats:
            result.append(module_name)
    return result


def get_addon_display_info(module_name: str) -> str:
    """获取插件的显示名称（从 bl_info 中读取 name 字段）。

    输入:
      module_name (str): 插件模块名
    输出:
      str - 插件显示名称，读取失败则返回模块名
    """
    try:
        for mod in addon_utils.modules():
            if mod.__name__ == module_name:
                info = addon_utils.module_bl_info(mod)
                return info.get("name", module_name)
    except Exception:
        pass
    return module_name


def draw_menu_items(self, context, category_id):
    """为指定分类动态生成菜单项。

    显示分类标题，列出该分类下的所有插件，
    每个插件显示名称和启用/停用按钮：
    - RIGHTARROW = 未启用（点击启用）
    - PAUSE = 已启用（点击停用）
    底部提供刷新按钮。

    输入:
      self - 菜单实例
      context - Blender 上下文
      category_id (str): 分类ID
    输出: 无
    """
    layout = self.layout
    addons_in_category = _get_all_addons_by_category(category_id)

    # 显示分类标题
    cat_label = category_id
    for cat in data.get_all_categories():
        if cat['id'] == category_id:
            cat_label = cat['label']
            break

    if not addons_in_category:
        layout.label(text=f"{cat_label}：无插件", icon='BLANK1')
    else:
        layout.label(text=f"{cat_label}：", icon='BLANK1')
        layout.separator()
        for module_name in addons_in_category:
            display_name = get_addon_display_info(module_name)

            try:
                from .operators import _is_addon_enabled
                is_enabled = _is_addon_enabled(module_name)
            except Exception:
                is_enabled = False

            # 一行：插件名称 + 图标表示启用/停用
            if is_enabled:
                op = layout.operator("pmp.unload_addon", text=display_name, icon='PAUSE')
            else:
                op = layout.operator("pmp.load_addon", text=display_name, icon='RIGHTARROW')
            op.module_name = module_name
            op.display_name = display_name

    layout.separator()
    layout.operator("pmp.refresh_addon_list", text="刷新", icon='FILE_REFRESH')


# --- 动态生成分类菜单类 ---
_menu_class_cache = []


def _create_category_menu_class(cat_id, cat_label, cat_icon):
    """动态创建一个分类菜单类（bpy.types.Menu 子类）。

    使用 type() 动态生成菜单类，draw 方法通过闭包捕获分类ID，
    调用 draw_menu_items 绘制菜单内容。

    输入:
      cat_id (str): 分类ID
      cat_label (str): 分类显示名称
      cat_icon (str): 分类图标标识符
    输出:
      type - 动态创建的 Menu 子类
    """
    def _make_draw(cid):
        def draw(self, context):
            draw_menu_items(self, context, cid)
        return draw

    cls = type(
        f"VIEW3D_MT_pmp_cat_{cat_id}",
        (bpy.types.Menu,),
        {
            "bl_idname": f"VIEW3D_MT_pmp_cat_{cat_id}",
            "bl_label": cat_label,
            "draw": _make_draw(cat_id),
        }
    )
    return cls


def build_menu_classes():
    """构建所有菜单类（内置+自定义分类+设置菜单），同时更新 menu_classes。

    先注销旧的菜单类，再为每个分类创建菜单类，
    最后创建设置菜单类。结果同步更新到 menu_classes 列表。

    输入: 无
    输出:
      list - 菜单类列表
    """
    global _menu_class_cache, menu_classes
    # 先注销旧的
    for cls in _menu_class_cache:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _menu_class_cache = []

    # 为每个分类创建菜单
    for cat in data.get_all_categories():
        # 跳过不可删除分类（如"所有插件"、"无分类插件"），它们没有对应的菜单
        if cat.get('undeletable'):
            continue
        cls = _create_category_menu_class(cat['id'], cat['label'], cat['icon'])
        _menu_class_cache.append(cls)

    # 设置菜单：刷新 + 提示
    settings_cls = type(
        "VIEW3D_MT_pmp_settings",
        (bpy.types.Menu,),
        {
            "bl_idname": "VIEW3D_MT_pmp_settings",
            "bl_label": "PMP 设置",
            "draw": lambda self, context: _draw_settings_menu(self, context),
        }
    )
    _menu_class_cache.append(settings_cls)

    # 同步更新 menu_classes
    menu_classes = list(_menu_class_cache)
    return _menu_class_cache


def _draw_settings_menu(self, context):
    """绘制设置菜单内容：设置面板、分类管理和刷新按钮。

    输入:
      self - 菜单实例
      context - Blender 上下文
    输出: 无
    """
    layout = self.layout
    layout.operator("pmp.open_settings", text="设置面板", icon='PLUGIN')
    layout.operator("pmp.open_category_management", text="分类管理", icon='PREFERENCES')
    layout.separator()
    layout.operator("pmp.refresh_addon_list", text="刷新插件列表", icon='FILE_REFRESH')


# 导出菜单类列表（初始为空，在register时由build_menu_classes构建）
menu_classes = []  # type: list
