# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: config_panel.py
# 模块作用: PMP 弹窗面板模块，提供插件列表、自启切换、
#           分类管理、图标选择等完整的UI界面。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

"""PMP 弹窗面板：插件列表 + 自启切换 + 分类管理 + 图标选择。

主要功能:
  - PMP_addon_item: 插件列表项属性组
  - PMP_UL_addon_list: 插件UI列表
  - PMP_OT_clear_search / PMP_OT_filter_all: 搜索和过滤操作符
  - build_filter_operators: 动态构建分类过滤操作符
  - PMP_OT_open_settings: 设置面板弹窗（搜索+过滤+列表+详情）
  - PMP_OT_pick_icon / PMP_OT_pick_icon_select: 图标选择弹窗
  - PMP_OT_rename_category: 分类重命名
  - PMP_OT_open_category_management: 分类管理弹窗
  - refresh_addon_list: 刷新插件列表数据
  - register_properties / unregister_properties: 属性注册/注销
  - register / unregister: 模块注册/注销
"""

import bpy
import addon_utils
import os
from bpy.types import PropertyGroup, Operator, UIList
from bpy.props import (
    StringProperty, IntProperty, BoolProperty,
    CollectionProperty, EnumProperty,
)
from . import config, data


# ---------- Property Group ----------

class PMP_addon_item(PropertyGroup):
    """插件列表项属性组，存储单个插件在UI列表中的显示数据。

    属性:
      name: 插件模块名（唯一标识）
      display_name: 插件显示名称
      categories: 所属分类ID列表（逗号分隔）
      is_enabled: 当前会话是否已启用
      startup: 是否设置为随Blender自启
      selected: 是否被选中（多选支持）
    """
    name: StringProperty(default="")
    display_name: StringProperty(default="")
    categories: StringProperty(default="")
    is_enabled: BoolProperty(default=False)
    startup: BoolProperty(default=False)
    selected: BoolProperty(default=False, description="多选状态")


# ---------- UI List ----------

class PMP_UL_addon_list(UIList):
    """插件UI列表，自定义绘制每个插件项的显示方式。

    每行显示：勾选框 + 自启图标按钮 + 插件名称 + 启用/停用按钮。
    选中的行通过背景色高亮显示。
    支持通过 filter_items 根据搜索文本在UI层面过滤，无需重建列表数据。
    """
    use_filter_show = True

    def draw_item(self, context, layout, data_obj, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            # 勾选框：用操作符实现可点击的打勾方块
            check_icon = 'CHECKBOX_HLT' if item.selected else 'CHECKBOX_DEHLT'
            op = row.operator("pmp.toggle_select_item", text="", icon=check_icon, emboss=False)
            op.item_index = index
            # 自启图标
            su_icon = 'RADIOBUT_ON' if item.startup else 'PLAY'
            op = row.operator("pmp.toggle_startup", text="", icon=su_icon, emboss=False)
            op.module_name = item.name
            op.display_name = item.display_name
            # 插件名称（截断过长名称，选中时加前缀标记）
            display = item.display_name
            if len(display) > 28:
                display = display[:25] + "..."
            row.label(text=display)
            # 启用状态图标（仅显示，不可点击）
            if item.is_enabled:
                row.label(text="", icon='CHECKMARK')
            else:
                row.label(text="", icon='BLANK1')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.display_name)

    def draw_filter(self, context, layout):
        """在列表过滤区域绘制全选/取消全选按钮。"""
        row = layout.row(align=True)
        row.operator("pmp.select_all", text="", icon='CHECKBOX_HLT')
        row.operator("pmp.deselect_all", text="", icon='CHECKBOX_DEHLT')


# ---------- Operators ----------

class PMP_OT_confirm_search(Operator):
    """确认搜索：让搜索输入框失焦，触发搜索刷新。"""
    bl_idname = "pmp.confirm_search"
    bl_label = "搜索"
    bl_description = "确认搜索关键字"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # 无需额外操作，点击按钮时输入框已失焦，update回调自动触发刷新
        return {'FINISHED'}


