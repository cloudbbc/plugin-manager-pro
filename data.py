# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: data.py
# 模块作用: 数据定义模块，负责分类定义、图标库管理、自动映射、
#           自定义类别及图标/顺序的 JSON 持久化读写。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

"""数据定义：分类定义 + 图标库管理 + 自动映射 + 自定义类别 + 图标/顺序持久化。

主要功能:
  - ICON_LIBRARY / SAFE_ICONS: 精选图标库及扁平化集合
  - _get_valid_icons / is_icon_valid / validate_icon: 运行时图标验证
  - get_all_icons_grouped / get_icon_library_items: 图标分组与枚举
  - BUILTIN_CATEGORIES: 内置分类定义列表
  - get_all_categories / get_category_by_id: 分类查询
  - set_category_icon / set_category_label: 分类属性修改
  - move_category_up / move_category_down: 分类排序
  - add_custom_category / remove_custom_category / remove_category: 分类增删
  - CATEGORY_AUTO_MAP: Blender bl_info category → PMP 分类自动映射

数据存储路径: Blender用户配置目录/scripts/pmp/categories_config.json
数据格式: {order: [cat_id, ...], overrides: {cat_id: {icon, label, tooltip}}, custom: [...], hidden_builtins: [...]}
"""

import os
import json
import bpy

# ──────────────────────────────────────────────
# 图标库：精选常用图标，按用途分组
# ──────────────────────────────────────────────
ICON_LIBRARY = {
    # ── 通用 ──
    "通用": [
        'BLANK1', 'SCRIPT', 'PLUGIN', 'SETTINGS', 'PREFERENCES',
        'INFO', 'HELP', 'COLOR', 'QUESTION', 'ERROR',
        'CHECKMARK', 'X', 'PLUS', 'TRIA_RIGHT', 'TRIA_DOWN',
        'CANCEL', 'ADD', 'REMOVE', 'DUPLICATE', 'OPTIONS',
    ],
    # ── 编辑器/工作区 ──
    "编辑器": [
        'VIEW3D', 'MATERIAL', 'RENDER_RESULT', 'NODETREE',
        'UV', 'IMAGE', 'SEQUENCE', 'TEXT', 'CONSOLE',
        'OUTLINER', 'TRACKER', 'WORLD', 'SCENE',
        'PROPERTIES', 'ASSET_MANAGER', 'SPREADSHEET',
    ],
    # ── 数据类型 ──
    "数据": [
        'MESH_DATA', 'CURVE_DATA', 'SURFACE_DATA', 'META_DATA',
        'ARMATURE_DATA', 'LATTICE_DATA', 'CAMERA_DATA', 'LIGHT_DATA',
        'FORCE_TEXTURE', 'BRUSH_DATA', 'SHAPEKEY_DATA',
        'PARTICLE_DATA', 'GREASEPENCIL', 'OBJECT_DATA',
        'GROUP', 'MODIFIER', 'SHADERFX', 'CAMERA_STEREO',
        'CURVES_DATA', 'POINTCLOUD_DATA', 'VOLUME_DATA',
    ],
    # ── 文件/系统 ──
    "文件": [
        'FILE_FOLDER', 'FILE_REFRESH', 'RECOVER_LAST',
        'LOCKVIEW_OFF', 'FILTER', 'SYSTEM', 'SORTSIZE',
        'SORTALPHA', 'SORTTIME', 'FILE_BLEND', 'FILE_SCRIPT',
    ],
    # ── 动画/渲染 ──
    "动画": [
        'RENDER_ANIMATION', 'RENDER_STILL', 'PLAY', 'PAUSE',
        'REW', 'FRAME_PREV', 'FRAME_NEXT',
        'KEYFRAME_HLT', 'KEYFRAME', 'KEYINGSET',
        'ACTION', 'NLA_PUSHDOWN', 'HANDLE_AUTO',
    ],
    # ── 界面元素 ──
    "界面": [
        'WINDOW', 'ZOOM_ALL', 'ZOOM_IN', 'ZOOM_OUT',
        'DISCLOSURE_TRI_RIGHT', 'DISCLOSURE_TRI_DOWN',
        'TRIA_RIGHT', 'TRIA_DOWN', 'TRIA_LEFT', 'TRIA_UP',
        'RADIOBUT_OFF', 'RADIOBUT_ON',
        'PINNED', 'UNPINNED', 'LOOP_BACK', 'LOOP_FORWARDS',
        'FULLSCREEN_ENTER', 'FULLSCREEN_EXIT',
        'SCREEN_BACK', 'TOPBAR', 'STATUSBAR',
    ],
    # ── 工具/模式 ──
    "工具": [
        'SCULPTMODE_HLT', 'VPAINT_HLT', 'EDITMODE_HLT',
        'POSE_HLT', 'PARTICLEMODE', 'FACE_MAPS',
        'ORIENTATION_CURSOR', 'ORIENTATION_GIMBAL',
        'SNAP_INCREMENT', 'SNAP_VERTEX', 'SNAP_EDGE',
        'SNAP_FACE', 'SNAP_VOLUME', 'CURSOR',
        'PIVOT_MEDIAN', 'PIVOT_ACTIVE', 'PIVOT_BOUNDBOX',
    ],
}

