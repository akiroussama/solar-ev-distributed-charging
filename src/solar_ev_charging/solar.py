"""Simple photovoltaic generation models for research simulations."""

from __future__ import annotations

from math import pi, sin


def diurnal_irradiance(
    hour: float,
    *,
    sunrise: float = 6.0,
    sunset: float = 18.0,
    max_irradiance_kw_m2: float = 1.0,
) -> float:
    """Return a smooth daylight irradiance curve in kW/m^2."""

    if hour < sunrise or hour > sunset:
        return 0.0
    daylight_fraction = (hour - sunrise) / (sunset - sunrise)
    return max_irradiance_kw_m2 * max(0.0, sin(pi * daylight_fraction))


def cloud_adjusted_pv_power_kw(
    hour: float,
    *,
    panel_area_m2: float,
    efficiency: float,
    orientation_factor: float = 1.0,
    cloud_factor: float = 1.0,
) -> float:
    """Estimate PV power from area, efficiency, orientation, and cloud factor."""

    if panel_area_m2 < 0:
        msg = "panel_area_m2 must be non-negative"
        raise ValueError(msg)
    if not 0 <= efficiency <= 1:
        msg = "efficiency must be in [0, 1]"
        raise ValueError(msg)
    if not 0 <= orientation_factor <= 1:
        msg = "orientation_factor must be in [0, 1]"
        raise ValueError(msg)
    if not 0 <= cloud_factor <= 1:
        msg = "cloud_factor must be in [0, 1]"
        raise ValueError(msg)

    return panel_area_m2 * efficiency * diurnal_irradiance(hour) * orientation_factor * cloud_factor
