def merge_intervals(intervals):
    normalized = []
    for iv in intervals:
        lo, hi = iv[0], iv[1]
        if lo > hi:
            lo, hi = hi, lo
        normalized.append((lo, hi))

    normalized.sort(key=lambda item: item[0])

    merged = []
    for lo, hi in normalized:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged
