# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: operators.py
# 模块作用: 操作符定义模块，统一定义所有 PMP 操作符，
#           包括插件加载/停用、自启切换、分类管理、图标修改等。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

"""操作符定义：所有 PMP 操作符的统一定义。

主要功能:
  - _refresh: 操作后刷新插件列表
  - _rebuild_dynamic: 重建动态菜单并重新注册
  - PMP_OT_toggle_startup: 切换插件自启状态
  - PMP_OT_load / PMP_OT_unload: 加载/停用插件
  - PMP_OT_refresh_addon_list: 刷新插件列表
  - PMP_OT_set_category: 切换插件分类归属
  - PMP_OT_add_custom_category / PMP_OT_remove_custom_category: 自定义分类增删
  - PMP_OT_remove_category: 删除分类
  - PMP_OT_set_category_icon / PMP_OT_set_category_label: 修改分类属性
  - PMP_OT_move_category_up / PMP_OT_move_category_down: 分类排序
  - PMP_OT_reset_category / PMP_OT_reset_all: 重置分类设置
"""

import sys
import bpy
import addon_utils
import inspect
import re
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty
from . import config, data


# 全局集合：跟踪已加载的插件模块名
# 由 PMP_OT_load 添加，由 PMP_OT_unload 移除
_loaded_addons = set()
# 会话临时状态：记录加载前的偏好/加载状态，用于在停用时恢复到加载之前的状态
# 结构: { module_name: { 'was_loaded': bool, 'was_in_preferences': bool } }
_session_prev_state = {}
# 启动时偏好快照（用于完整恢复到插件管理器注册时的首选项状态）
_initial_pref_addons = None


def _capture_initial_prefs():
    """Capture the initial set of preferences.addons modules at PMP registration time."""
    global _initial_pref_addons
    try:
        addon_names = {a.module for a in bpy.context.preferences.addons}
        _initial_pref_addons = set(addon_names)
        _debug_log(f"Captured initial preferences.addons snapshot: {_initial_pref_addons}")
    except Exception as e:
        _debug_log(f"Failed to capture initial prefs snapshot: {e}")
        _initial_pref_addons = None


def _restore_to_initial_prefs(delay=0.25):
    """Restore preferences.addons to the captured initial snapshot.

    This enables addons present in the snapshot and removes prefs entries that were not
    present at startup. Runs asynchronously via bpy.app.timers to avoid registration races.
    """
    def _do_restore():
        try:
            if not _initial_pref_addons:
                _debug_log("No initial snapshot available; skipping initial restore")
                return None
            addon_utils.modules_refresh()
            current = {a.module for a in bpy.context.preferences.addons}
            desired = set(_initial_pref_addons)
            # enable missing desired addons
            for mod_name in desired - current:
                try:
                    addon_utils.enable(mod_name, default_set=True)
                    _debug_log(f"Restored pref addon: {mod_name}")
                except Exception as e:
                    _debug_log(f"Failed to enable pref addon {mod_name}: {e}")
            # remove extras that shouldn't be present
            for mod_name in current - desired:
                try:
                    _safe_remove_pref_addon(mod_name)
                    _debug_log(f"Removed extra pref addon: {mod_name}")
                except Exception as e:
                    _debug_log(f"Failed to remove extra pref addon {mod_name}: {e}")
            # refresh modules
            addon_utils.modules_refresh()
            _debug_log("Initial prefs restore completed")
        except Exception as e:
            _debug_log(f"Initial prefs restore failed: {e}")
        return None

    try:
        bpy.app.timers.register(_do_restore, first_interval=delay)
    except Exception as e:
        _debug_log(f"Failed schedule initial prefs restore: {e}")
        try:
            _do_restore()
        except Exception:
            pass



def _check_addon_loaded(module_name):
    """检测插件是否已加载（模块已导入到 sys.modules）。

    输入:
      module_name (str): 插件模块名
    输出:
      bool - True 表示已加载
    """
    return module_name in sys.modules


def _is_addon_enabled(module_name):
    """检测插件是否在当前会话中已启用（已加载且正在运行）。

    使用 preferences.addons 作为主要检测方式，这是 Blender 官方判断插件启用的标准。
    同时使用 _loaded_addons 作为快速路径优化。

    输入:
      module_name (str): 插件模块名
    输出:
      bool - True 表示已加载
    """
    # 快速路径：检查缓存集合
    if module_name in _loaded_addons:
        return True
    
    # 可靠路径：检查 Blender 的 preferences.addons
    # 这是 Blender 判断插件是否启用的官方标准
    try:
        for addon in bpy.context.preferences.addons:
            if addon.module == module_name:
                # 在 preferences.addons 中找到，说明插件已启用
                _loaded_addons.add(module_name)  # 更新缓存
                return True
    except Exception as e:
        _debug_log(f"Error checking preferences.addons for {module_name}: {e}")
    
    # 不在 preferences.addons 中，说明插件未启用
    # 从缓存中移除（如果存在）
    _loaded_addons.discard(module_name)
    return False


def _init_loaded_addons():
    """初始化 _loaded_addons 集合，将当前所有已加载的插件加入。

    在插件注册时调用，确保 _loaded_addons 与 Blender 实际状态一致。
    """
    global _loaded_addons
    _loaded_addons.clear()
    # 从 sys.modules 获取所有已加载的插件模块
    try:
        addon_names = {mod.__name__ for mod in addon_utils.modules()}
        _loaded_addons.update(addon_names & sys.modules.keys())
    except Exception:
        pass
    # 从 preferences.addons 获取自启插件（确保不遗漏）
    try:
        for addon in bpy.context.preferences.addons:
            _loaded_addons.add(addon.module)
    except Exception as e:
        _debug_log(f"Error iterating preferences.addons during init: {e}")
        try:
            _schedule_restore_system_addons(delay=0.25)
        except Exception:
            pass