class PMP_OT_clear_search(Operator):
    """清空搜索文本。"""
    bl_idname = "pmp.clear_search"
    bl_label = "Clear"
    bl_description = "清空搜索"

    def execute(self, context):
        context.scene.pmp_search_text = ""
        return {'FINISHED'}


class PMP_OT_filter_all(Operator):
    """显示所有插件，不进行分类过滤。"""
    bl_idname = "pmp.filter_all"
    bl_label = "全部"
    bl_description = "显示所有插件，不进行分类过滤"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.pmp_filter_category = 'ALL'
        refresh_addon_list(context)
        return {'FINISHED'}


# ──────────────────────────────────────────────
# 动态分类过滤操作符
# ──────────────────────────────────────────────
_filter_op_cache = []


def _create_filter_operator(cat_id, cat_label, cat_tooltip):
    """为每个分类动态创建一个过滤操作符类。

    使用 type() 动态生成 Operator 子类，通过闭包捕获分类ID，
    执行时设置过滤分类并刷新列表。

    输入:
      cat_id (str): 分类ID
      cat_label (str): 分类显示名称
      cat_tooltip (str): 分类提示文本
    输出:
      type - 动态创建的 Operator 子类
    """
    class_name = f"PMP_OT_filter_{cat_id.lower()}"

    # 使用闭包捕获 cat_id，避免 StringProperty 在 type() 中的问题
    def execute_filter(self, context):
        context.scene.pmp_filter_category = cat_id
        refresh_addon_list(context)
        return {'FINISHED'}

    cls = type(
        class_name,
        (Operator,),
        {
            "bl_idname": f"pmp.filter_{cat_id.lower()}",
            "bl_label": cat_label,
            "bl_description": cat_tooltip,
            "bl_options": {'INTERNAL'},
            "execute": execute_filter,
        }
    )
    return cls


def _filter_by_category(self, context):
    """分类过滤操作符的执行回调（备用，当前使用闭包方式）。

    输入:
      self - 操作符实例
      context - Blender 上下文
    输出:
      set - {'FINISHED'}
    """
    context.scene.pmp_filter_category = self.category_id
    refresh_addon_list(context)
    return {'FINISHED'}


def build_filter_operators():
    """构建所有分类的过滤操作符，先注销旧的操作符再重新创建。

    遍历所有分类，为每个分类调用 _create_filter_operator 创建操作符类，
    结果缓存到 _filter_op_cache 供注册使用。

    输入: 无
    输出:
      list - 过滤操作符类列表
    """
    global _filter_op_cache
    for cls in _filter_op_cache:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _filter_op_cache = []
    for cat in data.get_all_categories():
        tooltip = cat.get('tooltip', cat['label'])
        cls = _create_filter_operator(cat['id'], cat['label'], tooltip)
        _filter_op_cache.append(cls)
    return _filter_op_cache


# ---------- 主面板 ----------

