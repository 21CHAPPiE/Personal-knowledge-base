import random


def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)


if __name__ == "__main__":
    data = random.sample(range(1, 101), 15)
    sorted_data = quicksort(data)
    print("Original:", data)
    print("Sorted:  ", sorted_data)