# 扁平化图标集合（用于验证）
SAFE_ICONS = set()
for _icons in ICON_LIBRARY.values():
    SAFE_ICONS.update(_icons)

# 图标分组标签列表（用于图标选择器显示）
ICON_GROUP_LABELS = list(ICON_LIBRARY.keys())



# ──────────────────────────────────────────────
# 运行时图标系统：从 Blender 主系统获取所有可用图标
# ──────────────────────────────────────────────
_valid_icons_cache = None
_grouped_icons_cache = None

# 图标前缀 → 分组名映射
_ICON_PREFIX_GROUPS = [
    ("EVENT_", "键盘事件"),
    ("KEYTYPE_", "关键帧类型"),
    ("HANDLETYPE_", "手柄类型"),
    ("COLORSET_", "调色板"),
    ("COLLECTION_COLOR_", "集合颜色"),
    ("STRIP_COLOR_", "片段颜色"),
    ("LAYERGROUP_COLOR_", "层组颜色"),
    ("KEY_", "按键"),
    ("MOD_", "修改器"),
    ("CON_", "约束"),
    ("FORCE_", "力场"),
    ("NODE_", "节点"),
    ("SNAP_", "捕捉"),
    ("OUTLINER_OB_", "对象大纲"),
    ("OUTLINER_DATA_", "数据大纲"),
    ("GP_", "蜡笔"),
    ("SEQ_", "序列器"),
    ("IMAGE_", "图像"),
    ("FILE_", "文件"),
    ("MODIFIER_", "修改器图标"),
    ("RESTRICT_", "限制"),
    ("DECORATE_", "装饰"),
    ("ORIENTATION_", "方向"),
    ("PIVOT_", "轴心点"),
    ("SHADING_", "着色"),
    ("VIEW_", "视图"),
    ("AXIS_", "轴"),
    ("LIGHT_", "灯光"),
    ("LIGHTPROBE_", "光照探针"),
    ("MESH_", "网格图元"),
    ("CURVE_", "曲线图元"),
    ("SURFACE_N", "曲面图元"),
    ("META_", "元球图元"),
    ("EMPTY_", "空物体"),
    ("RIGID_", "刚体"),
    ("SPLIT_", "分割"),
    ("ANCHOR_", "锚点"),
    ("ALIGN_", "对齐"),
    ("ACTION_", "动作"),
    ("NORMALS_", "法线"),
    ("UV_", "UV"),
    ("STICKY_", "粘性"),
    ("LOCKVIEW_", "锁定视图"),
    ("FULLSCREEN_", "全屏"),
    ("DISCLOSURE_TRI_", "展开三角"),
    ("TRIA_", "三角箭头"),
    ("RADIOBUT_", "单选按钮"),
    ("CHECKBOX_", "复选框"),
    ("SORT_", "排序"),
    ("LOOP_", "循环"),
    ("ZOOM_", "缩放"),
    ("SCREEN_", "屏幕"),
    ("AREA_", "区域"),
    ("GESTURE_", "手势"),
]