class PMP_OT_open_settings(Operator):
    """PMP设置面板：搜索栏 + 分类过滤 + 插件列表 + 选中插件详情 + 分类管理。

    点击Header上的PMP图标或设置按钮弹出，
    提供插件的搜索、分类过滤、自启切换、启用/停用和分类归属管理。
    """
    bl_idname = "pmp.open_settings"
    bl_label = "Plugin Manager Pro"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 搜索栏（确认按钮用于让输入框失焦，触发update回调刷新列表）
        row = layout.row(align=True)
        row.prop(scene, "pmp_search_text", text="", icon='VIEWZOOM')
        row.operator("pmp.confirm_search", text="", icon='CHECKMARK')
        row.operator("pmp.clear_search", text="", icon='X')

        # 分类过滤（只显示图标，节省空间）
        current_filter = scene.pmp_filter_category
        row = layout.row(align=True)
        # 全部按钮
        if current_filter == 'ALL':
            row.label(text="", icon='LAYER_ACTIVE')
        else:
            op = row.operator("pmp.filter_all", text="", icon='LAYER_USED')
        # 各分类按钮（只显示图标）
        for cat in data.get_all_categories():
            op_idname = f"pmp.filter_{cat['id'].lower()}"
            if not hasattr(bpy.types, f"PMP_OT_filter_{cat['id'].lower()}"):
                continue
            if current_filter == cat['id']:
                row.label(text="", icon=cat['icon'] + '_SEL' if data.is_icon_valid(cat['icon'] + '_SEL') else cat['icon'])
            else:
                op = row.operator(op_idname, text="", icon=cat['icon'])

        # 插件列表
        row = layout.row()
        row.template_list(
            "PMP_UL_addon_list", "",
            scene, "pmp_addon_items",
            scene, "pmp_addon_index",
            rows=10,
        )

        # 分类设置区域
        idx = scene.pmp_addon_index
        items = scene.pmp_addon_items
        selected_count = sum(1 for item in items if item.selected)

        if selected_count > 0:
            # 有打勾的插件：批量分类模式
            box = layout.box()
            col = box.column(align=True)
            col.label(text=f"✓ 已选中 {selected_count} 个插件", icon='CHECKMARK')
            col.separator()
            # 分类设置标题
            col.label(text="设置分类:", icon='GROUP')
            # 收集所有选中插件的分类，用于判断depress状态
            selected_cats = set()
            for item in items:
                if item.selected:
                    for c in config.get_categories(item.name):
                        selected_cats.add(c)
            for cat in data.get_all_categories():
                if cat.get('undeletable'):
                    continue
                is_in_cat = cat['id'] in selected_cats
                row = col.row(align=True)
                op = row.operator(
                    "pmp.batch_add_category",
                    text=cat['label'],
                    icon=cat['icon'],
                    depress=is_in_cat,
                )
                op.category_id = cat['id']
                # 重置按钮（仅影响此分类），图标按钮无文本
                reset_op = row.operator("pmp.reset_addons_category", text="", icon='FILE_REFRESH', emboss=False)
                reset_op.category_id = cat['id']
            col.separator()
            row = col.row(align=True)
            row.operator("pmp.uncategorize", text="取消分类", icon='X')
        elif 0 <= idx < len(items):
            # 仅高亮单个插件（未打勾）：单插件分类模式
            item = items[idx]
            box = layout.box()
            col = box.column(align=True)
            col.label(text=item.display_name, icon='INFO')
            col.separator()
            col.label(text="设置分类:", icon='GROUP')
            # 显示当前插件的分类归属
            current_cats = set(config.get_categories(item.name))
            for cat in data.get_all_categories():
                if cat.get('undeletable'):
                    continue
                is_in_cat = cat['id'] in current_cats
                row = col.row(align=True)
                op = row.operator(
                    "pmp.batch_add_category",
                    text=cat['label'],
                    icon=cat['icon'],
                    depress=is_in_cat,
                )
                op.category_id = cat['id']
                reset_op = row.operator("pmp.reset_addons_category", text="", icon='FILE_REFRESH', emboss=False)
                reset_op.category_id = cat['id']
            col.separator()
            row = col.row(align=True)
            op = row.operator("pmp.uncategorize", text="取消分类", icon='X')

        # 底部操作
        row = layout.row(align=True)
        row.operator("pmp.refresh_addon_list", text="刷新", icon='FILE_REFRESH')
        row.operator("pmp.open_category_management", text="分类管理", icon='PREFERENCES')


# ---------- 分类管理面板 ----------

# ──────────────────────────────────────────────
# 图标选择弹窗（使用自建图标库，按分组展示）
# ──────────────────────────────────────────────
_pick_icon_op_cache = []



# 全局临时变量：记录图标选择器中待确认的图标
_pending_icon = None


