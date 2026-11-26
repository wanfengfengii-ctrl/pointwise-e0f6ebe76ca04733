def mix_frames(levels, samples):
    frame_count = max((len(frames) for frames in samples.values()), default=0)
    mixed = [0] * frame_count
    for channel, frames in samples.items():
        gain = levels[channel]
        for index, frame in enumerate(frames):
            mixed[index] += frame * gain
    return mixed