def _get_valid_icons():
    """获取 Blender 运行时所有有效图标的标识符集合"""
    global _valid_icons_cache
    if _valid_icons_cache is not None:
        return _valid_icons_cache
    _valid_icons_cache = set()
    try:
        for item in bpy.types.UILayout.bl_rna.properties['icon'].enum_items_static:
            ident = item.identifier
            if ident and ident != 'NONE':
                _valid_icons_cache.add(ident)
    except Exception:
        for icons in ICON_LIBRARY.values():
            _valid_icons_cache.update(icons)
    return _valid_icons_cache


def invalidate_icon_cache():
    """使图标缓存失效（在需要时调用）"""
    global _valid_icons_cache, _grouped_icons_cache
    _valid_icons_cache = None
    _grouped_icons_cache = None


def is_icon_valid(icon_name):
    """检查图标名在当前 Blender 版本中是否有效"""
    if not icon_name or icon_name == 'NONE':
        return False
    return icon_name in _get_valid_icons()


def validate_icon(icon_name):
    """验证图标名是否有效，无效则返回 BLANK1。"""
    if not icon_name:
        return 'BLANK1'
    if is_icon_valid(icon_name):
        return icon_name
    return 'BLANK1'


def _get_icon_group(icon_name):
    """根据图标名前缀返回分组名"""
    for prefix, group_name in _ICON_PREFIX_GROUPS:
        if icon_name.startswith(prefix):
            return group_name
    return "通用"


def get_all_icons_grouped():
    """获取 Blender 运行时所有可用图标，按前缀自动分组。
    返回: OrderedDict，key=分组名, value=图标名列表
    """
    global _grouped_icons_cache
    if _grouped_icons_cache is not None:
        return _grouped_icons_cache

    from collections import OrderedDict
    all_icons = _get_valid_icons()

    # 按前缀分组
    groups = OrderedDict()
    groups["通用"] = []

    # 先收集通用图标（无特殊前缀的常用图标）
    common_icons = []
    other_icons = []

    for icon_name in sorted(all_icons):
        group = _get_icon_group(icon_name)
        if group == "通用":
            common_icons.append(icon_name)
        else:
            if group not in groups:
                groups[group] = []
            groups[group].append(icon_name)

    groups["通用"] = common_icons

    # 移除空分组
    _grouped_icons_cache = OrderedDict(
        (k, v) for k, v in groups.items() if v
    )
    return _grouped_icons_cache


def get_icon_library_items():
    """获取所有有效图标的枚举项列表，按分组组织。
    返回格式: [(identifier, label, description, icon_value), ...]
    """
    items = []
    for group_name, icons in get_all_icons_grouped().items():
        for icon_name in icons:
            items.append((icon_name, icon_name, f"[{group_name}] {icon_name}", icon_name))
    return items


def get_all_icons_list():
    """获取所有可用图标的排序列表，用于图标选择器。"""
    return sorted(_get_valid_icons())


def get_valid_library_icons():
    """获取按分组组织的有效图标字典，用于 UI 绘制。"""
    return get_all_icons_grouped()


