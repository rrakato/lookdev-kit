# Metadata (verze, název…) jsou v blender_manifest.toml

import bpy
import aud
from mathutils import Matrix
from bpy.app.handlers import persistent
import os
import sys
import subprocess
import glob
import tempfile
import colorsys
import numpy as np


# ---------------------------------------------------------------------------
# Render Ding – zvuk po dokončení renderu
# ---------------------------------------------------------------------------

ADDON_ID = __package__ or __name__
DEFAULT_SOUND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ding.wav")

_device = None
_handle = None  # drží referenci, jinak by zvuk přes aud mohl hned utichnout


def _sound_path():
    """Vlastní soubor z preferencí, jinak přibalený ding.wav."""
    try:
        prefs = bpy.context.preferences.addons[ADDON_ID].preferences
        custom = bpy.path.abspath(prefs.sound_path) if prefs.sound_path else ""
        if custom and os.path.isfile(custom):
            return custom
    except Exception:
        pass
    return DEFAULT_SOUND


def _play_aud(path):
    global _device, _handle
    if _device is None:
        _device = aud.Device()
    _handle = _device.play(aud.Sound(path))


def play_ding():
    """Přehraje zvuk přes systém (Windows/macOS), jinak přes aud. Vrací chybu nebo None."""
    path = _sound_path()
    if not os.path.isfile(path):
        return f"Sound file not found: {path}"
    try:
        if sys.platform == "win32" and path.lower().endswith(".wav"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC
                               | winsound.SND_NODEFAULT)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", path])
        else:
            _play_aud(path)
    except Exception as e:
        try:
            _play_aud(path)
        except Exception as e2:
            return f"{e} / {e2}"
    return None


@persistent
def _on_render_complete(*args):
    scene = args[0] if args and isinstance(args[0], bpy.types.Scene) else bpy.context.scene
    if scene is not None and not getattr(scene, "evp_render_ding", True):
        return
    err = play_ding()
    if err:
        print(f"[Render Ding] Nepodařilo se přehrát zvuk: {err}")


class EVP_OT_test_ding(bpy.types.Operator):
    """Play the render-finished sound"""
    bl_idname = "evp.test_ding"
    bl_label = "Test Render Ding"

    def execute(self, context):
        err = play_ding()
        if err:
            self.report({'WARNING'}, err)
            return {'CANCELLED'}
        return {'FINISHED'}


class EVP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    sound_path: bpy.props.StringProperty(
        name="Render Ding Sound",
        description="Sound played when a render finishes. Leave empty to use the built-in ding",
        subtype='FILE_PATH', default="")
    name_separator: bpy.props.StringProperty(
        name="File Name Separator",
        description="Character used to join file name parts. Leave empty to use a space",
        default="")
    section_order: bpy.props.StringProperty(
        name="Section Order", description="Internal: order of panel sections", default="")

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Render Ding", icon='PLAY_SOUND')
        row = box.row(align=True)
        row.prop(self, "sound_path")
        row.operator(EVP_OT_test_ding.bl_idname, text="", icon='PLAY')
        box.label(text="Leave empty to use the built-in ding. On Windows, use a WAV file.", icon='INFO')

        box = layout.box()
        box.label(text="Output", icon='FILE_IMAGE')
        box.prop(self, "name_separator")
        box.label(text="Leave empty to use a space.", icon='INFO')

        box = layout.box()
        box.label(text="Section Order", icon='SORTSIZE')
        labels = {k: label for k, label, _ in SECTIONS}
        order = get_order()
        col = box.column(align=True)
        for i, key in enumerate(order):
            row = col.row(align=True)
            row.label(text=labels[key])
            sub = row.row(align=True)
            sub.enabled = i > 0
            op = sub.operator("evp.section_move", text="", icon='TRIA_UP')
            op.key = key
            op.direction = -1
            sub = row.row(align=True)
            sub.enabled = i < len(order) - 1
            op = sub.operator("evp.section_move", text="", icon='TRIA_DOWN')
            op.key = key
            op.direction = 1
        box.operator("evp.section_reset", text="Reset Order", icon='LOOP_BACK')


# ---------------------------------------------------------------------------
# Světlo
# ---------------------------------------------------------------------------