class PMP_OT_pick_icon(Operator):
    """从图标库选择图标的弹窗操作符。

    弹出对话框显示所有可用图标的网格，点击选中后确认生效。
    支持通过图标名称直接输入和网格点击两种方式选择。
    """
    bl_idname = "pmp.pick_icon"
    bl_label = "选择图标"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()
    icon_name: StringProperty(name="图标名称")

    @classmethod
    def description(cls, context, properties):
        from . import data as cat_data
        cat = cat_data.get_category_by_id(properties.category_id)
        if cat:
            return f"点击修改图标\n名称: {cat['label']}\nID: {cat['id']}"
        return "从图标库中选择一个图标"

    def execute(self, context):
        global _pending_icon
        # 确认时：如果有待确认图标则保存，否则保存 icon_name
        from .data import set_category_icon, validate_icon
        if _pending_icon is not None:
            icon = validate_icon(_pending_icon)
            _pending_icon = None
        else:
            icon = validate_icon(self.icon_name)
        set_category_icon(self.category_id, icon)
        from .operators import _rebuild_dynamic, _redraw_areas
        _rebuild_dynamic()
        _redraw_areas(context)
        return {'FINISHED'}

    def cancel(self, context):
        global _pending_icon
        # 弹窗被取消（ESC/点击外部）时，如果有待确认图标也保存
        if _pending_icon is not None:
            from .data import set_category_icon, validate_icon
            icon = validate_icon(_pending_icon)
            set_category_icon(self.category_id, icon)
            from .operators import _rebuild_dynamic, _redraw_areas
            _rebuild_dynamic()
            _redraw_areas(context)
            _pending_icon = None

    def invoke(self, context, event):
        global _pending_icon
        _pending_icon = None
        cat = data.get_category_by_id(self.category_id)
        if cat:
            self.icon_name = cat['icon']
        else:
            self.icon_name = "SCRIPT"
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        global _pending_icon
        layout = self.layout
        # 显示待确认图标或当前图标
        display_icon = _pending_icon if _pending_icon else self.icon_name
        if not display_icon:
            display_icon = "BLANK1"
        safe_icon = display_icon if data.is_icon_valid(display_icon) else 'BLANK1'
        layout.label(text="已选: " + display_icon, icon=safe_icon)
        layout.separator()
        # 图标网格，点击选中（通过 pick_icon_select 设置 _pending_icon）
        grid = layout.grid_flow(row_major=True, columns=12, even_columns=True)
        for icon_name in data.get_all_icons_list():
            op = grid.operator("pmp.pick_icon_select", text="", icon=icon_name,
                               depress=(icon_name == display_icon))
            op.icon_name = icon_name
        layout.separator()
        layout.prop(self, "icon_name", text="当前图标名称:")


class PMP_OT_pick_icon_select(Operator):
    """在图标选择弹窗内选中一个图标（设置待确认图标，确认后生效）。"""
    bl_idname = "pmp.pick_icon_select"
    bl_label = "选择"
    bl_options = {'INTERNAL'}
    icon_name: StringProperty()

    def execute(self, context):
        global _pending_icon
        _pending_icon = self.icon_name
        return {'FINISHED'}



def build_pick_icon_operators():
    """构建图标选择操作符（已改为统一弹窗方式，此函数保留兼容性）。

    清空旧的缓存列表，当前无需动态创建操作符。

    输入: 无
    输出:
      list - 空列表
    """
    global _pick_icon_op_cache
    for cls in _pick_icon_op_cache:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _pick_icon_op_cache = []
    return _pick_icon_op_cache


class PMP_OT_rename_category(Operator):
    """重命名分类，弹出对话框输入新名称。"""
    bl_idname = "pmp.rename_category"
    bl_label = "重命名分类"
    bl_description = "输入新名称"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()
    new_label: StringProperty(
        name="新名称",
        description="输入分类的新名称",
        default="",
    )

    def execute(self, context):
        from .data import set_category_label
        label = self.new_label.strip()
        if not label:
            self.report({'WARNING'}, "名称不能为空")
            return {'CANCELLED'}
        set_category_label(self.category_id, label)
        from .operators import _rebuild_dynamic
        _rebuild_dynamic()
        return {'FINISHED'}

    def invoke(self, context, event):
        # 预填当前名称
        cat = data.get_category_by_id(self.category_id)
        if cat:
            self.new_label = cat['label']
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_label", text="新名称")


