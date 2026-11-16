"""
Screen 9 - Builder base: building / star lab upgrade toggles, priority vs random, idle builders to
keep, and drag-and-drop priority levels for buildings and the star laboratory.
"""
from ..widgets.controls import GlassCard, num_row, toggle_row
from ..widgets.tier_editor import TierEditor
from .base import Screen, grid, page


class BuilderBaseScreen(Screen):
    key, title_key, icon_name = "bb", "sub_bb", "moon"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page()
        self.root.addWidget(sa)
        st = self.store
        top = GlassCard("bb_upgrades", "moon", "bb_upgrades_sub")
        top.add(toggle_row(st, "t_builder_base", "tasks.builder_base"))
        top.add(toggle_row(st, "t_builder_lab", "tasks.builder_lab"))
        top.add(toggle_row(st, "use_priority_bb", "tasks.builder_base_priority", "use_priority_sub"))
        top.add(toggle_row(st, "use_priority_bl", "tasks.builder_lab_priority", "use_priority_sub"))
        top.add(num_row(st, "open_builders", "upgrades.open_builder_builders", "open_builders_sub", None, 0, 5, 1, 80))
        v.addWidget(top)
        w, g = grid(2)
        bb = GlassCard("bb_priority", "hammer", "priority_sub")
        bb.add(TierEditor(st, "priorities.builder_base", "builder_base"))
        g.addWidget(bb, 0, 0)
        bl = GlassCard("bl_priority", "flask", "priority_sub")
        bl.add(TierEditor(st, "priorities.builder_lab", "builder_lab"))
        g.addWidget(bl, 0, 1)
        v.addWidget(w)
        v.addStretch(1)