# ──────────────────────────────────────────────
# 内置分类
# ──────────────────────────────────────────────
BUILTIN_CATEGORIES = [
    {
        "id": "3D_VIEWPORT",
        "label": "3D视图",
        "icon": "VIEW3D",
        "tooltip": "3D视口相关插件",
        "builtin": True
    },
    {
        "id": "MESH_EDIT",
        "label": "网格编辑",
        "icon": "MODIFIER",
        "tooltip": "网格建模/编辑插件",
        "builtin": True
    },
    {
        "id": "SCULPT",
        "label": "雕刻模式",
        "icon": "SCULPTMODE_HLT",
        "tooltip": "雕刻/笔刷相关插件",
        "builtin": True
    },
    {
        "id": "POSE_MODE",
        "label": "姿态模式",
        "icon": "POSE_HLT",
        "tooltip": "姿态/绑定/骨骼相关插件",
        "builtin": True
    },
    {
        "id": "UV_TEXTURE",
        "label": "UV纹理",
        "icon": "UV",
        "tooltip": "UV编辑/纹理绘制相关插件",
        "builtin": True
    },
    {
        "id": "SHADER_EDITOR",
        "label": "着色器模式",
        "icon": "MATERIAL",
        "tooltip": "着色器/材质节点编辑器插件",
        "builtin": True
    },
    {
        "id": "GEOMETRY_NODES",
        "label": "几何节点模式",
        "icon": "NODETREE",
        "tooltip": "几何节点编辑器插件",
        "builtin": True
    },
    {
        "id": "COMPOSITOR",
        "label": "合成器模式",
        "icon": "RENDER_RESULT",
        "tooltip": "合成器相关插件",
        "builtin": True
    },
    {
        "id": "IMAGE_EDITOR",
        "label": "图像",
        "icon": "IMAGE",
        "tooltip": "图像编辑器/纹理绘制插件",
        "builtin": True
    },
    {
        "id": "SEQUENCER",
        "label": "视频编辑",
        "icon": "SEQUENCE",
        "tooltip": "视频序列编辑器插件",
        "builtin": True
    },
    {
        "id": "SYSTEM",
        "label": "系统插件",
        "icon": "SETTINGS",
        "tooltip": "系统级插件（导入/导出/渲染等）",
        "builtin": True
    },
    {
        "id": "UNCATEGORIZED",
        "label": "无分类插件",
        "icon": "QUESTION",
        "tooltip": "尚未设置分类的插件",
        "builtin": True,
        "undeletable": True
    },
]

# ──────────────────────────────────────────────
# 分类配置持久化（顺序、图标覆盖、自定义类别）
# ──────────────────────────────────────────────
_config_path = None
_category_order: list = []
_category_overrides: dict = {}
_custom_categories: list = []
_hidden_builtin_ids: set = set()
_config_loaded = False


def _get_config_path():
    """获取分类配置文件路径（延迟计算）。

    配置文件位于 Blender 用户资源目录下的 scripts/pmp/categories_config.json。
    首次调用时计算路径并缓存，后续调用直接返回缓存值。

    输入: 无（使用全局变量 _config_path）
    输出: str - 配置文件的绝对路径
    """
    global _config_path
    if _config_path is None:
        _config_path = os.path.join(
            bpy.utils.user_resource('CONFIG', path="scripts/pmp", create=True),
            "categories_config.json"
        )
    return _config_path


def _load_config():
    """从JSON文件加载分类配置到内存缓存。

    读取配置文件中的分类顺序、图标/名称覆盖、自定义类别和隐藏的内置分类。
    如果文件不存在或解析失败，则初始化为空值。

    输入: 无
    输出: 无（修改全局变量 _category_order, _category_overrides, _custom_categories, _hidden_builtin_ids）
    """
    global _category_order, _category_overrides, _custom_categories, _config_loaded, _hidden_builtin_ids
    _config_loaded = True
    path = _get_config_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            _category_order = cfg.get("order", [])
            _category_overrides = cfg.get("overrides", {})
            _custom_categories = cfg.get("custom", [])
            _hidden_builtin_ids = set(cfg.get("hidden_builtins", []))
        except Exception:
            _category_order = []
            _category_overrides = {}
            _custom_categories = []
            _hidden_builtin_ids = set()
    else:
        _category_order = []
        _category_overrides = {}
        _custom_categories = []
        _hidden_builtin_ids = set()


