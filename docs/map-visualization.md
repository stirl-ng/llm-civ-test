# Map Visualization for LLM

This document describes an ASCII map visualization system to give the LLM spatial awareness of the game world.

## Rationale

Civilization V is fundamentally a spatial game. Key strategic decisions depend on understanding:
- Terrain layout and chokepoints
- Resource clusters and city placement opportunities
- Unit positions relative to threats and objectives
- Expansion paths and defensible borders

Currently, the LLM receives terrain data as JSON with coordinates:
```json
{"x": 5, "y": 12, "terrain": "TERRAIN_PLAINS", "feature": "FEATURE_FOREST"}
```

While precise, this requires the LLM to mentally reconstruct spatial relationships from coordinate pairs. A visual representation allows pattern recognition that's more natural for strategic reasoning.

### Design Philosophy Alignment

From CLAUDE.md: "The LLM should have access to the same information as a human player."

Human players see a map constantly. Providing an ASCII map representation gives the LLM equivalent spatial awareness without requiring vision capabilities or expensive image tokens.

## Design Goals

1. **Token efficient** - Compact representation that conveys maximum spatial information
2. **No vision required** - Works with any text-based LLM
3. **Layered information** - Show terrain, units, cities, and fog-of-war together
4. **Coordinate-aligned** - Easy to correlate visual positions with JSON coordinates
5. **Configurable scope** - Full map, viewport around capital, or specific region

## ASCII Representation

### Terrain Symbols

| Symbol | Terrain | Notes |
|--------|---------|-------|
| `.` | Grassland | Base fertile terrain |
| `:` | Plains | Slightly less fertile |
| `^` | Hills | Defensive bonus, production |
| `M` | Mountains | Impassable |
| `~` | Coast/Ocean | Water tiles |
| `≈` | Ocean | Deep water (if distinguishing) |
| `n` | Forest | On grassland/plains |
| `N` | Jungle | Dense vegetation |
| `d` | Desert | Low yield |
| `t` | Tundra | Cold, low yield |
| `s` | Snow | Very low yield |
| `#` | Marsh | Movement penalty |
| `?` | Fog of war | Unexplored |

### Overlay Symbols (take precedence)

| Symbol | Meaning |
|--------|---------|
| `@` | Your capital |
| `C` | Your other cities |
| `c` | Enemy/other civ cities |
| `U` | Your military unit |
| `S` | Your settler |
| `W` | Your worker |
| `u` | Enemy unit (visible) |
| `*` | Resource (luxury/strategic) |
| `+` | Improvement (farm, mine, etc.) |
| `R` | Road |
| `=` | Railroad |

### Example Output

```
Map View (Turn 47) - Center: Washington (12,8)
Legend: @=capital C=city U=unit S=settler *=resource .=grass ^=hills M=mount ~=water ?=fog

    08 09 10 11 12 13 14 15 16 17
   +------------------------------+
05 | ?  ?  ?  ?  ^  M  M  ^  ?  ? |
06 | ?  ?  ^  n  .  ^  M  .  n  ? |
07 | ?  n  .  . +*  .  ^  .  .  ? |
08 | ~  ~  .  . +C  @  .  U  .  n |
09 | ~  ~  ~  .  .  . +.  .  *  . |
10 | ?  ~  ~  ~  .  S  .  .  n  ^ |
11 | ?  ?  ~  ~  ~  .  .  c  .  . |
12 | ?  ?  ?  ~  ~  ~  .  u  .  ? |
   +------------------------------+

Units:
- Warrior (id=1) at (15,8) - 1 move remaining
- Settler (id=2) at (13,10) - 2 moves remaining

Visible enemy:
- Barbarian Warrior at (15,12)
```

## MCP Tool Interface

### `get_map_view`

Returns an ASCII map visualization of the game world.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `center` | `string` | No | Capital | Center point: `"capital"`, `"unit:<id>"`, or `"<x>,<y>"` |
| `radius` | `int` | No | 8 | Tiles from center to edge (creates 2r+1 square) |
| `show_fog` | `bool` | No | true | Show unexplored tiles as `?` |
| `show_grid` | `bool` | No | true | Show coordinate grid lines |
| `layers` | `array` | No | all | Which layers: `["terrain", "units", "cities", "resources", "improvements"]` |

**Example Request:**
```json
{
  "type": "get_map_view",
  "center": "capital",
  "radius": 10,
  "show_grid": true
}
```

**Example Response:**
```json
{
  "type": "map_view",
  "success": true,
  "center": {"x": 12, "y": 8, "name": "Washington"},
  "bounds": {"x_min": 2, "x_max": 22, "y_min": -2, "y_max": 18},
  "turn": 47,
  "map": "... ASCII map string ...",
  "legend": "@=capital C=city U=unit ...",
  "units_in_view": [
    {"id": 1, "type": "Warrior", "x": 15, "y": 8, "moves": 1},
    {"id": 2, "type": "Settler", "x": 13, "y": 10, "moves": 2}
  ],
  "cities_in_view": [
    {"id": 0, "name": "Washington", "x": 12, "y": 8, "owner": "player"}
  ],
  "enemy_units_visible": [
    {"type": "Barbarian Warrior", "x": 15, "y": 12}
  ]
}
```

