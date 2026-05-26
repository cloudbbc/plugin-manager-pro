# ==============================================================================
# Copyright (c) 2025 terryye. All rights reserved.
#
# 文件名: __init__.py
# 模块作用: Plugin Manager Pro 插件入口模块，负责插件的注册/注销流程、
#           启动配置强制执行及延迟刷新。
# 作者: terryye
# 日期: 2025-06-05
# ==============================================================================

bl_info = {
    "name": "Plugin Manager Pro",
    "author": "terryye",
    "version": (5, 2, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Header (right of Options)",
    "description": "Advanced plugin manager: Editor-type categories + startup control + on-demand loading",
    "category": "System",
}

import bpy
import addon_utils
from . import config, header
from .operators import classes as operator_classes
# logging helper from operators
from .operators import _debug_log
from . import menus
from . import config_panel


def _enforce_startup():
    """启动时同步 PMP 自启配置到 Blender 的启动设置。

    该函数通过定时器在 Blender 启动后延迟执行（2秒）。
    核心逻辑：PMP 配置清单是唯一真理源，接管系统的插件管理。

    - 遍历所有插件，根据 PMP 配置的自启状态重新初始化系统状态
    - PMP 标记为自启的插件 → enable(default_set=True) 确保启用并设为自启
    - PMP 标记为非自启的插件 → disable(default_set=True) 确保停用并从 preferences.addons 移除
    
    首次使用时，将当前所有已启用插件的自启状态同步到 PMP 配置。

    输入: 无（读取 config 模块中的启动配置）
    输出: None
    """
    try:
        config.load()
        my_name = __package__

        # 检查 PMP 配置是否为首次使用（配置为空）
        is_first_use = not config.has_user_config()

        # 先刷新模块列表，确保检测到所有已安装插件
        addon_utils.modules_refresh()
        
        if is_first_use:
            # 首次使用：将当前所有插件的启用状态同步到 PMP 配置
            for mod in addon_utils.modules():
                name = mod.__name__
                if name == my_name or name.startswith(my_name + "."):
                    continue
                try:
                    from .operators import _is_addon_enabled
                    is_enabled = _is_addon_enabled(name)
                except Exception:
                    is_enabled = False
                
                config.set_startup(name, is_enabled)
                if is_enabled:
                    _debug_log(f"First-use sync: {name} -> startup=True")
            
            _debug_log("First-use detected: synced currently enabled addons to PMP config.")
        else:
            # 非首次使用：PMP 接管系统，根据 PMP 配置重新初始化系统状态
            for mod in addon_utils.modules():
                name = mod.__name__
                if name == my_name or name.startswith(my_name + "."):
                    continue
                
                if name not in config.get_all_addons():
                    continue
                
                pmp_startup = config.get_startup(name)
                
                try:
                    from .operators import _is_addon_enabled, _is_addon_in_preferences
                    is_enabled = _is_addon_enabled(name)
                    in_prefs = _is_addon_in_preferences(name)
                except Exception:
                    is_enabled = False
                    in_prefs = False
                
                if pmp_startup:
                    # PMP 标记为自启 → 确保插件启用并设为自启
                    if not is_enabled or not in_prefs:
                        try:
                            addon_utils.enable(name, default_set=True)
                            from .operators import _loaded_addons
                            _loaded_addons.add(name)
                            _debug_log(f"PMP enforce: {name} -> enabled & startup")
                        except Exception as e:
                            _debug_log(f"Warning: Failed to enable {name}: {e}")
                else:
                    # PMP 标记为非自启 → 确保插件停用并从 preferences.addons 移除
                    if is_enabled or in_prefs:
                        try:
                            addon_utils.disable(name, default_set=True)
                            from .operators import _loaded_addons
                            _loaded_addons.discard(name)
                            _debug_log(f"PMP enforce: {name} -> disabled & no startup")
                        except Exception as e:
                            _debug_log(f"Warning: Failed to disable {name}: {e}")

        # 【关键修复】在 _enforce_startup 执行完成后，重新初始化 _loaded_addons 集合
        # 确保它与实际的系统状态一致，避免被之前会话的临时加载状态污染
        from .operators import _init_loaded_addons
        _init_loaded_addons()
        _debug_log("_loaded_addons reinitialized after _enforce_startup")

    except Exception as e:
        _debug_log(f"Error in _enforce_startup: {e}")
    return None


def _delayed_refresh():
    """延迟刷新插件列表，确保所有属性已注册后再填充数据。

    该函数通过定时器在注册完成后延迟1秒执行，
    避免在属性尚未完全注册时刷新导致错误。
    仅执行一次（返回 None 而非时间间隔）。

    输入: 无
    输出: None（只执行一次，不重复）
    """
    try:
        for window in bpy.context.window_manager.windows:
            config_panel.refresh_addon_list(bpy.context)
            break
    except Exception:
        pass
    return None  # 只执行一次


def register():
    """插件注册入口：按顺序注册所有模块、操作符、面板、菜单和定时器。

    注册顺序：
    1. 加载配置（config.load）—— 菜单绘制依赖分类数据
    2. 注册操作符（operators.classes）
    3. 构建并注册动态菜单类（menus.build_menu_classes）
    4. 构建分类过滤操作符（config_panel.build_filter_operators）
    5. 注册配置面板模块（config_panel.register）
    6. 构建弹出菜单操作符（header.build_popup_operators）
    7. 注册 Header 绘制函数（header.register）
    8. 注册启动强制器定时器（_enforce_startup，延迟2秒）
    9. 注册延迟刷新定时器（_delayed_refresh，延迟1秒）

    输入: 无
    输出: 无
    """
    # 先加载配置（必须在菜单注册之前，因为菜单绘制需要读取分类数据）
    config.load()
    # 捕获 Blender 启动时的 preferences.addons 快照，便于后续执行“恢复到启动状态”操作
    try:
        from .operators import _capture_initial_prefs
        _capture_initial_prefs()
    except Exception:
        pass

    # 注册操作符（先尝试注销，以防重复注册）
    for cls in operator_classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    for cls in operator_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            _debug_log(f"Warning: Failed to register {cls.__name__}: {e}")

    # 重建菜单类（支持动态自定义类别）
    menu_classes = menus.build_menu_classes()
    for cls in menu_classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    for cls in menu_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            _debug_log(f"Warning: Failed to register {cls.__name__}: {e}")

    # 构建分类过滤操作符（必须在 config_panel.register 之前，因为 register() 会注册这些操作符）
    config_panel.build_filter_operators()

    # 注册配置面板模块
    try:
        config_panel.unregister()
    except Exception:
        pass

    config_panel.register()

    # 构建弹出菜单操作符（必须在 header.register 之前）
    header.build_popup_operators()

    # 注册 Header 绘制函数
    try:
        header.unregister()
    except Exception:
        pass

    header.register()

    # 设置启动强制器定时器
    try:
        bpy.app.timers.unregister(_enforce_startup)
    except Exception:
        pass

    bpy.app.timers.register(_enforce_startup, first_interval=2.0)

    # 初始化已加载插件集合
    from .operators import _init_loaded_addons
    _init_loaded_addons()

    # 延迟刷新插件列表（确保所有属性已注册）
    try:
        bpy.app.timers.unregister(_delayed_refresh)
    except Exception:
        pass

    bpy.app.timers.register(_delayed_refresh, first_interval=1.0)

    _debug_log("Plugin Manager Pro registered.")


def unregister():
    """插件注销入口：逆序注销所有已注册的模块、定时器和绘制函数。

    注销顺序（与注册相反）：
    1. 移除定时器（_enforce_startup, _delayed_refresh）
    2. 注销 Header 绘制
    3. 注销配置面板
    4. 逆序注销菜单类
    5. 逆序注销操作符

    输入: 无
    输出: 无
    """
    # 清空已加载插件集合
    from .operators import _loaded_addons
    _loaded_addons.clear()

    # 移除定时器
    try:
        bpy.app.timers.unregister(_enforce_startup)
    except Exception:
        pass

    try:
        bpy.app.timers.unregister(_delayed_refresh)
    except Exception:
        pass

    # 注销 Header
    try:
        header.unregister()
    except Exception:
        pass

    # 注销配置面板
    try:
        config_panel.unregister()
    except Exception:
        pass

    # 注销菜单（逆序）
    menu_classes = menus.menu_classes
    for cls in reversed(menu_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    # 注销操作符（逆序）
    for cls in reversed(operator_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    _debug_log("Plugin Manager Pro unregistered.")