def _save_config():
    """将内存中的分类配置写入JSON文件。

    自动创建配置目录（如不存在），以UTF-8编码、缩进2格写入。
    写入失败时静默忽略（不抛出异常）。

    输入: 无（读取全局变量）
    输出: 无
    """
    try:
        path = _get_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cfg = {
            "order": _category_order,
            "overrides": _category_overrides,
            "custom": _custom_categories,
            "hidden_builtins": list(_hidden_builtin_ids),
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _ensure_loaded():
    """确保分类配置已加载，若未加载则自动执行加载。

    输入: 无
    输出: 无
    """
    global _config_loaded
    if not _config_loaded:
        _load_config()


def get_all_categories(include_hidden=False) -> list:
    """获取所有分类（内置 + 自定义），按自定义顺序排列，应用图标覆盖。
    include_hidden=False 时排除 hidden=True 的分类（如"通用"）。
    include_hidden=True 时排除已删除的分类，但保留 hidden=True 的分类（如"通用"）。
    """
    _ensure_loaded()
    all_cats_dict = {}
    for cat in BUILTIN_CATEGORIES:
        entry = dict(cat)
        if entry['id'] in _category_overrides:
            ov = _category_overrides[entry['id']]
            entry['icon'] = validate_icon(ov.get('icon', entry['icon']))
            if 'label' in ov:
                entry['label'] = ov['label']
            if 'tooltip' in ov:
                entry['tooltip'] = ov['tooltip']
        else:
            entry['icon'] = validate_icon(entry['icon'])
        all_cats_dict[entry['id']] = entry

    for cat in _custom_categories:
        entry = dict(cat)
        if entry['id'] in _category_overrides:
            ov = _category_overrides[entry['id']]
            entry['icon'] = validate_icon(ov.get('icon', entry['icon']))
            if 'label' in ov:
                entry['label'] = ov['label']
            if 'tooltip' in ov:
                entry['tooltip'] = ov['tooltip']
        else:
            entry['icon'] = validate_icon(entry.get('icon', 'SCRIPT'))
        all_cats_dict[entry['id']] = entry

    result = []
    for cat_id in _category_order:
        if cat_id in all_cats_dict:
            result.append(all_cats_dict.pop(cat_id))
    for cat_id, cat in all_cats_dict.items():
        result.append(cat)

    # 始终排除已删除的分类（被用户主动删除的内置分类）
    result = [cat for cat in result if not is_category_hidden(cat['id'])]

    # include_hidden=False 时额外排除 hidden=True 的分类（如"通用"）
    if not include_hidden:
        result = [cat for cat in result if not cat.get('hidden')]
    return result


def get_category_by_id(cat_id):
    """根据分类ID获取分类信息字典。

    输入:
      cat_id (str): 分类ID，如 "3D_VIEWPORT"
    输出:
      dict | None - 分类信息字典，未找到则返回 None
    """
    for cat in get_all_categories():
        if cat['id'] == cat_id:
            return cat
    return None


def set_category_icon(cat_id, icon_name):
    """设置分类的图标，并持久化保存。

    输入:
      cat_id (str): 分类ID
      icon_name (str): 图标标识符，无效图标会被替换为 BLANK1
    输出: 无
    """
    _ensure_loaded()
    icon_name = validate_icon(icon_name)
    if cat_id not in _category_overrides:
        _category_overrides[cat_id] = {}
    _category_overrides[cat_id]['icon'] = icon_name
    _save_config()


def set_category_label(cat_id, label):
    """设置分类的显示名称，并持久化保存。

    输入:
      cat_id (str): 分类ID
      label (str): 新的显示名称
    输出: 无
    """
    _ensure_loaded()
    if cat_id not in _category_overrides:
        _category_overrides[cat_id] = {}
    _category_overrides[cat_id]['label'] = label
    _save_config()


def _ensure_order_initialized():
    """确保 _category_order 已初始化，包含所有可见分类的ID。

    同时处理旧分类ID到新分类ID的迁移，确保已保存的排序配置兼容新版本。
    """
    global _category_order
    # 旧分类ID → 新分类ID 映射（用于迁移已保存的排序配置）
    _legacy_id_map = {
        "UV_EDITOR": "UV_TEXTURE",
        "TEXT_EDITOR": "SYSTEM",
    }
    # 先迁移旧的分类ID
    _category_order = [_legacy_id_map.get(cid, cid) for cid in _category_order]
    # 去重（迁移后可能出现重复，保留首次出现的位置）
    seen = set()
    deduped = []
    for cid in _category_order:
        if cid not in seen:
            seen.add(cid)
            deduped.append(cid)
    _category_order = deduped

    all_ids = [c['id'] for c in get_all_categories(include_hidden=True)]
    # 过滤掉隐藏的已删除内置分类
    all_ids = [cid for cid in all_ids if not is_category_hidden(cid)]
    if not _category_order:
        _category_order = all_ids
    else:
        # 确保所有分类都在顺序列表中
        ordered_set = set(_category_order)
        for cid in all_ids:
            if cid not in ordered_set:
                _category_order.append(cid)
        # 移除已不存在的分类
        all_set = set(all_ids)
        _category_order = [cid for cid in _category_order if cid in all_set]


def move_category_up(cat_id):
    """将指定分类在排序列表中上移一位，并持久化保存。

    输入:
      cat_id (str): 分类ID
    输出:
      bool - 移动成功返回 True，已在顶部或不存在返回 False
    """
    _ensure_loaded()
    _ensure_order_initialized()
    if cat_id not in _category_order:
        return False
    idx = _category_order.index(cat_id)
    if idx > 0:
        _category_order[idx], _category_order[idx - 1] = _category_order[idx - 1], _category_order[idx]
        _save_config()
        return True
    return False


def move_category_down(cat_id):
    """将指定分类在排序列表中下移一位，并持久化保存。

    输入:
      cat_id (str): 分类ID
    输出:
      bool - 移动成功返回 True，已在底部或不存在返回 False
    """
    _ensure_loaded()
    _ensure_order_initialized()
    if cat_id not in _category_order:
        return False
    idx = _category_order.index(cat_id)
    if idx < len(_category_order) - 1:
        _category_order[idx], _category_order[idx + 1] = _category_order[idx + 1], _category_order[idx]
        _save_config()
        return True
    return False


def add_custom_category(cat_id: str, label: str, icon: str = "SCRIPT") -> bool:
    """添加一个自定义分类，并持久化保存。

    如果分类ID已存在则不添加。

    输入:
      cat_id (str): 唯一分类ID（英文，无空格）
      label (str): 分类显示名称
      icon (str): 分类图标标识符，默认 "SCRIPT"
    输出:
      bool - 添加成功返回 True，ID已存在返回 False
    """
    _ensure_loaded()
    all_cats = get_all_categories()
    for cat in all_cats:
        if cat["id"] == cat_id:
            return False
    icon = validate_icon(icon)
    entry = {"id": cat_id, "label": label, "icon": icon, "tooltip": label, "custom": True}
    _custom_categories.append(entry)
    _category_order.append(cat_id)
    _save_config()
    return True


def remove_custom_category(cat_id: str) -> bool:
    """移除一个自定义分类，并持久化保存。

    同时清除该分类的覆盖设置和排序记录。

    输入:
      cat_id (str): 要移除的自定义分类ID
    输出:
      bool - 移除成功返回 True，未找到返回 False
    """
    _ensure_loaded()
    global _custom_categories, _category_order
    for i, cat in enumerate(_custom_categories):
        if cat["id"] == cat_id:
            _custom_categories.pop(i)
            if cat_id in _category_order:
                _category_order.remove(cat_id)
            if cat_id in _category_overrides:
                del _category_overrides[cat_id]
            _save_config()
            return True
    return False


# _hidden_builtin_ids 已在文件顶部声明，此处不再重复


def remove_category(cat_id: str) -> bool:
    """删除任意分类（内置或自定义），将该分类下的插件归入 UNCATEGORIZED。
    UNCATEGORIZED 分类不可删除。
    """
    if cat_id == "UNCATEGORIZED":
        return False
    _ensure_loaded()
    global _custom_categories, _category_order, _hidden_builtin_ids

    # 从自定义分类中移除
    for i, cat in enumerate(_custom_categories):
        if cat["id"] == cat_id:
            _custom_categories.pop(i)
            break

    # 从顺序中移除
    if cat_id in _category_order:
        _category_order.remove(cat_id)

    # 清除覆盖
    if cat_id in _category_overrides:
        del _category_overrides[cat_id]

    # 标记内置分类为隐藏
    _hidden_builtin_ids.add(cat_id)

    # 将该分类下的插件归入 UNCATEGORIZED
    from . import config
    for module_name in config.get_all_addons():
        cats = config.get_categories(module_name)
        if cat_id in cats:
            cats = [c for c in cats if c != cat_id]
            if not cats:
                cats = ["UNCATEGORIZED"]
            config.set_categories(module_name, cats)

    _save_config()
    return True


def is_category_hidden(cat_id: str) -> bool:
    """检查分类是否被隐藏（已删除的内置分类）"""
    return cat_id in _hidden_builtin_ids


def get_custom_categories() -> list:
    """获取所有自定义分类的列表副本。

    输入: 无
    输出:
      list - 自定义分类字典列表的浅拷贝
    """
    _ensure_loaded()
    return _custom_categories.copy()


def reset_category_overrides(cat_id):
    """重置分类的图标和名称覆盖为默认值，并持久化保存。

    输入:
      cat_id (str): 分类ID
    输出:
      bool - 有覆盖被重置返回 True，无覆盖返回 False
    """
    _ensure_loaded()
    if cat_id in _category_overrides:
        del _category_overrides[cat_id]
        _save_config()
        return True
    return False


# 便捷属性
CATEGORY_LABELS = {cat["id"]: cat["label"] for cat in BUILTIN_CATEGORIES}
ALL_CATEGORY_IDS = [cat["id"] for cat in BUILTIN_CATEGORIES]

# ──────────────────────────────────────────────
# Blender bl_info category → PMP 分类自动映射
# ──────────────────────────────────────────────
CATEGORY_AUTO_MAP = {
    "3d view": ["3D_VIEWPORT"],
    "3dview": ["3D_VIEWPORT"],
    "object": ["3D_VIEWPORT"],
    "animation": ["3D_VIEWPORT"],
    "motion": ["3D_VIEWPORT"],
    "tracking": ["3D_VIEWPORT"],
    "light": ["3D_VIEWPORT"],
    "camera": ["3D_VIEWPORT"],
    "scene": ["3D_VIEWPORT"],
    "layout": ["3D_VIEWPORT"],
    "mesh": ["MESH_EDIT"],
    "add mesh": ["MESH_EDIT"],
    "mesh editing": ["MESH_EDIT"],
    "mesh model": ["MESH_EDIT"],
    "modeling": ["MESH_EDIT"],
    "retopology": ["MESH_EDIT"],
    "curve": ["MESH_EDIT"],
    "add curve": ["MESH_EDIT"],
    "surface": ["MESH_EDIT"],
    "lattice": ["MESH_EDIT"],
    "sculpt": ["SCULPT"],
    "sculpting": ["SCULPT"],
    "armature": ["POSE_MODE"],
    "rigging": ["POSE_MODE"],
    "uv": ["UV_TEXTURE"],
    "paint": ["UV_TEXTURE"],
    "texture": ["UV_TEXTURE"],
    "material": ["SHADER_EDITOR"],
    "shader": ["SHADER_EDITOR"],
    "geometry": ["GEOMETRY_NODES"],
    "node": ["GEOMETRY_NODES"],
    "nodes": ["GEOMETRY_NODES"],
    "compositing": ["COMPOSITOR"],
    "image": ["IMAGE_EDITOR"],
    "sequencer": ["SEQUENCER"],
    "text editor": ["SYSTEM"],
    "development": ["SYSTEM"],
    "console": ["SYSTEM"],
    "import": ["SYSTEM"],
    "export": ["SYSTEM"],
    "render": ["SYSTEM"],
    "physics": ["SYSTEM"],
    "boid": ["SYSTEM"],
    "cloth": ["SYSTEM"],
    "fluid": ["SYSTEM"],
    "particle": ["SYSTEM"],
    "rigid body": ["SYSTEM"],
    "simulation": ["SYSTEM"],
    "game engine": ["SYSTEM"],
    "system": ["UNCATEGORIZED"],
    "user interface": ["UNCATEGORIZED"],
    "ui": ["UNCATEGORIZED"],
    "file browser": ["UNCATEGORIZED"],
    "outliner": ["UNCATEGORIZED"],
    "preferences": ["UNCATEGORIZED"],
    "info": ["UNCATEGORIZED"],
    "mesh analysis": ["UNCATEGORIZED"],
}
