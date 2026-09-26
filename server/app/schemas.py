from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_\-가-힣]+$")


class AvatarIn(BaseModel):
    preset: int = Field(ge=0, default=0)
    skin: int = Field(ge=0)
    eyes: int = Field(ge=0, default=0)
    hair: int = Field(ge=0)
    hair_color: int = Field(ge=0, default=0)  # legacy column, no longer a layer
    outfit: int = Field(ge=0)
    acc: int = Field(ge=0)


class PlaceIn(BaseModel):
    item_id: str
    room_id: str = "inn"
    x: int
    y: int
    span: int | None = Field(default=None, ge=1)  # wallpaper width in cells


class MoveIn(BaseModel):
    uid: int
    x: int
    y: int
    span: int | None = Field(default=None, ge=1)  # wallpaper: new width (None keeps the current one)
