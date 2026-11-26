def merge_heard(existing, fresh):
    merged = []
    for start, end in sorted((*existing, *fresh)):
        if start == end:
            continue
        if merged and start <= merged[-1][1]:
            left, right = merged[-1]
            merged[-1] = (left, max(right, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def covers_whole_revision(heard, total_frames):
    return heard == ((0, total_frames),)


def pending_windows(heard, total_frames):
    position = 0
    pending = []
    for start, end in heard:
        if position < start:
            pending.append((position, start))
        position = end
    if position < total_frames:
        pending.append((position, total_frames))
    return tuple(pending)
