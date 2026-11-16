"""
Screens 11-14 - Main village upgrades, four sub-tabs:
 walls     : wall automation + smart budget reserve
 buildings : buildings / heroes / builder apprentice, priority mode, limits, priority levels
 lab       : laboratory + lab assistant, priority levels
 pets      : pet house, priority levels
"""
from ..widgets.controls import GlassCard, note, num_row, toggle_row
from ..widgets.tier_editor import TierEditor
from .base import Screen, grid


class VillageScreen(Screen):
    key, title_key, icon_name = "upg", "sub_upg", "home"

    def __init__(self, ctx):
        super().__init__(ctx)
        st = self.store
        L = self.make_tabs([("walls", "walls", "brick"), ("buildings", "buildings", "castle"),
                            ("lab", "lab", "flask"), ("pets", "pets", "paw")])

        # ---------------- walls
        w, g = grid(2)
        wall = GlassCard("wall_auto", "brick", "wall_auto_sub")
        wall.add(toggle_row(st, "wall_enabled", "walls.enabled"))
        wall.add(toggle_row(st, "wall_farming", "walls.during_farming", "wall_farming_sub"))
        wall.add(num_row(st, "run_every", "walls.every_cycles", None, "cycles", 1, 100, 1, 90))
        wall.add(num_row(st, "max_walls_run", "walls.max_per_run", None, "walls_unit", 0, 500, 1, 90))
        wall.add(note("wall_note"))
        g.addWidget(wall, 0, 0)
        bud = GlassCard("smart_budget", "gold", "smart_budget_sub")
        bud.add(toggle_row(st, "budget_enabled", "budget.enabled"))
        bud.add(num_row(st, "keep_gold", "budget.keep_gold", None, None, 0, 10**9, 100000, 150))
        bud.add(num_row(st, "keep_elixir", "budget.keep_elixir", None, None, 0, 10**9, 100000, 150))
        for k in ("bf1", "bf2", "bf3"): bud.add(note(k, "check"))
        g.addWidget(bud, 0, 1)
        L["walls"].addWidget(w)
        L["walls"].addStretch(1)

        # ---------------- buildings
        w, g = grid(2)
        b = GlassCard("home_upgrades", "castle", "home_upgrades_sub")
        b.add(toggle_row(st, "t_home_base", "tasks.home_base"))
        b.add(toggle_row(st, "t_heroes", "tasks.heroes"))
        b.add(toggle_row(st, "t_builder_apprentice", "tasks.builder_apprentice"))
        b.add(toggle_row(st, "use_priority", "tasks.home_base_priority", "use_priority_sub"))
        b.add(toggle_row(st, "from_top", "upgrades.start_from_menu_top"))
        b.add(num_row(st, "max_upgrades_cycle", "upgrades.max_per_cycle", None, None, 1, 100, 1, 90))
        b.add(num_row(st, "up_every", "upgrades.every_cycles", "up_every_sub", "cycles", 1, 50, 1, 90))
        b.add(num_row(st, "open_builders", "upgrades.open_home_builders", "open_builders_sub", None, 0, 6, 1, 80))
        g.addWidget(b, 0, 0)
        pr = GlassCard("priority_order", "list", "priority_sub")
        pr.add(TierEditor(st, "priorities.home_base", "home_base"))
        g.addWidget(pr, 0, 1)
        L["buildings"].addWidget(w)
        L["buildings"].addStretch(1)

        # ---------------- lab
        w, g = grid(2)
        lab = GlassCard("lab", "flask", "lab_sub")
        lab.add(toggle_row(st, "t_home_lab", "tasks.home_lab"))
        lab.add(toggle_row(st, "t_lab_assistant", "tasks.lab_assistant"))
        lab.add(toggle_row(st, "use_priority", "tasks.home_lab_priority", "use_priority_sub"))
        g.addWidget(lab, 0, 0)
        lp = GlassCard("priority_order", "list", "priority_sub")
        lp.add(TierEditor(st, "priorities.home_lab", "home_lab"))
        g.addWidget(lp, 0, 1)
        L["lab"].addWidget(w)
        L["lab"].addStretch(1)

        # ---------------- pets
        w, g = grid(2)
        pets = GlassCard("pets", "paw", "pets_sub")
        pets.add(toggle_row(st, "t_pet_house", "tasks.pet_house"))
        pets.add(toggle_row(st, "use_priority", "tasks.pet_house_priority", "use_priority_sub"))
        g.addWidget(pets, 0, 0)
        pp = GlassCard("priority_order", "list", "priority_sub")
        pp.add(TierEditor(st, "priorities.pet_house", "pet_house"))
        g.addWidget(pp, 0, 1)
        L["pets"].addWidget(w)
        L["pets"].addStretch(1)
