"""Stand-in for bpy.types.UILayout that records a tree of elements instead of drawing.

This lets us run the original Python `draw()` methods of Blender's panels and menus
(scripts/startup/bl_ui/*.py as well as add-on panels) and build the result in Qt.
Unknown methods (`template_*` etc.) are recorded as 'unsupported' and do no harm.
"""
import inspect
import types

import bpy

from .bridge import tr

_INHERIT = ("use_property_split", "use_property_decorate", "active", "enabled", "alert",
            "operator_context", "ctx_ptrs", "emboss")
_DEFAULTS = {
    "active": True, "enabled": True, "alert": False, "use_property_split": False,
    "use_property_decorate": False, "operator_context": "EXEC_REGION_WIN", "scale_x": 1.0,
    "scale_y": 1.0, "alignment": "EXPAND", "emboss": "NORMAL", "ui_units_x": 0.0,
    "ui_units_y": 0.0, "activate_init": False, "active_default": False, "ctx_ptrs": None,
    "direction": "VERTICAL", "use_property_split_decorate": False,
}


class Node:
    __slots__ = ("kind", "args", "children", "flags")

    def __init__(self, kind, args=None, flags=None):
        self.kind = kind
        self.args = args or {}
        self.children = []
        self.flags = flags or {}

    def signature(self):
        """Tree structure used to decide whether to rebuild the widgets."""
        parts = [self.kind]
        for k, v in self.args.items():
            if k == "props":
                parts.append(repr(sorted(v.items())) if isinstance(v, dict) else "")
                continue
            if hasattr(v, "as_pointer"):
                try:
                    v = v.as_pointer()
                except Exception:
                    v = id(v)
            elif not isinstance(v, (str, int, float, bool, type(None), tuple)):
                v = type(v).__name__
            parts.append(f"{k}={v!r}")
        parts.append(repr(sorted((k, v) for k, v in self.flags.items()
                                 if k in ("enabled", "active", "use_property_split"))))
        return "(" + ",".join(parts) + "[" + ";".join(c.signature() for c in self.children) + "])"


class OpProps:
    """Return value of layout.operator(): records the operator properties that get set."""

    def __init__(self, store):
        object.__setattr__(self, "_store", store)

    def __setattr__(self, k, v):
        self._store[k] = v

    def __getattr__(self, k):
        return self._store.get(k)


