"""
Configuration & Options Bar Component

Mockup alignment ("Toggle Bar"):
  * Height 38px (37.5px + 0.5px border in the exports), padding 0 18px, gap 22px
  * Background = input surface (#242424 dark / #F1F2F4 light)
  * 1px bottom border in the theme border colour
  * Checkbox labels in muted text, right side shows the clickable OUTPUT target
"""

from nicegui import ui
from core.state import FXsonicState
from core.dialogs import choose_directory_dialog

OPTION_FIELDS = (
    ("Fetch Cover Art", "auto_fetch_artwork"),
    ("Strip Junk Info", "strip_junk_frames"),
    ("Prefer Romanized Script", "prefer_romanized"),
    ("Organize Files", "rename_organize"),
    ("Rename Files to Song Title", "rename_to_title"),
)


class OptionsBar:
    def __init__(self, state: FXsonicState):
        self.state = state
        self.output_label = None
        self.checkboxes = {}
        self.render()

    def render(self):
        with ui.row().classes(
            "fx-optionsbar w-full h-[38px] px-[18px] items-center justify-between border-b no-wrap flex-shrink-0"
        ).style(
            "gap: 22px; background-color: var(--fx-bg-input); border-bottom: 1px solid var(--fx-border);"
        ):
            # Left: Checkbox Group (22px gap, matching the export)
            with ui.row().classes("items-center gap-[22px] no-wrap"):
                for label, field_name in OPTION_FIELDS:
                    box = ui.checkbox(
                        label,
                        value=getattr(self.state, field_name),
                        on_change=lambda e, f=field_name: self.on_opt_changed(f, e.value),
                    ).props('dense size="xs"').classes("fx-check text-[12.5px]")
                    box.style("color: var(--fx-text-muted);")
                    self.checkboxes[field_name] = box

            # Right: Clickable Output Directory Link
            with ui.row().classes("items-center gap-2 no-wrap flex-shrink-0"):
                self.output_label = ui.label(self.output_text()).classes(
                    "font-mono text-xs cursor-pointer hover:underline"
                ).style("color: var(--fx-text-muted);")
                self.output_label.on("click", self.choose_output_dir)

                ui.button(
                    "CHANGE",
                    on_click=self.choose_output_dir,
                    color=None,
                ).props("flat dense").classes(
                    "text-[10.5px] font-bold font-oswald tracking-[0.5px]"
                ).style("color: var(--fx-crimson);")

                if self.state.output_directory:
                    ui.button(
                        "RESET IN-PLACE",
                        on_click=self.reset_output_dir,
                        color=None,
                    ).props("flat dense").classes(
                        "text-[10px] font-bold font-oswald tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")

    def output_text(self) -> str:
        if self.state.output_directory:
            return f"OUTPUT: {self.state.output_directory}"
        return "OUTPUT: (Overwrite In-Place)"

    def on_opt_changed(self, field_name: str, val: bool):
        setattr(self.state, field_name, val)
        self.state.refresh_destination_paths()
        self.state.notify()

    async def choose_output_dir(self):
        folder = await choose_directory_dialog("Select Output Destination Directory")
        if folder:
            self.state.output_directory = folder
            self.state.refresh_destination_paths()
            self.update_display()
            self.state.notify()

    def reset_output_dir(self):
        self.state.output_directory = ""
        self.state.refresh_destination_paths()
        self.update_display()
        self.state.notify()

    def update_display(self):
        if self.output_label:
            self.output_label.text = self.output_text()
        for field_name, box in self.checkboxes.items():
            value = getattr(self.state, field_name)
            if box.value != value:
                box.value = value