def _is_addon_in_preferences(module_name):
    """检测插件是否在 preferences.addons 中（即是否设置了自启）。

    输入:
      module_name (str): 插件模块名
    输出:
      bool - True 表示在 preferences.addons 中（自启已开启）
    """
    try:
        return module_name in {a.module for a in bpy.context.preferences.addons}
    except Exception:
        # 遇到访问 preferences.addons 的异常时，调度恢复系统插件初始化以修复偏好损坏
        try:
            _debug_log(f"Error accessing preferences.addons while checking {module_name}; scheduling restore")
            _schedule_restore_system_addons(delay=0.25)
        except Exception:
            pass
        return False


# ---------- Safe preferences helpers ----------

def _safe_get_pref_addon(module_name):
    """Safe accessor for bpy.context.preferences.addons.get(module_name)."""
    try:
        return bpy.context.preferences.addons.get(module_name)
    except Exception as e:
        _debug_log(f"_safe_get_pref_addon exception for {module_name}: {e}")
        try:
            _schedule_restore_system_addons(delay=0.25)
        except Exception:
            pass
        return None


def _safe_remove_pref_addon(module_name):
    """Safely remove a preferences.addons entry if present; returns True if removed."""
    try:
        addon = bpy.context.preferences.addons.get(module_name)
        if addon:
            bpy.context.preferences.addons.remove(addon)
            bpy.context.preferences.is_dirty = True
            return True
        return False
    except Exception as e:
        _debug_log(f"_safe_remove_pref_addon exception for {module_name}: {e}")
        try:
            _schedule_restore_system_addons(delay=0.25)
        except Exception:
            pass
        return False


def _cleanup_addon(module_name):
    """Thorough cleanup of an addon module to avoid leftover registrations.

    Steps:
    - If module present, unregister known bpy types defined in module (Operator/Panel/Menu/PropertyGroup/Add-onPrefs).
    - Attempt to unregister tools registered via bpy.utils.register_tool.
    - Call module.unregister() if available.
    - Remove submodules from sys.modules (module_name.*)
    - Remove the module itself from sys.modules.
    - Ensure preferences entry can be removed by caller if needed.
    """
    try:
        mod = sys.modules.get(module_name)
        if mod:
            # 尝试反注册模块中定义的 bpy.types 子类
            try:
                for name in dir(mod):
                    try:
                        attr = getattr(mod, name)
                    except Exception:
                        continue
                    if inspect.isclass(attr):
                        try:
                            # 判断是否为 bpy.types 的子类
                            bases = (bpy.types.Operator, bpy.types.Panel, bpy.types.Menu, bpy.types.PropertyGroup, bpy.types.AddonPreferences)
                            for base in bases:
                                try:
                                    if issubclass(attr, base) and attr is not base:
                                        try:
                                            bpy.utils.unregister_class(attr)
                                        except Exception:
                                            pass
                                        break
                                except Exception:
                                    continue
                        except Exception:
                            continue
            except Exception:
                pass

            # 尝试反注册通过 register_tool 注册的工具
            try:
                for name in dir(mod):
                    try:
                        attr = getattr(mod, name)
                    except Exception:
                        continue
                    if inspect.isclass(attr):
                        try:
                            bpy.utils.unregister_tool(attr, group=True)
                        except Exception:
                            pass
            except Exception:
                pass

            # 调用模块的 unregister()（如果存在）以便模块执行自有清理逻辑
            if hasattr(mod, "unregister"):
                try:
                    mod.unregister()
                except Exception:
                    pass

        # 移除模块及其子模块的 sys.modules 条目
        try:
            for key in list(sys.modules.keys()):
                if key == module_name or key.startswith(module_name + "."):
                    try:
                        del sys.modules[key]
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception:
        pass


def _unregister_tool_by_bl_id(tool_bl_id):
    """Attempt to find and unregister a tool class by its bl_idname across loaded modules."""
    try:
        for mod in list(sys.modules.values()):
            try:
                for name in dir(mod):
                    try:
                        attr = getattr(mod, name)
                    except Exception:
                        continue
                    if inspect.isclass(attr):
                        bl_id = getattr(attr, 'bl_idname', None)
                        if bl_id == tool_bl_id:
                            try:
                                bpy.utils.unregister_tool(attr, group=True)
                                _debug_log(f"Unregistered tool class {attr} for bl_id {tool_bl_id}")
                            except Exception:
                                pass
            except Exception:
                continue
    except Exception:
        pass


def _schedule_retry_enable(module_name, default_set=False, delay=0.2):
    """Schedule a retry of enabling the addon after a short delay."""
    def _retry():
        try:
            _debug_log(f"Retrying enable for {module_name} (default_set={default_set})")
            addon_utils.enable(module_name, default_set=default_set)
            _debug_log(f"Retry enable succeeded for {module_name} (default_set={default_set})")
        except Exception as e:
            _debug_log(f"Retry enable failed for {module_name}: {e}")
        return None

    try:
        bpy.app.timers.register(_retry, first_interval=delay)
    except Exception:
        # fallback immediate try
        try:
            addon_utils.enable(module_name, default_set=default_set)
        except Exception as e:
            _debug_log(f"Immediate retry enable failed for {module_name}: {e}")


# Debug flag: set True during development to enable verbose debug printing
_DEBUG = False

