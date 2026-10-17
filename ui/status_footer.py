"""
Bottom Activity Drawer Component

Mockup alignment ("Activity Drawer"):
  * 43.5px tall, 0 18px padding, 16px gap, card surface background,
    1px top border - pinned flush to the bottom of the full-viewport shell.
  * Progress group: 300px wide, Oswald/Roboto 11px muted label, 5px track.
  * Counters: 7px status dots (matched / ambiguous / errors) on primary text.
  * Console: 430x26px input-surface box with a mono 11px ticker.
"""

from nicegui import ui
from core.state import FXsonicState

#: Phases that paint the bar GREEN instead of the FXsonic crimson.  The CPU-bound
#: pre-fingerprint pass (fpcalc decoding every unmatched file) uses the matched-status
#: green so it reads as "gathering data", and the AcoustID fingerprint/matching pass
#: that follows sweeps the same bar again in crimson.  Quasar palette names are used so
#: the fill stays correct in both themes (``green-8`` is the closest palette step to the
#: theme's ``--fx-status-matched-dot``).
GREEN_PROGRESS_PHASES = ("Pre-fingerprinting",)
GREEN_PROGRESS_COLOR = "green-8"

#: Colour of every other phase (``--q-primary`` is themed to ``--fx-crimson``).
DEFAULT_PROGRESS_COLOR = "primary"


class StatusFooter:
    def __init__(self, state: FXsonicState, dark_mode=None):
        self.state = state
        self.dark_mode_element = dark_mode
        self.theme_btn = None
        self.progress_bar = None
        self.progress_label = None
        self.counter_verified = None
        self.counter_ambiguous = None
        self.counter_errors = None
        self.console_ticker = None
        # Tracks the colour currently applied to the bar so a phase change only pushes
        # one prop update per transition (not per progress report).
        self._progress_color = DEFAULT_PROGRESS_COLOR
        self.render()

    def render(self):
        with ui.row().classes(
            "fx-footer w-full h-[43.5px] px-[18px] items-center justify-between no-wrap flex-shrink-0"
        ).style(
            "gap: 16px; background-color: var(--fx-bg-card); border-top: 1px solid var(--fx-border);"
        ):
            # Left: Theme Toggle (Bottom Left) + Linear Progress Group
            with ui.row().classes("items-center no-wrap").style("gap: 12px;"):
                self.theme_btn = ui.button(
                    icon="dark_mode" if self.state.dark_mode else "light_mode",
                    on_click=self.toggle_theme,
                    color=None,
                ).props("flat round dense").classes("fx-theme-toggle")
                self.theme_btn.tooltip("Toggle Dark / Light Theme")

                with ui.column().classes("w-[280px] flex-shrink-0").style("gap: 5px;"):
                    self.progress_label = ui.label(self.progress_text()).classes(
                        "font-roboto text-[11px] leading-none truncate"
                    ).style("color: var(--fx-text-muted);")

                    self.progress_bar = ui.linear_progress(
                        value=self.state.progress_val,
                        show_value=False,
                    ).props('rounded size="5px"').classes("w-full").style(
                        "background-color: var(--fx-progress-bg); border-radius: 0px;"
                    )

            # Center: Metrics Counters
            with ui.row().classes("items-center gap-4 flex-shrink-0 no-wrap"):
                self.counter_verified = self._counter("var(--fx-status-matched-dot)", self.state.count_verified, "IDENTIFIED")
                self.counter_ambiguous = self._counter("var(--fx-status-ambig-dot)", self.state.count_ambiguous, "AMBIGUOUS")
                self.counter_errors = self._counter("var(--fx-text-muted)", self.state.count_errors, "ERRORS")

            # Right: Activity Console Input/Ticker (430x26px)
            with ui.row().classes(
                "w-[430px] h-[26px] px-[10px] items-center flex-shrink-0 no-wrap overflow-hidden"
            ).style(
                "gap: 8px; background-color: var(--fx-bg-input); border: 1px solid var(--fx-border); border-radius: 2px;"
            ):
                ui.icon("terminal", size="13px").style("color: var(--fx-text-muted);")
                self.console_ticker = ui.label(self.state.status_message).classes("fx-console")

    def _counter(self, dot_color: str, count: int, caption: str):
        with ui.row().classes("items-center no-wrap").style("gap: 6px;"):
            ui.element("div").classes("rounded-full").style(
                f"width: 7px; height: 7px; background-color: {dot_color};"
            )
            return ui.label(f"{count} {caption}").classes(
                "font-oswald text-[10.5px] font-semibold tracking-[0.5px]"
            ).style("color: var(--fx-text-primary);")

    def progress_text(self) -> str:
        """Footer label for the phase that is running."""
        total = len(self.state.tracks)
        if not total:
            return "Ready • Idle"
        pct = int(self.state.progress_val * 100)
        done = int(total * self.state.progress_val)
        phase = getattr(self.state, "progress_phase", "") or "Fingerprinting"

        # When operation has finished (100% or not running scan/apply)
        if not self.state.is_scanning and not self.state.is_applying:
            if pct >= 100 or self.state.progress_val >= 1.0 or "complete" in phase.lower():
                if "fingerprint" in phase.lower():
                    return f"Fingerprinting Complete: {total} tracks (100%)"
                if "apply" in phase.lower():
                    return f"Apply Complete: {total} tracks (100%)"
                if "identif" in phase.lower():
                    return f"Identification Complete: {total} tracks (100%)"
                return f"{phase}: {total} tracks (100%)"
            if self.state.progress_val == 0.0:
                return f"Ready • {total} tracks staged"

        if "complete" in phase.lower() or pct >= 100:
            if "fingerprint" in phase.lower():
                return f"Fingerprinting Complete: {total} tracks (100%)"
            return f"{phase}: {total} tracks (100%)"

        return f"{phase}: {done} of {total} tracks ({pct}%)"

    def _apply_progress_color(self) -> None:
        """Recolour the bar for the running phase (green pre-fingerprint pass)."""
        phase = getattr(self.state, "progress_phase", "") or ""
        color = GREEN_PROGRESS_COLOR if phase in GREEN_PROGRESS_PHASES else DEFAULT_PROGRESS_COLOR
        if color != self._progress_color:
            self._progress_color = color
            self.progress_bar.props(f'color="{color}"')

    def toggle_theme(self):
        self.set_theme(not self.state.dark_mode)

    def set_theme(self, is_dark: bool):
        self.state.dark_mode = bool(is_dark)
        if self.dark_mode_element is not None:
            self.dark_mode_element.set_value(self.state.dark_mode)
        else:
            ui.dark_mode().set_value(self.state.dark_mode)
        if self.theme_btn:
            self.theme_btn.props(f'icon="{"dark_mode" if self.state.dark_mode else "light_mode"}"')
        self.state.notify()

    def update_display(self):
        if self.theme_btn:
            self.theme_btn.props(f'icon="{"dark_mode" if self.state.dark_mode else "light_mode"}"')
        if self.progress_label:
            self.progress_label.text = self.progress_text()
        if self.progress_bar:
            self.progress_bar.value = self.state.progress_val
            self._apply_progress_color()
        if self.counter_verified:
            self.counter_verified.text = f"{self.state.count_verified} IDENTIFIED"
        if self.counter_ambiguous:
            self.counter_ambiguous.text = f"{self.state.count_ambiguous} AMBIGUOUS"
        if self.counter_errors:
            self.counter_errors.text = f"{self.state.count_errors} ERRORS"
        if self.console_ticker:
            self.console_ticker.text = self.state.status_message
