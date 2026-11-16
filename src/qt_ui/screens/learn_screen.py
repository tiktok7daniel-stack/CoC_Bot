"""
Learn mode — its own section. Nothing here happens by itself: the bot only learns when you start it.
 - capture: you play, the bot watches (no taps of its own) and photographs every new screen + your attacks
 - armies: you prepare an army once, the bot learns the steps
 - Claude: what was sent, what was learned (with the check seals), the GitHub connection
"""
from PySide6.QtWidgets import QHBoxLayout, QLabel

from .. import icons
from ..theme import TOKENS
from ..widgets.army_library import ArmyLibrary
from ..widgets.controls import Box, GlassCard, label
from .base import Screen, page
from .learn_panel import LearnPanel


class LearnScreen(Screen):
    key, title_key, icon_name = "learn", "sub_learn", "school"

    def __init__(self, ctx):
        super().__init__(ctx)
        from .bot_settings_screen import secret_field
        sa, v = page()
        self.root.addWidget(sa)
        # the two modes, said plainly
        from PySide6.QtWidgets import QVBoxLayout
        modes = QVBoxLayout()
        modes.setSpacing(8)
        for ic, tk, sk, col in (("swords", "lm_work", "lm_work_sub", TOKENS["ok"]), ("school", "lm_learn", "lm_learn_sub", TOKENS["accent"])):
            b = Box(radius=18, border=col)
            h = QHBoxLayout(b)
            h.setContentsMargins(16, 12, 16, 12)
            h.setSpacing(12)
            i = QLabel()
            i.setPixmap(icons.pixmap(ic, 26, col))
            h.addWidget(i)
            col_box = __import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout()
            col_box.setSpacing(2)
            col_box.addWidget(label(key=tk, role="h3"))
            col_box.addWidget(label(key=sk, role="sub", wrap=True))
            h.addLayout(col_box, 1)
            modes.addWidget(b)
        v.addLayout(modes)
        self.panel = LearnPanel(ctx, secret_field)
        v.addWidget(self.panel)
        army = GlassCard("al_title", "army", "al_sub")
        self.armies = ArmyLibrary(ctx)
        army.add(self.armies)
        v.addWidget(army)
        v.addStretch(1)

    def on_show(self):
        self.panel.load()
        self.armies.load()