def _debug_log(msg):
    if not _DEBUG:
        return
    try:
        print(f"[PMP DEBUG] {msg}")
    except Exception:
        pass


def _restore_system_addons():
    """Attempt to restore Blender's preference-enabled addons to their registered state.

    For each addon listed in bpy.context.preferences.addons, enable it (default_set=True)
    if it's not present in sys.modules. This helps recover global registration state after partial failures.
    """
    try:
        addon_utils.modules_refresh()
        # iterate a stable list copy
        for a in list(bpy.context.preferences.addons):
            mod_name = a.module
            try:
                if mod_name not in sys.modules:
                    try:
                        addon_utils.enable(mod_name, default_set=True)
                        _debug_log(f"Restored system addon: {mod_name}")
                    except Exception as e:
                        _debug_log(f"Failed to enable system addon {mod_name}: {e}")
            except Exception as e:
                _debug_log(f"Error while restoring addon {mod_name}: {e}")
    except Exception as e:
        _debug_log(f"Failed to restore system addons: {e}")


def _schedule_restore_system_addons(delay=0.25):
    """Schedule a delayed restore of system addons to avoid race conditions.

    If an initial snapshot exists, prefer restoring to that snapshot; otherwise fall back
    to best-effort restoring based on current preferences.addons entries.
    """
    # Prefer restoring to initial snapshot if available
    try:
        if _initial_pref_addons:
            _debug_log("Scheduling restore to initial prefs snapshot")
            _restore_to_initial_prefs(delay=delay)
            return
    except Exception:
        pass

    def _do_restore():
        try:
            _restore_system_addons()
        except Exception as e:
            _debug_log(f"Scheduled restore failed: {e}")
        return None

    try:
        bpy.app.timers.register(_do_restore, first_interval=delay)
    except Exception as e:
        _debug_log(f"Failed to schedule system addons restore: {e}")
        try:
            _restore_system_addons()
        except Exception:
            pass


def _rollback_to_prev_state(module_name):
    """Restore addon to previous session state recorded in _session_prev_state.

    Attempts to restore preferences entry and loaded state. Does not change PMP startup config.
    Uses delayed system restore to avoid race conditions.
    """
    prev = _session_prev_state.get(module_name)
    _debug_log(f"Rolling back {module_name} to prev state: {prev}")
    if not prev:
        return
    was_in_prefs = prev.get('was_in_preferences', False)
    was_loaded = prev.get('was_loaded', False)

    # First, cleanup any partial registrations (unregister tools/classes)
    try:
        _cleanup_addon(module_name)
    except Exception:
        pass

    # Restore preferences entry and runtime loaded state conservatively
    try:
        now_in_prefs = _is_addon_in_preferences(module_name)
        if was_in_prefs and not now_in_prefs:
            # Schedule native enable shortly to avoid immediate registration races
            try:
                _debug_log(f"Scheduling native enable for {module_name} to restore prefs entry")
                _schedule_retry_enable(module_name, default_set=True, delay=0.2)
            except Exception as e:
                _debug_log(f"Failed to schedule native enable for {module_name}: {e}")
        elif not was_in_prefs and now_in_prefs:
            # Remove preferences entry
            try:
                removed = _safe_remove_pref_addon(module_name)
                if removed:
                    _debug_log(f"Removed preferences entry for {module_name} to restore prev state")
            except Exception as e:
                _debug_log(f"Failed to remove preferences entry for {module_name}: {e}")
    except Exception:
        pass

    # Restore loaded state: if was_loaded but now not, try to enable in-session without changing prefs
    try:
        now_loaded = _check_addon_loaded(module_name) or _is_addon_enabled(module_name)
        if was_loaded and not now_loaded:
            try:
                _debug_log(f"Scheduling session-only enable for {module_name} to restore runtime state")
                _schedule_retry_enable(module_name, default_set=False, delay=0.2)
            except Exception as e:
                _debug_log(f"Failed to schedule session-only enable for {module_name}: {e}")
        elif not was_loaded and now_loaded:
            # If it wasn't loaded previously but now is, attempt to disable without changing prefs
            try:
                addon_utils.disable(module_name, default_set=False)
                _loaded_addons.discard(module_name)
                _debug_log(f"Disabled runtime loaded state for {module_name} to restore prev state")
            except Exception as e:
                _debug_log(f"Failed to disable runtime loaded state for {module_name}: {e}")
    except Exception:
        pass

    # attempt to restore system-wide addons to their global registered state after a short delay
    try:
        _schedule_restore_system_addons(delay=0.25)
    except Exception:
        pass

    # finally, clear session prev state
    try:
        del _session_prev_state[module_name]
    except Exception:
        pass


