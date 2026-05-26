# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: header.py
# 模块作用: 3D视口Header绘制模块，在视口标题栏右侧绘制分类图标按钮，
#           点击后弹出该分类下的插件列表对话框，支持快速加载/停用插件。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

"""3D视口Header绘制：在视口标题栏右侧绘制分类图标，点击弹出插件列表对话框。

主要功能:
  - _get_addons_for_category: 获取指定分类下的所有插件
  - _create_popup_operator: 为每个分类动态创建弹出对话框操作符
  - build_popup_operators: 构建所有弹出菜单操作符
  - _draw_category_icons: 绘制分类图标按钮行
  - draw_pmp_header_icons: 挂载到VIEW3D_HT_header的绘制回调
  - register / unregister: 注册/注销模块
"""

import bpy
import addon_utils
from bpy.types import Operator
from . import data, config


# ──────────────────────────────────────────────
# 弹出插件列表对话框操作符（每个分类一个）
# ──────────────────────────────────────────────
_popup_op_cache = []


def _get_addons_for_category(category_id):
    """获取指定分类下的所有插件信息列表。

    遍历所有已安装插件，筛选属于指定分类的插件，
    返回包含模块名、显示名和启用状态的元组列表。
    自动跳过自身插件。
    
    注意：不再隐藏自启插件，所有插件都显示在分类列表中。

    输入:
      category_id (str): 分类ID，如 "3D_VIEWPORT"
    输出:
      list - [(module_name, display_name, is_enabled), ...] 插件信息元组列表
    """
    result = []
    addon_utils.modules_refresh()
    for mod in addon_utils.modules():
        module_name = mod.__name__
        if module_name == __package__ or module_name.startswith(__package__ + "."):
            continue
        # 不再跳过自启插件，所有插件都显示
        cats = config.get_categories(module_name)
        if category_id in cats:
            try:
                info = addon_utils.module_bl_info(mod)
                raw_name = info.get("name", module_name)
            except Exception:
                raw_name = module_name
            # 优先使用翻译后的名称，与设置面板保持一致
            translated = bpy.app.translations.pgettext(raw_name) if hasattr(bpy.app.translations, "pgettext") else raw_name
            display_name = translated if translated and translated != raw_name else raw_name
            
            # 【关键修复】实时从 preferences.addons 检测状态，确保准确性
            # 不依赖缓存，直接从 Blender 官方权威数据源读取
            is_enabled = False
            try:
                for addon in bpy.context.preferences.addons:
                    if addon.module == module_name:
                        is_enabled = True
                        break
            except Exception as e:
                _debug_log(f"Error checking addon status for {module_name}: {e}")
            
            result.append((module_name, display_name, is_enabled))
    return result


def _create_popup_operator(cat_id, cat_label, cat_tooltip):
    """为每个分类动态创建一个弹出插件列表对话框的操作符类。

    使用 type() 动态生成 Operator 子类，通过闭包捕获分类ID、标签和提示。
    操作符调用时弹出对话框，显示该分类下的插件列表及加载/停用按钮。

    输入:
      cat_id (str): 分类ID
      cat_label (str): 分类显示名称
      cat_tooltip (str): 分类提示文本
    输出:
      type - 动态创建的 Operator 子类
    """
    class_name = f"PMP_OT_popup_{cat_id.lower()}"

    def execute_popup(self, context):
        return {'FINISHED'}

    def invoke_popup(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=230)

    def draw_popup(self, context):
        layout = self.layout
        addons = _get_addons_for_category(cat_id)
        # Title already shown by the dialog header (bl_label). Add a small reset button aligned right.
        top_row = layout.row()
        top_row.alignment = 'RIGHT'
        top_row.operator("pmp.restore_initial_addon_system", text="", icon='FILE_REFRESH', emboss=False)

        if not addons:
            layout.label(text="该分类下暂无插件", icon='INFO')
            return

        layout.separator()
        for module_name, display_name, is_enabled in addons:
            row = layout.row(align=True)
            if is_enabled:
                op = row.operator("pmp.unload_addon", text=display_name, icon='PAUSE')
            else:
                op = row.operator("pmp.load_addon", text=display_name, icon='RIGHTARROW')
            op.module_name = module_name
            op.display_name = display_name

    cls = type(
        class_name,
        (Operator,),
        {
            "bl_idname": f"pmp.popup_{cat_id.lower()}",
            "bl_label": cat_label,
            "bl_description": cat_tooltip,
            "bl_options": {'INTERNAL'},
            "execute": execute_popup,
            "invoke": invoke_popup,
            "draw": draw_popup,
        }
    )
    return cls


def build_popup_operators():
    """构建所有分类的弹出菜单操作符，先注销旧的操作符再重新创建。

    遍历所有分类，为每个分类调用 _create_popup_operator 创建操作符类，
    结果缓存到 _popup_op_cache 供注册使用。

    输入: 无
    输出:
      list - 弹出操作符类列表
    """
    global _popup_op_cache
    for cls in _popup_op_cache:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _popup_op_cache = []
    for cat in data.get_all_categories():
        # 跳过不可删除分类（如"所有插件"、"无分类插件"），它们没有对应的弹出菜单
        if cat.get('undeletable'):
            continue
        tooltip = cat.get('tooltip', cat['label'])
        cls = _create_popup_operator(cat['id'], cat['label'], tooltip)
        _popup_op_cache.append(cls)
    return _popup_op_cache


# ──────────────────────────────────────────────
# 绘制函数
# ──────────────────────────────────────────────

def _draw_category_icons(layout):
    """在指定布局中绘制分类图标按钮行。

    从左到右依次绘制 "PMP:" 标签、各分类图标按钮和设置菜单按钮。
    点击分类图标弹出该分类的插件列表对话框。

    输入:
      layout - Blender UI 布局对象
    输出: 无
    """
    row = layout.row(align=True)
    # PMP主按钮：点击弹出设置面板
    row.operator("pmp.open_settings", text="", icon='PLUGIN')
    row.separator()
    for cat in data.get_all_categories():
        # 跳过不可删除分类（如"所有插件"、"无分类插件"），它们没有对应的Header图标
        if cat.get('undeletable'):
            continue
        op_idname = f"pmp.popup_{cat['id'].lower()}"
        if hasattr(bpy.types, f"PMP_OT_popup_{cat['id'].lower()}"):
            row.operator(
                op_idname,
                text="",
                icon=cat['icon'],
                emboss=False,
            )
        else:
            row.label(text="", icon=cat['icon'])
    # 分类管理按钮
    row.operator("pmp.open_category_management", text="", icon='PREFERENCES')
    # 关于/打赏按钮
    row.operator("pmp.open_about", text="", icon='HELP')


def draw_pmp_header_icons(self, context):
    """挂载到 VIEW3D_HT_header 的绘制回调函数。

    在3D视口标题栏右侧添加分隔符和分类图标按钮。

    输入:
      self - 面板实例
      context - Blender 上下文
    输出: 无
    """
    layout = self.layout
    layout.separator_spacer()
    _draw_category_icons(layout)


def register():
    """注册模块：注册所有弹出操作符并挂载Header绘制回调。

    输入: 无
    输出: 无
    """
    # 注册弹出操作符
    for cls in _popup_op_cache:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    bpy.types.VIEW3D_HT_header.append(draw_pmp_header_icons)


def unregister():
    """注销模块：移除Header绘制回调并注销所有弹出操作符。

    输入: 无
    输出: 无
    """
    try:
        bpy.types.VIEW3D_HT_header.remove(draw_pmp_header_icons)
    except Exception:
        pass
    for cls in reversed(_popup_op_cache):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