class FakeLayout:
    def __init__(self, kind="column", parent_flags=None, **args):
        flags = dict(_DEFAULTS)
        if parent_flags:
            for k in _INHERIT:
                if k in parent_flags:
                    flags[k] = parent_flags[k]
        object.__setattr__(self, "node", Node(kind, args, flags))

    # --- attributes like on UILayout
    def __setattr__(self, k, v):
        self.node.flags[k] = v

    def __getattr__(self, k):
        flags = object.__getattribute__(self, "node").flags
        if k in flags:
            return flags[k]
        if k.startswith("__"):
            raise AttributeError(k)
        # unknown method → record it and return a nested layout so chaining does not fail
        def _unsupported(*a, **kw):
            return self._child("unsupported", name=k)
        return _unsupported

    def _snap(self):
        f = self.node.flags
        return {k: f.get(k) for k in ("active", "enabled", "alert", "use_property_split",
                                      "use_property_decorate", "ctx_ptrs", "alignment", "emboss")}

    def _child(self, kind, **args):
        child = FakeLayout(kind, self.node.flags, **args)
        self.node.children.append(child.node)
        return child

    def _item(self, kind, **args):
        n = Node(kind, args, self._snap())
        self.node.children.append(n)
        return n

    # --- containers
    def row(self, align=False, heading="", heading_ctxt="", translate=True):
        return self._child("row", align=align, heading=tr(heading) if translate else heading)

    def column(self, align=False, heading="", heading_ctxt="", translate=True):
        return self._child("column", align=align, heading=tr(heading) if translate else heading)

    def box(self):
        return self._child("box")

    def split(self, factor=0.0, align=False):
        return self._child("split", factor=factor, align=align)

    def grid_flow(self, row_major=False, columns=0, even_columns=False, even_rows=False, align=False):
        return self._child("flow", columns=columns, row_major=row_major)

    def column_flow(self, columns=0, align=False):
        return self._child("flow", columns=columns, row_major=False)

    def menu_pie(self):
        return self._child("column")

    def panel(self, idname, default_closed=False):
        p = self._child("lpanel", idname=idname, default_closed=default_closed)
        header = p._child("row")
        body = p._child("column")
        return header, body

    def panel_prop(self, data, property):
        p = self._child("lpanel", idname=f"prop:{property}", default_closed=False)
        header = p._child("row")
        body = p._child("column")
        return header, body

    # --- items
    def label(self, text="", text_ctxt="", translate=True, icon="NONE", icon_value=0):
        self._item("label", text=tr(text) if translate else text, icon=icon)

    def separator(self, factor=1.0, type="AUTO"):
        self._item("separator", factor=factor)

    def separator_spacer(self):
        self._item("spacer")

    def prop(self, data, property, text=None, text_ctxt="", translate=True, icon="NONE",
             placeholder="", expand=False, slider=False, toggle=-1, icon_only=False,
             event=False, full_event=False, emboss=True, index=-1, icon_value=0,
             invert_checkbox=False, **_kw):
        if data is None:
            return
        self._item("prop", data=data, prop=property,
                   text=(tr(text) if translate else text) if text is not None else None,
                   expand=expand, slider=slider, toggle=toggle, icon_only=icon_only,
                   index=index, icon=icon, invert=invert_checkbox)

    prop_with_popover = prop
    prop_with_menu = prop

    def props_enum(self, data, property):
        self.prop(data, property, expand=True)

    prop_tabs_enum = props_enum

    def prop_enum(self, data, property, value, text=None, text_ctxt="", translate=True,
                  icon="NONE", icon_value=0):
        if data is None:
            return
        self._item("prop_enum", data=data, prop=property, value=value,
                   text=(tr(text) if translate else text) if text is not None else None)

    def prop_menu_enum(self, data, property, text=None, text_ctxt="", translate=True, icon="NONE"):
        self.prop(data, property, text=text, translate=translate)

    def prop_search(self, data, property, search_data, search_property, text=None,
                    text_ctxt="", translate=True, icon="NONE", results_are_suggestions=False, **_kw):
        if data is None:
            return
        self._item("prop_search", data=data, prop=property, search_data=search_data,
                   search_prop=search_property,
                   text=(tr(text) if translate else text) if text is not None else None)

    def prop_decorator(self, data, property, index=-1):
        pass

    def operator(self, operator, text=None, text_ctxt="", translate=True, icon="NONE",
                 emboss=True, depress=False, icon_value=0, **_kw):
        props = {}
        self._item("operator", idname=operator,
                   text=(tr(text) if translate else text) if text is not None else None,
                   icon=icon, props=props, depress=depress,
                   op_ctx=self.node.flags.get("operator_context"))
        return OpProps(props)

    operator_menu_hold = operator

    def operator_enum(self, operator, property, icon_only=False):
        self._item("operator_enum", idname=operator, prop=property)

    def operator_menu_enum(self, operator, property, text=None, text_ctxt="", translate=True, icon="NONE"):
        props = {}
        self._item("operator_menu_enum", idname=operator, prop=property, props=props,
                   text=(tr(text) if translate else text) if text is not None else None)
        return OpProps(props)

    def menu(self, menu, text=None, text_ctxt="", translate=True, icon="NONE", icon_value=0):
        self._item("menu", menu=menu,
                   text=(tr(text) if translate else text) if text is not None else None)

    def menu_contents(self, menu):
        cls = find_menu_class(menu)
        if cls is not None:
            run_draw(cls, self, bpy.context)

    def popover(self, panel, text="", text_ctxt="", translate=True, icon="NONE", icon_value=0, **_kw):
        self._item("popover", panel=panel, text=tr(text) if translate else text)

    def popover_group(self, *a, **kw):
        pass

    def context_pointer_set(self, name, data):
        ptrs = dict(self.node.flags.get("ctx_ptrs") or {})
        ptrs[name] = data
        self.node.flags["ctx_ptrs"] = ptrs

    def context_string_set(self, name, value):
        pass

    def template_list(self, listtype_name, list_id="", dataptr=None, propname="",
                      active_dataptr=None, active_propname="", item_dyntip_propname="",
                      rows=5, maxrows=5, type="DEFAULT", columns=9, sort_reverse=False,
                      sort_lock=False, **_kw):
        if dataptr is None:
            return
        self._item("template_list", data=dataptr, prop=propname, active_data=active_dataptr,
                   active_prop=active_propname, rows=rows)

    def template_ID(self, data, property, new="", open="", unlink="", filter="ALL",
                    live_icon=False, text="", text_ctxt="", translate=True, **_kw):
        if data is None:
            return
        self._item("template_id", data=data, prop=property, new=new, open=open, unlink=unlink,
                   text=tr(text) if translate else text)

    template_ID_preview = template_ID
    template_any_ID = template_ID

    def template_ID_tabs(self, data, property, new="", menu="", filter="ALL"):
        self.template_ID(data, property, new=new)

    def template_search(self, data, property, search_data, search_property, new="", unlink="",
                        text="", text_ctxt="", translate=True, **_kw):
        self.prop_search(data, property, search_data, search_property, text=text or None)

    def template_action(self, id, new="", unlink="", **_kw):
        ad = getattr(id, "animation_data", None)
        if ad is not None:
            self.template_ID(ad, "action", new=new, unlink=unlink)

    def template_node_view(self, ntree, node, socket):
        self._item("node_view", ntree=ntree, node=node, socket=socket)

    def template_image_settings(self, image_settings, color_management=False):
        self._item("struct", data=image_settings)

    def template_colormanaged_view_settings(self, data, property):
        self._item("struct", data=getattr(data, property, None))

    def template_preview(self, *a, **kw):
        pass

    def template_header(self, *a, **kw):
        pass

    def template_icon(self, *a, **kw):
        pass

    def template_recent_files(self, rows=5):
        return 0