def _safe_enable(module_name, default_set=False):
    """Try to enable an addon safely with targeted retries.

    Returns (status, info):
      - 'ok', None
      - 'requires_pref', error_message
      - 'tool_conflict', error_message
      - 'error', error_message
    """
    try:
        addon_utils.enable(module_name, default_set=default_set)
        return ('ok', None)
    except Exception as e:
        msg = str(e)
        _debug_log(f"enable(default_set={default_set}) exception for {module_name}: {msg}")
        # Tool conflict -> try unregistering the existing tool and retry once
        try:
            m = re.search(r"Tool '(.+?)' already exists", msg)
            if m:
                tool_id = m.group(1)
                _debug_log(f"Detected existing tool {tool_id}, attempting to unregister it")
                _unregister_tool_by_bl_id(tool_id)
                try:
                    _cleanup_addon(module_name)
                except Exception:
                    pass
                try:
                    addon_utils.enable(module_name, default_set=default_set)
                    return ('ok', None)
                except Exception as e2:
                    _debug_log(f"Retry enable(default_set={default_set}) failed for {module_name}: {e2}")
                    return ('tool_conflict', str(e2))
        except Exception:
            pass
        # Preference access errors may indicate addon expects to be in preferences.
        # Be conservative: only treat as requires_pref if the missing key or message mentions this module.
        try:
            mkey = re.search(r'key "([^"]+)"', msg)
            module_last = module_name.lower().split('.')[-1]
            module_lower = module_name.lower()
            if mkey:
                keystr = mkey.group(1).lower()
                if module_last in keystr or module_lower in keystr or keystr.endswith(module_last) or keystr.endswith(module_lower) or keystr.endswith('bl_ext.' + module_lower):
                    return ('requires_pref', msg)
            # fallback: if message mentions preferences.addons and module name, treat as requires_pref
            if 'preferences.addons' in msg.lower() and (module_last in msg.lower() or module_lower in msg.lower()):
                return ('requires_pref', msg)
        except Exception:
            pass
        return ('error', msg)


def _refresh(context):
    """操作后刷新插件列表，确保UI图标状态同步。"""
    from .config_panel import refresh_addon_list
    refresh_addon_list(context)


def _redraw_areas(context):
    """重绘所有区域。"""
    for area in context.screen.areas:
        area.tag_redraw()


def _get_selected_addons(context):
    """获取当前选中的插件列表（优先打勾，其次高亮）。

    输入:
      context - Blender 上下文
    输出:
      list - 选中的插件 item 列表，可能为空
    """
    selected = [item for item in context.scene.pmp_addon_items if item.selected]
    if not selected:
        idx = context.scene.pmp_addon_index
        items = context.scene.pmp_addon_items
        if 0 <= idx < len(items):
            selected = [items[idx]]
    return selected


def _restore_selected(context, selected_names):
    """刷新列表后恢复选中状态。

    输入:
      context - Blender 上下文
      selected_names - set of str, 需要恢复选中的模块名集合
    """
    _refresh(context)
    for item in context.scene.pmp_addon_items:
        if item.name in selected_names:
            item.selected = True


def _refresh_ui(context):
    """刷新插件列表并重绘所有区域。"""
    _refresh(context)
    _redraw_areas(context)


def _rebuild_dynamic():
    """重建动态菜单、弹出操作符、过滤操作符和图标选择操作符，并重新注册。

    在分类结构发生变化时调用，确保UI与数据一致。

    输入: 无
    输出: 无
    """
    from .menus import build_menu_classes
    new_menu_classes = build_menu_classes()
    for cls in new_menu_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    # 重建弹出菜单操作符
    from .header import build_popup_operators
    new_popup_ops = build_popup_operators()
    for cls in new_popup_ops:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    # 重建过滤操作符
    from .config_panel import build_filter_operators
    new_filter_ops = build_filter_operators()
    for cls in new_filter_ops:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    # 重建图标选择操作符
    from .config_panel import build_pick_icon_operators
    build_pick_icon_operators()


class PMP_OT_open_about(Operator):
    """打开关于/打赏弹窗，显示收款码和README。"""
    bl_idname = "pmp.open_about"
    bl_label = "关于 & 打赏"
    bl_description = "查看打赏信息和插件说明"
    bl_options = {'INTERNAL', 'REGISTER'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=210)

    def draw(self, context):
        from .config_panel import draw_about
        draw_about(self, context)
        self.layout.separator()
        self.layout.operator("pmp.close_popup", text="确定")


class PMP_OT_close_popup(Operator):
    """关闭当前弹窗。"""
    bl_idname = "pmp.close_popup"
    bl_label = "确定"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window.screen = context.window.screen
        return {'CANCELLED'}


class PMP_OT_toggle_startup(Operator):
    """切换插件是否随 Blender 启动自动加载。

    核心逻辑：PMP 配置是唯一真理源，仅更新 PMP 配置。
    实际的系统状态会在下次 Blender 启动时由 _enforce_startup 强制执行。
    
    - 开启自启：仅在 PMP 配置中标记为自启
    - 关闭自启：仅在 PMP 配置中取消自启标记
    
    当前会话的插件状态不受影响，保持兼容性。
    """
    bl_idname = "pmp.toggle_startup"
    bl_label = "切换自启"
    bl_description = "切换插件是否随 Blender 启动自动加载（仅更新PMP配置）"
    module_name: StringProperty()
    display_name: StringProperty()

    def execute(self, context):
        # 仅更新 PMP 配置，不直接操作系统状态
        cur = config.get_startup(self.module_name)
        new_val = not cur
        
        try:
            config.set_startup(self.module_name, new_val)
        except Exception as e:
            self.report({'ERROR'}, f"切换自启失败: {e}")
            return {'CANCELLED'}

        state = "自启已开启" if new_val else "自启已关闭"
        self.report({'INFO'}, f"{state}: {self.display_name}（重启后生效）")
        _refresh_ui(context)
        return {'FINISHED'}


class PMP_OT_load(Operator):
    """加载插件（使用 Blender 原生方式，在插件管理器中显示为打勾）。

    使用 addon_utils.enable(default_set=True)，这会在 Blender 插件管理器中显示为打勾状态。
    这是临时操作，不会修改 PMP 配置清单，重启后会被 _enforce_startup 覆盖。
    """
    bl_idname = "pmp.load_addon"
    bl_label = "加载"
    bl_description = "加载此插件（Blender原生方式）"
    module_name: StringProperty()
    display_name: StringProperty()

    def execute(self, context):
        # 使用 Blender 原生方式加载（default_set=True），在插件管理器中显示为打勾
        try:
            addon_utils.enable(self.module_name, default_set=True)
            _loaded_addons.add(self.module_name)
            config.set_compatibility(self.module_name, "compatible", None)
        except Exception as e:
            self.report({'ERROR'}, f"加载失败: {self.display_name} - {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已加载: {self.display_name}")
        _refresh_ui(context)
        return {'FINISHED'}


