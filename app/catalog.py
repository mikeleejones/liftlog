"""Built-in exercise name catalog for substitution fallback (CLAUDE.md
decision 5). Names, tags, and YouTube queries only — never programming
advice. Used when the library has fewer than 3 swap alternatives; picking
a catalog entry creates it as a real exercise."""

# movement_pattern -> [(name, muscle_group), ...]
CATALOG = {
    "horizontal_pull": [
        ("Barbell Row", "back"),
        ("Seated Cable Row", "back"),
        ("Single-Arm Dumbbell Row", "back"),
        ("Chest-Supported Row", "back"),
        ("Inverted Row", "back"),
        ("T-Bar Row", "back"),
    ],
    "vertical_pull": [
        ("Lat Pulldown", "back"),
        ("Pull-Up", "back"),
        ("Chin-Up", "back"),
        ("Assisted Pull-Up", "back"),
        ("Straight-Arm Pulldown", "back"),
    ],
    "hinge": [
        ("Romanian Deadlift", "legs"),
        ("Conventional Deadlift", "legs"),
        ("Trap Bar Deadlift", "legs"),
        ("Good Morning", "legs"),
        ("Hip Thrust", "glutes"),
        ("Kettlebell Swing", "legs"),
        ("Back Extension", "glutes"),
    ],
    "squat": [
        ("Back Squat", "legs"),
        ("Front Squat", "legs"),
        ("Goblet Squat", "legs"),
        ("Leg Press", "legs"),
        ("Bulgarian Split Squat", "legs"),
        ("Hack Squat", "legs"),
        ("Walking Lunge", "legs"),
    ],
    "horizontal_push": [
        ("Barbell Bench Press", "chest"),
        ("Dumbbell Bench Press", "chest"),
        ("Incline Dumbbell Press", "chest"),
        ("Machine Chest Press", "chest"),
        ("Push-Up", "chest"),
        ("Dip", "chest"),
    ],
    "vertical_push": [
        ("Overhead Press", "shoulders"),
        ("Dumbbell Shoulder Press", "shoulders"),
        ("Arnold Press", "shoulders"),
        ("Landmine Press", "shoulders"),
        ("Machine Shoulder Press", "shoulders"),
    ],
    "isolation": [
        ("Dumbbell Curl", "arms"),
        ("Hammer Curl", "arms"),
        ("Triceps Pushdown", "arms"),
        ("Skull Crusher", "arms"),
        ("Lateral Raise", "shoulders"),
        ("Face Pull", "shoulders"),
        ("Cable Fly", "chest"),
        ("Leg Curl", "legs"),
        ("Leg Extension", "legs"),
        ("Calf Raise", "legs"),
    ],
    "core": [
        ("Plank", "core"),
        ("Hanging Knee Raise", "core"),
        ("Cable Crunch", "core"),
        ("Ab Wheel Rollout", "core"),
        ("Dead Bug", "core"),
        ("Pallof Press", "core"),
    ],
}


def youtube_query(name):
    return f"{name.lower()} form"


def suggestions(db, planned, exclude_names, limit):
    """Catalog entries matching the planned exercise's movement pattern
    (same muscle_group ranked first) that aren't already in the library."""
    pool = sorted(
        CATALOG.get(planned["movement_pattern"], []),
        key=lambda entry: entry[1] != planned["muscle_group"],
    )
    out = []
    lowered = {n.lower() for n in exclude_names}
    for name, group in pool:
        if len(out) == limit:
            break
        if name.lower() in lowered:
            continue
        if db.execute(
            "SELECT 1 FROM exercise WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone():
            continue
        out.append({
            "name": name,
            "movement_pattern": planned["movement_pattern"],
            "muscle_group": group,
            "youtube_query": youtube_query(name),
        })
    return out


def lookup(name):
    """(movement_pattern, muscle_group, youtube_query) for a catalog name,
    or None."""
    lowered = name.lower()
    for pattern, entries in CATALOG.items():
        for entry_name, group in entries:
            if entry_name.lower() == lowered:
                return pattern, group, youtube_query(entry_name)
    return None
