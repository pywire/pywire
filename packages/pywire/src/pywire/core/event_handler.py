class EventHandler:
    """Marker type for component event handler props."""

    def __class_getitem__(cls, _params):
        return cls