# ---------------------------------------------------------------- shim for self in draw()
class Shim:
    """Acts as `self` inside Panel.draw / Menu.draw."""

    def __init__(self, cls, layout):
        d = self.__dict__
        d["_cls"] = cls
        d["layout"] = layout
        d["is_popover"] = False
        d["text"] = getattr(cls, "bl_label", "")
        d["bl_label"] = getattr(cls, "bl_label", "")

    def __getattr__(self, name):
        cls = self.__dict__["_cls"]
        val = getattr(cls, name)
        if inspect.isfunction(val):
            try:
                raw = inspect.getattr_static(cls, name)
            except AttributeError:
                raw = val
            if isinstance(raw, staticmethod):
                return val
            return types.MethodType(val, self)
        return val

    def __setattr__(self, k, v):
        self.__dict__[k] = v


def run_draw(cls, layout, context, method="draw"):
    fn = getattr(cls, method, None)
    if fn is None:
        return True
    shim = Shim(cls, layout)
    try:
        if inspect.ismethod(fn):          # classmethod
            fn(context)
        else:
            fn(shim, context)
        return True
    except Exception as ex:
        layout._item("label", text=f"⚠ {cls.__name__}: {ex}", icon="ERROR")
        return False


def safe_poll(cls, context):
    poll = getattr(cls, "poll", None)
    if poll is None:
        return True
    try:
        return bool(poll(context))
    except Exception:
        return False


# ---------------------------------------------------------------- class lookup
def _all_subclasses(base):
    seen = []
    stack = list(base.__subclasses__())
    ids = set()
    while stack:
        c = stack.pop(0)
        if id(c) in ids:
            continue
        ids.add(id(c))
        seen.append(c)
        stack.extend(c.__subclasses__())
    return seen


def _registered(cls):
    try:
        return bool(cls.is_registered)
    except Exception:
        return False


def class_id(cls):
    return getattr(cls, "bl_idname", "") or cls.__name__


def find_menu_class(idname):
    cls = getattr(bpy.types, idname, None)
    if cls is not None:
        return cls
    for c in _all_subclasses(bpy.types.Menu):
        if class_id(c) == idname and _registered(c):
            return c
    return None


def find_panel_class(idname):
    cls = getattr(bpy.types, idname, None)
    if cls is not None:
        return cls
    for c in _all_subclasses(bpy.types.Panel):
        if class_id(c) == idname and _registered(c):
            return c
    return None


def properties_panels(context_name):
    """Panel tree of the Properties editor for a given bl_context: [(cls, [children…]), …]."""
    classes = []
    for c in _all_subclasses(bpy.types.Panel):
        if not _registered(c):
            continue
        if getattr(c, "bl_space_type", "") != "PROPERTIES":
            continue
        if getattr(c, "bl_region_type", "WINDOW") != "WINDOW":
            continue
        if getattr(c, "bl_context", "") != context_name and not getattr(c, "bl_parent_id", ""):
            continue
        classes.append(c)
    by_id = {class_id(c): c for c in classes}
    children = {}
    top = []
    for c in classes:
        parent = getattr(c, "bl_parent_id", "")
        if parent:
            if parent in by_id:
                children.setdefault(parent, []).append(c)
        elif getattr(c, "bl_context", "") == context_name:
            top.append(c)

    def order(lst):
        return sorted(lst, key=lambda c: getattr(c, "bl_order", 0))

    def build(c):
        return (c, [build(ch) for ch in order(children.get(class_id(c), []))])

    return [build(c) for c in order(top)]