class PMP_OT_open_category_management(Operator):
    """分类管理弹窗：分类列表 + 排序/图标/重命名/删除 + 新增分类。

    从设置面板中点击"分类管理"按钮弹出。
    """
    bl_idname = "pmp.open_category_management"
    bl_label = "分类管理"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        all_cats = data.get_all_categories(include_hidden=True)

        # 分类列表
        col = layout.column(align=True)
        for i, cat in enumerate(all_cats):
            box = col.box()

            # 一行：序号+名称 + 图标(可修改) + 改名 + 上调 + 下调 + 删除
            row = box.row(align=True)

            # 序号+名称
            row.label(text=f"{i+1}. {cat['label']}")

            # 图标按钮：直接显示分类图标，点击可修改
            op = row.operator("pmp.pick_icon", text="", icon=cat['icon'])
            op.category_id = cat['id']

            # 改名按钮
            op = row.operator("pmp.rename_category", text="", icon='OUTLINER_DATA_FONT')
            op.category_id = cat['id']

            # 上调按钮
            op = row.operator("pmp.move_category_up", text="", icon='TRIA_UP')
            op.category_id = cat['id']

            # 下调按钮
            op = row.operator("pmp.move_category_down", text="", icon='TRIA_DOWN')
            op.category_id = cat['id']

            # 删除按钮（UNCATEGORIZED 不可删除）
            if cat['id'] != 'UNCATEGORIZED':
                op = row.operator("pmp.remove_category", text="", icon='X')
                op.category_id = cat['id']

        # 重置
        layout.separator()
        row = layout.row(align=True)
        row.operator("pmp.reset_addon_categories", text="重置插件分类", icon='PLUGIN')
        row.operator("pmp.reset_category_settings", text="重置分类设置", icon='SETTINGS')

        # 新增分类
        layout.separator()
        box = layout.box()
        col = box.column(align=True)
        col.label(text="新增分类:", icon='ADD')
        row = col.row(align=True)
        row.prop(scene, "pmp_new_cat_id", text="ID")
        row.prop(scene, "pmp_new_cat_label", text="名称")
        col.operator("pmp.add_custom_category", text="添加", icon='PLUS')


# ---------- 关于/打赏弹窗 ----------

# 收款码图片管理
_about_images_loaded = False


# 收款码图片 URL 列表
_TIP_IMAGE_URLS = [
    ("VX.jpg", "https://raw.githubusercontent.com/cloudbbc/plugin-manager-pro/main/Image/VX.jpg"),
]