class LIGHT_OT_ev_step(bpy.types.Operator):
    """Změní sílu aktivního světla o zadaný počet EV"""
    bl_idname = "light.ev_step"
    bl_label = "EV Step"
    bl_options = {'REGISTER', 'UNDO'}

    ev: bpy.props.FloatProperty(name="EV", default=1.0)

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'LIGHT'

    def execute(self, context):
        context.active_object.data.energy *= 2 ** self.ev
        return {'FINISHED'}


def split_row(layout, label):
    """Řádek ve stylu use_property_split: popisek vlevo (40 %), ovládání vpravo."""
    split = layout.split(factor=0.4, align=True)
    split.use_property_split = False  # jinak by si checkbox přidal vlastní prázdný popisek
    lab = split.row()
    lab.alignment = 'RIGHT'
    lab.label(text=label)
    return split.row(align=True)


RENDER_PRESETS = (
    # (popisek, render scale, denoiser)
    ("100%", 100, 'OPTIX'),
    ("123%", 123, 'OPTIX'),
    ("200%", 200, 'OPTIX'),
    ("400%", 400, 'OPENIMAGEDENOISE'),
)


class EVP_OT_render_preset(bpy.types.Operator):
    """Apply render preset: render scale, exposure 0, gamma 1, denoiser on, render ding on"""
    bl_idname = "evp.render_preset"
    bl_label = "Render Preset"
    bl_options = {'REGISTER', 'UNDO'}

    scale: bpy.props.IntProperty(default=100)
    denoiser: bpy.props.StringProperty(default='OPTIX')

    def execute(self, context):
        scene = context.scene
        scene.render.resolution_percentage = self.scale
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        scene.evp_render_ding = True
        cyc = getattr(scene, "cycles", None)
        if cyc is not None:
            cyc.use_denoising = True
            try:
                cyc.denoiser = self.denoiser
            except Exception:
                self.report({'WARNING'}, f"Denoiser {self.denoiser} is not available")
        return {'FINISHED'}


class EVP_RenderPresetsPanel:
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Render Presets"

    def draw(self, context):
        row = self.layout.row(align=True)
        scene = context.scene
        for label, scale, den in RENDER_PRESETS:
            cyc = getattr(scene, "cycles", None)
            active = (scene.render.resolution_percentage == scale
                      and (cyc is None or (cyc.use_denoising and cyc.denoiser == den)))
            op = row.operator(EVP_OT_render_preset.bl_idname, text=label, depress=active)
            op.scale = scale
            op.denoiser = den


class VIEW3D_PT_evp_render_presets(EVP_RenderPresetsPanel, bpy.types.Panel):
    bl_space_type = 'VIEW_3D'