### `get_full_map`

Returns the entire known map (may be large).

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `compact` | `bool` | No | false | Omit grid lines and spacing for smaller output |

## Implementation

### Location

Implement in `python/orchestrator/map_renderer.py` as a new module.

### Data Source

Uses existing terrain data from `turn_start` state or `get_game_state(category="terrain")`.

Required fields from terrain state:
- `x`, `y` - Tile coordinates
- `terrain` - Base terrain type
- `feature` - Forest, jungle, marsh, etc.
- `is_visible` - Currently visible to player
- `is_revealed` - Has been explored
- `has_road`, `has_railroad` - Transportation
- `improvement` - Farm, mine, etc.
- `resource` - Luxury/strategic resource

### Rendering Algorithm

```python
def render_map(state: GameState, center: tuple, radius: int) -> str:
    """Render ASCII map centered on given coordinates."""

    # 1. Create empty grid
    grid = {}
    x_min, x_max = center[0] - radius, center[0] + radius
    y_min, y_max = center[1] - radius, center[1] + radius

    # 2. Fill terrain layer
    for tile in state.terrain:
        if x_min <= tile.x <= x_max and y_min <= tile.y <= y_max:
            grid[(tile.x, tile.y)] = terrain_to_symbol(tile)

    # 3. Overlay improvements and roads
    for tile in state.terrain:
        if tile.improvement or tile.has_road:
            grid[(tile.x, tile.y)] = improvement_to_symbol(tile)

    # 4. Overlay resources
    for tile in state.terrain:
        if tile.resource and tile.is_visible:
            grid[(tile.x, tile.y)] = '*'

    # 5. Overlay cities (highest priority after units)
    for city in state.cities:
        symbol = '@' if city.is_capital else 'C' if city.is_ours else 'c'
        grid[(city.x, city.y)] = symbol

    # 6. Overlay units (highest priority)
    for unit in state.units:
        grid[(unit.x, unit.y)] = unit_to_symbol(unit)

    # 7. Render to string with coordinates
    return grid_to_string(grid, x_min, x_max, y_min, y_max)
```

### Symbol Priority (highest to lowest)

1. Player units (U, S, W)
2. Enemy units (u)
3. Player cities (@, C)
4. Enemy cities (c)
5. Resources (*)
6. Improvements (+, R, =)
7. Features (n, N, #)
8. Base terrain (., :, ^, M, ~, d, t, s)
9. Fog of war (?)

## Coordinate System Notes

Civ V uses a hex grid internally, but the pipe protocol exposes it as offset coordinates. The ASCII map uses a square grid approximation which works well enough for strategic overview.

For precise hex-accurate positioning, use the JSON coordinate data. The ASCII map is for spatial intuition, not pixel-perfect accuracy.

## Future Enhancements

### Phase 2: Contextual Views

- **Tactical view**: Zoom in on combat situation with movement ranges
- **Strategic view**: Compressed full-map showing only cities and major features
- **Resource view**: Highlight specific resource types for planning

### Phase 3: Annotations

Allow the LLM to annotate the map with notes:
```
annotate_map(x=15, y=8, note="Defend this chokepoint")
```

These annotations persist and appear in subsequent map views.

### Phase 4: Movement Visualization

Show movement paths and ranges:
```
    08 09 10 11 12 13 14 15
   +------------------------+
07 |  .  .  .  2  1  2  .  . |
08 |  .  .  1  1  U  1  1  . |
09 |  .  .  .  2  1  2  .  . |
```
Numbers show movement cost to reach each tile from unit U.

## Token Efficiency

Estimated token costs (GPT-4 tokenizer approximation):

| View Type | Grid Size | Characters | ~Tokens |
|-----------|-----------|------------|---------|
| Small (r=5) | 11x11 | ~400 | ~100 |
| Medium (r=10) | 21x21 | ~1,200 | ~300 |
| Large (r=15) | 31x31 | ~2,500 | ~600 |
| Full map (standard) | 80x50 | ~10,000 | ~2,500 |

Compare to raw JSON terrain data for same area:
- 21x21 tiles = 441 tiles × ~100 chars = ~44,000 chars = ~11,000 tokens

**ASCII map is ~30-40x more token efficient** for conveying spatial layout.

## Integration with Existing Tools

The map view complements but doesn't replace existing tools:

| Tool | Use Case |
|------|----------|
| `get_game_state(terrain)` | Precise tile data for specific decisions |
| `get_units` | Detailed unit status and available actions |
| `get_map_view` | Spatial overview for strategic planning |

Recommended workflow:
1. Call `get_map_view` at turn start for situational awareness
2. Use `get_units` / `get_game_state` for specific decisions
3. Call `get_map_view` centered on areas of interest as needed
