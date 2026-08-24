from dataclasses import dataclass

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"


@dataclass
class Task:
    id: int
    title: str
    status: str = STATUS_PENDING
    priority: int = 1

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data["id"],
            title=data["title"],
            status=data.get("status", STATUS_PENDING),
            priority=data.get("priority", 1),
        )
