import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from service import TaskService
from storage import TaskStorage

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_tasks.json")


def main():
    storage = TaskStorage(DATA_FILE)
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    service = TaskService(storage)

    print("== 1. 存储文件不存在时的初始化 ==")
    print(f"初始任务列表: {service.list_tasks()}")

    print("\n== 2. 添加任务 ==")
    service.add_task("Write project README", priority=1)
    service.add_task("Fix login BUG", priority=3)
    service.add_task("Update the docs", priority=2)
    for task in service.list_tasks():
        print(f"  [{task.id}] {task.title} (priority={task.priority}, status={task.status})")

    print("\n== 3. 完成任务 2 ==")
    service.complete_task(2)
    for task in service.list_tasks():
        print(f"  [{task.id}] {task.title} (status={task.status})")

    print("\n== 4. 大小写不敏感搜索 'bug' ==")
    for task in service.search_tasks("bug"):
        print(f"  匹配到: [{task.id}] {task.title}")

    print(f"\n数据已保存到: {DATA_FILE}")


if __name__ == "__main__":
    main()