def _load_about_images():
    """加载收款码图片到 Blender 数据库。

    优先从本地 Image 目录加载，如果本地不存在则从 GitHub 远程下载。
    如果已加载过则跳过，避免重复加载。

    输入: 无
    输出: list - 成功加载的 bpy.types.Image 列表
    """
    global _about_images_loaded
    images = []
    # 如果已加载过，直接返回已有图片
    if _about_images_loaded:
        try:
            return [img for img in bpy.data.images if img.name.startswith("PMP_ABOUT_")]
        except Exception:
            return images

    # 尝试从本地 Image 目录加载
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    image_dir = os.path.join(addon_dir, "Image")
    if not os.path.isdir(image_dir):
        for mod_path in addon_utils.module_paths():
            candidate = os.path.join(mod_path, "plugin_manager_pro", "Image")
            if os.path.isdir(candidate):
                image_dir = candidate
                break

    # 收集本地图片文件
    local_files = {}
    try:
        from .operators import _debug_log
    except Exception:
        def _debug_log(*a, **k):
            pass
    if os.path.isdir(image_dir):
        for fname in sorted(os.listdir(image_dir)):
            fpath = os.path.join(image_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.tif', '.tiff'):
                local_files[fname] = fpath

    # 如果本地没有图片，尝试从远程下载
    if not local_files:
        import tempfile
        temp_dir = os.path.join(tempfile.gettempdir(), "pmp_tip_images")
        os.makedirs(temp_dir, exist_ok=True)
        for fname, url in _TIP_IMAGE_URLS:
            temp_path = os.path.join(temp_dir, fname)
            # 如果临时目录已有缓存则直接用
            if os.path.isfile(temp_path):
                local_files[fname] = temp_path
                continue
            try:
                import urllib.request
                urllib.request.urlretrieve(url, temp_path)
                local_files[fname] = temp_path
            except Exception as e:
                _debug_log(f"Warning: Failed to download {fname}: {e}")

    # 加载图片到 Blender
    for fname, fpath in local_files.items():
        img_name = f"PMP_ABOUT_{fname}"
        try:
            if img_name in bpy.data.images:
                images.append(bpy.data.images[img_name])
                continue
        except Exception:
            pass
        try:
            img = bpy.data.images.load(fpath)
            img.name = img_name
            img.use_fake_user = True
            images.append(img)
        except Exception as e:
            _debug_log(f"Warning: Failed to load image {fname}: {e}")

    _about_images_loaded = True
    return images


def _unload_about_images():
    """卸载所有关于弹窗的收款码图片，释放资源。

    输入: 无
    输出: 无
    """
    global _about_images_loaded
    try:
        for img in bpy.data.images:
            if img.name.startswith("PMP_ABOUT_"):
                try:
                    img.use_fake_user = False
                    bpy.data.images.remove(img)
                except Exception:
                    pass
    except Exception:
        pass
    _about_images_loaded = False


class PMP_OT_open_readme(Operator):
    """用系统默认程序打开 help.html 帮助文档（包含收款码）。"""
    bl_idname = "pmp.open_readme"
    bl_label = "查看插件说明"
    bl_description = "打开 help.html 帮助文档（含打赏收款码）"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # 优先打开 help.html，如果不存在则回退到 README.md
        help_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help.html")
        
        if not os.path.exists(help_html_path):
            # 尝试在其他位置查找 help.html
            for mod_path in addon_utils.module_paths():
                candidate = os.path.join(mod_path, "plugin_manager_pro", "help.html")
                if os.path.exists(candidate):
                    help_html_path = candidate
                    break
        
        # 如果 help.html 不存在，回退到 README.md
        if not os.path.exists(help_html_path):
            readme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
            if not os.path.exists(readme_path):
                for mod_path in addon_utils.module_paths():
                    candidate = os.path.join(mod_path, "plugin_manager_pro", "README.md")
                    if os.path.exists(candidate):
                        readme_path = candidate
                        break
            help_html_path = readme_path
        
        if os.path.exists(help_html_path):
            try:
                import platform
                system = platform.system()
                if system == 'Windows':
                    os.startfile(help_html_path)
                elif system == 'Darwin':
                    import subprocess
                    subprocess.Popen(['open', help_html_path])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', help_html_path])
                
                if help_html_path.endswith('.html'):
                    self.report({'INFO'}, "已打开帮助文档（含收款码）")
                else:
                    self.report({'INFO'}, "已打开 README.md")
            except Exception as e:
                self.report({'ERROR'}, f"无法打开文件: {e}")
        else:
            self.report({'WARNING'}, "未找到帮助文档文件")
        return {'FINISHED'}


def _find_tip_image_path():
    """查找收款码图片文件路径。

    优先从本地 Image 目录查找，如果本地不存在则从 GitHub 远程下载到临时目录。

    输入: 无
    输出: str or None - 图片文件路径，找不到返回 None
    """
    # 尝试本地 Image 目录
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    image_dir = os.path.join(addon_dir, "Image")
    if not os.path.isdir(image_dir):
        for mod_path in addon_utils.module_paths():
            candidate = os.path.join(mod_path, "plugin_manager_pro", "Image")
            if os.path.isdir(candidate):
                image_dir = candidate
                break

    if os.path.isdir(image_dir):
        for fname in sorted(os.listdir(image_dir)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.tif', '.tiff'):
                return os.path.join(image_dir, fname)

    # 本地没有，从远程下载
    import tempfile
    temp_dir = os.path.join(tempfile.gettempdir(), "pmp_tip_images")
    os.makedirs(temp_dir, exist_ok=True)
    for fname, url in _TIP_IMAGE_URLS:
        temp_path = os.path.join(temp_dir, fname)
        if os.path.isfile(temp_path):
            return temp_path
        try:
            import urllib.request
            urllib.request.urlretrieve(url, temp_path)
            return temp_path
        except Exception as e:
            print(f"[PMP] Warning: Failed to download {fname}: {e}")

    return None


class PMP_OT_open_tip_image(Operator):
    """用系统默认程序打开收款码图片。"""
    bl_idname = "pmp.open_tip_image"
    bl_label = "打赏"
    bl_description = "打开收款码图片"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        img_path = _find_tip_image_path()
        if img_path and os.path.exists(img_path):
            try:
                import platform
                system = platform.system()
                if system == 'Windows':
                    os.startfile(img_path)
                elif system == 'Darwin':
                    import subprocess
                    subprocess.Popen(['open', img_path])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', img_path])
                self.report({'INFO'}, "已打开收款码图片")
            except Exception as e:
                self.report({'ERROR'}, f"无法打开图片: {e}")
        else:
            self.report({'WARNING'}, "未找到收款码图片")
        return {'FINISHED'}


def draw_about(operator_instance, context):
    """绘制关于/打赏弹窗内容。

    显示版本信息、打赏按钮（打开收款码图片）、查看插件说明按钮（打开HTML帮助文档）。

    输入:
      operator_instance - 操作符实例
      context - Blender 上下文
    输出: 无
    """
    layout = operator_instance.layout

    # 版本信息
    col = layout.column(align=True)
    col.label(text="Plugin Manager Pro v5.1.6", icon='PLUGIN')
    col.label(text="作者: terryye", icon='USER')

    layout.separator()

    # 打赏提示
    layout.label(text="如果觉得插件好用，欢迎打赏支持！", icon='FUND')

    layout.separator()

    # 打赏按钮 - 打开收款码图片
    layout.operator("pmp.open_tip_image", text="打赏", icon='FUND')

    layout.separator()

    # 查看插件说明按钮 - 打开HTML帮助文档（包含收款码）
    layout.operator("pmp.open_readme", text="查看帮助文档", icon='HELP')


# ---------- List Refresh ----------

def refresh_addon_list(context):
    """刷新插件列表数据，根据搜索和过滤条件重新填充列表。

    遍历所有已安装插件，根据搜索文本和分类过滤条件筛选，
    将符合条件的插件添加到场景属性中供UI列表显示。
    自动跳过自身插件。
    
    自启状态以 PMP 配置为准，确保显示与配置一致。

    输入:
      context - Blender 上下文
    输出: 无
    """
    scene = context.scene
    items = scene.pmp_addon_items
    items.clear()

    # 刷新模块列表，确保检测到所有已安装插件（包括未启用的）
    addon_utils.modules_refresh()

    search_text = scene.pmp_search_text.lower().strip()
    filter_cat = scene.pmp_filter_category

    for mod in addon_utils.modules():
        module_name = mod.__name__
        if module_name == __package__ or module_name.startswith(__package__ + "."):
            continue

        try:
            info = addon_utils.module_bl_info(mod)
            raw_name = info.get("name", module_name)
        except Exception:
            raw_name = module_name

        # 优先使用翻译后的名称作为显示名
        translated = bpy.app.translations.pgettext(raw_name) if hasattr(bpy.app.translations, "pgettext") else raw_name
        display_name = translated if translated and translated != raw_name else raw_name

        if search_text:
            # 同时搜索原始名称、翻译名称和模块名
            names_to_search = [raw_name.lower(), module_name.lower(), display_name.lower()]
            if not any(search_text in n for n in names_to_search):
                continue

        cats = config.get_categories(module_name)
        if filter_cat == 'UNCATEGORIZED':
            # 未分类：仅显示只属于 UNCATEGORIZED 分类的插件
            if cats != ['UNCATEGORIZED']:
                continue
        elif filter_cat != 'ALL' and filter_cat not in cats:
            continue

        try:
            from .operators import _is_addon_enabled
            is_enabled = _is_addon_enabled(module_name)
        except Exception:
            # 回退：无法检测时默认为未启用
            is_enabled = False

        item = items.add()
        item.name = module_name
        item.display_name = display_name
        item.categories = ",".join(cats)
        item.is_enabled = is_enabled
        # 自启状态：以 PMP 配置为准（PMP是唯一真理源）
        item.startup = config.get_startup(module_name)


# ---------- Property Registration ----------

def _force_remove_scene_prop(attr_name):
    """强制移除场景属性，确保重复注册时不会冲突。

    先尝试直接删除属性，失败则尝试从注解中移除后再删除。

    输入:
      attr_name (str): 属性名
    输出: 无
    """
    try:
        delattr(bpy.types.Scene, attr_name)
        return
    except Exception:
        pass
    try:
        if hasattr(bpy.types.Scene, '__annotations__') and attr_name in bpy.types.Scene.__annotations__:
            del bpy.types.Scene.__annotations__[attr_name]
        delattr(bpy.types.Scene, attr_name)
    except Exception:
        pass


def register_properties():
    """注册所有场景属性（插件列表、索引、搜索、过滤、新增分类等）。

    先强制移除已有属性（防止重复注册冲突），再重新注册。

    输入: 无
    输出: 无
    """
    for attr in ('pmp_addon_items', 'pmp_addon_index', 'pmp_search_text',
                 'pmp_filter_category', 'pmp_new_cat_id', 'pmp_new_cat_label'):
        _force_remove_scene_prop(attr)

    bpy.types.Scene.pmp_addon_items = CollectionProperty(type=PMP_addon_item)
    bpy.types.Scene.pmp_addon_index = IntProperty(default=0)
    bpy.types.Scene.pmp_search_text = StringProperty(
        default="",
        update=_on_search_changed,
    )
    bpy.types.Scene.pmp_filter_category = StringProperty(default="ALL")
    bpy.types.Scene.pmp_new_cat_id = StringProperty(
        name="ID",
        description="自定义类别的唯一标识（英文，无空格）",
    )
    bpy.types.Scene.pmp_new_cat_label = StringProperty(
        name="名称",
        description="自定义类别的显示名称",
    )


def _on_search_changed(self, context):
    """搜索文本变更回调，重新构建插件列表以应用搜索过滤。

    输入:
      self - 属性所属实例
      context - Blender 上下文
    输出: 无
    """
    refresh_addon_list(context)


def unregister_properties():
    """注销所有场景属性。

    输入: 无
    输出: 无
    """
    for attr in ('pmp_addon_items', 'pmp_addon_index', 'pmp_search_text',
                 'pmp_filter_category', 'pmp_new_cat_id', 'pmp_new_cat_label'):
        _force_remove_scene_prop(attr)


# ---------- Class List ----------

classes = (
    PMP_addon_item,
    PMP_UL_addon_list,
    PMP_OT_confirm_search,
    PMP_OT_clear_search,
    PMP_OT_filter_all,
    PMP_OT_pick_icon,
    PMP_OT_pick_icon_select,
    PMP_OT_rename_category,
    PMP_OT_open_settings,
    PMP_OT_open_category_management,
    PMP_OT_open_readme,
    PMP_OT_open_tip_image,
)


# ---------- Register / Unregister ----------

def register():
    """注册模块：注册所有类、动态过滤操作符和场景属性。

    输入: 无
    输出: 无
    """
    for cls in classes:
        bpy.utils.register_class(cls)
    for cls in _filter_op_cache:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    # 注册动态图标选择操作符
    build_pick_icon_operators()
    register_properties()
    # 收款码图片延迟加载：在用户点击问号按钮时由 _load_about_images() 加载


def unregister():
    """注销模块：注销场景属性、动态操作符和所有类。

    输入: 无
    输出: 无
    """
    # 卸载收款码图片
    _unload_about_images()
    unregister_properties()
    # 注销动态图标选择操作符
    for cls in reversed(_pick_icon_op_cache):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _pick_icon_op_cache.clear()
    for cls in reversed(_filter_op_cache):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