# ---------------------------------------------------------------- context for Properties
class FakeSpace:
    type = "PROPERTIES"
    pin_id = None
    use_pin_id = False

    def __init__(self, tab):
        self.context = tab.upper()

    def __getattr__(self, k):
        return None


class ContextProxy:
    def __init__(self, overrides):
        self.__dict__["_o"] = overrides

    def __getattr__(self, name):
        o = self.__dict__["_o"]
        if name in o:
            return o[name]
        return getattr(bpy.context, name)

    def path_resolve(self, path, coerce=True):
        head, sep, rest = path.partition(".")
        obj = getattr(self, head)
        if sep and obj is not None:
            obj = obj.path_resolve(rest, coerce)
        return obj


_DATA_KEYS = {
    "MESH": "mesh", "CURVE": "curve", "SURFACE": "curve", "FONT": "curve", "META": "meta_ball",
    "ARMATURE": "armature", "LATTICE": "lattice", "CAMERA": "camera", "LIGHT": "light",
    "SPEAKER": "speaker", "LIGHT_PROBE": "lightprobe", "VOLUME": "volume",
    "POINTCLOUD": "pointcloud", "CURVES": "curves", "GREASEPENCIL": "grease_pencil",
    "GPENCIL": "gpencil",
}
_PHYS = {"cloth": "CLOTH", "soft_body": "SOFT_BODY", "fluid": "FLUID",
         "collision": "COLLISION", "dynamic_paint": "DYNAMIC_PAINT"}


def properties_context(tab):
    ctx = bpy.context
    scene = ctx.scene
    vl = ctx.view_layer
    ob = vl.objects.active if vl else None
    o = {"space_data": FakeSpace(tab), "engine": scene.render.engine, "texture": None,
         "texture_slot": None, "texture_user": None, "texture_node": None, "brush": None,
         "line_style": None, "particle_system": None, "particle_settings": None,
         "material": None, "material_slot": None, "bone": None, "edit_bone": None,
         "pose_bone": None, "world": scene.world, "object": ob, "modifier": None}
    for key in set(_DATA_KEYS.values()):
        o[key] = None
    for key in _PHYS:
        o[key] = None
    try:
        o["collection"] = vl.active_layer_collection.collection
    except Exception:
        o["collection"] = None
    if ob is not None:
        key = _DATA_KEYS.get(ob.type)
        if key and ob.data is not None:
            o[key] = ob.data
        o["material"] = ob.active_material
        if len(ob.material_slots):
            idx = min(ob.active_material_index, len(ob.material_slots) - 1)
            o["material_slot"] = ob.material_slots[idx]
        psys = getattr(ob, "particle_systems", None)
        if psys is not None and psys.active is not None:
            o["particle_system"] = psys.active
            o["particle_settings"] = psys.active.settings
        for key, mtype in _PHYS.items():
            for m in ob.modifiers:
                if m.type == mtype:
                    o[key] = m
                    break
        if ob.type == "ARMATURE":
            arm = ob.data
            o["bone"] = arm.bones.active
            if arm.bones.active and ob.pose:
                o["pose_bone"] = ob.pose.bones.get(arm.bones.active.name)
            o["edit_bone"] = arm.edit_bones.active if ob.mode == "EDIT" else None
    return ContextProxy(o)


def record_panel(cls, context):
    """Returns (header_node|None, body_node), or None if poll fails."""
    if not safe_poll(cls, context):
        return None
    header = None
    if getattr(cls, "draw_header", None) is not None:
        hl = FakeLayout("row")
        run_draw(cls, hl, context, "draw_header")
        header = hl.node
    body = FakeLayout("column")
    run_draw(cls, body, context, "draw")
    return header, body.node


def record_menu(menu_id, context=None):
    cls = find_menu_class(menu_id)
    if cls is None:
        return None, menu_id
    ctx = context or bpy.context
    if not safe_poll(cls, ctx):
        return None, getattr(cls, "bl_label", menu_id)
    lay = FakeLayout("column")
    run_draw(cls, lay, ctx)
    return lay.node, tr(getattr(cls, "bl_label", menu_id))
