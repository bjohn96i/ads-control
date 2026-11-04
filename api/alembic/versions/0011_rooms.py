"""Rooms and floors for the zones, and label positions on the new house render.

Downgrade drops the columns but leaves the new positions: the old ones belonged to a picture
that no longer exists.
"""

from sqlalchemy import text

from alembic import op

revision = "0011"
down_revision = "0010"

# zone name: (room, floor, pin_x, pin_y); positions are percent across and down the render.
ROOMS = {
    "Primary Bedroom": ("Primary Bedroom", "2nd floor", 37, 20),
    "Guest Bedroom (Upstairs)": ("Guest Bedroom", "2nd floor", 66, 20),
    "Upstairs A/C": ("Upstairs A/C", "2nd floor", 29, 29),
    "Fridge/Stove": ("Kitchen", "1st floor", 33, 35),
    "Dishwasher": ("Kitchen", "1st floor", 33, 35),
    "Microwave/Sink Light": ("Kitchen", "1st floor", 33, 35),
    "Downstairs A/C": ("Downstairs A/C", "1st floor", 24, 45),
    "Living Room": ("Living Room", "1st floor", 35, 52),
    "Washer": ("Laundry", "Basement", 25, 80),
    "Dryer": ("Laundry", "Basement", 25, 80),
    "Basement": ("John's Office", "Basement", 36, 90),
    "Water Heater": ("Water Heater", "Basement", 56, 92),
    "Whole House": (None, "Basement", 65, 79),
}


def upgrade() -> None:
    op.execute("ALTER TABLE zones ADD COLUMN room text, ADD COLUMN floor text")
    update = text("UPDATE zones SET room = :r, floor = :f, pin_x = :x, pin_y = :y WHERE name = :n")
    for name, (room, floor, x, y) in ROOMS.items():
        op.get_bind().execute(update, {"n": name, "r": room, "f": floor, "x": x, "y": y})


def downgrade() -> None:
    op.execute("ALTER TABLE zones DROP COLUMN room, DROP COLUMN floor")
