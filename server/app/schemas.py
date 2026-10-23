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
    span: int | None = Field(default=None, ge=1)  # wallpaper / floor pattern width in cells
    span_h: int | None = Field(default=None, ge=1)  # floor pattern height in cells


class MoveIn(BaseModel):
    uid: int
    x: int
    y: int
    span: int | None = Field(default=None, ge=1)  # wallpaper / floor pattern: new width (None keeps the current one)
    span_h: int | None = Field(default=None, ge=1)  # floor pattern: new height (None keeps the current one)


class NoteIn(BaseModel):
    text: str = Field(max_length=200)  # empty = clear the note
