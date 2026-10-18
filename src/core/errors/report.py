import dataclasses
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Self

from src.core.errors.base import AppError, CoreError, InternalError, PersistenceConflictError
from src.core.errors.enums import ErrorLayer


@dataclass(frozen=True)
class ErrorLink:
    exception: str
    layer: ErrorLayer
    origin: str | None
    context: dict[str, object]

    @classmethod
    def from_exception(cls, exc: BaseException) -> Self:
        frames = [frame for frame, _ in traceback.walk_tb(exc.__traceback__)]
        project_frames = [frame for frame in frames if cls._is_project_frame(frame)]
        origin_frame = project_frames[-1] if project_frames else None

        if isinstance(exc, AppError) and exc.layer is not None:
            layer = exc.layer
        elif frames and not cls._is_project_frame(frames[-1]):
            layer = ErrorLayer.EXTERNAL
        elif origin_frame is not None:
            layer = cls._layer_for_module(cls._module_name(origin_frame))
        else:
            layer = ErrorLayer.APP

        return cls(
            exception=cls._type_name(type(exc)),
            layer=layer,
            origin=cls._origin(origin_frame) if origin_frame is not None else None,
            context=exc.context if isinstance(exc, AppError) else {},
        )

    @staticmethod
    def _is_project_frame(frame: FrameType) -> bool:
        src_root = Path(__file__).resolve().parents[2]
        filename = Path(frame.f_code.co_filename)
        return filename.is_absolute() and filename.resolve().is_relative_to(src_root)

    @staticmethod
    def _module_name(frame: FrameType) -> str:
        return str(frame.f_globals.get("__name__", "")).removeprefix("src.")

    @staticmethod
    def _origin(frame: FrameType) -> str:
        return f"{ErrorLink._module_name(frame)}:{frame.f_code.co_qualname}"

    @staticmethod
    def _type_name(exc_type: type[BaseException]) -> str:
        module = exc_type.__module__.removeprefix("src.")
        if module == "builtins":
            return exc_type.__qualname__
        return f"{module}.{exc_type.__qualname__}"

    @staticmethod
    def _layer_for_module(module: str) -> ErrorLayer:
        match module.split("."):
            case ["api"] | ["api", "exc", *_] | ["api", _, "router"]:
                return ErrorLayer.HTTP
            case ["api", *_]:
                return ErrorLayer.DOMAIN
            case ["core", "db", *_]:
                return ErrorLayer.DB
            case ["core", *_]:
                return ErrorLayer.CORE
            case _:
                return ErrorLayer.APP


@dataclass(frozen=True)
class ErrorReport:
    code: str
    layer: ErrorLayer
    untranslated: bool
    chain: tuple[ErrorLink, ...]

    @classmethod
    def from_exception(cls, exc: BaseException) -> Self:
        chain = tuple(ErrorLink.from_exception(item) for item in cls._unwind(exc))
        return cls(
            code=exc.code if isinstance(exc, AppError) else InternalError.code,
            layer=chain[0].layer,
            untranslated=isinstance(exc, CoreError | PersistenceConflictError),
            chain=chain,
        )

    def to_log(self) -> dict[str, object]:
        return {
            "code": self.code,
            "layer": self.layer.value,
            "untranslated": self.untranslated,
            "chain": [dataclasses.asdict(link) for link in self.chain],
        }

    @staticmethod
    def _unwind(exc: BaseException) -> list[BaseException]:
        chain: list[BaseException] = []
        current: BaseException | None = exc
        while current is not None and all(current is not seen for seen in chain):
            chain.append(current)
            if current.__cause__ is not None or current.__suppress_context__:
                current = current.__cause__
            else:
                current = current.__context__
        return chain
