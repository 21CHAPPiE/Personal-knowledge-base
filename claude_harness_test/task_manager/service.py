from models import STATUS_COMPLETED, Task


class TaskService:
    def __init__(self, storage):
        self.storage = storage

    def add_task(self, title, priority=1):
        tasks = self.storage.load()
        new_id = max((t.id for t in tasks), default=0) + 1
        task = Task(id=new_id, title=title, priority=priority)
        tasks.append(task)
        self.storage.save(tasks)
        return task

    def complete_task(self, task_id):
        tasks = self.storage.load()
        for task in tasks:
            if task.id == task_id:
                task.status = STATUS_COMPLETED
                self.storage.save(tasks)
                return task
        raise KeyError(f"task {task_id} not found")

    def list_tasks(self):
        return self.storage.load()

    def search_tasks(self, keyword):
        needle = keyword.lower()
        return [t for t in self.storage.load() if needle in t.title.lower()]
