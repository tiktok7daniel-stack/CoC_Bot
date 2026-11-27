"""
Building blocks used by every screen: glass cards, animated toggles, number fields, status pills,
icon buttons, underline tabs, a flow layout, toasts / banners, ConsoleLog, and helpers.

Backward compatible: legacy imports (GlassCard, StatusPill, Toggle, KpiTile, IconButton) work
exactly as before via re-export from controls.py.
"""
from .controls import (
    # Legacy exports (backward compatible)
    GlassCard,
    StatusPill,
    Toggle,
    KpiTile,
    IconButton,
    # Additional widgets from controls
    IconBadge,
    NumField,
    FloatField,
    Combo,
    Chip,
    SegTabs,
    TimeField,
    Toast,
    Banner,
    Box,
    FlowLayout,
    # Form row helpers
    label,
    retext,
    form_row,
    hline,
    note,
    # Store bindings
    bind_toggle,
    bind_num,
    bind_combo,
    bind_line,
    bind_time,
    toggle_row,
    num_row,
    float_row,
    combo_row,
    time_edit,
)

from .glass import GlassPanel, ElevatedCard

from .status import LiveDot, LiveStatusBadge, StatusRow

from .toggle import AnimatedToggle

from .metric import MetricTile, KpiRow, MetricLabel, LiveCounter

from .log import ConsoleLog, LogPanel

__all__ = [
    # Legacy exports (backward compatible - must come first for zero breaking changes)
    "GlassCard",
    "StatusPill",
    "Toggle",
    "KpiTile",
    "IconButton",
    # New glass widgets (additional functionality)
    "GlassPanel",
    "ElevatedCard",
    # Status widgets (additional functionality)
    "LiveDot",
    "LiveStatusBadge",
    "StatusRow",
    # Toggle widget (additional - AnimatedToggle vs Toggle)
    "AnimatedToggle",
    # Metric widgets
    "MetricTile",
    "KpiRow",
    "MetricLabel",
    "LiveCounter",
    # Console log widget
    "ConsoleLog",
    "LogPanel",
    # Additional controls
    "IconBadge",
    "NumField",
    "FloatField",
    "Combo",
    "Chip",
    "SegTabs",
    "TimeField",
    "Toast",
    "Banner",
    "Box",
    "FlowLayout",
    # Form row helpers
    "label",
    "retext",
    "form_row",
    "hline",
    "note",
    # Store bindings
    "bind_toggle",
    "bind_num",
    "bind_combo",
    "bind_line",
    "bind_time",
    "toggle_row",
    "num_row",
    "float_row",
    "combo_row",
    "time_edit",
]