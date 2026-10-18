import enum
import re
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData
from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        enum.Enum: Enum(
            enum.Enum,
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
    }
    __mapper_args__: Any = {"eager_defaults": True}

    @declared_attr.directive
    def __tablename__(cls) -> str:
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        if snake.endswith("y"):
            return f"{snake[:-1]}ies"
        if snake.endswith(("s", "x", "ch", "sh")):
            return f"{snake}es"
        return f"{snake}s"
