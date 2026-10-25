# Chefkoch Collections for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/janhuehne/ha-chefkoch-collections.svg)](https://github.com/janhuehne/ha-chefkoch-collections/releases)
[![Validate](https://github.com/janhuehne/ha-chefkoch-collections/actions/workflows/validate.yml/badge.svg)](https://github.com/janhuehne/ha-chefkoch-collections/actions/workflows/validate.yml)

Unofficial Home Assistant integration that exposes **Chefkoch cookbook collections** (favorites folders) and the week plan (when Chefkoch Plus meal planner is entitled) as a sensor — with write services for folder management and week-plan edits.

> Not affiliated with Chefkoch / Funke Mediengruppe.
> For personal use only — respect Chefkoch ToS and recipe copyright.

## Why this exists

Existing Chefkoch Home Assistant integrations focus on **recipe discovery / search**. They do **not** expose your private cookbook collections or meal planner. This bridge fills that gap so you can build a joined favorites + week UI (for example with [ha-foodwithlove](https://github.com/janhuehne/ha-foodwithlove) Lovelace cards).

## Features

| Feature | Description |
|---|---|
| Favorites sensor | `sensor.chefkoch_collections_favoriten` — collections + recipes (FWL-shaped attributes) |
| Week meals | `week_meals` attribute when the account has Plus meal planner |
| Folders | `create_favorite_folder`, `delete_favorite_folder` (empty only), `move_favorite` |
| Week plan writes | `add_weekplan_meal` / `remove_weekplan_meal` (Plus entitlement required) |

## Requirements

- Home Assistant **2024.1+**
- A Chefkoch account
- Optional: Chefkoch Plus with meal planner for week-plan read/write
- Optional: [ha-foodwithlove](https://github.com/janhuehne/ha-foodwithlove) **≥ 0.5.9** for joined Lovelace cards (`chefkoch_entity`)

## Install (HACS)

### Custom repository

1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. URL: `https://github.com/janhuehne/ha-chefkoch-collections` — category **Integration**
3. Download **Chefkoch Collections**, restart Home Assistant
4. Settings → Devices & services → **Add integration** → **Chefkoch Collections**

### Manual

Copy `custom_components/chefkoch_collections` into your HA `config/custom_components/` folder, restart, then add the integration.

## Setup

Enter your Chefkoch email/username + password. The integration stores them in the config entry and polls every 30 minutes.

## Joined Lovelace (with food with love)

```yaml
type: custom:fwl-week-card
entity: sensor.food_with_love_wochenuberblick
chefkoch_entity: sensor.chefkoch_collections_favoriten

type: custom:fwl-favorites-card
entity: sensor.food_with_love_favoriten
chefkoch_entity: sensor.chefkoch_collections_favoriten
```

You can combine with Cookidoo in the same cards:

```yaml
type: custom:fwl-favorites-card
entity: sensor.food_with_love_favoriten
cookidoo_entity: sensor.cookidoo_collections_favoriten
chefkoch_entity: sensor.chefkoch_collections_favoriten
```

## Services

| Service | Fields |
|---|---|
| `chefkoch_collections.add_weekplan_meal` | `date`, `recipe_id` |
| `chefkoch_collections.remove_weekplan_meal` | `date`, `recipe_id` |
| `chefkoch_collections.create_favorite_folder` | `name` |
| `chefkoch_collections.delete_favorite_folder` | `folder_id` |
| `chefkoch_collections.move_favorite` | `recipe_id`, optional `folder_id` |

## Notes

- Collection IDs look like `user-<uid>-N` (not just `N`).
- Week-plan APIs return **403** without `ROLE_ENTITLEMENT_MEAL_PLANNER` (Chefkoch Plus). Favorites still work on free accounts.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with Chefkoch / Funke Mediengruppe.
