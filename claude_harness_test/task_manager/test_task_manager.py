import json
import os
import tempfile

from models import STATUS_COMPLETED, STATUS_PENDING
from service import TaskService
from storage import TaskStorage


def make_service(tmpdir):
    storage = TaskStorage(os.path.join(tmpdir, "tasks.json"))
    return TaskService(storage)


def test_load_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        storage = TaskStorage(os.path.join(tmp, "does_not_exist.json"))
        assert storage.load() == []


def test_add_task_fields():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        task = service.add_task("Write docs", priority=2)
        assert task.id == 1
        assert task.title == "Write docs"
        assert task.status == STATUS_PENDING
        assert task.priority == 2


def test_add_task_increments_id():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        t1 = service.add_task("one")
        t2 = service.add_task("two")
        assert t2.id == t1.id + 1
        assert len(service.list_tasks()) == 2


def test_complete_task_sets_status():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        task = service.add_task("fix bug")
        completed = service.complete_task(task.id)
        assert completed.status == STATUS_COMPLETED
        assert service.list_tasks()[0].status == STATUS_COMPLETED


def test_complete_missing_task_raises():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        try:
            service.complete_task(99)
            raised = False
        except KeyError:
            raised = True
        assert raised


def test_persistence_across_service_instances():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tasks.json")
        TaskService(TaskStorage(path)).add_task("persist me")
        tasks = TaskService(TaskStorage(path)).list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "persist me"


def test_search_case_insensitive():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        service.add_task("Fix Login Bug")
        assert len(service.search_tasks("bug")) == 1
        assert len(service.search_tasks("BUG")) == 1
        assert service.search_tasks("bug")[0].title == "Fix Login Bug"


def test_search_no_match():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        service.add_task("Alpha")
        assert service.search_tasks("zzz") == []


def test_search_empty_storage():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        assert service.search_tasks("anything") == []


def test_save_leaves_no_temp_files():
    with tempfile.TemporaryDirectory() as tmp:
        service = make_service(tmp)
        service.add_task("one")
        assert [n for n in os.listdir(tmp) if n != "tasks.json"] == []


def test_save_crash_mid_write_keeps_old_data():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tasks.json")
        service = make_service(tmp)
        service.add_task("original")
        original = open(path, encoding="utf-8").read()

        def crashing_dump(obj, fp, **kwargs):
            fp.write('[{"id": 1, "title": "par')
            raise RuntimeError("simulated crash mid-write")

        real_dump = json.dump
        json.dump = crashing_dump
        try:
            try:
                service.add_task("second")
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected RuntimeError from crashing dump")
        finally:
            json.dump = real_dump
        assert open(path, encoding="utf-8").read() == original
        assert [t.title for t in service.list_tasks()] == ["original"]
        assert [n for n in os.listdir(tmp) if n != "tasks.json"] == []


if __name__ == "__main__":
    import sys

    test_funcs = [
        f for name, f in sorted(globals().items())
        if name.startswith("test_") and callable(f)
    ]
    failed = 0
    for func in test_funcs:
        try:
            func()
            print(f"PASS {func.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {func.__name__}: {e}")
    print(f"\n{len(test_funcs) - failed}/{len(test_funcs)} tests passed")
    sys.exit(1 if failed else 0)
