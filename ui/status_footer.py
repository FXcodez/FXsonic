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
    def __init__(self, state: FXsonicState):
        self.state = state
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
            # Left: Linear Progress Group (300px, label above the bar)
            with ui.column().classes("w-[300px] flex-shrink-0").style("gap: 5px;"):
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
        """Footer label for the phase that is running.

        The percentage is the *current phase's* own 0-100% (a phase sweeps the bar
        once), so the label mirrors the mockup's "Fingerprinting: 24 of 28 tracks
        (85%)" while always matching what the bar is showing.
        """
        total = len(self.state.tracks)
        if not total:
            return "Ready • Idle"
        done = int(total * self.state.progress_val)
        pct = int(self.state.progress_val * 100)
        phase = getattr(self.state, "progress_phase", "") or "Fingerprinting"
        return f"{phase}: {done} of {total} tracks ({pct}%)"

    def _apply_progress_color(self) -> None:
        """Recolour the bar for the running phase (green pre-fingerprint pass)."""
        phase = getattr(self.state, "progress_phase", "") or ""
        color = GREEN_PROGRESS_COLOR if phase in GREEN_PROGRESS_PHASES else DEFAULT_PROGRESS_COLOR
        if color != self._progress_color:
            self._progress_color = color
            self.progress_bar.props(f'color="{color}"')

    def update_display(self):
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
