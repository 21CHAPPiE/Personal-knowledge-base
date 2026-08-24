from sorter import merge_intervals


def test_empty_input():
    assert merge_intervals([]) == []


def test_single_interval():
    assert merge_intervals([[1, 3]]) == [[1, 3]]


def test_unsorted_intervals():
    assert merge_intervals([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]]


def test_reversed_endpoints():
    assert merge_intervals([[5, 2]]) == [[2, 5]]


def test_reversed_overlapping():
    assert merge_intervals([[5, 2], [3, 7]]) == [[2, 7]]


def test_overlapping_intervals():
    assert merge_intervals([[1, 4], [2, 5]]) == [[1, 5]]


def test_touching_endpoints_are_merged():
    assert merge_intervals([[1, 3], [3, 5]]) == [[1, 5]]


def test_no_overlap_kept_separate():
    assert merge_intervals([[1, 2], [4, 5]]) == [[1, 2], [4, 5]]


def test_input_not_modified():
    data = [[3, 5], [1, 2]]
    original = [iv[:] for iv in data]
    result = merge_intervals(data)
    assert data == original
    assert result == [[1, 2], [3, 5]]


def test_contained_interval():
    assert merge_intervals([[1, 10], [2, 3]]) == [[1, 10]]


def test_touching_chain():
    assert merge_intervals([[1, 2], [2, 3], [3, 4]]) == [[1, 4]]


def test_duplicate_intervals():
    assert merge_intervals([[1, 3], [1, 3]]) == [[1, 3]]


def test_reversed_unsorted_mixed():
    assert merge_intervals([[5, 2], [8, 1], [3, 4]]) == [[1, 8]]


def test_negative_numbers():
    assert merge_intervals([[-5, -1], [-3, 0]]) == [[-5, 0]]


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