class PMP_OT_unload(Operator):
    """停用插件（使用 Blender 原生方式，在插件管理器中取消打勾）。

    使用 addon_utils.disable(default_set=True)，这会在 Blender 插件管理器中取消打勾。
    这是临时操作，不会修改 PMP 配置清单，重启后会被 _enforce_startup 覆盖。
    """
    bl_idname = "pmp.unload_addon"
    bl_label = "停用"
    bl_description = "停用此插件（Blender原生方式）"
    module_name: StringProperty()
    display_name: StringProperty()

    def execute(self, context):
        # 使用 Blender 原生方式停用（default_set=True），在插件管理器中取消打勾
        try:
            addon_utils.disable(self.module_name, default_set=True)
            _loaded_addons.discard(self.module_name)
        except Exception as e:
            self.report({'ERROR'}, f"停用失败: {self.display_name} - {e}")
            return {'CANCELLED'}

        # 清理残留注册
        try:
            _cleanup_addon(self.module_name)
        except Exception as e:
            _debug_log(f"Cleanup after disable failed for {self.module_name}: {e}")

        self.report({'INFO'}, f"已停用: {self.display_name}")
        _refresh_ui(context)
        return {'FINISHED'}


class PMP_OT_refresh_addon_list(Operator):
    """刷新插件列表，重新扫描所有已安装的插件并更新列表。"""
    bl_idname = "pmp.refresh_addon_list"
    bl_label = "刷新插件列表"
    bl_description = "重新扫描所有已安装的插件并更新列表"

    def execute(self, context):
        _refresh(context)
        self.report({'INFO'}, "插件列表已刷新")
        return {'FINISHED'}


class PMP_OT_reset_addon_system(Operator):
    """手动重置 Blender 插件系统：尝试恢复 preferences.addons 中的注册状态。

    在遇到因 preferences.addons 访问异常导致的错误时调用此操作符以修复系统状态。
    """
    bl_idname = "pmp.reset_addon_system"
    bl_label = "重置插件系统"
    bl_description = "尝试修复 Blender 的插件首选项/注册状态"

    def execute(self, context):
        try:
            _debug_log("Manual reset: scheduling restore of system addons")
            _schedule_restore_system_addons(delay=0.1)
            self.report({'INFO'}, "已调度插件系统恢复")
        except Exception as e:
            self.report({'ERROR'}, f"调度恢复失败: {e}")
        return {'FINISHED'}


