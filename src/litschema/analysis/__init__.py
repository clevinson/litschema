"""Pre-flattened domain DataFrames from ERW extraction JSONs.

Usage::

    from litschema.analysis import load_extractions
    dfs = load_extractions()
    dfs["articles"]        # 1 row per extraction
    dfs["setups"]          # 1 row per ExperimentalSetup
    dfs["interventions"]   # 1 row per Intervention
    dfs["quantification"]  # 1 row per media x measurement
    dfs["modeling"]        # 1 row per modeling paper
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..articles import iter_active_extraction_paths
from ..config import load_config


def _default_extraction_paths() -> list[Path]:
    """Lazy lookup so tests / tooling can override LITSCHEMA_CONFIG."""
    return list(iter_active_extraction_paths(load_config()))


def load_extractions(
    extraction_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Load extraction JSONs into 5 flat domain DataFrames.

    Parameters
    ----------
    extraction_dir : path, optional
        Directory containing ``{article_id}.json`` files.
        Defaults to extraction files found under ``data/papers/<article_id>/``.

    Returns
    -------
    dict with keys: articles, setups, interventions, quantification, modeling
    """
    if extraction_dir:
        extraction_paths = sorted(Path(extraction_dir).glob("*.json"))
    else:
        extraction_paths = _default_extraction_paths()

    records: list[dict[str, Any]] = []
    for f in extraction_paths:
        with open(f) as fh:
            records.append(json.load(fh))

    return {
        "articles": _build_articles(records),
        "setups": _build_setups(records),
        "interventions": _build_interventions(records),
        "quantification": _build_quantification(records),
        "modeling": _build_modeling(records),
    }


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------


def _build_articles(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append(
            {
                "article_id": r["article_id"],
                "study_types": r.get("study_types", []),
                "focus_areas": r.get("focus_areas", []),
                "document_type": r.get("document_type"),
                "n_setups": len(r.get("experimental_setups") or []),
            }
        )
    return pd.DataFrame(rows)


def _build_setups(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        for idx, setup in enumerate(r.get("experimental_setups") or []):
            loc = setup.get("site_location") or {}
            soil = setup.get("soil") or {}
            land = setup.get("land_use") or {}
            irr = setup.get("irrigation") or {}
            rows.append(
                {
                    "article_id": r["article_id"],
                    "setup_idx": idx,
                    "experimental_scale": setup.get("experimental_scale"),
                    # location
                    "country": loc.get("country"),
                    "admin_boundary": loc.get("admin_boundary"),
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                    # soil
                    "soil_texture": soil.get("texture_class"),
                    "soil_order": soil.get("soil_order"),
                    # land use
                    "land_use_type": land.get("land_use_type"),
                    "crop": land.get("crop"),
                    # irrigation
                    "irrigated": irr.get("irrigated"),
                }
            )
    return pd.DataFrame(rows)


def _build_interventions(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        for s_idx, setup in enumerate(r.get("experimental_setups") or []):
            for i_idx, intv in enumerate(setup.get("interventions") or []):
                fs = intv.get("feedstock") or {}
                rows.append(
                    {
                        "article_id": r["article_id"],
                        "setup_idx": s_idx,
                        "intervention_idx": i_idx,
                        # feedstock
                        "rock_type": fs.get("rock_type"),
                        "particle_size_value": fs.get("particle_size_value"),
                        "particle_size_type": fs.get("particle_size_type"),
                        "particle_size_description": fs.get("particle_size_description"),
                        # application
                        "application_rate_value": intv.get("application_rate_value"),
                        "application_rate_unit": intv.get("application_rate_unit"),
                        "incorporation_depth_m": intv.get("incorporation_depth_m"),
                        "application_method": intv.get("application_method"),
                        # mineralogy summary
                        "n_minerals": len(fs.get("mineralogy") or []),
                        "mineral_names": [
                            m.get("mineral_name")
                            for m in (fs.get("mineralogy") or [])
                            if m.get("mineral_name")
                        ]
                        or None,
                    }
                )
    return pd.DataFrame(rows)


def _build_quantification(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        # Article-level quantification
        for qa in r.get("quantification_approaches") or []:
            for meas in qa.get("measurements") or [qa.get("media")]:
                rows.append(
                    {
                        "article_id": r["article_id"],
                        "setup_idx": None,
                        "media": qa.get("media"),
                        "measurement": meas,
                    }
                )
        # Setup-level quantification
        for s_idx, setup in enumerate(r.get("experimental_setups") or []):
            for qa in setup.get("quantification_approaches") or []:
                for meas in qa.get("measurements") or [qa.get("media")]:
                    rows.append(
                        {
                            "article_id": r["article_id"],
                            "setup_idx": s_idx,
                            "media": qa.get("media"),
                            "measurement": meas,
                        }
                    )
    return pd.DataFrame(rows)


def _build_modeling(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        md = r.get("modeling_details")
        if not md:
            continue
        rows.append(
            {
                "article_id": r["article_id"],
                "models_used": md.get("models_used"),
                "scale": md.get("scale"),
                "modeling_type": md.get("modeling_type"),
                "parameters": md.get("parameters"),
            }
        )
    return pd.DataFrame(rows)
