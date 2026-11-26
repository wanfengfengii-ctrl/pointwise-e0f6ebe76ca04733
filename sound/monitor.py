from room.levels import read_levels
from session.store import get_session
from sound.mix import mix_frames
from sound.routing import route_samples


def listen(database, hall, selection):
    with database.read_snapshot() as connection:
        get_session(connection, hall)
        levels = read_levels(connection, hall)
        samples = route_samples(connection, hall, selection)
    return {"hall": hall, "levels": levels, "mix": mix_frames(levels, samples)}