class PMP_OT_restore_initial_addon_system(Operator):
    """Restore preferences.addons to the initial snapshot captured at PMP registration.

    Conservative behavior: avoid aggressive runtime cleanup that may crash Blender.
    Prefer scheduling the initial-snapshot restore and suggesting a restart when needed.
    """
    bl_idname = "pmp.restore_initial_addon_system"
    bl_label = "恢复启动时插件首选项"
    bl_description = "将 preferences.addons 恢复到插件管理器启动时的状态；遇到严重注册冲突请重启 Blender"

    def execute(self, context):
        try:
            if not _initial_pref_addons:
                self.report({'WARNING'}, "没有可用的启动快照")
                return {'CANCELLED'}

            _debug_log("Conservative restore: scheduling restore to initial prefs snapshot")

            # Refresh available modules (non-invasive)
            try:
                addon_utils.modules_refresh()
            except Exception as e:
                _debug_log(f"modules_refresh failed: {e}")

            # Schedule a non-invasive restore to the recorded startup snapshot
            _restore_to_initial_prefs(delay=0.25)

            # Inform user that a full Blender restart may still be required for some conflicts
            self.report({'INFO'}, "已调度恢复启动快照；对于工具冲突请重启 Blender 以确保彻底清理")
        except Exception as e:
            _debug_log(f"Conservative restore failed: {e}")
            self.report({'ERROR'}, f"恢复调度失败: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class PMP_OT_add_custom_category(Operator):
    """添加自定义类别，从场景属性读取ID和名称。"""
    bl_idname = "pmp.add_custom_category"
    bl_label = "添加自定义类别"
    bl_description = "添加一个新的自定义类别"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from .data import add_custom_category
        cat_id = context.scene.pmp_new_cat_id.strip()
        cat_label = context.scene.pmp_new_cat_label.strip()
        if not cat_id or not cat_label:
            self.report({'WARNING'}, "类别ID和名称不能为空")
            return {'CANCELLED'}
        if add_custom_category(cat_id, cat_label, "SCRIPT"):
            _rebuild_dynamic()
            _redraw_areas(context)
        else:
            self.report({'WARNING'}, f"类别ID已存在: {cat_id}")
            return {'CANCELLED'}
        return {'FINISHED'}


class PMP_OT_remove_custom_category(Operator):
    """移除指定的自定义类别及其相关配置。"""
    bl_idname = "pmp.remove_custom_category"
    bl_label = "移除自定义类别"
    bl_description = "移除指定的自定义类别"
    category_id: StringProperty()

    def execute(self, context):
        from .data import remove_custom_category
        if remove_custom_category(self.category_id):
            self.report({'INFO'}, f"已移除类别: {self.category_id}")
            _rebuild_dynamic()
        else:
            self.report({'WARNING'}, f"未找到类别: {self.category_id}")
            return {'CANCELLED'}
        return {'FINISHED'}


class PMP_OT_remove_category(Operator):
    """删除分类（内置或自定义），该分类下的插件将归入通用分类。

    删除前弹出确认对话框，UNCATEGORIZED 分类不可删除。
    """
    bl_idname = "pmp.remove_category"
    bl_label = "删除分类"
    bl_description = "删除此分类，其下的插件将归入通用分类"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from .data import remove_category
        if self.category_id == "UNCATEGORIZED":
            self.report({'WARNING'}, "该分类不可删除")
            return {'CANCELLED'}
        if remove_category(self.category_id):
            _rebuild_dynamic()
            _refresh_ui(context)
        else:
            self.report({'WARNING'}, f"删除分类失败: {self.category_id}")
            return {'CANCELLED'}
        return {'FINISHED'}


class PMP_OT_set_category_icon(Operator):
    """修改分类图标，将输入的图标名应用到此分类。"""
    bl_idname = "pmp.set_category_icon"
    bl_label = "修改图标"
    bl_description = "将输入的图标名应用到此分类"
    category_id: StringProperty()
    icon_name: StringProperty()

    def execute(self, context):
        from .data import set_category_icon
        icon = self.icon_name.strip() if self.icon_name else "BLANK1"
        set_category_icon(self.category_id, icon)
        self.report({'INFO'}, f"图标已修改: {self.category_id} -> {icon}")
        _rebuild_dynamic()
        return {'FINISHED'}


class PMP_OT_set_category_label(Operator):
    """修改分类名称，将输入的名称应用到此分类。"""
    bl_idname = "pmp.set_category_label"
    bl_label = "修改名称"
    bl_description = "将输入的名称应用到此分类"
    category_id: StringProperty()
    new_label: StringProperty()

    def execute(self, context):
        from .data import set_category_label
        label = self.new_label.strip() if self.new_label else ""
        if not label:
            self.report({'WARNING'}, "名称不能为空")
            return {'CANCELLED'}
        set_category_label(self.category_id, label)
        self.report({'INFO'}, f"名称已修改: {self.category_id} -> {label}")
        _rebuild_dynamic()
        return {'FINISHED'}


class PMP_OT_move_category_up(Operator):
    """将指定分类在排序列表中上移一位。"""
    bl_idname = "pmp.move_category_up"
    bl_label = "上移"
    bl_description = "将此分类上移一位"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()

    def execute(self, context):
        from .data import move_category_up
        if move_category_up(self.category_id):
            _rebuild_dynamic()
            _redraw_areas(context)
        return {'FINISHED'}


class PMP_OT_move_category_down(Operator):
    """将指定分类在排序列表中下移一位。"""
    bl_idname = "pmp.move_category_down"
    bl_label = "下移"
    bl_description = "将此分类下移一位"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()

    def execute(self, context):
        from .data import move_category_down
        if move_category_down(self.category_id):
            _rebuild_dynamic()
            _redraw_areas(context)
        return {'FINISHED'}


class PMP_OT_reset_category(Operator):
    """重置分类的图标和名称为默认值。"""
    bl_idname = "pmp.reset_category"
    bl_label = "重置"
    bl_description = "重置分类的图标和名称为默认值"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()

    def execute(self, context):
        from .data import reset_category_overrides
        if reset_category_overrides(self.category_id):
            _rebuild_dynamic()
            _redraw_areas(context)
        return {'FINISHED'}


class PMP_OT_reset_addon_categories(Operator):
    """重置所有插件的分类为无分类（通用）。

    将所有插件的分类归入通用分类，不影响分类管理中的分类设置。
    执行前弹出确认对话框。
    """
    bl_idname = "pmp.reset_addon_categories"
    bl_label = "重置插件分类"
    bl_description = "将所有插件的分类重置为无分类（通用），不影响分类设置"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        # 重置所有插件分类到通用
        for module_name in config.get_all_addons():
            cats = config.get_categories(module_name)
            if cats != ["UNCATEGORIZED"]:
                config.set_categories(module_name, ["UNCATEGORIZED"])
        # 刷新列表
        _rebuild_dynamic()
        _refresh_ui(context)
        self.report({'INFO'}, "已将所有插件分类重置为无分类")
        return {'FINISHED'}


class PMP_OT_reset_category_settings(Operator):
    """重置分类管理中的分类为初始分类。

    重置所有分类的图标和名称覆盖为默认值，
    移除所有自定义分类，恢复内置分类的显示，
    重置分类排序为默认顺序。不影响插件的分类归属。
    执行前弹出确认对话框。
    """
    bl_idname = "pmp.reset_category_settings"
    bl_label = "重置分类设置"
    bl_description = "将分类管理中的分类重置为初始分类，不影响插件分类归属"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from .data import reset_category_overrides, get_custom_categories, remove_custom_category
        from .data import _hidden_builtin_ids, _category_order, _save_config
        # 1. 重置所有分类的图标和名称覆盖
        for cat in data.get_all_categories(include_hidden=True):
            reset_category_overrides(cat['id'])
        # 2. 移除所有自定义分类
        for cat in get_custom_categories():
            remove_custom_category(cat['id'])
        # 3. 恢复内置分类的显示（清除隐藏标记）
        _hidden_builtin_ids.clear()
        _save_config()
        # 4. 重置分类排序为默认顺序
        _category_order.clear()
        _save_config()
        # 刷新
        _rebuild_dynamic()
        _refresh_ui(context)
        self.report({'INFO'}, "已将分类设置重置为初始状态")
        return {'FINISHED'}


class PMP_OT_toggle_select_item(Operator):
    """切换列表中单个插件的选中状态（打勾/取消打勾）。"""
    bl_idname = "pmp.toggle_select_item"
    bl_label = "切换选中"
    bl_description = "切换此插件的选中状态"
    bl_options = {'INTERNAL'}

    item_index: IntProperty()

    def execute(self, context):
        items = context.scene.pmp_addon_items
        if 0 <= self.item_index < len(items):
            items[self.item_index].selected = not items[self.item_index].selected
        return {'FINISHED'}


class PMP_OT_select_all(Operator):
    """全选当前列表中的所有插件。"""
    bl_idname = "pmp.select_all"
    bl_label = "全选"
    bl_description = "选中当前列表中的所有插件"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        for item in context.scene.pmp_addon_items:
            item.selected = True
        return {'FINISHED'}


class PMP_OT_deselect_all(Operator):
    """取消选中当前列表中的所有插件。"""
    bl_idname = "pmp.deselect_all"
    bl_label = "取消全选"
    bl_description = "取消选中当前列表中的所有插件"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        for item in context.scene.pmp_addon_items:
            item.selected = False
        return {'FINISHED'}


class PMP_OT_batch_add_category(Operator):
    """为插件切换指定分类（已有则移除，没有则添加）。

    支持两种模式：
    - 有打勾的插件：对打勾的插件批量操作
    - 无打勾但有高亮插件：对当前高亮的单个插件操作
    """
    bl_idname = "pmp.batch_add_category"
    bl_label = "切换分类"
    bl_description = "为插件切换分类归属（已有则移除，没有则添加）"
    bl_options = {'INTERNAL'}

    category_id: StringProperty()

    def execute(self, context):
        selected = _get_selected_addons(context)
        if not selected:
            self.report({'WARNING'}, "没有选中的插件")
            return {'CANCELLED'}
        selected_names = {item.name for item in selected}
        # 判断操作方向：如果所有选中插件都已属于该分类，则移除；否则添加
        all_in_cat = all(self.category_id in config.get_categories(item.name) for item in selected)
        add_count = 0
        remove_count = 0
        for item in selected:
            cats = config.get_categories(item.name)
            if all_in_cat:
                # 移除分类（至少保留一个分类）
                if self.category_id in cats and len(cats) > 1:
                    cats.remove(self.category_id)
                    config.set_categories(item.name, cats)
                    remove_count += 1
            else:
                # 添加分类
                if self.category_id not in cats:
                    cats.append(self.category_id)
                    config.set_categories(item.name, cats)
                    add_count += 1
        # 刷新列表并恢复选中状态
        _restore_selected(context, selected_names)
        # 获取分类标签
        cat_label = self.category_id
        for cat in data.get_all_categories(include_hidden=True):
            if cat['id'] == self.category_id:
                cat_label = cat['label']
                break
        if add_count > 0:
            self.report({'INFO'}, f"已为 {add_count} 个插件添加分类「{cat_label}」")
        elif remove_count > 0:
            self.report({'INFO'}, f"已为 {remove_count} 个插件移除分类「{cat_label}」")
        else:
            self.report({'INFO'}, "无需更改")
        return {'FINISHED'}


class PMP_OT_uncategorize(Operator):
    """将插件的分类设置为未分类（通用）。

    支持两种模式：
    - 有打勾的插件：对打勾的插件批量操作
    - 无打勾但有高亮插件：对当前高亮的单个插件操作
    """
    bl_idname = "pmp.uncategorize"
    bl_label = "取消分类"
    bl_description = "将插件的分类设置为未分类"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        selected = _get_selected_addons(context)
        if not selected:
            self.report({'WARNING'}, "没有选中的插件")
            return {'CANCELLED'}
        selected_names = {item.name for item in selected}
        count = 0
        for item in selected:
            cats = config.get_categories(item.name)
            if cats != ["UNCATEGORIZED"]:
                config.set_categories(item.name, ["UNCATEGORIZED"])
                count += 1
        # 刷新列表并恢复选中状态
        _restore_selected(context, selected_names)
        if count > 0:
            self.report({'INFO'}, f"已将 {count} 个插件设为未分类")
        else:
            self.report({'INFO'}, "选中的插件已是未分类")
        return {'FINISHED'}


class PMP_OT_reset_addons_category(Operator):
    """重置指定分类下的所有插件：停用->清理->重新启用（优先会话内）。"""
    bl_idname = "pmp.reset_addons_category"
    bl_label = "重置分类插件"
    bl_description = "停用并重新加载此分类下的所有插件（优先会话内）"
    bl_options = {'INTERNAL'}
    category_id: StringProperty()

    def execute(self, context):
        mods = config.get_addons_by_category(self.category_id)
        if not mods:
            self.report({'INFO'}, "该分类下无插件可重置")
            return {'FINISHED'}
        # 如果没有初始快照，则退回到原有逐个重置行为（兼容）
        if not _initial_pref_addons:
            _debug_log("No initial snapshot available, falling back to full reset behavior")
            return self._full_reset(context, mods)

        success = 0
        failed = 0
        for m in mods:
            try:
                desired_pref = (m in _initial_pref_addons)
                now_in_prefs = _is_addon_in_preferences(m)

                # 如果初始快照要求此插件为自启，但当前未设置，自启动并启用
                if desired_pref and not now_in_prefs:
                    try:
                        addon_utils.enable(m, default_set=True)
                        _loaded_addons.add(m)
                        success += 1
                        continue
                    except Exception as e:
                        _debug_log(f"Failed to enable pref addon {m}: {e}")
                        failed += 1
                        continue

                # 如果初始快照要求此插件不自启，但当前有首选项条目，则移除并尝试停用会话
                if (not desired_pref) and now_in_prefs:
                    try:
                        _safe_remove_pref_addon(m)
                    except Exception as e:
                        _debug_log(f"Failed to remove pref addon {m}: {e}")
                    try:
                        addon_utils.disable(m, default_set=False)
                        _loaded_addons.discard(m)
                    except Exception as e:
                        _debug_log(f"Failed to disable runtime for {m}: {e}")
                    success += 1
                    continue

                # 否则，确保运行时状态与首选项一致：如果应自启且未运行，启用（不再重复 prefs 操作）
                if desired_pref and not _is_addon_enabled(m):
                    try:
                        addon_utils.enable(m, default_set=True)
                        _loaded_addons.add(m)
                        success += 1
                    except Exception as e:
                        _debug_log(f"Failed to ensure enabled for {m}: {e}")
                        failed += 1
                elif (not desired_pref) and _is_addon_enabled(m):
                    try:
                        addon_utils.disable(m, default_set=False)
                        _loaded_addons.discard(m)
                        success += 1
                    except Exception as e:
                        _debug_log(f"Failed to ensure disabled for {m}: {e}")
                        failed += 1
                else:
                    # 已与初始状态一致，无需操作
                    success += 1
            except Exception as e:
                _debug_log(f"Reset failed for {m}: {e}")
                failed += 1

        if failed:
            self.report({'WARNING'}, f"重置完成（按启动快照）: 成功 {success}, 失败 {failed}")
        else:
            self.report({'INFO'}, f"重置完成（按启动快照）: 成功 {success}")
        _refresh_ui(context)
        return {'FINISHED'}

    def _full_reset(self, context, mods):
        """兼容回退：原先的逐插件停用→清理→启用流程。"""
        success = 0
        failed = 0
        for m in mods:
            try:
                try:
                    addon_utils.disable(m, default_set=False)
                except Exception:
                    pass
                try:
                    _cleanup_addon(m)
                except Exception:
                    pass
                try:
                    addon_utils.enable(m, default_set=False)
                    _loaded_addons.add(m)
                    success += 1
                except Exception as e:
                    _debug_log(f"Session enable failed for {m}: {e}")
                    try:
                        addon_utils.enable(m, default_set=True)
                        _loaded_addons.add(m)
                        success += 1
                    except Exception as e2:
                        _debug_log(f"Fallback enable failed for {m}: {e2}")
                        failed += 1
            except Exception as e:
                _debug_log(f"Reset failed for {m}: {e}")
                failed += 1
        if failed:
            self.report({'WARNING'}, f"重置完成: 成功 {success}, 失败 {failed}")
        else:
            self.report({'INFO'}, f"重置完成: 成功 {success}")
        _refresh_ui(context)
        return {'FINISHED'}

class PMP_OT_batch_toggle_startup(Operator):
    """批量切换选中插件的自启状态。

    判断逻辑：如果所有选中插件都已开启自启，则统一关闭；
    否则统一开启。这样用户点击按钮的结果是可预测的。
    """
    bl_idname = "pmp.batch_toggle_startup"
    bl_label = "批量切换自启"
    bl_description = "统一开启或关闭选中插件的自启状态"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        selected = _get_selected_addons(context)
        if not selected:
            self.report({'WARNING'}, "没有选中的插件")
            return {'CANCELLED'}
        selected_names = {item.name for item in selected}
        # 判断操作方向：如果所有选中插件都已开启自启，则统一关闭；否则统一开启
        new_val = not all(_is_addon_in_preferences(item.name) for item in selected)
        on_count = 0
        off_count = 0
        for item in selected:
            cur = _is_addon_in_preferences(item.name)
            config.set_startup(item.name, new_val)
            if new_val and not cur:
                # 开启自启
                try:
                    addon_utils.enable(item.name, default_set=True)
                    _loaded_addons.add(item.name)
                    on_count += 1
                except Exception:
                    pass
            elif not new_val and cur:
                # 关闭自启：仅从 preferences.addons 移除条目，不停用插件
                try:
                    _safe_remove_pref_addon(item.name)
                except Exception:
                    pass
                off_count += 1
        # 刷新列表并恢复选中状态
        _restore_selected(context, selected_names)
        if new_val:
            self.report({'INFO'}, f"已开启 {on_count} 个插件的自启")
        else:
            self.report({'INFO'}, f"已关闭 {off_count} 个插件的自启")
        return {'FINISHED'}


classes = (
    PMP_OT_open_about,
    PMP_OT_close_popup,
    PMP_OT_toggle_startup,
    PMP_OT_load,
    PMP_OT_unload,
    PMP_OT_refresh_addon_list,
    PMP_OT_reset_addon_system,
    PMP_OT_restore_initial_addon_system,
    PMP_OT_reset_addons_category,
    PMP_OT_add_custom_category,
    PMP_OT_remove_custom_category,
    PMP_OT_set_category_icon,
    PMP_OT_set_category_label,
    PMP_OT_move_category_up,
    PMP_OT_move_category_down,
    PMP_OT_reset_category,
    PMP_OT_remove_category,
    PMP_OT_reset_addon_categories,
    PMP_OT_reset_category_settings,
    PMP_OT_toggle_select_item,
    PMP_OT_select_all,
    PMP_OT_deselect_all,
    PMP_OT_batch_add_category,
    PMP_OT_uncategorize,
    PMP_OT_batch_toggle_startup,
)
