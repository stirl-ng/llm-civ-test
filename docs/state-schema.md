# Game State Information List for Civ V LLM Agent

This document catalogs all possible game state information an LLM agent would need to make informed decisions in Civilization V. This serves as a reference for designing the `state.schema.json` JSON schema and implementing state serialization in the DLL.

## Table of Contents

1. [Game-Level Information](#1-game-level-information)
2. [Player/Civilization State](#2-playercivilization-state)
3. [Technology Tree](#3-technology-tree)
4. [Social Policies](#4-social-policies)
5. [Cities](#5-cities)
6. [Units](#6-units)
7. [Map and Terrain](#7-map-and-terrain)
8. [Diplomacy](#8-diplomacy)
9. [City-States](#9-city-states)
10. [Religion](#10-religion)
11. [Trade Routes](#11-trade-routes)
12. [Wonders](#12-wonders)
13. [Great People](#13-great-people)
14. [Combat Information](#14-combat-information)
15. [Victory Conditions](#15-victory-conditions)
16. [Game Events and Notifications](#16-game-events-and-notifications)
17. [Economic Information](#17-economic-information)
18. [Strategic Resources](#18-strategic-resources)
19. [Luxury Resources](#19-luxury-resources)
20. [Espionage](#20-espionage)

---

## 1. Game-Level Information

**Critical for initial implementation**

Core game settings and turn-level state that frames all decisions.

### Fields

- `turn`: Current turn number (integer)
- `game_speed`: Game speed type (string: "QUICK", "STANDARD", "EPIC", "MARATHON")
- `difficulty`: Difficulty level (string: "SETTLER", "CHIEFTAIN", "WARLORD", "PRINCE", "KING", "EMPEROR", "IMMORTAL", "DEITY")
- `era`: Current game era (string: "ANCIENT", "CLASSICAL", "MEDIEVAL", "RENAISSANCE", "INDUSTRIAL", "MODERN", "ATOMIC", "INFORMATION")
- `map_size`: Map size (string: "DUEL", "TINY", "SMALL", "STANDARD", "LARGE", "HUGE")
- `map_type`: Map type (string: "PANGEA", "CONTINENTS", "ARCHIPELAGO", etc.)
- `sea_level`: Sea level setting (string: "LOW", "MEDIUM", "HIGH")
- `players_alive`: Number of active players (integer)
- `civs_ever`: Total civilizations that have existed (integer)
- `victory_conditions`: Available victory types (array of strings)
- `victory_progress`: Progress toward each victory condition (object)

### Example JSON

```json
{
  "turn": 42,
  "game_speed": "STANDARD",
  "difficulty": "PRINCE",
  "era": "CLASSICAL",
  "map_size": "STANDARD",
  "map_type": "CONTINENTS",
  "sea_level": "MEDIUM",
  "players_alive": 6,
  "civs_ever": 8,
  "victory_conditions": ["DOMINATION", "SCIENCE", "CULTURE", "DIPLOMATIC", "TIME"],
  "victory_progress": {
    "domination": {"capitals_controlled": 1, "capitals_needed": 6},
    "science": {"parts_built": 0, "parts_needed": 6},
    "culture": {"tourism": 0, "influential_civs": 0},
    "diplomatic": {"votes_controlled": 0, "votes_needed": 0},
    "time": {"score": 245, "rank": 3}
  }
}
```

---

## 2. Player/Civilization State

**Critical for initial implementation**

Core resources and yields that drive all decision-making.

### Fields

- `player_id`: Player identifier (integer)
- `civilization`: Civilization name (string: "AMERICA", "ARABIA", etc.)
- `leader`: Leader name (string)
- `gold`: Current gold amount (integer)
- `gold_per_turn`: Gold income per turn (integer, can be negative)
- `culture`: Current culture amount (integer)
- `culture_per_turn`: Culture income per turn (integer)
- `faith`: Current faith amount (integer)
- `faith_per_turn`: Faith income per turn (integer)
- `science`: Current science (integer, accumulated)
- `science_per_turn`: Science income per turn (integer)
- `tourism`: Current tourism output (integer)
- `tourism_per_turn`: Tourism income per turn (integer)
- `happiness`: Current happiness (integer, can be negative)
- `unhappiness`: Total unhappiness (integer)
- `happiness_sources`: Breakdown of happiness sources (object)
- `unhappiness_sources`: Breakdown of unhappiness sources (object)
- `great_person_points`: Points toward great people (object)
  - `engineer`: Engineer points and progress (integer)
  - `scientist`: Scientist points and progress (integer)
  - `merchant`: Merchant points and progress (integer)
  - `artist`: Artist points and progress (integer)
  - `writer`: Writer points and progress (integer)
  - `musician`: Musician points and progress (integer)
  - `general`: General points and progress (integer)
  - `admiral`: Admiral points and progress (integer)
- `golden_age`: Golden age status (object)
  - `active`: Whether golden age is active (boolean)
  - `turns_remaining`: Turns left in golden age (integer, 0 if not active)
  - `progress`: Progress toward next golden age (integer)
  - `points_needed`: Points needed for next golden age (integer)
- `ideology`: Ideology adopted (string: null, "FREEDOM", "ORDER", "AUTOCRACY")
- `ideology_tenets`: Adopted ideology tenets (array of strings)
- `available_tenets`: Available tenets to adopt (array of strings)
- `tourism_pressure`: Tourism pressure on other civs (object mapping civ_id to pressure amount)

### Example JSON

```json
{
  "player_id": 0,
  "civilization": "AMERICA",
  "leader": "WASHINGTON",
  "gold": 1234,
  "gold_per_turn": 45,
  "culture": 567,
  "culture_per_turn": 12,
  "faith": 89,
  "faith_per_turn": 3,
  "science": 2345,
  "science_per_turn": 28,
  "tourism": 0,
  "tourism_per_turn": 0,
  "happiness": 8,
  "unhappiness": 2,
  "happiness_sources": {
    "luxury_resources": 4,
    "buildings": 2,
    "policies": 2,
    "natural_wonders": 0
  },
  "unhappiness_sources": {
    "population": 2,
    "cities": 0,
    "puppets": 0
  },
  "great_person_points": {
    "engineer": {"current": 45, "needed": 100},
    "scientist": {"current": 12, "needed": 100},
    "merchant": {"current": 0, "needed": 100},
    "artist": {"current": 0, "needed": 100},
    "writer": {"current": 0, "needed": 100},
    "musician": {"current": 0, "needed": 100},
    "general": {"current": 8, "needed": 200},
    "admiral": {"current": 0, "needed": 200}
  },
  "golden_age": {
    "active": false,
    "turns_remaining": 0,
    "progress": 120,
    "points_needed": 200
  },
  "ideology": null,
  "ideology_tenets": [],
  "available_tenets": [],
  "tourism_pressure": {}
}
```

---

## 3. Technology Tree

**Critical for initial implementation**

Technology research status and available options.

### Fields

- `researched_techs`: List of researched technology IDs (array of strings)
- `current_research`: Currently researching technology (string or null)
- `research_progress`: Progress toward current research (integer)
- `research_cost`: Total cost of current research (integer)
- `research_per_turn`: Science applied to current research (integer)
- `turns_remaining`: Estimated turns to complete research (integer)
- `available_techs`: Technologies that can be researched (prerequisites met) (array of objects)
  - `tech_id`: Technology identifier (string)
  - `cost`: Research cost (integer)
  - `prerequisites`: Prerequisite technologies (array of strings)
- `tech_tree`: Full technology tree structure (object, optional for full snapshot)

### Example JSON

```json
{
  "researched_techs": ["TECH_AGRICULTURE", "TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY", "TECH_MINING", "TECH_BRONZE_WORKING"],
  "current_research": "TECH_THE_WHEEL",
  "research_progress": 45,
  "research_cost": 100,
  "research_per_turn": 28,
  "turns_remaining": 2,
  "available_techs": [
    {
      "tech_id": "TECH_THE_WHEEL",
      "cost": 100,
      "prerequisites": ["TECH_AGRICULTURE"]
    },
    {
      "tech_id": "TECH_SAILING",
      "cost": 100,
      "prerequisites": ["TECH_POTTERY"]
    },
    {
      "tech_id": "TECH_TRAPPING",
      "cost": 100,
      "prerequisites": ["TECH_ANIMAL_HUSBANDRY"]
    }
  ]
}
```

---

## 4. Social Policies

**Critical for initial implementation**

Social policy trees and adopted policies.

### Fields

- `policy_trees`: Policy tree status (object)
  - `TRADITION`: Tree status (object)
    - `unlocked`: Whether tree is unlocked (boolean)
    - `policies_adopted`: Adopted policy IDs (array of strings)
    - `available_policies`: Policies that can be adopted (array of strings)
  - `LIBERTY`: Same structure
  - `HONOR`: Same structure
  - `PIETY`: Same structure
  - `PATRONAGE`: Same structure
  - `COMMERCE`: Same structure
  - `RATIONALISM`: Same structure (requires Renaissance era)
  - `FREEDOM`: Same structure (ideology)
  - `ORDER`: Same structure (ideology)
  - `AUTOCRACY`: Same structure (ideology)
- `policy_points`: Current policy points (integer)
- `policy_cost`: Cost of next policy (integer)
- `policies_per_turn`: Policy points per turn (integer)
- `turns_until_policy`: Estimated turns until next policy (integer)

### Example JSON

```json
{
  "policy_trees": {
    "TRADITION": {
      "unlocked": true,
      "policies_adopted": ["POLICY_ARISTOCRACY", "POLICY_LEGALISM"],
      "available_policies": ["POLICY_OLIGARCHY", "POLICY_LANDED_ELITE", "POLICY_MONARCHY"]
    },
    "LIBERTY": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "HONOR": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "PIETY": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "PATRONAGE": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "COMMERCE": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "RATIONALISM": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "FREEDOM": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "ORDER": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    },
    "AUTOCRACY": {
      "unlocked": false,
      "policies_adopted": [],
      "available_policies": []
    }
  },
  "policy_points": 45,
  "policy_cost": 100,
  "policies_per_turn": 12,
  "turns_until_policy": 5
}
```

---

## 5. Cities

**Critical for initial implementation**

Complete city information including production, population, and buildings.

### Fields

- `cities`: Array of city objects (array)
  - `id`: City identifier (integer)
  - `name`: City name (string)
  - `x`: X coordinate (integer)
  - `y`: Y coordinate (integer)
  - `population`: Current population (integer)
  - `food`: Current food stored (integer)
  - `food_per_turn`: Food per turn (integer)
  - `food_needed`: Food needed for next growth (integer)
  - `turns_until_growth`: Estimated turns until population growth (integer)
  - `production`: Current production stored (integer)
  - `production_per_turn`: Production per turn (integer)
  - `current_production`: Currently producing (object)
    - `type`: Production type (string: "UNIT", "BUILDING", "WONDER")
    - `name`: Item name (string)
    - `cost`: Production cost (integer)
    - `turns_remaining`: Estimated turns to complete (integer)
  - `production_queue`: Production queue (array of objects, same structure as current_production)
  - `buildings`: List of building IDs present (array of strings)
  - `specialists`: Specialist slots (object)
    - `engineer`: Engineer specialists (integer)
    - `scientist`: Scientist specialists (integer)
    - `merchant`: Merchant specialists (integer)
    - `artist`: Artist specialists (integer)
    - `writer`: Writer specialists (integer)
    - `musician`: Musician specialists (integer)
  - `border_tiles`: Tiles owned by city (array of objects with x, y)
  - `border_expansion_progress`: Progress toward next border expansion (integer)
  - `border_expansion_cost`: Culture cost for next border expansion (integer)
  - `worked_tiles`: Tiles currently being worked (array of objects with x, y)
  - `unhappiness`: City unhappiness (integer)
  - `unhappiness_sources`: Breakdown of unhappiness (object)
  - `religion`: Religious status (object)
    - `majority_religion`: Majority religion ID (string or null)
    - `pressure_sources`: Religious pressure sources (array of objects)
  - `garrison`: Garrisoned unit ID (integer or null)
  - `defense_strength`: City defense strength (integer)
  - `health`: City health/HP (integer)
  - `max_health`: Maximum city health (integer)
  - `is_capital`: Whether city is capital (boolean)
  - `is_puppet`: Whether city is a puppet (boolean)
  - `is_occupied`: Whether city is occupied (boolean)
  - `trade_routes_incoming`: Incoming trade routes (array of trade route IDs)
  - `trade_routes_outgoing`: Outgoing trade routes (array of trade route IDs)

### Example JSON

```json
{
  "cities": [
    {
      "id": 1,
      "name": "Washington",
      "x": 15,
      "y": 20,
      "population": 5,
      "food": 12,
      "food_per_turn": 4,
      "food_needed": 20,
      "turns_until_growth": 2,
      "production": 8,
      "production_per_turn": 6,
      "current_production": {
        "type": "UNIT",
        "name": "UNIT_SETTLER",
        "cost": 89,
        "turns_remaining": 14
      },
      "production_queue": [],
      "buildings": ["BUILDING_MONUMENT", "BUILDING_GRANARY"],
      "specialists": {
        "engineer": 0,
        "scientist": 0,
        "merchant": 0,
        "artist": 0,
        "writer": 0,
        "musician": 0
      },
      "border_tiles": [
        {"x": 15, "y": 20},
        {"x": 16, "y": 20},
        {"x": 15, "y": 21},
        {"x": 14, "y": 20}
      ],
      "border_expansion_progress": 45,
      "border_expansion_cost": 100,
      "worked_tiles": [
        {"x": 16, "y": 20},
        {"x": 15, "y": 21},
        {"x": 14, "y": 20}
      ],
      "unhappiness": 2,
      "unhappiness_sources": {
        "population": 2,
        "puppet": 0
      },
      "religion": {
        "majority_religion": null,
        "pressure_sources": []
      },
      "garrison": null,
      "defense_strength": 6,
      "health": 20,
      "max_health": 20,
      "is_capital": true,
      "is_puppet": false,
      "is_occupied": false,
      "trade_routes_incoming": [],
      "trade_routes_outgoing": []
    }
  ]
}
```

---

## 6. Units

**Critical for initial implementation**

All unit information including location, health, and capabilities.

### Fields

- `units`: Array of unit objects (array)
  - `id`: Unit identifier (integer)
  - `type`: Unit type ID (string: "UNIT_WARRIOR", "UNIT_SETTLER", etc.)
  - `name`: Unit name (string, if named)
  - `x`: X coordinate (integer)
  - `y`: Y coordinate (integer)
  - `hp`: Current hit points (integer)
  - `max_hp`: Maximum hit points (integer)
  - `moves`: Current movement points (integer)
  - `max_moves`: Maximum movement points (integer)
  - `combat_strength`: Combat strength (integer)
  - `ranged_strength`: Ranged combat strength (integer, 0 if not ranged)
  - `range`: Attack range (integer, 1 for melee)
  - `promotions`: List of promotion IDs (array of strings)
  - `experience`: Current experience points (integer)
  - `level`: Unit level (integer)
  - `experience_for_next_level`: Experience needed for next level (integer)
  - `fortified`: Whether unit is fortified (boolean)
  - `fortified_turns`: Turns fortified (integer)
  - `embarked`: Whether unit is embarked (boolean)
  - `can_build_improvements`: Whether unit can build tile improvements (boolean)
  - `can_explore`: Whether unit can explore (boolean)
  - `can_settle`: Whether unit can found cities (boolean)
  - `automation_type`: Current automation (string or null: "EXPLORE", "BUILD", etc.)
  - `orders_remaining`: Number of orders in queue (integer)
  - `unit_class`: Unit class (string: "UNITCLASS_WARRIOR", etc.)
  - `domain`: Unit domain (string: "DOMAIN_LAND", "DOMAIN_SEA", "DOMAIN_AIR")

### Example JSON

```json
{
  "units": [
    {
      "id": 10,
      "type": "UNIT_WARRIOR",
      "name": null,
      "x": 16,
      "y": 21,
      "hp": 100,
      "max_hp": 100,
      "moves": 2,
      "max_moves": 2,
      "combat_strength": 6,
      "ranged_strength": 0,
      "range": 1,
      "promotions": [],
      "experience": 0,
      "level": 1,
      "experience_for_next_level": 10,
      "fortified": false,
      "fortified_turns": 0,
      "embarked": false,
      "can_build_improvements": false,
      "can_explore": true,
      "can_settle": false,
      "automation_type": null,
      "orders_remaining": 0,
      "unit_class": "UNITCLASS_WARRIOR",
      "domain": "DOMAIN_LAND"
    },
    {
      "id": 11,
      "type": "UNIT_SETTLER",
      "name": null,
      "x": 15,
      "y": 20,
      "hp": 100,
      "max_hp": 100,
      "moves": 2,
      "max_moves": 2,
      "combat_strength": 0,
      "ranged_strength": 0,
      "range": 0,
      "promotions": [],
      "experience": 0,
      "level": 0,
      "experience_for_next_level": 0,
      "fortified": false,
      "fortified_turns": 0,
      "embarked": false,
      "can_build_improvements": false,
      "can_explore": false,
      "can_settle": true,
      "automation_type": null,
      "orders_remaining": 0,
      "unit_class": "UNITCLASS_SETTLER",
      "domain": "DOMAIN_LAND"
    }
  ]
}
```

---

## 7. Map and Terrain

**Critical for initial implementation**

Terrain, features, resources, and improvements on visible tiles.

### Fields

- `map_width`: Map width in tiles (integer)
- `map_height`: Map height in tiles (integer)
- `tiles`: Array of tile objects for visible/explored tiles (array)
  - `x`: X coordinate (integer)
  - `y`: Y coordinate (integer)
  - `visibility`: Visibility level (string: "EXPLORED", "VISIBLE", "REVEALED")
  - `terrain`: Terrain type (string: "TERRAIN_GRASS", "TERRAIN_PLAINS", "TERRAIN_DESERT", "TERRAIN_TUNDRA", "TERRAIN_SNOW", "TERRAIN_COAST", "TERRAIN_OCEAN")
  - `feature`: Feature type (string or null: "FEATURE_FOREST", "FEATURE_JUNGLE", "FEATURE_MARSH", "FEATURE_ICE")
  - `hills`: Whether tile has hills (boolean)
  - `mountain`: Whether tile is a mountain (boolean)
  - `resource`: Resource type (string or null: "RESOURCE_IRON", "RESOURCE_HORSES", "RESOURCE_WHEAT", etc.)
  - `improvement`: Improvement type (string or null: "IMPROVEMENT_FARM", "IMPROVEMENT_MINE", etc.)
  - `road`: Whether tile has a road (boolean)
  - `railroad`: Whether tile has a railroad (boolean)
  - `owner`: Player ID who owns the tile (integer or null)
  - `city_id`: City ID that owns the tile (integer or null)
  - `worked_by`: City ID working the tile (integer or null)
  - `yields`: Tile yields (object)
    - `food`: Food yield (integer)
    - `production`: Production yield (integer)
    - `gold`: Gold yield (integer)
    - `science`: Science yield (integer)
    - `culture`: Culture yield (integer)
    - `faith`: Faith yield (integer)
  - `natural_wonder`: Whether tile is a natural wonder (boolean)
  - `natural_wonder_type`: Natural wonder type (string or null)
- `barbarian_camps`: Barbarian camp locations (array of objects with x, y)
- `ancient_ruins`: Ancient ruin locations (array of objects with x, y, explored: boolean)

### Example JSON

```json
{
  "map_width": 80,
  "map_height": 52,
  "tiles": [
    {
      "x": 15,
      "y": 20,
      "visibility": "VISIBLE",
      "terrain": "TERRAIN_GRASS",
      "feature": null,
      "hills": false,
      "mountain": false,
      "resource": null,
      "improvement": null,
      "road": false,
      "railroad": false,
      "owner": 0,
      "city_id": 1,
      "worked_by": 1,
      "yields": {
        "food": 2,
        "production": 0,
        "gold": 0,
        "science": 0,
        "culture": 0,
        "faith": 0
      },
      "natural_wonder": false,
      "natural_wonder_type": null
    },
    {
      "x": 16,
      "y": 20,
      "visibility": "VISIBLE",
      "terrain": "TERRAIN_GRASS",
      "feature": "FEATURE_FOREST",
      "hills": true,
      "mountain": false,
      "resource": "RESOURCE_IRON",
      "improvement": "IMPROVEMENT_MINE",
      "road": false,
      "railroad": false,
      "owner": 0,
      "city_id": 1,
      "worked_by": 1,
      "yields": {
        "food": 1,
        "production": 3,
        "gold": 0,
        "science": 0,
        "culture": 0,
        "faith": 0
      },
      "natural_wonder": false,
      "natural_wonder_type": null
    }
  ],
  "barbarian_camps": [
    {"x": 25, "y": 30}
  ],
  "ancient_ruins": [
    {"x": 18, "y": 22, "explored": false}
  ]
}
```

---

## 8. Diplomacy

**Important for initial implementation**

Relationships, deals, and diplomatic status with other civilizations.

### Fields

- `known_civs`: Known civilizations (array of objects)
  - `player_id`: Player identifier (integer)
  - `civilization`: Civilization name (string)
  - `leader`: Leader name (string)
  - `diplomatic_status`: Current status (string: "WAR", "PEACE", "DENOUNCED", "FRIENDSHIP", "DECLARATION_OF_FRIENDSHIP")
  - `at_war`: Whether at war (boolean)
  - `peace_treaty_turns`: Turns remaining in peace treaty (integer, 0 if not applicable)
  - `denounced_turns`: Turns since denouncement (integer, 0 if not denounced)
  - `declaration_of_friendship_turns`: Turns remaining in declaration of friendship (integer, 0 if not applicable)
  - `embassy_established`: Whether embassy is established (boolean)
  - `trade_deals`: Active trade deals (array of objects)
    - `type`: Deal type (string: "RESOURCE", "GOLD_PER_TURN", "LUMP_SUM", "OPEN_BORDERS", "RESEARCH_AGREEMENT")
    - `resource_type`: Resource type if applicable (string or null)
    - `amount`: Amount (integer, for gold per turn or lump sum)
    - `turns_remaining`: Turns remaining in deal (integer)
  - `diplomatic_modifiers`: Diplomatic relationship modifiers (array of objects)
    - `type`: Modifier type (string: "SHARED_BORDERS", "COMPETING_CITY_STATES", etc.)
    - `value`: Modifier value (integer)
  - `war_score`: War score if at war (integer, positive means winning)
  - `capital_location`: Capital city location (object with x, y, or null if unknown)
- `available_deals`: Available deals/offers from other civs (array of objects)
  - `from_player_id`: Player making offer (integer)
  - `deal_type`: Type of deal (string)
  - `terms`: Deal terms (object)

### Example JSON

```json
{
  "known_civs": [
    {
      "player_id": 1,
      "civilization": "ENGLAND",
      "leader": "ELIZABETH",
      "diplomatic_status": "PEACE",
      "at_war": false,
      "peace_treaty_turns": 0,
      "denounced_turns": 0,
      "declaration_of_friendship_turns": 0,
      "embassy_established": true,
      "trade_deals": [
        {
          "type": "OPEN_BORDERS",
          "resource_type": null,
          "amount": 0,
          "turns_remaining": 15
        }
      ],
      "diplomatic_modifiers": [
        {
          "type": "SHARED_BORDERS",
          "value": -2
        },
        {
          "type": "TRADE_ROUTES",
          "value": 1
        }
      ],
      "war_score": 0,
      "capital_location": {"x": 30, "y": 25}
    }
  ],
  "available_deals": []
}
```

---

## 9. City-States

**Important for initial implementation**

City-state relationships, influence, and quests.

### Fields

- `city_states`: Array of city-state objects (array)
  - `player_id`: City-state player ID (integer)
  - `name`: City-state name (string)
  - `type`: City-state type (string: "MILITARISTIC", "CULTURAL", "MERCANTILE", "RELIGIOUS", "MARITIME")
  - `location`: City location (object with x, y)
  - `influence`: Current influence level (integer)
  - `status`: Relationship status (string: "ALLY", "FRIEND", "NEUTRAL", "HOSTILE")
  - `influence_thresholds`: Influence thresholds (object)
    - `friend`: Influence needed for friend status (integer)
    - `ally`: Influence needed for ally status (integer)
  - `quests`: Active quests (array of objects)
    - `type`: Quest type (string: "CONNECT_RESOURCE", "KILL_BARBARIANS", "FIND_CITY", etc.)
    - `description`: Quest description (string)
    - `progress`: Quest progress (integer)
    - `target`: Quest target (object, varies by quest type)
  - `protected_by`: Player ID protecting this city-state (integer or null)
  - `trade_routes`: Trade routes connected to this city-state (array of trade route IDs)
  - `bonus_yields`: Bonus yields from city-state (object)
    - `food": Food bonus (integer)
    - `production": Production bonus (integer)
    - `culture": Culture bonus (integer)
    - `faith": Faith bonus (integer)
    - `science": Science bonus (integer)

### Example JSON

```json
{
  "city_states": [
    {
      "player_id": 10,
      "name": "Geneva",
      "type": "CULTURAL",
      "location": {"x": 40, "y": 15},
      "influence": 35,
      "status": "FRIEND",
      "influence_thresholds": {
        "friend": 30,
        "ally": 60
      },
      "quests": [
        {
          "type": "CONNECT_RESOURCE",
          "description": "Connect Spices to your trade network",
          "progress": 0,
          "target": {"resource": "RESOURCE_SPICES"}
        }
      ],
      "protected_by": null,
      "trade_routes": [],
      "bonus_yields": {
        "food": 0,
        "production": 0,
        "culture": 3,
        "faith": 0,
        "science": 0
      }
    }
  ]
}
```

---

## 10. Religion

**Nice-to-have for initial implementation**

Religious status, pressure, and beliefs.

### Fields

- `founded_religion`: Religion founded by player (object or null)
  - `religion_id`: Religion identifier (string)
  - `name`: Religion name (string)
  - `founder_belief`: Founder belief ID (string)
  - `follower_belief`: Follower belief ID (string)
  - `enhancer_belief`: Enhancer belief ID (string or null)
  - `reformation_belief`: Reformation belief ID (string or null)
- `religions_in_cities`: Religion status in each city (object mapping city_id to religion object)
  - `majority_religion`: Majority religion ID (string or null)
  - `minority_religions`: Minority religions (array of objects with religion_id and pressure)
  - `pressure_sources`: Sources of religious pressure (array of objects)
- `religious_units`: Religious units (array of objects)
  - `unit_id`: Unit identifier (integer)
  - `type`: Unit type (string: "UNIT_MISSIONARY", "UNIT_INQUISITOR", "UNIT_PROPHET")
  - `religion`: Religion ID (string)
  - `spreads_remaining`: Remaining spreads (integer, for missionaries/prophets)
- `available_beliefs`: Available beliefs that can be selected (array of strings)

### Example JSON

```json
{
  "founded_religion": null,
  "religions_in_cities": {
    "1": {
      "majority_religion": null,
      "minority_religions": [],
      "pressure_sources": []
    }
  },
  "religious_units": [],
  "available_beliefs": []
}
```

---

## 11. Trade Routes

**Important for initial implementation**

Active trade routes and their yields.

### Fields

- `trade_routes`: Array of trade route objects (array)
  - `id`: Trade route identifier (integer)
  - `origin_city_id`: Origin city ID (integer)
  - `destination_city_id`: Destination city ID (integer, or null for external routes)
  - `destination_player_id`: Destination player ID (integer, for external routes)
  - `type`: Trade route type (string: "INTERNAL", "EXTERNAL", "CITY_STATE")
  - `yields`: Trade route yields (object)
    - `gold`: Gold per turn (integer)
    - `food": Food per turn (integer, internal routes only)
    - `production": Production per turn (integer, internal routes only)
    - `science": Science per turn (integer, external routes only)
  - `turns_remaining": Turns remaining (integer)
  - `needs_protection": Whether route needs military protection (boolean)
- `trade_route_capacity": Current trade route capacity (integer)
- `max_trade_routes": Maximum trade routes available (integer)
- `available_destinations": Available trade route destinations (array of objects)
  - `city_id": City ID (integer or null)
  - `player_id": Player ID (integer)
  - `estimated_yield": Estimated yield (object)

### Example JSON

```json
{
  "trade_routes": [],
  "trade_route_capacity": 1,
  "max_trade_routes": 1,
  "available_destinations": []
}
```

---

## 12. Wonders

**Nice-to-have for initial implementation**

World wonders and national wonders built or available.

### Fields

- `world_wonders_built": World wonders built by player (array of objects)
  - `wonder_id": Wonder identifier (string)
  - `name": Wonder name (string)
  - `city_id": City where wonder is built (integer)
  - `turn_built": Turn when built (integer)
- `world_wonders_others": World wonders built by other players (array of objects)
  - `wonder_id": Wonder identifier (string)
  - `name": Wonder name (string)
  - `player_id": Player who built it (integer)
  - `city_id": City where built (integer, if known)
  - `turn_built": Turn when built (integer, if known)
- `national_wonders_built": National wonders built (array of objects)
  - `wonder_id": Wonder identifier (string)
  - `name": Wonder name (string)
  - `city_id": City where built (integer)
- `available_wonders": Wonders that can be built (array of objects)
  - `wonder_id": Wonder identifier (string)
  - `name": Wonder name (string)
  - `type": Wonder type (string: "WORLD", "NATIONAL")
  - `prerequisites": Prerequisites (object)
    - `tech": Required technology (string or null)
    - `building": Required building (string or null)
    - `policy": Required policy (string or null)
  - `cost": Production cost (integer)
  - `cities_can_build": Cities that can build this wonder (array of city IDs)

### Example JSON

```json
{
  "world_wonders_built": [],
  "world_wonders_others": [],
  "national_wonders_built": [],
  "available_wonders": [
    {
      "wonder_id": "BUILDING_PYRAMID",
      "name": "Pyramids",
      "type": "WORLD",
      "prerequisites": {
        "tech": "TECH_MASONRY",
        "building": null,
        "policy": null
      },
      "cost": 185,
      "cities_can_build": [1]
    }
  ]
}
```

---

## 13. Great People

**Nice-to-have for initial implementation**

Great people points, available great people, and great people in cities.

### Fields

- `great_people_available": Great people ready to spawn (array of objects)
  - `type": Great person type (string: "GREAT_ENGINEER", "GREAT_SCIENTIST", etc.)
  - `city_id": City where great person will spawn (integer)
  - `turns_until_spawn": Turns until spawn (integer, 0 if ready)
- `great_people_in_cities": Great people present in cities (array of objects)
  - `type": Great person type (string)
  - `city_id": City ID (integer)
  - `name": Great person name (string)
  - `can_use_ability": Whether ability can be used (boolean)
  - `ability_type": Ability type (string: "TILE_IMPROVEMENT", "INSTANT_YIELD", "GOLDEN_AGE", etc.)

### Example JSON

```json
{
  "great_people_available": [],
  "great_people_in_cities": []
}
```

---

## 14. Combat Information

**Important for initial implementation**

Combat-related information for tactical decisions.

### Fields

- `unit_combat_info": Combat information for units (object, can be derived from unit data)
  - For each unit, combat modifiers based on:
    - `terrain_bonus": Terrain defense bonus (integer)
    - `fortification_bonus": Fortification defense bonus (integer)
    - `promotion_bonuses": Bonuses from promotions (object)
    - `adjacent_units": Adjacent friendly units (integer)
    - `flanking_bonus": Flanking bonus (integer)
- `city_defense_info": City defense information (object)
  - For each city:
    - `defense_strength": Base defense strength (integer)
    - `current_health": Current health (integer)
    - `max_health": Maximum health (integer)
    - `garrison_bonus": Bonus from garrison (integer)
    - `building_bonuses": Bonuses from defensive buildings (object)
- `siege_status": Siege status for cities under attack (array of objects)
  - `city_id": City ID (integer)
  - `siege_level": Siege level (integer, 0-3)
  - `attacking_units": Number of adjacent enemy units (integer)

### Example JSON

```json
{
  "unit_combat_info": {
    "10": {
      "terrain_bonus": 0,
      "fortification_bonus": 0,
      "promotion_bonuses": {},
      "adjacent_units": 0,
      "flanking_bonus": 0
    }
  },
  "city_defense_info": {
    "1": {
      "defense_strength": 6,
      "current_health": 20,
      "max_health": 20,
      "garrison_bonus": 0,
      "building_bonuses": {}
    }
  },
  "siege_status": []
}
```

---

## 15. Victory Conditions

**Important for initial implementation**

Progress toward all victory conditions.

### Fields

- `victory_progress": Victory condition progress (object)
  - `domination": Domination victory (object)
    - `capitals_controlled": Number of capitals controlled (integer)
    - `capitals_needed": Number of capitals needed (integer)
    - `capital_locations": Locations of controlled capitals (array of objects with player_id, x, y)
  - `science": Science victory (object)
    - `parts_built": Spaceship parts built (integer)
    - `parts_needed": Total parts needed (integer)
    - `parts_status": Status of each part (object)
    - `techs_researched": Technologies researched (integer)
    - `techs_needed": Technologies needed for victory (integer)
  - `culture": Culture victory (object)
    - `tourism": Current tourism output (integer)
    - `tourism_per_turn": Tourism per turn (integer)
    - `influential_civs": Number of influential civilizations (integer)
    - `civs_needed": Number of civs needed to be influential with (integer)
    - `influence_status": Influence status with each civ (object)
  - `diplomatic": Diplomatic victory (object)
    - `votes_controlled": Votes controlled (integer)
    - `votes_needed": Votes needed to win (integer)
    - `city_state_allies": Number of city-state allies (integer)
    - `diplomatic_victory_turns": Turns until next world leader vote (integer)
  - `time": Time victory (object)
    - `score": Current score (integer)
    - `rank": Current rank (integer)
    - `turns_remaining": Turns remaining in game (integer)
    - `score_breakdown": Score breakdown (object)

### Example JSON

```json
{
  "victory_progress": {
    "domination": {
      "capitals_controlled": 1,
      "capitals_needed": 6,
      "capital_locations": [
        {"player_id": 0, "x": 15, "y": 20}
      ]
    },
    "science": {
      "parts_built": 0,
      "parts_needed": 6,
      "parts_status": {},
      "techs_researched": 5,
      "techs_needed": 0
    },
    "culture": {
      "tourism": 0,
      "tourism_per_turn": 0,
      "influential_civs": 0,
      "civs_needed": 0,
      "influence_status": {}
    },
    "diplomatic": {
      "votes_controlled": 0,
      "votes_needed": 0,
      "city_state_allies": 0,
      "diplomatic_victory_turns": 0
    },
    "time": {
      "score": 245,
      "rank": 3,
      "turns_remaining": 458,
      "score_breakdown": {
        "land": 50,
        "population": 80,
        "techs": 60,
        "wonders": 30,
        "culture": 25
      }
    }
  }
}
```

---

## 16. Game Events and Notifications

**Nice-to-have for initial implementation**

Recent game events and available notifications.

### Fields

- `recent_events": Recent game events (array of objects)
  - `turn": Turn when event occurred (integer)
  - `type": Event type (string: "BARBARIAN_SPAWN", "CITY_STATE_QUEST", "TECH_COMPLETE", etc.)
  - `description": Event description (string)
  - `data": Event-specific data (object)
- `pending_notifications": Pending notifications (array of objects)
  - `type": Notification type (string)
  - `message": Notification message (string)
  - `action_required": Whether action is required (boolean)
- `city_state_quests": Active city-state quests (array, see City-States section)
- `available_deals": Available diplomatic deals (array, see Diplomacy section)

### Example JSON

```json
{
  "recent_events": [
    {
      "turn": 40,
      "type": "TECH_COMPLETE",
      "description": "Research completed: Pottery",
      "data": {"tech": "TECH_POTTERY"}
    }
  ],
  "pending_notifications": [],
  "city_state_quests": [],
  "available_deals": []
}
```

---

## 17. Economic Information

**Important for initial implementation**

Detailed economic breakdown for resource management.

### Fields

- `gold_breakdown": Gold income/expense breakdown (object)
  - `income": Income sources (object)
    - `city_yields": Gold from city tiles (integer)
    - `trade_routes": Gold from trade routes (integer)
    - `buildings": Gold from buildings (integer)
    - `policies": Gold from policies (integer)
    - `resource_trading": Gold from resource trading (integer)
    - `city_states": Gold from city-states (integer)
  - `expenses": Expense sources (object)
    - `unit_maintenance": Unit maintenance costs (integer)
    - `building_maintenance": Building maintenance costs (integer)
    - `policy_maintenance": Policy maintenance costs (integer)
    - `diplomatic_costs": Diplomatic costs (integer)
  - `net": Net gold per turn (integer)
- `maintenance_costs": Detailed maintenance costs (object)
  - `units": Maintenance per unit type (object)
  - `buildings": Maintenance per building type (object)
- `economic_health": Economic health indicators (object)
  - `gold_reserves": Current gold reserves (integer)
  - `turns_until_bankruptcy": Turns until bankruptcy at current rate (integer, negative if positive income)
  - `recommended_actions": Recommended economic actions (array of strings)

### Example JSON

```json
{
  "gold_breakdown": {
    "income": {
      "city_yields": 5,
      "trade_routes": 0,
      "buildings": 2,
      "policies": 0,
      "resource_trading": 0,
      "city_states": 0
    },
    "expenses": {
      "unit_maintenance": 4,
      "building_maintenance": 3,
      "policy_maintenance": 0,
      "diplomatic_costs": 0
    },
    "net": 0
  },
  "maintenance_costs": {
    "units": {
      "UNIT_WARRIOR": 1,
      "UNIT_SETTLER": 0
    },
    "buildings": {
      "BUILDING_MONUMENT": 1,
      "BUILDING_GRANARY": 1
    }
  },
  "economic_health": {
    "gold_reserves": 1234,
    "turns_until_bankruptcy": -1,
    "recommended_actions": []
  }
}
```

---

## 18. Strategic Resources

**Important for initial implementation**

Strategic resources needed for unit production and available quantities.

### Fields

- `strategic_resources": Strategic resources owned (object)
  - For each resource type (string key: "RESOURCE_IRON", "RESOURCE_HORSES", etc.):
    - `quantity": Quantity available (integer)
    - `sources": Sources of resource (array of objects)
      - `city_id": City ID (integer)
      - `tile_x": Tile X coordinate (integer)
      - `tile_y": Tile Y coordinate (integer)
      - `improved": Whether tile is improved (boolean)
- `strategic_resources_needed": Strategic resources needed for units (object)
  - For each unit type that requires strategic resources:
    - `unit_type": Unit type (string)
    - `resource_type": Required resource (string)
    - `quantity_needed": Quantity needed per unit (integer)
    - `can_build": Whether enough resources available (boolean)
- `strategic_resources_trading": Strategic resource trading status (object)
  - `imported": Resources being imported (array of objects with resource, from_player_id, turns_remaining)
  - `exported": Resources being exported (array of objects with resource, to_player_id, turns_remaining)

### Example JSON

```json
{
  "strategic_resources": {
    "RESOURCE_IRON": {
      "quantity": 2,
      "sources": [
        {
          "city_id": 1,
          "tile_x": 16,
          "tile_y": 20,
          "improved": true
        }
      ]
    },
    "RESOURCE_HORSES": {
      "quantity": 0,
      "sources": []
    }
  },
  "strategic_resources_needed": {
    "UNIT_SWORDSMAN": {
      "unit_type": "UNIT_SWORDSMAN",
      "resource_type": "RESOURCE_IRON",
      "quantity_needed": 1,
      "can_build": true
    }
  },
  "strategic_resources_trading": {
    "imported": [],
    "exported": []
  }
}
```

---

## 19. Luxury Resources

**Important for initial implementation**

Luxury resources providing happiness and trading status.

### Fields

- `luxury_resources": Luxury resources owned (object)
  - For each resource type (string key: "RESOURCE_SPICES", "RESOURCE_SILK", etc.):
    - `quantity": Quantity available (integer)
    - `happiness": Happiness provided (integer, typically 4 per unique luxury)
    - `sources": Sources of resource (array of objects with city_id, tile_x, tile_y, improved)
    - `connected": Whether resource is connected to trade network (boolean)
- `luxury_resources_trading": Luxury resource trading status (object)
  - `imported": Resources being imported (array of objects with resource, from_player_id, turns_remaining, happiness_provided)
  - `exported": Resources being exported (array of objects with resource, to_player_id, turns_remaining)
- `unique_luxuries": Number of unique luxury resources (integer)
- `total_happiness_from_luxuries": Total happiness from luxury resources (integer)

### Example JSON

```json
{
  "luxury_resources": {
    "RESOURCE_SPICES": {
      "quantity": 1,
      "happiness": 4,
      "sources": [
        {
          "city_id": 1,
          "tile_x": 17,
          "tile_y": 21,
          "improved": false
        }
      ],
      "connected": false
    }
  },
  "luxury_resources_trading": {
    "imported": [],
    "exported": []
  },
  "unique_luxuries": 1,
  "total_happiness_from_luxuries": 4
}
```

---

## 20. Espionage

**Nice-to-have for initial implementation**

Spy locations, missions, and intelligence gathering.

### Fields

- `spies": Array of spy objects (array)
  - `spy_id": Spy identifier (integer)
  - `name": Spy name (string)
  - `level": Spy level (integer)
  - `experience": Spy experience (integer)
  - `location_type": Location type (string: "CITY", "CITY_STATE", "CAPITAL")
  - `city_id": City ID where spy is located (integer or null)
  - `player_id": Player ID of target (integer or null)
  - `mission_type": Current mission type (string or null: "STEAL_TECH", "COUP", "RIG_ELECTION", "SIPHON_INCOME")
  - `turns_until_mission": Turns until mission completes (integer, 0 if no mission)
  - `can_steal_tech": Whether spy can steal technology (boolean)
  - `stealable_techs": Technologies that can be stolen (array of strings)
- `espionage_defense": Espionage defense in own cities (object)
  - For each city:
    - `city_id": City ID (integer)
    - `defense_rating": Defense rating (integer)
    - `buildings": Defensive buildings (array of strings)

### Example JSON

```json
{
  "spies": [],
  "espionage_defense": {
    "1": {
      "city_id": 1,
      "defense_rating": 0,
      "buildings": []
    }
  }
}
```

---

## Implementation Priority Notes

### Critical for Initial Implementation

These categories are essential for basic gameplay:

1. **Game-Level Information** - Provides context for all decisions
2. **Player/Civilization State** - Core resources drive all actions
3. **Technology Tree** - Research decisions are fundamental
4. **Social Policies** - Policy choices shape strategy
5. **Cities** - City management is core to gameplay
6. **Units** - Unit movement and combat are essential
7. **Map and Terrain** - Spatial awareness required for all decisions

### Important for Initial Implementation

These categories significantly enhance decision-making:

8. **Diplomacy** - Relationships with other civs affect strategy
9. **City-States** - City-state relationships provide bonuses
11. **Trade Routes** - Economic optimization through trade
14. **Combat Information** - Tactical combat decisions
15. **Victory Conditions** - Goal-oriented play
17. **Economic Information** - Resource management
18. **Strategic Resources** - Unit production requirements
19. **Luxury Resources** - Happiness management

### Nice-to-Have for Initial Implementation

These categories add depth but can be added incrementally:

10. **Religion** - Adds complexity but not essential for basic play
12. **Wonders** - Important but can be tracked via city production
13. **Great People** - Important but can be tracked via great person points
16. **Game Events and Notifications** - Helpful but can be inferred from state
20. **Espionage** - Advanced feature, not essential for initial implementation

---

## State Update Strategies

### Turn-Level Updates

These should be sent every turn:
- Game-level information (turn number, era)
- Player state (resources, yields)
- Technology progress
- Policy progress
- City production progress
- Unit movement/status
- Diplomacy changes
- Victory condition progress

### Incremental Updates

These should be sent when changes occur:
- New cities founded
- Units created/destroyed
- Buildings completed
- Technologies researched
- Policies adopted
- Diplomatic status changes
- Trade deals made/expired
- City-state quests completed

### Full Snapshots

These should be sent periodically or on demand:
- Complete map visibility
- All known civilizations
- All city-states
- Complete technology tree
- Complete policy trees
- All trade routes
- Complete resource inventory

### Fog of War Considerations

- Only send information about tiles that are currently visible or have been explored
- Distinguish between "explored" (seen before, may have changed) and "visible" (currently in view)
- Hide information about other players' units and cities that are not visible
- Hide other players' research progress, policies, and resources (unless revealed through diplomacy/espionage)

---

## JSON Schema Design Notes

- Use snake_case for all field names (consistent with existing examples)
- Use string constants for enumerated types (e.g., "TERRAIN_GRASS" not numeric IDs)
- Include null values explicitly for optional fields
- Use arrays for lists, objects for keyed data
- Keep IDs consistent across related objects (city_id, player_id, unit_id)
- Include both current values and per-turn values where applicable
- Include both absolute values and progress toward goals (e.g., food and food_needed)

---

This document should be updated as the implementation progresses and new requirements are discovered.

---

## Design notes (added 2026-01-02)

### Keep the DLL minimal (recommended)
The DLL should focus on:
- emitting **stable primitives** at safe turn-boundary hooks (snapshots)
- accepting **command bundles**
- performing **final validation** (never crash / never hang)
Everything else (enumerations, heuristics, scoring, search) belongs in the orchestrator.

### What’s missing / should be added

#### Critical: required-decision prompts
Add a top-level list of **action-required prompts** for the active player (so the agent doesn’t need to infer from state):
- needs_tech_choice
- needs_policy_choice
- needs_production_choice (by city_id)
- needs_religion_choice / enhance / reform (if applicable)
- needs_trade_route_assignment (if applicable)
- any forced popup/choice that blocks end-turn

> Recommendation: expose this as a small field in the snapshot **and** as a tool in the orchestrator, since it changes frequently.

#### Critical: legal-action interface (not necessarily full enumeration)
Agents *can* be judged on proposing legal moves, but **you still want a legality API** to keep the environment robust and to avoid wasting turns:
- `validate_action(action) -> {legal: bool, reason: str, alternatives?: ...}`
- optionally `enumerate_legal_actions(unit_id or city_id, scope=...)`

Why: legality in Civ is full of edge cases (movement rules, ZOC, embark/disembark, promotions, domain restrictions, embark techs, one-per-turn attacks, etc.). Final legality should be checked in the DLL regardless.

> Recommendation: do **on-demand** legal action enumeration for a specific entity (unit/city), not a full “all legal actions” dump every turn.

#### High-value: city micro control knobs
Snapshot already includes worked tiles and specialists; add the **controls** that change them:
- tile locks (which plot indices are locked)
- focus flags (production / food / gold / avoid growth, etc.)
- specialist assignments vs available slots (not just totals)

#### High-value: worker/build actions
For units that can build improvements, add:
- current build action (if any) + turns remaining
- per-plot available build actions (on-demand tool preferred), incl. build time

#### High-value: player knowledge state
To avoid treating “unknown” as “absent”, add per-other-player relationship/knowledge flags:
- has_met, embassy, open_borders, at_war, defensive_pact, friendship, denounced
- last_seen timestamps for enemy units/cities (optional, can live in orchestrator memory)

### What should be computed in the orchestrator (not in the DLL)

#### Derived “turns remaining” estimates
Prefer exporting `{stored, cost, rate}` and computing:
- tech turns remaining
- growth turns remaining
- production turns remaining
- policy turns remaining

This avoids DLL-side rounding drift and special-case logic duplication.

#### Combat evaluation / “best attack” scoring
Export primitives (positions, strengths, promotions, terrain); compute:
- expected damage / kill chances
- tactical value heuristics
in the orchestrator via a dedicated evaluator tool.

#### Pathfinding suggestions
Do not dump “all reachable tiles” globally. Instead:
- orchestrator requests `enumerate_moves(unit_id, max_cost or radius)` on-demand
or computes approximations from map layers when acceptable.

### Notes on judging agents for legality
You can still score agents on legality without forcing the orchestrator to enumerate everything:
- Treat **illegal proposals** as a penalty signal in evaluation/logs.
- But keep a `validate_action` tool and DLL-side validation so the sim remains stable and debugging is easy.
- A good compromise: “agent proposes actions; orchestrator validates; agent may revise within a budget; final bundle is applied.”
