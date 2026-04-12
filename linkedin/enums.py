import enum

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, enum.Enum):
        pass


class ProfileState(StrEnum):
    QUALIFIED = "Qualified"
    PENDING = "Pending"

    CONNECTED = "Connected"
    COMPLETED = "Completed"
    FAILED = "Failed"

