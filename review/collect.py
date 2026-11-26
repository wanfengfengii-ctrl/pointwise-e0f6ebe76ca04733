from room.history import list_operations, list_remote_results


def collect_operations(connection, hall):
    # Both sets describe the same closing snapshot. Rejections appear only in the second.
    operations = list_operations(connection, hall)
    terminals = list_remote_results(connection, hall)
    return operations, terminals
