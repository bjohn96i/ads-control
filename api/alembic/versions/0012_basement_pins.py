"""Water Heater and Whole House labels onto the tank and the power box of the upscaled render."""

from sqlalchemy import text

from alembic import op

revision = "0012"
down_revision = "0011"

# zone name: (new pin, old pin); percent across and down the render.
PINS = {
    "Water Heater": ((55, 90), (56, 92)),
    "Whole House": ((63, 84), (65, 79)),
}
_MOVE = text("UPDATE zones SET pin_x = :x, pin_y = :y WHERE name = :n")


def upgrade() -> None:
    for name, ((x, y), _) in PINS.items():
        op.get_bind().execute(_MOVE, {"n": name, "x": x, "y": y})


def downgrade() -> None:
    for name, (_, (x, y)) in PINS.items():
        op.get_bind().execute(_MOVE, {"n": name, "x": x, "y": y})