class IMAGE_PT_evp_render_presets(EVP_RenderPresetsPanel, bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'


class EVP_RenderPanel:
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene

        layout.prop(scene.render, "resolution_percentage", text="Render Scale")
        layout.prop(scene.view_settings, "exposure", text="Exposure", slider=True)
        layout.prop(scene.view_settings, "gamma", text="Gamma", slider=True)

        cyc = getattr(scene, "cycles", None)
        if cyc is not None:
            row = split_row(layout, "Denoiser")
            row.active = scene.render.engine == 'CYCLES'
            row.prop(cyc, "use_denoising", text="")
            sub = row.row(align=True)
            sub.active = cyc.use_denoising
            sub.prop(cyc, "denoiser", text="")

        row = split_row(layout, "Render Ding")
        row.prop(scene, "evp_render_ding", text="")
        sub = row.row(align=True)
        sub.enabled = scene.evp_render_ding
        sub.operator(EVP_OT_test_ding.bl_idname, text="", icon='PLAY')


class VIEW3D_PT_evp_render(EVP_RenderPanel, bpy.types.Panel):
    bl_space_type = 'VIEW_3D'


class IMAGE_PT_evp_render(EVP_RenderPanel, bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class EVP_NamePart(bpy.types.PropertyGroup):
    text: bpy.props.StringProperty(name="Part", default="")


def _prefs():
    try:
        return bpy.context.preferences.addons[ADDON_ID].preferences
    except Exception:
        return None


def name_separator():
    """Spojovací znak z preferencí, prázdné = mezera."""
    p = _prefs()
    return p.name_separator if p is not None and p.name_separator else " "


def output_filename(scene):
    """Spojí části názvu spojovacím znakem, přidá příponu podle formátu výstupu."""
    name = name_separator().join(p.text.strip() for p in scene.evp_name_parts if p.text.strip())
    return name + scene.render.file_extension if name else ""


def output_filepath(scene):
    fname = output_filename(scene)
    if not fname:
        return ""
    folder = bpy.path.abspath(scene.evp_out_dir) if scene.evp_out_dir else ""
    return os.path.join(folder, fname)


class EVP_OT_name_part_add(bpy.types.Operator):
    """Add a file name part"""
    bl_idname = "evp.name_part_add"
    bl_label = "Add Name Part"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.evp_name_parts.add()
        return {'FINISHED'}


class EVP_OT_name_part_remove(bpy.types.Operator):
    """Remove this file name part"""
    bl_idname = "evp.name_part_remove"
    bl_label = "Remove Name Part"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        parts = context.scene.evp_name_parts
        if 0 <= self.index < len(parts):
            parts.remove(self.index)
        return {'FINISHED'}


class EVP_OT_save_render(bpy.types.Operator):
    """Save the current render result to the path and file name set above"""
    bl_idname = "evp.save_render"
    bl_label = "Save Render"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.evp_out_dir) and bool(output_filename(context.scene))

    def invoke(self, context, event):
        path = output_filepath(context.scene)
        if os.path.exists(path):
            return context.window_manager.invoke_confirm(
                self, event, title="File exists", message=f"Overwrite {os.path.basename(path)}?") \
                if bpy.app.version >= (4, 1, 0) else context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        img = bpy.data.images.get("Render Result")
        if img is None or not img.has_data:
            self.report({'ERROR'}, "No render result – render first (F12)")
            return {'CANCELLED'}
        path = output_filepath(scene)
        folder = os.path.dirname(path)
        try:
            if folder:
                os.makedirs(folder, exist_ok=True)
            img.save_render(filepath=path, scene=scene)
        except Exception as e:
            self.report({'ERROR'}, f"Save failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Saved: {path}")
        return {'FINISHED'}


class EVP_OT_filename_hint(bpy.types.Operator):
    """Add file name parts with the + button. They are joined with the separator set in the add-on preferences (space by default) and the extension is added from the output format"""
    bl_idname = "evp.filename_hint"
    bl_label = "Setup filename"

    def execute(self, context):
        return {'CANCELLED'}


class EVP_OT_set_format(bpy.types.Operator):
    """Set the output format: PNG or Multi-Layer EXR"""
    bl_idname = "evp.set_format"
    bl_label = "Set Output Format"
    bl_options = {'REGISTER', 'UNDO'}

    fmt: bpy.props.EnumProperty(items=[('PNG', "PNG", ""), ('EXR', "EXR", "")])

    def execute(self, context):
        img = context.scene.render.image_settings
        try:
            if self.fmt == 'PNG':
                # Novější Blender: nejdřív Media Type, pak formát
                if hasattr(img, "media_type"):
                    img.media_type = 'IMAGE'
                img.file_format = 'PNG'
            else:
                if hasattr(img, "media_type"):
                    img.media_type = 'MULTI_LAYER_IMAGE'
                else:
                    img.file_format = 'OPEN_EXR_MULTILAYER'
        except Exception as e:
            self.report({'ERROR'}, f"Could not set format: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


class EVP_OutputPanel:
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Output"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        img = scene.render.image_settings

        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(scene, "evp_out_dir", text="Path")

        layout.label(text="File Name")
        col = layout.column(align=True)
        for i, part in enumerate(scene.evp_name_parts):
            row = col.row(align=True)
            row.prop(part, "text", text="")
            op = row.operator(EVP_OT_name_part_remove.bl_idname, text="", icon='REMOVE')
            op.index = i
        col.operator(EVP_OT_name_part_add.bl_idname, text="", icon='ADD')

        fname = output_filename(scene)
        box = layout.box()
        if fname:
            box.label(text=fname, icon='FILE_IMAGE')
        else:
            box.operator(EVP_OT_filename_hint.bl_idname, text="Setup filename",
                         icon='INFO', emboss=False)

        row = layout.row(align=True)
        media = getattr(img, "media_type", None)
        is_exr = img.file_format == 'OPEN_EXR_MULTILAYER' or media == 'MULTI_LAYER_IMAGE'
        is_png = img.file_format == 'PNG' and not is_exr
        op = row.operator(EVP_OT_set_format.bl_idname, text="PNG", depress=is_png)
        op.fmt = 'PNG'
        op = row.operator(EVP_OT_set_format.bl_idname, text="EXR", depress=is_exr)
        op.fmt = 'EXR'

        layout.operator(EVP_OT_save_render.bl_idname, text="Save", icon='FILE_TICK')


class VIEW3D_PT_evp_output(EVP_OutputPanel, bpy.types.Panel):
    bl_space_type = 'VIEW_3D'


class IMAGE_PT_evp_output(EVP_OutputPanel, bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'


class OBJECT_OT_evp_copy_transform(bpy.types.Operator):
    """Zkopíruje lokaci / rotaci aktivního objektu na ostatní vybrané objekty (ve world space)"""
    bl_idname = "object.evp_copy_transform"
    bl_label = "Copy Transform"
    bl_options = {'REGISTER', 'UNDO'}

    what: bpy.props.EnumProperty(
        items=[('LOC', "Location", ""), ('ROT', "Rotation", "")], default='LOC')

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and len(context.selected_objects) > 1)

    def execute(self, context):
        src = context.active_object
        s_loc, s_rot, _ = src.matrix_world.decompose()
        count = 0
        for ob in context.selected_objects:
            if ob == src:
                continue
            loc, rot, scale = ob.matrix_world.decompose()
            if self.what == 'LOC':
                loc = s_loc
            else:
                rot = s_rot
            ob.matrix_world = Matrix.LocRotScale(loc, rot, scale)
            count += 1
        self.report({'INFO'}, f"Zkopírováno na {count} objekt(y)")
        return {'FINISHED'}


class VIEW3D_PT_evp_transformation(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Transformation"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        op = row.operator(OBJECT_OT_evp_copy_transform.bl_idname, text="Copy Location")
        op.what = 'LOC'
        op = row.operator(OBJECT_OT_evp_copy_transform.bl_idname, text="Copy Rotation")
        op.what = 'ROT'
        row = layout.row(align=True)
        op = row.operator("object.origin_set", text="Origin to 3D Cursor", icon='PIVOT_CURSOR')
        op.type = 'ORIGIN_CURSOR'
        # Origin to Geometry se středem podle bounding boxu (nezávisí na pivot pointu)
        op = row.operator("object.origin_set", text="Origin to Bounding Box", icon='PIVOT_BOUNDBOX')
        op.type = 'ORIGIN_GEOMETRY'
        op.center = 'BOUNDS'


class VIEW3D_PT_evp_ray_visibility(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Ray Visibility"

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        if ob is None or not hasattr(ob, "visible_camera"):
            layout.label(text="Select object", icon='INFO')
            return

        layout.label(text=ob.name, icon='OBJECT_DATA')
        col = layout.column(align=True)
        col.prop(ob, "visible_camera", text="Camera")
        col.prop(ob, "visible_diffuse", text="Diffuse")
        col.prop(ob, "visible_glossy", text="Glossy")
        col.prop(ob, "visible_transmission", text="Transmission")
        col.prop(ob, "visible_volume_scatter", text="Volume Scatter")


class VIEW3D_PT_light_ev(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Light"

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        if not (ob and ob.type == 'LIGHT'):
            layout.label(text="Select light", icon='INFO')
            return

        layout.label(text=ob.name, icon='LIGHT')
        layout.prop(ob.data, "energy", text="Power")

        row = layout.row(align=True)
        for ev, label in ((-1.0, "-1 EV"), (-0.5, "-0.5 EV"),
                          (0.5, "+0.5 EV"), (1.0, "+1 EV")):
            op = row.operator(LIGHT_OT_ev_step.bl_idname, text=label)
            op.ev = ev


def draw_linking(layout, ll, prop, new_op, link_op, select_op):
    """Společné vykreslení pro Light Linking i Shadow Linking"""
    layout.template_ID(ll, prop, new=new_op)
    if not getattr(ll, prop):
        return

    row = layout.row()
    row.template_light_linking_collection(row, ll, prop)

    row = layout.row(align=True)
    op = row.operator(link_op, text="Include", icon='ADD')
    op.link_state = 'INCLUDE'
    op = row.operator(link_op, text="Exclude", icon='REMOVE')
    op.link_state = 'EXCLUDE'
    row.operator(select_op, text="", icon='RESTRICT_SELECT_OFF')


class VIEW3D_PT_light_linking(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Light Linking"
    bl_parent_id = "VIEW3D_PT_light_ev"

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'LIGHT' and hasattr(ob, "light_linking")

    def draw(self, context):
        layout = self.layout
        ll = context.active_object.light_linking

        layout.label(text="Light Receivers")
        draw_linking(layout, ll, "receiver_collection",
                     "object.light_linking_receiver_collection_new",
                     "object.light_linking_receivers_link",
                     "object.light_linking_receivers_select")

        layout.separator()
        layout.label(text="Light Blockers")
        draw_linking(layout, ll, "blocker_collection",
                     "object.light_linking_blocker_collection_new",
                     "object.light_linking_blockers_link",
                     "object.light_linking_blockers_select")


# ---------------------------------------------------------------------------
# Kapátko – převody barev
# ---------------------------------------------------------------------------

_WHITE = (0.95047, 1.0, 1.08883)  # D65


def _to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c):
    c = 12.92 * c if c <= 0.0031308 else 1.055 * (max(c, 0.0) ** (1 / 2.4)) - 0.055
    return min(max(c, 0.0), 1.0)


def rgb_to_lab(rgb):
    r, g, b = (_to_lin(c) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / _WHITE[0]
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / _WHITE[1]
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / _WHITE[2]
    d = 6 / 29

    def f(t):
        return t ** (1 / 3) if t > d ** 3 else t / (3 * d * d) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_to_rgb(lab):
    L, a, b = lab
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    d = 6 / 29

    def finv(t):
        return t ** 3 if t > d else 3 * d * d * (t - 4 / 29)

    x, y, z = finv(fx) * _WHITE[0], finv(fy) * _WHITE[1], finv(fz) * _WHITE[2]
    r = 3.2404542 * x - 1.5371385 * y - 0.4985314 * z
    g = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z
    bb = 0.0556434 * x - 0.2040259 * y + 1.0572252 * z
    return tuple(_to_srgb(c) for c in (r, g, bb))


# ---------------------------------------------------------------------------
# Kapátko – vlastnosti (slidery ovládají průměrovanou barvu)
# ---------------------------------------------------------------------------

def _col(self):
    """Barva, kterou ukazují slidery – podle naposledy použitého kapátka."""
    return self.color_avg if self.active == 'AVG' else self.color_px


def _set_col(self, c):
    if self.active == 'AVG':
        self.color_avg = c
    else:
        self.color_px = c


def _hsv(self):
    return colorsys.rgb_to_hsv(*_col(self))


def _set_hsv(self, h, s, v):
    _set_col(self, colorsys.hsv_to_rgb(h, s, v))


def _get_h(self):
    h, s, v = _hsv(self)
    return h * 360 if s > 0 and v > 0 else self.hue_cache


def _set_h(self, value):
    self.hue_cache = value
    _, s, v = _hsv(self)
    _set_hsv(self, value / 360, s, v)


def _get_s(self):
    return _hsv(self)[1] * 100


def _set_s(self, value):
    h = _get_h(self)
    self.hue_cache = h
    _set_hsv(self, h / 360, value / 100, _hsv(self)[2])


def _get_v(self):
    return _hsv(self)[2] * 100


def _set_v(self, value):
    h = _get_h(self)
    self.hue_cache = h
    _set_hsv(self, h / 360, _hsv(self)[1], value / 100)


def _rgb_get(i):
    def get(self):
        return round(_col(self)[i] * 255)
    return get


def _rgb_set(i):
    def set(self, value):
        c = list(_col(self))
        c[i] = value / 255
        _set_col(self, c)
    return set


def _lab_get(i):
    def get(self):
        return rgb_to_lab(_col(self))[i]
    return get


def _lab_set(i):
    def set(self, value):
        lab = list(rgb_to_lab(_col(self)))
        lab[i] = value
        _set_col(self, lab_to_rgb(lab))
    return set


class EVP_ColorProps(bpy.types.PropertyGroup):
    color_avg: bpy.props.FloatVectorProperty(
        name="Průměr", subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=(0.5, 0.5, 0.5))
    color_px: bpy.props.FloatVectorProperty(
        name="Pixel", subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=(0.5, 0.5, 0.5))
    sample_px: bpy.props.IntProperty(
        name="Sample px", description="Velikost čtverce pro průměrování (px)",
        default=10, min=1, max=100)
    slider_mode: bpy.props.EnumProperty(
        items=[('HSV', "HSV", ""), ('RGB', "RGB", ""), ('LAB', "LAB", "")],
        default='HSV')
    hue_cache: bpy.props.FloatProperty(default=0.0)
    active: bpy.props.EnumProperty(
        items=[('PX', "Pixel", ""), ('AVG', "Průměr", "")], default='PX')

    hsv_h: bpy.props.FloatProperty(min=0, max=360, precision=0, get=_get_h, set=_set_h)
    hsv_s: bpy.props.FloatProperty(min=0, max=100, precision=0, subtype='PERCENTAGE',
                                   get=_get_s, set=_set_s)
    hsv_v: bpy.props.FloatProperty(min=0, max=100, precision=0, subtype='PERCENTAGE',
                                   get=_get_v, set=_set_v)

    rgb_r: bpy.props.IntProperty(min=0, max=255, get=_rgb_get(0), set=_rgb_set(0))
    rgb_g: bpy.props.IntProperty(min=0, max=255, get=_rgb_get(1), set=_rgb_set(1))
    rgb_b: bpy.props.IntProperty(min=0, max=255, get=_rgb_get(2), set=_rgb_set(2))

    lab_l: bpy.props.FloatProperty(min=0, max=100, precision=0, get=_lab_get(0), set=_lab_set(0))
    lab_a: bpy.props.FloatProperty(min=-128, max=127, precision=0, get=_lab_get(1), set=_lab_set(1))
    lab_b: bpy.props.FloatProperty(min=-128, max=127, precision=0, get=_lab_get(2), set=_lab_set(2))


# ---------------------------------------------------------------------------
# Kapátko – operátor
# ---------------------------------------------------------------------------

class EVP_OT_pick_color(bpy.types.Operator):
    """Barva se snímá živě pod kurzorem, kliknutím potvrdíš. Esc / pravé tlačítko = zrušit"""
    bl_idname = "evp.pick_color"
    bl_label = "Pick Color"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        items=[('PX', "Pixel", "Barva jednoho pixelu"),
               ('AVG', "Průměr", "Zprůměrovaná barva ze čtverce Sample px")],
        default='PX')

    def invoke(self, context, event):
        cp = context.scene.evp_color
        # Uložit původní stav pro případ zrušení
        self.old = (tuple(cp.color_avg), tuple(cp.color_px), cp.hue_cache, cp.active)
        cp.active = self.mode
        # Jeden snímek okna hned na začátku – pak se snímá živě z něj
        try:
            self.px = self.grab_window(context)
        except Exception as e:
            self.report({'ERROR'}, f"Kapátko selhalo: {e}")
            return {'CANCELLED'}
        context.window.cursor_modal_set('EYEDROPPER')
        context.window_manager.evp_picking = self.mode
        context.window_manager.modal_handler_add(self)
        self.sample(context, event.mouse_x, event.mouse_y)
        return {'RUNNING_MODAL'}

    def redraw(self, context):
        for area in context.screen.areas:
            area.tag_redraw()

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            cp = context.scene.evp_color
            cp.color_avg, cp.color_px, cp.hue_cache, cp.active = self.old
            context.window.cursor_modal_restore()
            context.window_manager.evp_picking = 'NONE'
            self.redraw(context)
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            self.sample(context, event.mouse_x, event.mouse_y)
            self.redraw(context)
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.sample(context, event.mouse_x, event.mouse_y)
            context.window.cursor_modal_restore()
            context.window_manager.evp_picking = 'NONE'
            self.redraw(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def grab_window(self, context):
        """Udělá screenshot okna jako PNG a vrátí pixely (h, w, 4)."""
        base = os.path.join(tempfile.gettempdir(), "evp pick")
        for f in glob.glob(base + ".*"):
            os.remove(f)

        # Screenshot bere formát ze scény – dočasně přepnout na PNG
        ims = context.scene.render.image_settings
        saved = {}
        for attr in ("media_type", "file_format", "color_mode", "color_depth"):
            if hasattr(ims, attr):
                saved[attr] = getattr(ims, attr)
        try:
            if hasattr(ims, "media_type"):
                ims.media_type = 'IMAGE'
            ims.file_format = 'PNG'
            bpy.ops.screen.screenshot(filepath=base + ".png", check_existing=False)
        finally:
            for attr, val in saved.items():
                try:
                    setattr(ims, attr, val)
                except Exception:
                    pass

        files = glob.glob(base + ".*")
        if not files:
            raise RuntimeError("screenshot se neuložil")
        img = bpy.data.images.load(files[0], check_existing=False)
        try:
            w, h = img.size
            px = np.empty(w * h * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
        finally:
            bpy.data.images.remove(img)
            for f in files:
                os.remove(f)
        return px.reshape(h, w, 4)

    def sample(self, context, mx, my):
        cp = context.scene.evp_color
        win = context.window
        px = self.px
        h, w = px.shape[:2]

        cx = min(max(int(mx * w / win.width), 0), w - 1)
        cy = min(max(int(my * h / win.height), 0), h - 1)

        # Vždy se aktualizují obě barvy, kapátko určuje jen, co ukazují slidery
        n = cp.sample_px
        x0 = max(cx - n // 2, 0)
        y0 = max(cy - n // 2, 0)
        x1 = min(x0 + n, w)
        y1 = min(y0 + n, h)
        avg = px[y0:y1, x0:x1, :3].reshape(-1, 3).mean(axis=0)
        cp.color_avg = tuple(float(c) for c in avg)
        cp.color_px = tuple(float(c) for c in px[cy, cx, :3])

        hh, s, v = colorsys.rgb_to_hsv(*_col(cp))
        if s > 0 and v > 0:
            cp.hue_cache = hh * 360


class EVP_OT_copy_hex(bpy.types.Operator):
    """Zkopíruje hex kód do schránky"""
    bl_idname = "evp.copy_hex"
    bl_label = "Copy Hex"

    hex: bpy.props.StringProperty()

    def execute(self, context):
        context.window_manager.clipboard = self.hex
        self.report({'INFO'}, f"Zkopírováno: {self.hex}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Kapátko – panely
# ---------------------------------------------------------------------------

class VIEW3D_PT_evp_color_picker(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Color Picker"

    def draw(self, context):
        layout = self.layout
        cp = context.scene.evp_color

        row = layout.row(align=True)
        split = row.split(factor=0.65, align=True)
        split.prop(cp, "color_avg", text="")
        split.prop(cp, "color_px", text="")
        picking = context.window_manager.evp_picking
        op = row.operator(EVP_OT_pick_color.bl_idname, text="", icon='EYEDROPPER',
                          depress=picking == 'PX')
        op.mode = 'PX'

        row = layout.row(align=True)
        row.prop(cp, "sample_px", text="Sample px", slider=True)
        op = row.operator(EVP_OT_pick_color.bl_idname, text="", icon='EYEDROPPER',
                          depress=picking == 'AVG')
        op.mode = 'AVG'


class VIEW3D_PT_evp_color_sliders(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lookdev"
    bl_label = "Color Sliders"

    def draw(self, context):
        layout = self.layout
        cp = context.scene.evp_color

        layout.row().prop(cp, "slider_mode", expand=True)
        col = layout.column(align=True)
        if cp.slider_mode == 'HSV':
            col.prop(cp, "hsv_h", text="H:", slider=True)
            col.prop(cp, "hsv_s", text="S:", slider=True)
            col.prop(cp, "hsv_v", text="V:", slider=True)
        elif cp.slider_mode == 'RGB':
            col.prop(cp, "rgb_r", text="R:", slider=True)
            col.prop(cp, "rgb_g", text="G:", slider=True)
            col.prop(cp, "rgb_b", text="B:", slider=True)
        else:
            col.prop(cp, "lab_l", text="L:", slider=True)
            col.prop(cp, "lab_a", text="a:", slider=True)
            col.prop(cp, "lab_b", text="b:", slider=True)

        r, g, b = (round(c * 255) for c in _col(cp))
        hexcode = f"#{r:02X}{g:02X}{b:02X}"
        op = layout.operator(EVP_OT_copy_hex.bl_idname, text=hexcode, icon='COPYDOWN')
        op.hex = hexcode


# ---------------------------------------------------------------------------

# Oddíly panelu – pořadí si uživatel nastaví v preferencích
SECTIONS = (
    ('PRESETS', "Render Presets", (VIEW3D_PT_evp_render_presets, IMAGE_PT_evp_render_presets)),
    ('RENDER', "Render", (VIEW3D_PT_evp_render, IMAGE_PT_evp_render)),
    ('OUTPUT', "Output", (VIEW3D_PT_evp_output, IMAGE_PT_evp_output)),
    ('TRANSFORM', "Transformation", (VIEW3D_PT_evp_transformation,)),
    ('RAYVIS', "Ray Visibility", (VIEW3D_PT_evp_ray_visibility,)),
    ('LIGHT', "Light", (VIEW3D_PT_light_ev, VIEW3D_PT_light_linking)),
    ('PICKER', "Color Picker", (VIEW3D_PT_evp_color_picker,)),
    ('SLIDERS', "Color Sliders", (VIEW3D_PT_evp_color_sliders,)),
)
DEFAULT_ORDER = [k for k, _, _ in SECTIONS]


def get_order():
    p = _prefs()
    keys = p.section_order.split(",") if p is not None and p.section_order else []
    keys = [k for k in keys if k in DEFAULT_ORDER]
    return keys + [k for k in DEFAULT_ORDER if k not in keys]


_registered_panels = []


def unregister_panels():
    global _registered_panels
    for cls in reversed(_registered_panels):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _registered_panels = []


def register_panels():
    """Zaregistruje panely v pořadí z preferencí (bl_order + pořadí registrace)."""
    global _registered_panels
    unregister_panels()
    by_key = {k: panels for k, _, panels in SECTIONS}
    for i, key in enumerate(get_order()):
        for cls in by_key[key]:
            cls.bl_order = i
            bpy.utils.register_class(cls)
            _registered_panels.append(cls)


def _redraw_all(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class EVP_OT_section_move(bpy.types.Operator):
    """Move this section up or down in the side panel"""
    bl_idname = "evp.section_move"
    bl_label = "Move Section"

    key: bpy.props.StringProperty()
    direction: bpy.props.IntProperty()

    def execute(self, context):
        order = get_order()
        if self.key not in order:
            return {'CANCELLED'}
        i = order.index(self.key)
        j = i + self.direction
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            _prefs().section_order = ",".join(order)
            register_panels()
            _redraw_all(context)
        return {'FINISHED'}


class EVP_OT_section_reset(bpy.types.Operator):
    """Reset the section order to default"""
    bl_idname = "evp.section_reset"
    bl_label = "Reset Section Order"

    def execute(self, context):
        _prefs().section_order = ""
        register_panels()
        _redraw_all(context)
        return {'FINISHED'}


classes = (
    LIGHT_OT_ev_step,
    EVP_OT_test_ding,
    EVP_AddonPreferences,
    EVP_OT_section_move,
    EVP_OT_section_reset,
    EVP_OT_render_preset,
    EVP_NamePart,
    EVP_OT_name_part_add,
    EVP_OT_name_part_remove,
    EVP_OT_save_render,
    EVP_OT_filename_hint,
    EVP_OT_set_format,
    OBJECT_OT_evp_copy_transform,
    EVP_ColorProps,
    EVP_OT_pick_color,
    EVP_OT_copy_hex,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    register_panels()
    bpy.types.Scene.evp_color = bpy.props.PointerProperty(type=EVP_ColorProps)
    # Stav nabírání – na WindowManageru, neukládá se do souboru
    bpy.types.WindowManager.evp_picking = bpy.props.EnumProperty(
        items=[('NONE', "", ""), ('PX', "", ""), ('AVG', "", "")], default='NONE')
    bpy.types.Scene.evp_out_dir = bpy.props.StringProperty(
        name="Output Path", subtype='DIR_PATH', default="//EXR/")
    bpy.types.Scene.evp_name_parts = bpy.props.CollectionProperty(type=EVP_NamePart)
    bpy.types.Scene.evp_render_ding = bpy.props.BoolProperty(
        name="Render Ding", description="Play a sound when a render finishes",
        default=True)
    if _on_render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(_on_render_complete)


def unregister():
    if _on_render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(_on_render_complete)
    del bpy.types.Scene.evp_render_ding
    del bpy.types.Scene.evp_name_parts
    del bpy.types.Scene.evp_out_dir
    del bpy.types.WindowManager.evp_picking
    del bpy.types.Scene.evp_color
    unregister_panels()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
